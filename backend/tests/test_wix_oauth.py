"""Tests for WixOAuthService (P1-US-16: Wix OAuth client credentials auto-refresh)."""
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import Settings
from app.services.wix_oauth import WixOAuthService, get_wix_oauth_service, set_wix_oauth_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings(**overrides) -> Settings:
    defaults = dict(
        wix_mock_mode=False,
        wix_app_id="test-app-id",
        wix_app_secret="test-app-secret",
        wix_app_instance_id="test-instance-id",
        wix_base_url="https://www.wixapis.com",
        wix_timeout_ms=5000,
        credential_provider_mode="oauth",
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _token_response(expires_in: int = 300) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"access_token": "live-token-abc", "expires_in": expires_in}
    return resp


# ---------------------------------------------------------------------------
# is_configured
# ---------------------------------------------------------------------------

def test_is_configured_true():
    svc = WixOAuthService(_settings())
    assert svc.is_configured() is True


def test_is_configured_false_missing_app_id():
    svc = WixOAuthService(_settings(wix_app_id=""))
    assert svc.is_configured() is False


def test_is_configured_false_missing_secret():
    svc = WixOAuthService(_settings(wix_app_secret=""))
    assert svc.is_configured() is False


def test_is_configured_false_missing_instance_id():
    svc = WixOAuthService(_settings(wix_app_instance_id=""))
    assert svc.is_configured() is False


# ---------------------------------------------------------------------------
# Mock mode
# ---------------------------------------------------------------------------

def test_mock_mode_returns_token_without_http_call():
    svc = WixOAuthService(_settings(wix_mock_mode=True))
    with patch("httpx.Client") as mock_client:
        token = svc.get_access_token()
    assert token == "mock-oauth-token"
    mock_client.assert_not_called()


def test_mock_mode_populates_cache():
    svc = WixOAuthService(_settings(wix_mock_mode=True))
    svc.get_access_token()
    assert svc._access_token == "mock-oauth-token"
    assert svc._expires_at is not None
    assert svc._last_refresh_at is not None


# ---------------------------------------------------------------------------
# Token caching
# ---------------------------------------------------------------------------

def test_token_cached_after_first_fetch():
    svc = WixOAuthService(_settings())
    mock_resp = _token_response()
    with patch("httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp
        token1 = svc.get_access_token()
        token2 = svc.get_access_token()

    assert token1 == "live-token-abc"
    assert token2 == "live-token-abc"
    # Only one HTTP call should have been made
    post_calls = mock_client_cls.return_value.__enter__.return_value.post.call_count
    assert post_calls == 1


def test_token_refreshed_when_near_expiry():
    svc = WixOAuthService(_settings())
    # Pre-seed a token that expires in 30 s (< 60 s buffer)
    svc._access_token = "old-token"
    svc._expires_at = datetime.now(UTC) + timedelta(seconds=30)

    mock_resp = _token_response()
    with patch("httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp
        token = svc.get_access_token()

    assert token == "live-token-abc"
    mock_client_cls.return_value.__enter__.return_value.post.assert_called_once()


def test_token_not_refreshed_when_ample_time_remains():
    svc = WixOAuthService(_settings())
    svc._access_token = "cached-token"
    svc._expires_at = datetime.now(UTC) + timedelta(minutes=4)

    with patch("httpx.Client") as mock_client_cls:
        token = svc.get_access_token()

    assert token == "cached-token"
    mock_client_cls.assert_not_called()


# ---------------------------------------------------------------------------
# force_refresh
# ---------------------------------------------------------------------------

def test_force_refresh_always_fetches():
    svc = WixOAuthService(_settings())
    svc._access_token = "old-token"
    svc._expires_at = datetime.now(UTC) + timedelta(minutes=10)

    mock_resp = _token_response()
    with patch("httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp
        svc.force_refresh()

    assert svc._access_token == "live-token-abc"
    mock_client_cls.return_value.__enter__.return_value.post.assert_called_once()


# ---------------------------------------------------------------------------
# OAuth request payload
# ---------------------------------------------------------------------------

def test_oauth_request_contains_correct_payload():
    svc = WixOAuthService(_settings())
    mock_resp = _token_response()
    captured_payload: dict = {}

    def capture_post(url, **kwargs):
        captured_payload.update(kwargs.get("json", {}))
        return mock_resp

    with patch("httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__.return_value.post.side_effect = capture_post
        svc.get_access_token()

    assert captured_payload["grant_type"] == "client_credentials"
    assert captured_payload["client_id"] == "test-app-id"
    assert captured_payload["client_secret"] == "test-app-secret"
    assert captured_payload["instance_id"] == "test-instance-id"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_get_access_token_raises_on_http_error():
    svc = WixOAuthService(_settings())
    error_resp = MagicMock()
    error_resp.status_code = 401
    error_resp.text = "Unauthorized"

    with patch("httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__.return_value.post.return_value = error_resp
        with pytest.raises(RuntimeError, match="HTTP 401"):
            svc.get_access_token()


def test_get_access_token_records_last_error_on_failure():
    svc = WixOAuthService(_settings())
    error_resp = MagicMock()
    error_resp.status_code = 500
    error_resp.text = "Internal Server Error"

    with patch("httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__.return_value.post.return_value = error_resp
        try:
            svc.get_access_token()
        except RuntimeError:
            pass

    assert svc._last_error is not None
    assert "500" in svc._last_error


def test_raises_when_not_configured():
    svc = WixOAuthService(_settings(wix_app_id=""))
    with pytest.raises(RuntimeError, match="OAuth credentials not configured"):
        svc.get_access_token()


# ---------------------------------------------------------------------------
# get_token_status
# ---------------------------------------------------------------------------

def test_token_status_missing_when_no_token():
    svc = WixOAuthService(_settings())
    status = svc.get_token_status()
    assert status["configured"] is True
    assert status["status"] == "missing"


def test_token_status_healthy_when_valid():
    svc = WixOAuthService(_settings(wix_mock_mode=True))
    svc.get_access_token()
    status = svc.get_token_status()
    assert status["status"] == "healthy"
    assert status["expires_at"] is not None
    assert status["last_refresh_at"] is not None


def test_token_status_expired_when_past_expiry():
    svc = WixOAuthService(_settings())
    svc._access_token = "old-token"
    svc._expires_at = datetime.now(UTC) - timedelta(seconds=1)
    status = svc.get_token_status()
    assert status["status"] == "expired"


def test_token_status_expiring_soon():
    svc = WixOAuthService(_settings())
    svc._access_token = "old-token"
    svc._expires_at = datetime.now(UTC) + timedelta(seconds=30)
    status = svc.get_token_status()
    assert status["status"] == "expiring_soon"


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

def test_set_and_get_singleton():
    original = get_wix_oauth_service()
    try:
        fake = WixOAuthService(_settings(wix_mock_mode=True))
        set_wix_oauth_service(fake)
        assert get_wix_oauth_service() is fake
    finally:
        set_wix_oauth_service(original)
