"""Tests for the Okta login helpers and the browser capture flow.

The pure helpers (JWT decode, URL redaction, trusted-host checks) are tested
directly; the browser flow runs against a faked ``playwright.sync_api``, so no
real browser is launched.
"""

from __future__ import annotations

import base64
import json
import sys
import types

from mlb_statsapi.auth import _is_trusted_host, _redact_url, decode_jwt_exp, login_with_browser


def make_jwt(exp: int) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"header.{payload}.sig"


class TestJwtDecode:
    def test_decodes_exp(self) -> None:
        assert decode_jwt_exp(make_jwt(1234567890)) == 1234567890

    def test_opaque_token_returns_none(self) -> None:
        assert decode_jwt_exp("not-a-jwt") is None
        assert decode_jwt_exp("a.b.c") is None


class TestRedactUrl:
    def test_redacts_token_params_in_logged_urls(self) -> None:
        url = "https://statsapi.mlb.com/user/info#access_token=eyJsecret&expires_in=3600"
        redacted = _redact_url(url)
        assert "eyJsecret" not in redacted
        assert "access_token=***" in redacted
        # Non-sensitive params are left intact for debugging.
        assert "expires_in=3600" in redacted

    def test_redacts_oauth_code_and_refresh_token(self) -> None:
        url = "https://statsapi.mlb.com/cb?code=authz-code-secret&refresh_token=rt-secret&state=x"
        redacted = _redact_url(url)
        assert "authz-code-secret" not in redacted
        assert "rt-secret" not in redacted
        assert "code=***" in redacted
        assert "refresh_token=***" in redacted
        assert "state=x" in redacted

    def test_leaves_plain_urls_untouched(self) -> None:
        url = "https://statsapi.mlb.com/api/v1/user/info"
        assert _redact_url(url) == url


class TestTrustedHost:
    def test_accepts_mlb_hosts(self) -> None:
        assert _is_trusted_host("https://statsapi.mlb.com/api/v1/user/info")
        assert _is_trusted_host("https://mlb.com/anything")
        assert _is_trusted_host("https://ids.mlb.com/oauth2/authorize#access_token=x")

    def test_rejects_foreign_and_lookalike_hosts(self) -> None:
        assert not _is_trusted_host("https://mlb.okta.com/#access_token=x")
        assert not _is_trusted_host("https://evil.com/#access_token=x")
        # A suffix attack must not slip through the endswith check.
        assert not _is_trusted_host("https://notmlb.com/#access_token=x")
        assert not _is_trusted_host("https://mlb.com.evil.com/#access_token=x")
        assert not _is_trusted_host("not a url")


# -- browser login flow (Playwright faked) ------------------------------------


class _FakePage:
    def __init__(self, url: str) -> None:
        self.url = url

    def add_init_script(self, script: str) -> None: ...
    def on(self, event: str, callback: object) -> None: ...
    def goto(self, url: str, wait_until: str | None = None) -> None: ...
    def evaluate(self, script: str) -> None:
        return None


class _FakeBrowser:
    def __init__(self, page: _FakePage, events: list[str]) -> None:
        self._page = page
        self._events = events

    def new_context(self) -> object:
        return types.SimpleNamespace(new_page=lambda: self._page)

    def close(self) -> None:
        # Real headed-Chrome teardown takes tens of seconds; order matters.
        self._events.append("browser.close")


class _FakeSyncPlaywright:
    """Stands in for the ``sync_playwright()`` context manager."""

    def __init__(self, browser: _FakeBrowser) -> None:
        self._playwright = types.SimpleNamespace(
            chromium=types.SimpleNamespace(launch=lambda **kw: browser)
        )

    def __enter__(self) -> object:
        return self._playwright

    def __exit__(self, *exc: object) -> bool:
        return False


def _install_fake_playwright(monkeypatch, page_url: str, events: list[str]) -> None:
    browser = _FakeBrowser(_FakePage(page_url), events)
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: _FakeSyncPlaywright(browser)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)


TOKEN_URL = "https://statsapi.mlb.com/api/v1/user/info#access_token=abc123"


class TestLoginWithBrowser:
    def test_returns_captured_token(self, monkeypatch) -> None:
        _install_fake_playwright(monkeypatch, TOKEN_URL, [])
        assert login_with_browser(timeout_s=5) == "abc123"

    def test_on_token_fires_before_browser_teardown(self, monkeypatch) -> None:
        events: list[str] = []
        _install_fake_playwright(monkeypatch, TOKEN_URL, events)
        token = login_with_browser(timeout_s=5, on_token=lambda t: events.append(f"on_token:{t}"))
        assert token == "abc123"
        # The whole point: callers learn the token before the slow close().
        assert events == ["on_token:abc123", "browser.close"]

    def test_callback_failure_does_not_fail_login(self, monkeypatch) -> None:
        events: list[str] = []
        _install_fake_playwright(monkeypatch, TOKEN_URL, events)

        def boom(token: str) -> None:
            raise RuntimeError("caller blew up")

        assert login_with_browser(timeout_s=5, on_token=boom) == "abc123"
        assert events == ["browser.close"]

    def test_untrusted_host_token_is_not_captured(self, monkeypatch) -> None:
        _install_fake_playwright(monkeypatch, "https://evil.example.com/cb#access_token=abc123", [])
        # No capture and no login-complete signal → times out rather than
        # trusting a fragment from a non-MLB host.
        try:
            login_with_browser(timeout_s=1)
        except TimeoutError:
            pass
        else:
            raise AssertionError("expected TimeoutError")
