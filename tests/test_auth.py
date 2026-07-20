"""Tests for the auth helpers (JWT decode + URL redaction).

These cover pure helpers only; the Playwright browser flow is not exercised.
"""

from __future__ import annotations

import base64
import json

from mlb_statsapi.auth import _is_trusted_host, _redact_url, decode_jwt_exp


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
