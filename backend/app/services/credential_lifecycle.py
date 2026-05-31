from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx
from sqlalchemy import Column, String
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import Settings, get_settings
from app.db import make_engine

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


Base = declarative_base()


class _CredentialLifecycleRow(Base):
    __tablename__ = "credential_lifecycle"

    credential_id = Column(String, primary_key=True)
    profile_name = Column(String, nullable=False)
    auth_mode = Column(String, nullable=False)
    lifecycle_state = Column(String, nullable=False, default="created")
    created_at = Column(String, nullable=False)
    validated_at = Column(String, nullable=True)
    activated_at = Column(String, nullable=True)
    last_validated_at = Column(String, nullable=True)
    validation_error = Column(String, nullable=True)
    expires_at = Column(String, nullable=True)
    rotation_note = Column(String, nullable=True)
    created_by_actor = Column(String, nullable=False)


class _CredentialLifecycleEventRow(Base):
    __tablename__ = "credential_lifecycle_events"

    event_id = Column(String, primary_key=True)
    credential_id = Column(String, nullable=False, index=True)
    from_state = Column(String, nullable=True)
    to_state = Column(String, nullable=False)
    actor = Column(String, nullable=False)
    event_note = Column(String, nullable=True)
    occurred_at = Column(String, nullable=False)


class CredentialLifecycleService:
    def __init__(
        self,
        *,
        settings: Settings,
        db_path: str | None = None,
        db_url: str | None = None,
    ) -> None:
        self._settings = settings
        if db_url:
            url = db_url
        elif db_path:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            url = f"sqlite:///{Path(db_path).resolve()}"
        else:
            url = settings.database_url
        self._engine = make_engine(url)
        Base.metadata.create_all(self._engine)
        self._Session = sessionmaker(bind=self._engine, autoflush=False, autocommit=False)

    def _now(self) -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def _row_to_record(self, row: _CredentialLifecycleRow) -> CredentialLifecycleRecord:
        return CredentialLifecycleRecord(
            credential_id=row.credential_id,
            profile_name=row.profile_name,
            auth_mode=row.auth_mode,  # type: ignore[arg-type]
            lifecycle_state=row.lifecycle_state,  # type: ignore[arg-type]
            created_at=row.created_at,
            validated_at=row.validated_at,
            activated_at=row.activated_at,
            last_validated_at=row.last_validated_at,
            validation_error=row.validation_error,
            expires_at=row.expires_at,
            rotation_note=row.rotation_note,
            created_by_actor=row.created_by_actor,
        )

    def _emit_event(
        self,
        session,
        credential_id: str,
        from_state: str | None,
        to_state: str,
        actor: str,
        note: str | None = None,
    ) -> None:
        session.add(
            _CredentialLifecycleEventRow(
                event_id=str(uuid4()),
                credential_id=credential_id,
                from_state=from_state,
                to_state=to_state,
                actor=actor,
                event_note=note,
                occurred_at=self._now(),
            )
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
        with self._Session() as session:
            row = _CredentialLifecycleRow(
                credential_id=credential_id,
                profile_name=profile_name,
                auth_mode=auth_mode,
                lifecycle_state="created",
                created_at=now,
                created_by_actor=actor,
                expires_at=expires_at,
            )
            session.add(row)
            self._emit_event(session, credential_id, None, "created", actor, "Credential registered")
            session.commit()
        logger.info("credential.lifecycle.created", extra={"credential_id": credential_id, "auth_mode": auth_mode})
        record = self.get_credential(credential_id)
        assert record is not None
        return record

    def _call_wix_api_for_validation(self) -> tuple[bool, str | None]:
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
        if record.lifecycle_state not in VALID_TRANSITIONS or (
            "validated" not in VALID_TRANSITIONS.get(record.lifecycle_state, ())
            and "failed" not in VALID_TRANSITIONS.get(record.lifecycle_state, ())
        ):
            raise ValueError(f"Cannot validate credential in state '{record.lifecycle_state}'")

        if self._settings.wix_mock_mode:
            if credential_id.startswith("cred-fail-"):
                success, error = False, "Mock: credential ID starts with cred-fail-"
            else:
                success, error = True, None
        else:
            success, error = self._call_wix_api_for_validation()

        now = self._now()
        new_state: CredentialLifecycleState = "validated" if success else "failed"

        with self._Session() as session:
            row = session.query(_CredentialLifecycleRow).filter_by(credential_id=credential_id).first()
            if row is not None:
                row.lifecycle_state = new_state
                row.last_validated_at = now
                if new_state == "validated" and row.validated_at is None:
                    row.validated_at = now
                row.validation_error = error
                self._emit_event(
                    session, credential_id, record.lifecycle_state, new_state, actor,
                    None if success else f"Validation failed: {error}",
                )
                session.commit()

        logger.info("credential.lifecycle.validated", extra={"credential_id": credential_id, "success": success})
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
        with self._Session() as session:
            row = session.query(_CredentialLifecycleRow).filter_by(credential_id=credential_id).first()
            if row is not None:
                row.lifecycle_state = "active"
                row.activated_at = now
                self._emit_event(session, credential_id, record.lifecycle_state, "active", actor)
                session.commit()

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
            with self._Session() as session:
                row = session.query(_CredentialLifecycleRow).filter_by(credential_id=credential_id).first()
                if row is not None:
                    row.lifecycle_state = "expiring_soon"
                    self._emit_event(
                        session, credential_id, "active", "expiring_soon", "system",
                        f"Expires at {record.expires_at}; within {hours}h warning window",
                    )
                    session.commit()
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

        with self._Session() as session:
            row = session.query(_CredentialLifecycleRow).filter_by(credential_id=credential_id).first()
            if row is not None:
                row.lifecycle_state = "rotation_pending"
                row.rotation_note = f"Rotation initiated by {actor}"
                self._emit_event(
                    session, credential_id, old_record.lifecycle_state, "rotation_pending",
                    actor, "Rotation initiated",
                )
                session.commit()

        new_record = self.create_credential(
            profile_name=new_profile_name,
            auth_mode=new_auth_mode,
            actor=actor,
            expires_at=new_expires_at,
        )
        new_record = self.validate_credential(new_record.credential_id, actor=actor)

        if new_record.lifecycle_state == "failed":
            with self._Session() as session:
                row = session.query(_CredentialLifecycleRow).filter_by(credential_id=credential_id).first()
                if row is not None:
                    row.lifecycle_state = old_record.lifecycle_state
                    row.rotation_note = None
                    self._emit_event(
                        session, credential_id, "rotation_pending", old_record.lifecycle_state,
                        actor, "Rotation rolled back: new credential validation failed",
                    )
                    session.commit()
            raise RuntimeError(
                f"Rotation failed: new credential validation failed: {new_record.validation_error}"
            )

        new_record = self.activate_credential(new_record.credential_id, actor=actor)
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

        with self._Session() as session:
            row = session.query(_CredentialLifecycleRow).filter_by(credential_id=credential_id).first()
            if row is not None:
                row.lifecycle_state = "revoked"
                self._emit_event(
                    session, credential_id, record.lifecycle_state, "revoked", actor,
                    note or "Credential revoked",
                )
                session.commit()

        logger.info("credential.lifecycle.revoked", extra={"credential_id": credential_id})
        updated = self.get_credential(credential_id)
        assert updated is not None
        return updated

    def validate_no_mixed_modes(self, environment: str) -> None:
        if environment != "production":
            return
        with self._Session() as session:
            rows = (
                session.query(_CredentialLifecycleRow.auth_mode)
                .filter(
                    _CredentialLifecycleRow.lifecycle_state.in_(["active", "expiring_soon", "validated"])
                )
                .distinct()
                .all()
            )
        active_modes = {r.auth_mode for r in rows}
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

        with self._Session() as session:
            row = session.query(_CredentialLifecycleRow).filter_by(credential_id=credential_id).first()
            if row is not None:
                row.lifecycle_state = "active"
                row.expires_at = expires_at
                row.last_validated_at = refreshed_at
                row.validation_error = None
                row.rotation_note = f"Manual token refresh by {actor}"
                self._emit_event(session, credential_id, record.lifecycle_state, "active", actor, "Manual token refresh")
                session.commit()

        updated = self.get_credential(credential_id)
        assert updated is not None
        return updated

    def get_credential(self, credential_id: str) -> CredentialLifecycleRecord | None:
        with self._Session() as session:
            row = session.query(_CredentialLifecycleRow).filter_by(credential_id=credential_id).first()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_credentials(self) -> list[CredentialLifecycleRecord]:
        with self._Session() as session:
            rows = (
                session.query(_CredentialLifecycleRow)
                .order_by(_CredentialLifecycleRow.created_at.desc())
                .all()
            )
        return [self._row_to_record(r) for r in rows]

    def list_events(self, credential_id: str) -> list[CredentialLifecycleEvent]:
        with self._Session() as session:
            rows = (
                session.query(_CredentialLifecycleEventRow)
                .filter_by(credential_id=credential_id)
                .order_by(_CredentialLifecycleEventRow.occurred_at.asc())
                .all()
            )
        return [
            CredentialLifecycleEvent(
                event_id=r.event_id,
                credential_id=r.credential_id,
                from_state=r.from_state,
                to_state=r.to_state,
                actor=r.actor,
                event_note=r.event_note,
                occurred_at=r.occurred_at,
            )
            for r in rows
        ]

    def get_auth_strategy(self) -> dict[str, dict[str, str]]:
        return AUTH_STRATEGY


_service_instance: CredentialLifecycleService | None = None


def get_credential_lifecycle_service(
    settings: Settings | None = None,
) -> CredentialLifecycleService:
    global _service_instance  # noqa: PLW0603
    if _service_instance is None:
        s = settings or get_settings()
        _service_instance = CredentialLifecycleService(settings=s)
    return _service_instance
