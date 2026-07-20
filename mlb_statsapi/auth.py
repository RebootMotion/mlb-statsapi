"""Interactive Okta browser login for the MLB Stats API.

Some Stats API endpoints (e.g. the play-guids endpoint) require an MLB-org
bearer token. :func:`login_with_browser` opens a real Chrome/Chromium window
(Playwright sync API) pointed at the Stats API; the user authenticates on MLB's
Okta page and the bearer token is captured from the redirect URL fragment or
request headers. The browser context is ephemeral — no access to the user's own
profile/cookies, and nothing persists after close. The captured token is
returned to the caller and never written to disk by this module.

Playwright is an optional dependency (the ``[auth]`` extra); it is imported
lazily so this module imports fine without it.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import time
from urllib.parse import parse_qs

from mlb_statsapi.statsapi import MLB_STATS_BASE_URL

logger = logging.getLogger(__name__)

LOGIN_TIMEOUT_SECONDS = 300
POST_LOGIN_GRACE_SECONDS = 3

PLAYWRIGHT_INSTALL_HINT = (
    "Browser login requires Playwright — run `pip install 'mlb-statsapi[auth]'` "
    "and `playwright install chromium`, or supply an access token another way"
)


class LoginUnavailableError(Exception):
    """Interactive browser login cannot run here (e.g. Playwright not installed)."""


# Any URL logged during login may carry the token in its fragment/query; scrub
# the value so the token never lands in logs.
_TOKEN_PARAM_RE = re.compile(r"(access_token|id_token|token)=[^&\s]+", re.IGNORECASE)


def _redact_url(url: str) -> str:
    return _TOKEN_PARAM_RE.sub(r"\1=***", url)


def decode_jwt_exp(token: str) -> int | None:
    """Return the ``exp`` claim (unix seconds) of a JWT, or None if undecodable.

    Undecodable/opaque tokens are treated as valid until the API returns 401.
    """
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        exp = payload.get("exp")
        return int(exp) if exp is not None else None
    except (IndexError, ValueError, binascii.Error, json.JSONDecodeError):
        return None


def _extract_token_from_url(url: str) -> str | None:
    if "#" not in url:
        return None
    fragment = url.split("#", 1)[1]
    tokens = parse_qs(fragment).get("access_token")
    return tokens[0] if tokens else None


def _extract_bearer(header_value: str | None) -> str | None:
    if header_value and header_value.lower().startswith("bearer "):
        token = header_value[7:].strip()
        return token or None
    return None


# Injected before any page script on every navigation. The token arrives in the
# redirect URL fragment; some OAuth handlers immediately scrub it from the URL
# (history.replaceState), which can beat our 0.25s poll. Stash it on a window
# global at document-start so a later scrub can't lose it.
_CAPTURE_INIT_SCRIPT = """
() => {
  try {
    const hash = window.location.hash.slice(1);
    if (hash) {
      const t = new URLSearchParams(hash).get("access_token");
      if (t) { window.__mlbCapturedToken = t; }
    }
  } catch (e) { /* ignore */ }
}
"""

_READ_CAPTURED_SCRIPT = """
() => {
  if (window.__mlbCapturedToken) { return window.__mlbCapturedToken; }
  const hash = window.location.hash.slice(1);
  if (!hash) { return null; }
  return new URLSearchParams(hash).get("access_token");
}
"""


def login_with_browser(timeout_s: int = LOGIN_TIMEOUT_SECONDS) -> str:
    """Open a browser for Okta login and return the captured access token.

    Blocking (Playwright sync API) — callers on an event loop must dispatch to a
    worker thread.

    :raises LoginUnavailableError: Playwright is not installed.
    :raises RuntimeError: Login completed but no token was captured.
    :raises TimeoutError: The user did not complete login in time.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as err:
        raise LoginUnavailableError(PLAYWRIGHT_INSTALL_HINT) from err

    login_url = f"{MLB_STATS_BASE_URL}/user/info"
    token: str | None = None
    captured_via: str | None = None
    login_complete_at: float | None = None
    deadline = time.time() + timeout_s
    logger.info(
        "MLB Stats browser login starting (timeout=%ss); opening %s",
        timeout_s,
        _redact_url(login_url),
    )

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(channel="chrome", headless=False)
        except Exception:
            logger.info("System Chrome unavailable; falling back to bundled Chromium")
            browser = playwright.chromium.launch(headless=False)

        context = browser.new_context()
        page = context.new_page()
        page.add_init_script(_CAPTURE_INIT_SCRIPT)

        def note_capture(source: str) -> None:
            nonlocal captured_via
            if captured_via is None:
                captured_via = source
                logger.info("Captured access token via %s (len=%d)", source, len(token or ""))

        def try_capture_from_url(url: str, source: str) -> None:
            nonlocal token
            if token:
                return
            found = _extract_token_from_url(url)
            if found:
                token = found
                note_capture(source)

        def on_request(request: object) -> None:
            nonlocal token
            if token:
                return
            headers = getattr(request, "headers", {}) or {}
            found = _extract_bearer(headers.get("authorization"))
            if found:
                token = found
                note_capture("request-header")

        def on_response(response: object) -> None:
            nonlocal login_complete_at
            if token or login_complete_at is not None:
                return
            url = getattr(response, "url", "")
            status = getattr(response, "status", None)
            if "/api/v1/user/info" in url and status == 200:
                login_complete_at = time.time()
                logger.info("Login completed (200 from %s); watching for token", _redact_url(url))

        def on_framenavigated(frame: object) -> None:
            url = getattr(frame, "url", "")
            logger.debug("Frame navigated: %s", _redact_url(url))
            try_capture_from_url(url, "frame-navigation")

        page.on("request", on_request)
        page.on("response", on_response)
        page.on("framenavigated", on_framenavigated)
        page.goto(login_url, wait_until="domcontentloaded")

        while time.time() < deadline and not token:
            try_capture_from_url(page.url, "url-poll")
            if token:
                break

            try:
                found = page.evaluate(_READ_CAPTURED_SCRIPT)
                if found:
                    token = found
                    note_capture("page-eval")
                    break
            except Exception as err:  # page navigating/closing between reads
                logger.debug("Token read failed (transient): %s", err)

            if login_complete_at is not None and time.time() - login_complete_at > (
                POST_LOGIN_GRACE_SECONDS
            ):
                logger.info("Grace period elapsed after login with no token captured")
                break

            time.sleep(0.25)

        browser.close()

    if not token:
        if login_complete_at is not None:
            logger.warning("Login succeeded in browser but no token was captured")
            raise RuntimeError(
                "Sign-in succeeded in the browser but no API token was captured. "
                "Use 'Login with Okta' (not username/password), or supply a token manually."
            )
        logger.warning("Login timed out after %ss with no completion detected", timeout_s)
        raise TimeoutError("Sign-in timed out. Try again or supply a token manually.")

    logger.info("MLB Stats browser login succeeded (token via %s)", captured_via)
    return token
