from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

CredentialLifecycleState = Literal[
    "created",
    "validated",
    "active",
    "expiring_soon",
    "rotation_pending",
    "revoked",
    "failed",
]

AuthMode = Literal["oauth", "api_key"]

# Auth-strategy decision table: which auth mode each endpoint type supports
AUTH_STRATEGY: dict[str, dict[str, str]] = {
    "check_in": {
        "scope": "WIX_EVENTS.CHECK-IN",
        "production_mode": "oauth",
        "staging_mode": "api_key",
        "notes": "Check-in endpoint. OAuth required in production for user-identity audit trail.",
    },
    "ticket_read": {
        "scope": "WIX_EVENTS.READ_TICKETS",
        "production_mode": "oauth",
        "staging_mode": "api_key",
        "notes": "Ticket-read endpoint. OAuth required in production.",
    },
    "event_read": {
        "scope": "WIX_EVENTS.READ_EVENTS",
        "production_mode": "oauth",
        "staging_mode": "api_key",
        "notes": "Event-read endpoint. OAuth required in production.",
    },
    "sync": {
        "scope": "WIX_EVENTS.CHECK-IN,WIX_EVENTS.READ_TICKETS,WIX_EVENTS.READ_EVENTS",
        "production_mode": "oauth",
        "staging_mode": "api_key",
        "notes": "Full-sync operations. OAuth required in production for all scopes.",
    },
}

VALID_TRANSITIONS: dict[CredentialLifecycleState, tuple[CredentialLifecycleState, ...]] = {
    "created": ("validated", "failed", "revoked"),
    "validated": ("active", "revoked"),
    "active": ("expiring_soon", "rotation_pending", "revoked"),
    "expiring_soon": ("rotation_pending", "revoked"),
    "rotation_pending": ("revoked",),
    "revoked": (),
    "failed": ("created", "revoked"),
}


@dataclass(frozen=True)
class CredentialLifecycleRecord:
    credential_id: str
    profile_name: str
    auth_mode: AuthMode
    lifecycle_state: CredentialLifecycleState
    created_at: str
    validated_at: str | None
    activated_at: str | None
    last_validated_at: str | None
    validation_error: str | None
    expires_at: str | None
    rotation_note: str | None
    created_by_actor: str


@dataclass(frozen=True)
class CredentialLifecycleEvent:
    event_id: str
    credential_id: str
    from_state: str | None
    to_state: str
    actor: str
    event_note: str | None
    occurred_at: str


class CredentialLifecycleService:
    def __init__(
        self,
        *,
        settings: Settings,
        db_path: str,
    ) -> None:
        self._settings = settings
        self._db_path = str(Path(db_path))
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS credential_lifecycle (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    credential_id TEXT NOT NULL UNIQUE,
                    profile_name TEXT NOT NULL,
                    auth_mode TEXT NOT NULL,
                    lifecycle_state TEXT NOT NULL DEFAULT 'created',
                    created_at TEXT NOT NULL,
                    validated_at TEXT,
                    activated_at TEXT,
                    last_validated_at TEXT,
                    validation_error TEXT,
                    expires_at TEXT,
                    rotation_note TEXT,
                    created_by_actor TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS credential_lifecycle_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    credential_id TEXT NOT NULL,
                    from_state TEXT,
                    to_state TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    event_note TEXT,
                    occurred_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _now(self) -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def _row_to_record(self, row: tuple) -> CredentialLifecycleRecord:  # type: ignore[type-arg]
        return CredentialLifecycleRecord(
            credential_id=str(row[0]),
            profile_name=str(row[1]),
            auth_mode=str(row[2]),  # type: ignore[arg-type]
            lifecycle_state=str(row[3]),  # type: ignore[arg-type]
            created_at=str(row[4]),
            validated_at=str(row[5]) if row[5] else None,
            activated_at=str(row[6]) if row[6] else None,
            last_validated_at=str(row[7]) if row[7] else None,
            validation_error=str(row[8]) if row[8] else None,
            expires_at=str(row[9]) if row[9] else None,
            rotation_note=str(row[10]) if row[10] else None,
            created_by_actor=str(row[11]),
        )

    def _emit_event(
        self,
        conn: sqlite3.Connection,
        credential_id: str,
        from_state: str | None,
        to_state: str,
        actor: str,
        note: str | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO credential_lifecycle_events
                (event_id, credential_id, from_state, to_state, actor, event_note, occurred_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (str(uuid4()), credential_id, from_state, to_state, actor, note, self._now()),
        )

    def create_credential(
        self,
        *,
        profile_name: str,
        auth_mode: AuthMode,
        actor: str,
        expires_at: str | None = None,
    ) -> CredentialLifecycleRecord:
        now = self._now()
        credential_id = str(uuid4())
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO credential_lifecycle
                    (credential_id, profile_name, auth_mode, lifecycle_state,
                     created_at, created_by_actor, expires_at)
                VALUES (?, ?, ?, 'created', ?, ?, ?)
                """,
                (credential_id, profile_name, auth_mode, now, actor, expires_at),
            )
            self._emit_event(conn, credential_id, None, "created", actor, "Credential registered")
            conn.commit()
        logger.info("credential.lifecycle.created", extra={"credential_id": credential_id, "auth_mode": auth_mode})
        record = self.get_credential(credential_id)
        assert record is not None
        return record

    def _call_wix_api_for_validation(self) -> tuple[bool, str | None]:
        """Call Wix API to validate credential. Returns (success, error_message)."""
        if self._settings.wix_mock_mode:
            return True, None
        token = self._settings.wix_api_token
        if not token:
            return False, "No Wix API token configured"
        try:
            url = f"{self._settings.wix_base_url}/apps/v1/instance"
            with httpx.Client(timeout=self._settings.wix_timeout_ms / 1000) as client:
                resp = client.get(url, headers={"Authorization": token})
            if resp.status_code == 200:
                return True, None
            return False, f"Wix API returned HTTP {resp.status_code}"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    def validate_credential(
        self,
        credential_id: str,
        *,
        actor: str,
    ) -> CredentialLifecycleRecord:
        record = self.get_credential(credential_id)
        if record is None:
            raise KeyError(credential_id)
        if record.lifecycle_state not in VALID_TRANSITIONS or "validated" not in VALID_TRANSITIONS.get(record.lifecycle_state, ()) and "failed" not in VALID_TRANSITIONS.get(record.lifecycle_state, ()):  # type: ignore[comparison-overlap]
            raise ValueError(
                f"Cannot validate credential in state '{record.lifecycle_state}'"
            )

        # In mock mode, deterministic result based on credential_id prefix
        if self._settings.wix_mock_mode:
            if credential_id.startswith("cred-fail-"):
                success, error = False, "Mock: credential ID starts with cred-fail-"
            else:
                success, error = True, None
        else:
            success, error = self._call_wix_api_for_validation()

        now = self._now()
        new_state: CredentialLifecycleState = "validated" if success else "failed"

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                UPDATE credential_lifecycle
                SET lifecycle_state = ?,
                    last_validated_at = ?,
                    validated_at = CASE WHEN ? = 'validated' AND validated_at IS NULL THEN ? ELSE validated_at END,
                    validation_error = ?
                WHERE credential_id = ?
                """,
                (new_state, now, new_state, now, error, credential_id),
            )
            self._emit_event(
                conn, credential_id, record.lifecycle_state, new_state, actor,
                None if success else f"Validation failed: {error}",
            )
            conn.commit()

        logger.info(
            "credential.lifecycle.validated",
            extra={"credential_id": credential_id, "success": success},
        )
        updated = self.get_credential(credential_id)
        assert updated is not None
        return updated

    def activate_credential(
        self,
        credential_id: str,
        *,
        actor: str,
    ) -> CredentialLifecycleRecord:
        record = self.get_credential(credential_id)
        if record is None:
            raise KeyError(credential_id)
        if "active" not in VALID_TRANSITIONS.get(record.lifecycle_state, ()):
            raise ValueError(
                f"Cannot activate credential in state '{record.lifecycle_state}'. "
                "Credential must be in 'validated' state."
            )

        now = self._now()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                UPDATE credential_lifecycle
                SET lifecycle_state = 'active', activated_at = ?
                WHERE credential_id = ?
                """,
                (now, credential_id),
            )
            self._emit_event(conn, credential_id, record.lifecycle_state, "active", actor)
            conn.commit()

        logger.info("credential.lifecycle.activated", extra={"credential_id": credential_id})
        updated = self.get_credential(credential_id)
        assert updated is not None
        return updated

    def check_expiry(
        self,
        credential_id: str,
        *,
        warning_hours: int | None = None,
    ) -> CredentialLifecycleRecord:
        """Transition active credential to expiring_soon if within warning window."""
        record = self.get_credential(credential_id)
        if record is None:
            raise KeyError(credential_id)

        if record.lifecycle_state != "active":
            return record

        if record.expires_at is None:
            return record

        hours = warning_hours if warning_hours is not None else self._settings.credential_expiry_warning_hours
        now_dt = datetime.now(UTC)
        try:
            expires_dt = datetime.fromisoformat(record.expires_at.replace("Z", "+00:00"))
        except ValueError:
            return record

        threshold = now_dt + timedelta(hours=hours)
        if expires_dt <= threshold:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "UPDATE credential_lifecycle SET lifecycle_state = 'expiring_soon' WHERE credential_id = ?",
                    (credential_id,),
                )
                self._emit_event(
                    conn, credential_id, "active", "expiring_soon", "system",
                    f"Expires at {record.expires_at}; within {hours}h warning window",
                )
                conn.commit()
            logger.info("credential.lifecycle.expiring_soon", extra={"credential_id": credential_id})
            updated = self.get_credential(credential_id)
            assert updated is not None
            return updated

        return record

    def rotate_credential(
        self,
        credential_id: str,
        *,
        new_profile_name: str,
        new_auth_mode: AuthMode,
        actor: str,
        new_expires_at: str | None = None,
    ) -> tuple[CredentialLifecycleRecord, CredentialLifecycleRecord]:
        """Rotate a credential: create and validate a new one, revoke the old.

        Returns (new_record, revoked_old_record).
        """
        old_record = self.get_credential(credential_id)
        if old_record is None:
            raise KeyError(credential_id)

        allowed_rotation_states: tuple[CredentialLifecycleState, ...] = (
            "active",
            "expiring_soon",
            "validated",
        )
        if old_record.lifecycle_state not in allowed_rotation_states:
            raise ValueError(
                f"Cannot rotate credential in state '{old_record.lifecycle_state}'. "
                f"Must be in {allowed_rotation_states}."
            )

        # Mark old as rotation_pending
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                UPDATE credential_lifecycle
                SET lifecycle_state = 'rotation_pending', rotation_note = ?
                WHERE credential_id = ?
                """,
                (f"Rotation initiated by {actor}", credential_id),
            )
            self._emit_event(
                conn, credential_id, old_record.lifecycle_state, "rotation_pending",
                actor, "Rotation initiated",
            )
            conn.commit()

        # Create new credential
        new_record = self.create_credential(
            profile_name=new_profile_name,
            auth_mode=new_auth_mode,
            actor=actor,
            expires_at=new_expires_at,
        )

        # Validate new credential
        new_record = self.validate_credential(new_record.credential_id, actor=actor)

        if new_record.lifecycle_state == "failed":
            # Rollback rotation_pending → active on the old credential
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "UPDATE credential_lifecycle SET lifecycle_state = ?, rotation_note = NULL WHERE credential_id = ?",
                    (old_record.lifecycle_state, credential_id),
                )
                self._emit_event(
                    conn, credential_id, "rotation_pending", old_record.lifecycle_state,
                    actor, "Rotation rolled back: new credential validation failed",
                )
                conn.commit()
            raise RuntimeError(
                f"Rotation failed: new credential validation failed: {new_record.validation_error}"
            )

        # Activate new credential
        new_record = self.activate_credential(new_record.credential_id, actor=actor)

        # Revoke old credential
        revoked = self.revoke_credential(credential_id, actor=actor, note="Superseded by rotation")

        return new_record, revoked

    def revoke_credential(
        self,
        credential_id: str,
        *,
        actor: str,
        note: str | None = None,
    ) -> CredentialLifecycleRecord:
        record = self.get_credential(credential_id)
        if record is None:
            raise KeyError(credential_id)
        if record.lifecycle_state == "revoked":
            return record

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "UPDATE credential_lifecycle SET lifecycle_state = 'revoked' WHERE credential_id = ?",
                (credential_id,),
            )
            self._emit_event(
                conn, credential_id, record.lifecycle_state, "revoked", actor,
                note or "Credential revoked",
            )
            conn.commit()

        logger.info("credential.lifecycle.revoked", extra={"credential_id": credential_id})
        updated = self.get_credential(credential_id)
        assert updated is not None
        return updated

    def validate_no_mixed_modes(self, environment: str) -> None:
        """Raise ValueError if production environment has credentials with mixed auth modes."""
        if environment != "production":
            return
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT auth_mode FROM credential_lifecycle
                WHERE lifecycle_state IN ('active', 'expiring_soon', 'validated')
                """
            ).fetchall()
        active_modes = {str(row[0]) for row in rows}
        if len(active_modes) > 1:
            raise ValueError(
                f"Production environment cannot have mixed auth modes. "
                f"Found: {sorted(active_modes)}. "
                "All active credentials must use the same auth mode in production."
            )

    def mark_token_refreshed(
        self,
        credential_id: str,
        *,
        actor: str,
        expires_at: str,
        refreshed_at: str,
    ) -> CredentialLifecycleRecord:
        record = self.get_credential(credential_id)
        if record is None:
            raise KeyError(credential_id)

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                UPDATE credential_lifecycle
                SET lifecycle_state = 'active',
                    expires_at = ?,
                    last_validated_at = ?,
                    validation_error = NULL,
                    rotation_note = ?
                WHERE credential_id = ?
                """,
                (expires_at, refreshed_at, f"Manual token refresh by {actor}", credential_id),
            )
            self._emit_event(
                conn,
                credential_id,
                record.lifecycle_state,
                "active",
                actor,
                "Manual token refresh",
            )
            conn.commit()

        updated = self.get_credential(credential_id)
        assert updated is not None
        return updated

    def get_credential(self, credential_id: str) -> CredentialLifecycleRecord | None:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT credential_id, profile_name, auth_mode, lifecycle_state,
                       created_at, validated_at, activated_at, last_validated_at,
                       validation_error, expires_at, rotation_note, created_by_actor
                FROM credential_lifecycle
                WHERE credential_id = ?
                LIMIT 1
                """,
                (credential_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_credentials(self) -> list[CredentialLifecycleRecord]:
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT credential_id, profile_name, auth_mode, lifecycle_state,
                       created_at, validated_at, activated_at, last_validated_at,
                       validation_error, expires_at, rotation_note, created_by_actor
                FROM credential_lifecycle
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_events(self, credential_id: str) -> list[CredentialLifecycleEvent]:
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT event_id, credential_id, from_state, to_state, actor, event_note, occurred_at
                FROM credential_lifecycle_events
                WHERE credential_id = ?
                ORDER BY occurred_at ASC
                """,
                (credential_id,),
            ).fetchall()
        return [
            CredentialLifecycleEvent(
                event_id=str(row[0]),
                credential_id=str(row[1]),
                from_state=str(row[2]) if row[2] else None,
                to_state=str(row[3]),
                actor=str(row[4]),
                event_note=str(row[5]) if row[5] else None,
                occurred_at=str(row[6]),
            )
            for row in rows
        ]

    def get_auth_strategy(self) -> dict[str, dict[str, str]]:
        """Return the auth-strategy decision table for all endpoint types."""
        return AUTH_STRATEGY


_service_instance: CredentialLifecycleService | None = None


def get_credential_lifecycle_service(
    settings: Settings | None = None,
) -> CredentialLifecycleService:
    global _service_instance  # noqa: PLW0603
    if _service_instance is None:
        s = settings or get_settings()
        _service_instance = CredentialLifecycleService(
            settings=s,
            db_path=s.credential_lifecycle_db_path,
        )
    return _service_instance
