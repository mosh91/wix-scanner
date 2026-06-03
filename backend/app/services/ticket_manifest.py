from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import time

from sqlalchemy import Column, String, Float, Integer
from sqlalchemy.orm import DeclarativeBase

from app.db import make_engine, make_session_factory
from app.services.offline_queue import get_offline_queue_service
from app.services.wix_client import get_wix_client


@dataclass(frozen=True)
class ManifestTicketRecord:
    event_id: str
    ticket_number: str
    manifest_state: str
    last_known_sync_ts: float
    source_revision: str
    last_seen_scan_at: float | None


@dataclass(frozen=True)
class ManifestSyncStatus:
    event_id: str
    total_tickets: int
    checked_in_tickets: int
    stale: bool
    last_known_sync_ts: float
    source_revision: str


# ── ORM models ───────────────────────────────────────────────────────────────


class _Base(DeclarativeBase):
    pass


class _ManifestRow(_Base):
    __tablename__ = "event_ticket_manifest"
    event_id = Column(String, nullable=False, primary_key=True)
    ticket_number = Column(String, nullable=False, primary_key=True)
    manifest_state = Column(String, nullable=False)
    last_known_sync_ts = Column(Float, nullable=False)
    source_revision = Column(String, nullable=False)
    last_seen_scan_at = Column(Float, nullable=True)


class _ManifestSyncRow(_Base):
    __tablename__ = "event_manifest_sync"
    event_id = Column(String, primary_key=True)
    last_known_sync_ts = Column(Float, nullable=False)
    source_revision = Column(String, nullable=False)
    total_tickets = Column(Integer, nullable=False)
    checked_in_tickets = Column(Integer, nullable=False)


class TicketManifestService:
    def __init__(self, database_file: Path | None = None, db_url: str | None = None) -> None:
        if db_url is not None:
            url = db_url
        elif database_file is not None:
            url = f"sqlite:///{database_file}"
            database_file.parent.mkdir(parents=True, exist_ok=True)
        else:
            # Legacy default: use local SQLite file (backward-compat with pre-Postgres installs)
            default_file = Path("./data/ticket_manifest.db")
            default_file.parent.mkdir(parents=True, exist_ok=True)
            url = f"sqlite:///{default_file}"
        self._engine = make_engine(url)
        self._session_factory = make_session_factory(self._engine)
        self._lock = Lock()
        self._tracked_event_ids: set[str] = set()
        _Base.metadata.create_all(self._engine)

    def track_event(self, event_id: str) -> None:
        with self._lock:
            self._tracked_event_ids.add(event_id)

    def tracked_events(self) -> list[str]:
        with self._lock:
            return sorted(self._tracked_event_ids)

    def _sync_horizon_seconds(self) -> int:
        return 300

    def sync_event_from_wix(self, event_id: str) -> ManifestSyncStatus:
        self.track_event(event_id)
        client = get_wix_client()
        tickets = client.list_tickets(event_id=event_id)

        now = time()
        source_revision = f"{int(now)}:{len(tickets)}"
        total = len(tickets)
        checked_in = len([t for t in tickets if t.get("checked_in")])

        from sqlalchemy import select
        with self._session_factory() as session:
            for item in tickets:
                ticket_number = str(item["ticket_number"]).upper()
                state = "checked_in" if bool(item.get("checked_in")) else "not_checked_in"
                existing = session.execute(
                    select(_ManifestRow)
                    .where(_ManifestRow.event_id == event_id)
                    .where(_ManifestRow.ticket_number == ticket_number)
                ).scalar_one_or_none()
                if existing is None:
                    session.add(_ManifestRow(
                        event_id=event_id,
                        ticket_number=ticket_number,
                        manifest_state=state,
                        last_known_sync_ts=now,
                        source_revision=source_revision,
                        last_seen_scan_at=None,
                    ))
                else:
                    existing.manifest_state = state
                    existing.last_known_sync_ts = now
                    existing.source_revision = source_revision

            sync_row = session.get(_ManifestSyncRow, event_id)
            if sync_row is None:
                session.add(_ManifestSyncRow(
                    event_id=event_id,
                    last_known_sync_ts=now,
                    source_revision=source_revision,
                    total_tickets=total,
                    checked_in_tickets=checked_in,
                ))
            else:
                sync_row.last_known_sync_ts = now
                sync_row.source_revision = source_revision
                sync_row.total_tickets = total
                sync_row.checked_in_tickets = checked_in
            session.commit()

        get_offline_queue_service().remember_manifest_tickets(
            event_id=event_id,
            ticket_numbers=[str(item["ticket_number"]).upper() for item in tickets],
        )

        return ManifestSyncStatus(
            event_id=event_id,
            total_tickets=total,
            checked_in_tickets=checked_in,
            stale=False,
            last_known_sync_ts=now,
            source_revision=source_revision,
        )

    def sync_tracked_events_once(self) -> int:
        synced = 0
        for event_id in self.tracked_events():
            try:
                self.sync_event_from_wix(event_id)
            except Exception:
                continue
            synced += 1
        return synced

    def get_ticket(self, *, event_id: str, ticket_number: str) -> ManifestTicketRecord | None:
        normalized_ticket = ticket_number.strip().upper()
        from sqlalchemy import select
        with self._session_factory() as session:
            existing = session.execute(
                select(_ManifestRow)
                .where(_ManifestRow.event_id == event_id)
                .where(_ManifestRow.ticket_number == normalized_ticket)
            ).scalar_one_or_none()

        if existing is None:
            return None

        return ManifestTicketRecord(
            event_id=existing.event_id,
            ticket_number=existing.ticket_number,
            manifest_state=existing.manifest_state,
            last_known_sync_ts=float(existing.last_known_sync_ts),
            source_revision=existing.source_revision,
            last_seen_scan_at=float(existing.last_seen_scan_at) if existing.last_seen_scan_at is not None else None,
        )

    def list_tickets(self, *, event_id: str, limit: int = 10) -> list[ManifestTicketRecord]:
        from sqlalchemy import select
        with self._session_factory() as session:
            rows = session.execute(
                select(_ManifestRow)
                .where(_ManifestRow.event_id == event_id)
                .order_by(_ManifestRow.ticket_number)
                .limit(max(1, min(limit, 50)))
            ).scalars().all()

        return [
            ManifestTicketRecord(
                event_id=r.event_id,
                ticket_number=r.ticket_number,
                manifest_state=r.manifest_state,
                last_known_sync_ts=float(r.last_known_sync_ts),
                source_revision=r.source_revision,
                last_seen_scan_at=float(r.last_seen_scan_at) if r.last_seen_scan_at is not None else None,
            )
            for r in rows
        ]

    def list_all_tickets(self, *, event_id: str) -> list[ManifestTicketRecord]:
        from sqlalchemy import select
        with self._session_factory() as session:
            rows = session.execute(
                select(_ManifestRow)
                .where(_ManifestRow.event_id == event_id)
                .order_by(_ManifestRow.ticket_number)
            ).scalars().all()

        return [
            ManifestTicketRecord(
                event_id=r.event_id,
                ticket_number=r.ticket_number,
                manifest_state=r.manifest_state,
                last_known_sync_ts=float(r.last_known_sync_ts),
                source_revision=r.source_revision,
                last_seen_scan_at=float(r.last_seen_scan_at) if r.last_seen_scan_at is not None else None,
            )
            for r in rows
        ]

    def _upsert_ticket_state(self, *, event_id: str, ticket_number: str, manifest_state: str) -> None:
        normalized_ticket = ticket_number.strip().upper()
        now = time()
        source_revision = f"reconciliation:{int(now)}"
        from sqlalchemy import select
        with self._session_factory() as session:
            existing = session.execute(
                select(_ManifestRow)
                .where(_ManifestRow.event_id == event_id)
                .where(_ManifestRow.ticket_number == normalized_ticket)
            ).scalar_one_or_none()
            if existing is None:
                session.add(_ManifestRow(
                    event_id=event_id,
                    ticket_number=normalized_ticket,
                    manifest_state=manifest_state,
                    last_known_sync_ts=now,
                    source_revision=source_revision,
                    last_seen_scan_at=now if manifest_state == "checked_in" else None,
                ))
            else:
                existing.manifest_state = manifest_state
                existing.last_known_sync_ts = now
                existing.source_revision = source_revision
                existing.last_seen_scan_at = now if manifest_state == "checked_in" else None
            session.commit()

    def mark_checked_in(self, *, event_id: str, ticket_number: str) -> None:
        self._upsert_ticket_state(event_id=event_id, ticket_number=ticket_number, manifest_state="checked_in")

    def mark_not_checked_in(self, *, event_id: str, ticket_number: str) -> None:
        self._upsert_ticket_state(event_id=event_id, ticket_number=ticket_number, manifest_state="not_checked_in")

    def status(self, *, event_id: str) -> ManifestSyncStatus:
        with self._session_factory() as session:
            row = session.get(_ManifestSyncRow, event_id)

        if row is None:
            return ManifestSyncStatus(
                event_id=event_id,
                total_tickets=0,
                checked_in_tickets=0,
                stale=True,
                last_known_sync_ts=0.0,
                source_revision="none",
            )

        stale = (time() - float(row.last_known_sync_ts)) > self._sync_horizon_seconds()
        return ManifestSyncStatus(
            event_id=row.event_id,
            total_tickets=int(row.total_tickets),
            checked_in_tickets=int(row.checked_in_tickets),
            stale=stale,
            last_known_sync_ts=float(row.last_known_sync_ts),
            source_revision=row.source_revision,
        )

    def reset_for_tests(self) -> None:
        from sqlalchemy import delete
        with self._session_factory() as session:
            session.execute(delete(_ManifestRow))
            session.execute(delete(_ManifestSyncRow))
            session.commit()
        with self._lock:
            self._tracked_event_ids.clear()


_manifest_service: TicketManifestService | None = None


def get_ticket_manifest_service() -> TicketManifestService:
    global _manifest_service
    if _manifest_service is None:
        _manifest_service = TicketManifestService()
    return _manifest_service
