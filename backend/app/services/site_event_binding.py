from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from app.core.config import Settings, get_settings

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
    credential_profile_id: str | None
    sync_policy_profile_id: str | None
    binding_created_at: str
    binding_verified_at: str | None
    verified_by_actor: str | None
    last_verification_error: str | None
    verification_evidence: dict[str, object]


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


class SiteEventBindingService:
    def __init__(self, db_path: str, verifier: WixBindingVerifier) -> None:
        self._db_path = str(Path(db_path))
        self._verifier = verifier
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS wix_site_event_binding (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    binding_id TEXT NOT NULL UNIQUE,
                    wix_site_id TEXT NOT NULL,
                    wix_event_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    app_installation_status TEXT NOT NULL,
                    credential_profile_id TEXT,
                    sync_policy_profile_id TEXT,
                    binding_created_at TEXT NOT NULL,
                    binding_verified_at TEXT,
                    verified_by_actor TEXT,
                    last_verification_error TEXT,
                    verification_evidence TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(wix_site_id, wix_event_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS event_activation (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wix_event_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    activated_at TEXT NOT NULL,
                    activated_by_actor TEXT NOT NULL
                )
                """
            )
            for column_sql in (
                "ALTER TABLE event_activation ADD COLUMN readiness_status TEXT NOT NULL DEFAULT 'ready'",
                "ALTER TABLE event_activation ADD COLUMN readiness_acknowledged INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE event_activation ADD COLUMN readiness_failed_checks TEXT NOT NULL DEFAULT '[]'",
                "ALTER TABLE event_activation ADD COLUMN readiness_recommended_actions TEXT NOT NULL DEFAULT '[]'",
            ):
                try:
                    conn.execute(column_sql)
                except sqlite3.OperationalError:
                    pass
            conn.commit()

    def _now(self) -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def _row_to_record(self, row: sqlite3.Row) -> WixSiteEventBindingRecord:
        return WixSiteEventBindingRecord(
            binding_id=row["binding_id"],
            wix_site_id=row["wix_site_id"],
            wix_event_id=row["wix_event_id"],
            status=row["status"],
            app_installation_status=row["app_installation_status"],
            credential_profile_id=row["credential_profile_id"],
            sync_policy_profile_id=row["sync_policy_profile_id"],
            binding_created_at=row["binding_created_at"],
            binding_verified_at=row["binding_verified_at"],
            verified_by_actor=row["verified_by_actor"],
            last_verification_error=row["last_verification_error"],
            verification_evidence=json.loads(row["verification_evidence"] or "{}"),
        )

    def create_binding(
        self,
        *,
        wix_site_id: str,
        wix_event_id: str,
        created_by_actor: str,
        credential_profile_id: str | None = None,
        sync_policy_profile_id: str | None = None,
        verify_immediately: bool = True,
    ) -> WixSiteEventBindingRecord:
        binding_id = str(uuid4())
        now = self._now()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO wix_site_event_binding (
                    binding_id,
                    wix_site_id,
                    wix_event_id,
                    status,
                    app_installation_status,
                    credential_profile_id,
                    sync_policy_profile_id,
                    binding_created_at,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    binding_id,
                    wix_site_id,
                    wix_event_id,
                    "pending",
                    "pending_install",
                    credential_profile_id,
                    sync_policy_profile_id,
                    now,
                    now,
                    now,
                ),
            )
            conn.commit()

        if verify_immediately:
            return self.verify_binding(binding_id=binding_id, verified_by_actor=created_by_actor)

        return self.get_binding(binding_id)

    def get_binding(self, binding_id: str) -> WixSiteEventBindingRecord:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM wix_site_event_binding WHERE binding_id = ? LIMIT 1",
                (binding_id,),
            ).fetchone()
        if row is None:
            raise ValueError("Binding not found")
        return self._row_to_record(row)

    def get_binding_by_event_id(self, wix_event_id: str) -> WixSiteEventBindingRecord | None:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM wix_site_event_binding WHERE wix_event_id = ? LIMIT 1",
                (wix_event_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_bindings(self, *, status: BindingStatus | None = None) -> list[WixSiteEventBindingRecord]:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            if status is None:
                rows = conn.execute(
                    "SELECT * FROM wix_site_event_binding ORDER BY created_at DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM wix_site_event_binding WHERE status = ? ORDER BY created_at DESC",
                    (status,),
                ).fetchall()
        return [self._row_to_record(row) for row in rows]

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

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                UPDATE wix_site_event_binding
                SET status = ?,
                    app_installation_status = ?,
                    binding_verified_at = ?,
                    verified_by_actor = ?,
                    last_verification_error = ?,
                    verification_evidence = ?,
                    updated_at = ?
                WHERE binding_id = ?
                """,
                (
                    status,
                    app_status,
                    verified_at,
                    actor,
                    verification.error,
                    json.dumps(evidence),
                    now,
                    binding_id,
                ),
            )
            conn.commit()

        return self.get_binding(binding_id)

    def get_verified_events(self) -> list[dict[str, str]]:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT wix_event_id, wix_site_id
                FROM wix_site_event_binding
                WHERE status = 'verified'
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [
            {
                "wix_event_id": row["wix_event_id"],
                "wix_site_id": row["wix_site_id"],
            }
            for row in rows
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
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO event_activation (
                    wix_event_id,
                    status,
                    activated_at,
                    activated_by_actor,
                    readiness_status,
                    readiness_acknowledged,
                    readiness_failed_checks,
                    readiness_recommended_actions
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(wix_event_id)
                DO UPDATE SET status=excluded.status,
                              activated_at=excluded.activated_at,
                              activated_by_actor=excluded.activated_by_actor,
                              readiness_status=excluded.readiness_status,
                              readiness_acknowledged=excluded.readiness_acknowledged,
                              readiness_failed_checks=excluded.readiness_failed_checks,
                              readiness_recommended_actions=excluded.readiness_recommended_actions
                """,
                (
                    wix_event_id,
                    "active",
                    now,
                    actor,
                    readiness_status,
                    1 if readiness_acknowledged else 0,
                    json.dumps(readiness_failed_checks),
                    json.dumps(readiness_recommended_actions),
                ),
            )
            conn.commit()

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
            db_path=settings.site_event_binding_db_path,
            verifier=WixBindingVerifier(settings),
        )
    return _site_event_binding_service
