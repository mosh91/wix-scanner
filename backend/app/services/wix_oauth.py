"""Wix OAuth client credentials auto-refresh service (P1-US-16).

Wix issues short-lived Bearer tokens (~5 minutes) via:
    POST https://www.wixapis.com/oauth2/token
    { "grant_type": "client_credentials",
      "client_id": "<app_id>",
      "client_secret": "<app_secret>",
      "instance_id": "<app_instance_id>" }

This service maintains a thread-safe in-memory cache and refreshes the token
when ≤60 seconds remain before expiry.  It is used by OAuthCredentialProvider
so any call to get_wix_api_token() always returns a valid token transparently.
"""
from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_OAUTH_TOKEN_URL = "/oauth2/token"
_REFRESH_BUFFER_SECONDS = 60
_MOCK_TOKEN = "mock-oauth-token"
_MOCK_EXPIRES_IN = 300  # 5 minutes


class WixOAuthService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._access_token: str | None = None
        self._expires_at: datetime | None = None
        self._last_refresh_at: str | None = None
        self._last_error: str | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        return bool(
            self._settings.wix_app_id
            and self._settings.wix_app_secret
            and self._settings.wix_app_instance_id
        )

    def get_access_token(self) -> str:
        with self._lock:
            if self._needs_refresh():
                self._do_refresh()
            if self._access_token is None:
                raise RuntimeError(
                    "OAuth access token unavailable. "
                    "Ensure WIX_SCANNER_WIX_APP_ID, WIX_SCANNER_WIX_APP_SECRET, "
                    "and WIX_SCANNER_WIX_APP_INSTANCE_ID are configured."
                )
            return self._access_token

    def force_refresh(self) -> None:
        """Force an immediate token fetch regardless of cache state."""
        with self._lock:
            self._access_token = None
            self._do_refresh()

    def get_token_status(self) -> dict[str, object]:
        with self._lock:
            status = self._compute_status()
            return {
                "configured": self.is_configured(),
                "status": status,
                "expires_at": (
                    self._expires_at.isoformat().replace("+00:00", "Z")
                    if self._expires_at
                    else None
                ),
                "last_refresh_at": self._last_refresh_at,
                "last_error": self._last_error,
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _needs_refresh(self) -> bool:
        if self._access_token is None:
            return True
        if self._expires_at is None:
            return True
        return datetime.now(UTC) >= (self._expires_at - timedelta(seconds=_REFRESH_BUFFER_SECONDS))

    def _compute_status(self) -> str:
        if self._access_token is None:
            return "missing"
        if self._expires_at is None:
            return "healthy"
        now = datetime.now(UTC)
        if now >= self._expires_at:
            return "expired"
        if now >= (self._expires_at - timedelta(seconds=_REFRESH_BUFFER_SECONDS)):
            return "expiring_soon"
        return "healthy"

    def _do_refresh(self) -> None:
        """Fetch a new token from Wix OAuth endpoint.  Must be called under self._lock."""
        if self._settings.wix_mock_mode:
            self._access_token = _MOCK_TOKEN
            self._expires_at = datetime.now(UTC) + timedelta(seconds=_MOCK_EXPIRES_IN)
            self._last_refresh_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            self._last_error = None
            logger.debug("wix_oauth.refreshed.mock")
            return

        if not self.is_configured():
            self._last_error = (
                "OAuth credentials not configured: "
                "WIX_SCANNER_WIX_APP_ID, WIX_SCANNER_WIX_APP_SECRET, "
                "and WIX_SCANNER_WIX_APP_INSTANCE_ID must all be set."
            )
            raise RuntimeError(self._last_error)

        url = self._settings.wix_base_url.rstrip("/") + _OAUTH_TOKEN_URL
        payload = {
            "grant_type": "client_credentials",
            "client_id": self._settings.wix_app_id,
            "client_secret": self._settings.wix_app_secret,
            "instance_id": self._settings.wix_app_instance_id,
        }
        try:
            with httpx.Client(timeout=self._settings.wix_timeout_ms / 1000.0) as client:
                resp = client.post(url, json=payload)
            if resp.status_code >= 400:
                msg = f"Wix OAuth returned HTTP {resp.status_code}: {resp.text[:256]}"
                self._last_error = msg
                raise RuntimeError(msg)
            data: dict = resp.json()
            self._access_token = str(data["access_token"])
            expires_in = int(data.get("expires_in", _MOCK_EXPIRES_IN))
            self._expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
            self._last_refresh_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            self._last_error = None
            logger.info(
                "wix_oauth.refreshed",
                extra={"expires_in_s": expires_in},
            )
        except RuntimeError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            raise RuntimeError(f"Wix OAuth token refresh failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_wix_oauth_service: WixOAuthService | None = None


def get_wix_oauth_service() -> WixOAuthService:
    global _wix_oauth_service
    if _wix_oauth_service is None:
        _wix_oauth_service = WixOAuthService(get_settings())
    return _wix_oauth_service


def set_wix_oauth_service(service: WixOAuthService | None) -> None:
    global _wix_oauth_service
    _wix_oauth_service = service
