from __future__ import annotations

import base64
import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx

from app.core.config import Settings, get_settings
from app.services.credential_lifecycle import CredentialLifecycleRecord, get_credential_lifecycle_service
from app.services.credentials import get_credential_provider


def _derive_key_material(raw_key: str) -> bytes:
    return hashlib.sha256(raw_key.encode("utf-8")).digest()


def _xor_crypt(payload: bytes, key_material: bytes) -> bytes:
    if not payload:
        return payload
    output = bytearray(len(payload))
    key_len = len(key_material)
    for idx, byte in enumerate(payload):
        output[idx] = byte ^ key_material[idx % key_len]
    return bytes(output)


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


@dataclass(frozen=True)
class ApiKeySettingsRecord:
    auth_mode: str
    api_key_configured: bool
    wix_account_id: str | None
    last_rotated_at: str | None
    last_validated_at: str | None
    last_validation_error: str | None
    updated_at: str | None
    updated_by_actor: str | None


@dataclass(frozen=True)
class ApiKeyValidationRecord:
    ok: bool
    message: str
    tested_at: str
    wix_account_id: str | None


class AuthSettingsService:
    def __init__(self, settings: Settings | None = None, db_path: str | None = None) -> None:
        self._settings = settings or get_settings()
        self._db_path = str(Path(db_path or self._settings.auth_settings_db_path))
        self._key_material = _derive_key_material(self._settings.credential_encryption_key)
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_api_key_settings (
                    settings_key TEXT PRIMARY KEY,
                    encrypted_api_key TEXT NOT NULL,
                    encrypted_wix_account_id TEXT NOT NULL,
                    last_rotated_at TEXT,
                    last_validated_at TEXT,
                    last_validation_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    created_by_actor TEXT NOT NULL,
                    updated_by_actor TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_api_key_audit (
                    audit_id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    details TEXT,
                    occurred_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _now(self) -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def _encrypt(self, value: str) -> str:
        raw = value.encode("utf-8")
        encrypted = _xor_crypt(raw, self._key_material)
        return base64.urlsafe_b64encode(encrypted).decode("ascii")

    def _decrypt(self, value: str) -> str:
        raw = base64.urlsafe_b64decode(value.encode("ascii"))
        decrypted = _xor_crypt(raw, self._key_material)
        return decrypted.decode("utf-8")

    def _record_api_key_audit(self, *, action: str, actor: str, outcome: str, details: str | None = None) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO auth_api_key_audit (audit_id, action, actor, outcome, details, occurred_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (str(uuid4()), action, actor, outcome, details, self._now()),
            )
            conn.commit()

    def _write_api_key_settings(
        self,
        *,
        api_key: str,
        wix_account_id: str,
        actor: str,
        validated_at: str,
    ) -> None:
        now = self._now()
        encrypted_api_key = self._encrypt(api_key)
        encrypted_account_id = self._encrypt(wix_account_id)
        with sqlite3.connect(self._db_path) as conn:
            existing = conn.execute(
                "SELECT settings_key, created_at, created_by_actor FROM auth_api_key_settings WHERE settings_key = ?",
                ("primary",),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO auth_api_key_settings (
                        settings_key,
                        encrypted_api_key,
                        encrypted_wix_account_id,
                        last_rotated_at,
                        last_validated_at,
                        last_validation_error,
                        created_at,
                        updated_at,
                        created_by_actor,
                        updated_by_actor
                    ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
                    """,
                    (
                        "primary",
                        encrypted_api_key,
                        encrypted_account_id,
                        now,
                        validated_at,
                        now,
                        now,
                        actor,
                        actor,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE auth_api_key_settings
                    SET encrypted_api_key = ?,
                        encrypted_wix_account_id = ?,
                        last_rotated_at = ?,
                        last_validated_at = ?,
                        last_validation_error = NULL,
                        updated_at = ?,
                        updated_by_actor = ?
                    WHERE settings_key = ?
                    """,
                    (encrypted_api_key, encrypted_account_id, now, validated_at, now, actor, "primary"),
                )
            conn.commit()

    def _read_api_key_settings(self) -> ApiKeySettingsRecord:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT encrypted_wix_account_id, last_rotated_at, last_validated_at,
                       last_validation_error, updated_at, updated_by_actor
                FROM auth_api_key_settings
                WHERE settings_key = ?
                """,
                ("primary",),
            ).fetchone()
        if row is None:
            return ApiKeySettingsRecord(
                auth_mode="api_key",
                api_key_configured=False,
                wix_account_id=None,
                last_rotated_at=None,
                last_validated_at=None,
                last_validation_error="No API key configured.",
                updated_at=None,
                updated_by_actor=None,
            )
        return ApiKeySettingsRecord(
            auth_mode="api_key",
            api_key_configured=True,
            wix_account_id=self._decrypt(str(row[0])),
            last_rotated_at=str(row[1]) if row[1] else None,
            last_validated_at=str(row[2]) if row[2] else None,
            last_validation_error=str(row[3]) if row[3] else None,
            updated_at=str(row[4]) if row[4] else None,
            updated_by_actor=str(row[5]) if row[5] else None,
        )

    def _test_api_key_connection(
        self,
        *,
        api_key: str,
        wix_account_id: str | None,
        actor: str,
        persist_audit: bool = True,
    ) -> ApiKeyValidationRecord:
        tested_at = self._now()
        if self._settings.wix_mock_mode:
            record = ApiKeyValidationRecord(ok=True, message="Mock validation succeeded.", tested_at=tested_at, wix_account_id=wix_account_id)
            if persist_audit:
                self._record_api_key_audit(action="test", actor=actor, outcome="success", details=record.message)
            return record

        headers = {"Authorization": f"Bearer {api_key}"}
        if wix_account_id:
            headers["wix-account-id"] = wix_account_id

        url = f"{self._settings.wix_base_url.rstrip('/')}/apps/v1/instance"
        try:
            with httpx.Client(timeout=self._settings.wix_timeout_ms / 1000.0) as client:
                response = client.get(url, headers=headers)
        except Exception as exc:  # noqa: BLE001
            record = ApiKeyValidationRecord(ok=False, message=f"Connection test failed: {exc}", tested_at=tested_at, wix_account_id=wix_account_id)
            if persist_audit:
                self._record_api_key_audit(action="test", actor=actor, outcome="failure", details=record.message)
            return record

        if response.status_code >= 400:
            record = ApiKeyValidationRecord(
                ok=False,
                message=f"Connection test failed with status {response.status_code}.",
                tested_at=tested_at,
                wix_account_id=wix_account_id,
            )
            if persist_audit:
                self._record_api_key_audit(action="test", actor=actor, outcome="failure", details=record.message)
            return record

        record = ApiKeyValidationRecord(ok=True, message="Connection test succeeded.", tested_at=tested_at, wix_account_id=wix_account_id)
        if persist_audit:
            self._record_api_key_audit(action="test", actor=actor, outcome="success", details=record.message)
        return record

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

    def get_api_key_status(self) -> ApiKeySettingsRecord:
        return self._read_api_key_settings()

    def test_api_key_connection(self, *, api_key: str, wix_account_id: str | None, actor: str) -> ApiKeyValidationRecord:
        return self._test_api_key_connection(api_key=api_key, wix_account_id=wix_account_id, actor=actor)

    def save_api_key_settings(self, *, api_key: str, wix_account_id: str, actor: str) -> ApiKeySettingsRecord:
        result = self._test_api_key_connection(api_key=api_key, wix_account_id=wix_account_id, actor=actor)
        if not result.ok:
            raise RuntimeError(result.message)

        validated_at = result.tested_at
        self._write_api_key_settings(api_key=api_key, wix_account_id=wix_account_id, actor=actor, validated_at=validated_at)
        self._record_api_key_audit(action="save", actor=actor, outcome="success", details="API key settings saved")
        return self._read_api_key_settings()


_auth_settings_service: AuthSettingsService | None = None


def set_auth_settings_service(service: AuthSettingsService | None) -> None:
    global _auth_settings_service
    _auth_settings_service = service


def get_auth_settings_service() -> AuthSettingsService:
    global _auth_settings_service
    if _auth_settings_service is None:
        _auth_settings_service = AuthSettingsService()
    return _auth_settings_service
