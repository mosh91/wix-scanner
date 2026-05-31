from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from app.core.config import Settings, get_settings
from app.services.credential_lifecycle import CredentialLifecycleRecord, get_credential_lifecycle_service
from app.services.credentials import get_credential_provider


@dataclass(frozen=True)
class AuthTokenStatusRecord:
    auth_mode: str
    token_status: str
    credential_id: str | None
    profile_name: str | None
    expires_at: str | None
    last_refresh_at: str | None
    last_tested_at: str | None
    last_error: str | None


class AuthSettingsService:
    def __init__(self, settings: Settings | None = None, db_path: str | None = None) -> None:
        self._settings = settings or get_settings()
        self._db_path = str(Path(db_path or self._settings.auth_settings_db_path))
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_token_runtime (
                    credential_id TEXT PRIMARY KEY,
                    last_refresh_at TEXT,
                    last_tested_at TEXT,
                    last_error TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _now(self) -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def _select_active_oauth_credential(self) -> CredentialLifecycleRecord | None:
        records = get_credential_lifecycle_service().list_credentials()
        for record in records:
            if record.auth_mode == "oauth" and record.lifecycle_state in {"active", "expiring_soon", "validated"}:
                return record
        return None

    def _read_runtime(self, credential_id: str) -> tuple[str | None, str | None, str | None]:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT last_refresh_at, last_tested_at, last_error
                FROM auth_token_runtime
                WHERE credential_id = ?
                """,
                (credential_id,),
            ).fetchone()
        if row is None:
            return None, None, None
        return (
            str(row[0]) if row[0] else None,
            str(row[1]) if row[1] else None,
            str(row[2]) if row[2] else None,
        )

    def _write_runtime(
        self,
        *,
        credential_id: str,
        last_refresh_at: str | None = None,
        last_tested_at: str | None = None,
        last_error: str | None = None,
    ) -> None:
        now = self._now()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO auth_token_runtime (
                    credential_id,
                    last_refresh_at,
                    last_tested_at,
                    last_error,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(credential_id) DO UPDATE SET
                    last_refresh_at = COALESCE(excluded.last_refresh_at, auth_token_runtime.last_refresh_at),
                    last_tested_at = COALESCE(excluded.last_tested_at, auth_token_runtime.last_tested_at),
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at
                """,
                (credential_id, last_refresh_at, last_tested_at, last_error, now),
            )
            conn.commit()

    def _token_status(self, credential: CredentialLifecycleRecord | None) -> str:
        if credential is None:
            return "missing"
        if credential.lifecycle_state in {"revoked", "failed"}:
            return "invalid"
        if credential.expires_at is None:
            return "healthy"

        try:
            expiry = datetime.fromisoformat(credential.expires_at.replace("Z", "+00:00"))
        except ValueError:
            return "unknown"

        now = datetime.now(UTC)
        if expiry <= now:
            return "expired"
        warning_threshold = now + timedelta(hours=self._settings.credential_expiry_warning_hours)
        if expiry <= warning_threshold:
            return "expiring_soon"
        return "healthy"

    def get_token_status(self) -> AuthTokenStatusRecord:
        credential = self._select_active_oauth_credential()
        if credential is None:
            return AuthTokenStatusRecord(
                auth_mode=self._settings.auth_mode,
                token_status="missing",
                credential_id=None,
                profile_name=None,
                expires_at=None,
                last_refresh_at=None,
                last_tested_at=None,
                last_error="No active OAuth credential found.",
            )

        last_refresh_at, last_tested_at, last_error = self._read_runtime(credential.credential_id)
        return AuthTokenStatusRecord(
            auth_mode=self._settings.auth_mode,
            token_status=self._token_status(credential),
            credential_id=credential.credential_id,
            profile_name=credential.profile_name,
            expires_at=credential.expires_at,
            last_refresh_at=last_refresh_at,
            last_tested_at=last_tested_at,
            last_error=last_error,
        )

    def test_connection(self) -> AuthTokenStatusRecord:
        credential = self._select_active_oauth_credential()
        if credential is None:
            raise RuntimeError("No active OAuth credential found. Create and activate one before testing.")

        now = self._now()
        if self._settings.wix_mock_mode:
            self._write_runtime(credential_id=credential.credential_id, last_tested_at=now, last_error=None)
            return self.get_token_status()

        token = get_credential_provider(self._settings).get_wix_api_token()
        if not token:
            self._write_runtime(
                credential_id=credential.credential_id,
                last_tested_at=now,
                last_error="Wix API token not configured.",
            )
            raise RuntimeError("Wix API token not configured.")

        url = f"{self._settings.wix_base_url.rstrip('/')}/apps/v1/instance"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            with httpx.Client(timeout=self._settings.wix_timeout_ms / 1000.0) as client:
                response = client.get(url, headers=headers)
        except Exception as exc:  # noqa: BLE001
            self._write_runtime(credential_id=credential.credential_id, last_tested_at=now, last_error=str(exc))
            raise RuntimeError(f"Connection test failed: {exc}") from exc

        if response.status_code >= 400:
            msg = f"Connection test failed with status {response.status_code}."
            self._write_runtime(credential_id=credential.credential_id, last_tested_at=now, last_error=msg)
            raise RuntimeError(msg)

        self._write_runtime(credential_id=credential.credential_id, last_tested_at=now, last_error=None)
        return self.get_token_status()

    def refresh_token(self, *, actor: str) -> AuthTokenStatusRecord:
        credential = self._select_active_oauth_credential()
        if credential is None:
            raise RuntimeError("No active OAuth credential found. Create and activate one before refreshing.")

        self.test_connection()
        refresh_at = self._now()
        new_expiry = (datetime.now(UTC) + timedelta(hours=24)).isoformat().replace("+00:00", "Z")

        get_credential_lifecycle_service().mark_token_refreshed(
            credential.credential_id,
            actor=actor,
            expires_at=new_expiry,
            refreshed_at=refresh_at,
        )

        self._write_runtime(credential_id=credential.credential_id, last_refresh_at=refresh_at, last_error=None)
        return self.get_token_status()


_auth_settings_service: AuthSettingsService | None = None


def set_auth_settings_service(service: AuthSettingsService | None) -> None:
    global _auth_settings_service
    _auth_settings_service = service


def get_auth_settings_service() -> AuthSettingsService:
    global _auth_settings_service
    if _auth_settings_service is None:
        _auth_settings_service = AuthSettingsService()
    return _auth_settings_service
