from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from sqlalchemy import Column, String, Integer, Text, UniqueConstraint

from app.core.config import Settings, get_settings
from app.db import make_engine, make_session_factory

BindingStatus = Literal["pending", "verified", "unverified", "revoked"]
AppInstallationStatus = Literal["pending_install", "installed", "uninstalled", "failed"]


@dataclass(frozen=True)
class WixBindingVerificationResult:
    site_exists: bool
    event_exists: bool
    app_installed: bool
    error: str | None = None


class WixBindingVerifier:
    """Verifies site-event bindings against Wix integration state."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def verify(self, wix_site_id: str, wix_event_id: str) -> WixBindingVerificationResult:
        # In mock mode we use deterministic IDs so tests can validate all state transitions.
        if self._settings.wix_mock_mode:
            site_exists = wix_site_id.startswith("site-")
            event_exists = wix_event_id.startswith("event-")
            app_installed = site_exists and event_exists and not wix_site_id.endswith("-noapp")
            error: str | None = None
            if not site_exists:
                error = "Wix site not found."
            elif not event_exists:
                error = "Wix event not found."
            elif not app_installed:
                error = "Wix app not installed on site."
            return WixBindingVerificationResult(
                site_exists=site_exists,
                event_exists=event_exists,
                app_installed=app_installed,
                error=error,
            )

        return WixBindingVerificationResult(
            site_exists=False,
            event_exists=False,
            app_installed=False,
            error="Live Wix site/event verification is not configured.",
        )


@dataclass(frozen=True)
class WixSiteEventBindingRecord:
    binding_id: str
    wix_site_id: str
    wix_event_id: str
    status: BindingStatus
    app_installation_status: AppInstallationStatus
    binding_verified_at: str | None
    last_verification_error: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class EventActivationRecord:
    wix_event_id: str
    status: str
    activated_at: str
    activated_by_actor: str
    readiness_status: str
    readiness_acknowledged: bool
    readiness_failed_checks: list[str]
    readiness_recommended_actions: list[str]


# ── ORM models ───────────────────────────────────────────────────────────────

from sqlalchemy.orm import DeclarativeBase  # noqa: E402


class _Base(DeclarativeBase):
    pass


class _BindingRow(_Base):
    __tablename__ = "wix_site_event_binding"
    id = Column(String, primary_key=True)  # UUID from database
    event_id = Column(String, nullable=False)  # UUID reference to event table
    wix_site_id = Column(String, nullable=False)
    wix_event_id = Column(String, nullable=False)
    binding_id = Column(String, nullable=True)
    status = Column(String, nullable=False)
    app_installation_status = Column(String, nullable=False)
    binding_verified_at = Column(String, nullable=True)
    scopes_verified_at = Column(String, nullable=True)
    last_verification_error = Column(Text, nullable=True)
    binding_metadata = Column("metadata", Text, nullable=False, default="{}")
    created_by = Column(String, nullable=True)  # UUID
    updated_by = Column(String, nullable=True)  # UUID
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class _EventActivationRow(_Base):
    __tablename__ = "event_activation"
    id = Column(Integer, primary_key=True, autoincrement=True)
    wix_event_id = Column(String, nullable=False, unique=True)
    status = Column(String, nullable=False)
    activated_at = Column(String, nullable=False)
    activated_by_actor = Column(String, nullable=False)
    readiness_status = Column(String, nullable=False, default="ready")
    readiness_acknowledged = Column(Integer, nullable=False, default=0)
    readiness_failed_checks = Column(Text, nullable=False, default="[]")
    readiness_recommended_actions = Column(Text, nullable=False, default="[]")


class SiteEventBindingService:
    def __init__(self, db_path: str | None = None, db_url: str | None = None, *, verifier: WixBindingVerifier) -> None:
        if db_path is not None:
            url = f"sqlite:///{db_path}"
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        else:
            url = db_url or get_settings().database_url
        self._verifier = verifier
        self._engine = make_engine(url)
        self._session_factory = make_session_factory(self._engine)
        _Base.metadata.create_all(self._engine)

    def _now(self) -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _to_str(v) -> str | None:
        if v is None:
            return None
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return str(v)

    def _row_to_record(self, row: _BindingRow) -> WixSiteEventBindingRecord:
        return WixSiteEventBindingRecord(
            binding_id=str(row.binding_id or row.id),
            wix_site_id=row.wix_site_id,
            wix_event_id=row.wix_event_id,
            status=row.status,
            app_installation_status=row.app_installation_status,
            binding_verified_at=self._to_str(row.binding_verified_at),
            last_verification_error=row.last_verification_error,
            created_at=self._to_str(row.created_at),
            updated_at=self._to_str(row.updated_at),
        )

    def create_binding(
        self,
        *,
        wix_site_id: str,
        wix_event_id: str,
        created_by_actor: str,
        verify_immediately: bool = True,
    ) -> WixSiteEventBindingRecord:
        from sqlalchemy import select, text
        binding_id = str(uuid4())
        now = self._now()
        with self._session_factory() as session:
            # Look up the event by wix_event_id to get the real FK
            event_row = session.execute(
                text("SELECT id FROM event WHERE wix_event_id = :wix_event_id"),
                {"wix_event_id": wix_event_id},
            ).fetchone()
            if event_row is None:
                raise ValueError(f"Event with wix_event_id={wix_event_id!r} not found. Create the event first.")
            event_id = str(event_row[0])
            session.add(_BindingRow(
                id=binding_id,
                event_id=event_id,
                binding_id=binding_id,
                wix_site_id=wix_site_id,
                wix_event_id=wix_event_id,
                status="pending",
                app_installation_status="pending_install",
                created_at=now,
                updated_at=now,
            ))
            session.commit()

        if verify_immediately:
            return self.verify_binding(binding_id=binding_id, verified_by_actor=created_by_actor)

        return self.get_binding(binding_id)

    def get_binding(self, binding_id: str) -> WixSiteEventBindingRecord:
        from sqlalchemy import select
        with self._session_factory() as session:
            row = session.execute(
                select(_BindingRow).where(_BindingRow.binding_id == binding_id)
            ).scalar_one_or_none()
        if row is None:
            raise ValueError("Binding not found")
        return self._row_to_record(row)

    def get_binding_by_event_id(self, wix_event_id: str) -> WixSiteEventBindingRecord | None:
        from sqlalchemy import select
        with self._session_factory() as session:
            row = session.execute(
                select(_BindingRow).where(_BindingRow.wix_event_id == wix_event_id)
            ).scalar_one_or_none()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_bindings(self, *, status: BindingStatus | None = None) -> list[WixSiteEventBindingRecord]:
        from sqlalchemy import select, desc
        with self._session_factory() as session:
            q = select(_BindingRow).order_by(desc(_BindingRow.created_at))
            if status is not None:
                q = q.where(_BindingRow.status == status)
            rows = session.execute(q).scalars().all()
        return [self._row_to_record(r) for r in rows]

    def verify_binding(self, *, binding_id: str, verified_by_actor: str) -> WixSiteEventBindingRecord:
        existing = self.get_binding(binding_id)
        verification = self._verifier.verify(existing.wix_site_id, existing.wix_event_id)
        now = self._now()

        if not verification.site_exists or not verification.event_exists:
            status: BindingStatus = "unverified"
            app_status: AppInstallationStatus = "failed"
            verified_at: str | None = None
            actor: str | None = None
        elif not verification.app_installed:
            status = "pending"
            app_status = "uninstalled"
            verified_at = None
            actor = None
        else:
            status = "verified"
            app_status = "installed"
            verified_at = now
            actor = verified_by_actor

        evidence = {
            "checked_at": now,
            "checked_by_actor": verified_by_actor,
            "site_exists": verification.site_exists,
            "event_exists": verification.event_exists,
            "app_installed": verification.app_installed,
            "error": verification.error,
        }

        from sqlalchemy import select
        with self._session_factory() as session:
            row = session.execute(
                select(_BindingRow).where(_BindingRow.binding_id == binding_id)
            ).scalar_one_or_none()
            if row is not None:
                row.status = status
                row.app_installation_status = app_status
                row.binding_verified_at = verified_at
                row.verified_by_actor = actor
                row.last_verification_error = verification.error
                row.verification_evidence = json.dumps(evidence)
                row.updated_at = now
            session.commit()

        return self.get_binding(binding_id)

    def get_verified_events(self) -> list[dict[str, str]]:
        from sqlalchemy import select, desc
        with self._session_factory() as session:
            rows = session.execute(
                select(_BindingRow)
                .where(_BindingRow.status == "verified")
                .order_by(desc(_BindingRow.created_at))
            ).scalars().all()
        return [
            {"wix_event_id": r.wix_event_id, "wix_site_id": r.wix_site_id}
            for r in rows
        ]

    def activate_event(self, *, wix_event_id: str, actor: str) -> EventActivationRecord:
        return self.activate_event_with_readiness(
            wix_event_id=wix_event_id,
            actor=actor,
            readiness_status="ready",
            readiness_acknowledged=False,
            readiness_failed_checks=[],
            readiness_recommended_actions=[],
        )

    def activate_event_with_readiness(
        self,
        *,
        wix_event_id: str,
        actor: str,
        readiness_status: str,
        readiness_acknowledged: bool,
        readiness_failed_checks: list[str],
        readiness_recommended_actions: list[str],
    ) -> EventActivationRecord:
        verified_events = {row["wix_event_id"] for row in self.get_verified_events()}
        if wix_event_id not in verified_events:
            raise PermissionError("Event activation blocked: no verified Wix site-event binding")

        now = self._now()
        from sqlalchemy import select
        with self._session_factory() as session:
            existing = session.execute(
                select(_EventActivationRow).where(_EventActivationRow.wix_event_id == wix_event_id)
            ).scalar_one_or_none()
            if existing is None:
                session.add(_EventActivationRow(
                    wix_event_id=wix_event_id,
                    status="active",
                    activated_at=now,
                    activated_by_actor=actor,
                    readiness_status=readiness_status,
                    readiness_acknowledged=1 if readiness_acknowledged else 0,
                    readiness_failed_checks=json.dumps(readiness_failed_checks),
                    readiness_recommended_actions=json.dumps(readiness_recommended_actions),
                ))
            else:
                existing.status = "active"
                existing.activated_at = now
                existing.activated_by_actor = actor
                existing.readiness_status = readiness_status
                existing.readiness_acknowledged = 1 if readiness_acknowledged else 0
                existing.readiness_failed_checks = json.dumps(readiness_failed_checks)
                existing.readiness_recommended_actions = json.dumps(readiness_recommended_actions)
            session.commit()

        return EventActivationRecord(
            wix_event_id=wix_event_id,
            status="active",
            activated_at=now,
            activated_by_actor=actor,
            readiness_status=readiness_status,
            readiness_acknowledged=readiness_acknowledged,
            readiness_failed_checks=readiness_failed_checks,
            readiness_recommended_actions=readiness_recommended_actions,
        )


_site_event_binding_service: SiteEventBindingService | None = None


def set_site_event_binding_service(service: SiteEventBindingService) -> None:
    global _site_event_binding_service
    _site_event_binding_service = service


def get_site_event_binding_service() -> SiteEventBindingService:
    global _site_event_binding_service
    if _site_event_binding_service is None:
        settings = get_settings()
        _site_event_binding_service = SiteEventBindingService(
            verifier=WixBindingVerifier(settings),
        )
    return _site_event_binding_service
