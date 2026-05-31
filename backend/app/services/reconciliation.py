from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import time
from uuid import uuid4

from sqlalchemy import Column, String, Integer, Text, Index
from sqlalchemy.orm import DeclarativeBase, Session

from app.core.config import get_settings
from app.db import make_engine, make_session_factory
from app.services.offline_queue import get_offline_queue_service
from app.services.ticket_manifest import ManifestTicketRecord, get_ticket_manifest_service
from app.services.wix_client import get_wix_client

ReconciliationState = str


class _Base(DeclarativeBase):
    pass


class _RunRow(_Base):
    __tablename__ = "reconciliation_run"
    run_id = Column(String, primary_key=True)
    event_id = Column(String, nullable=False)
    status = Column(String, nullable=False)
    reconciliation_state = Column(String, nullable=False)
    drift_count = Column(Integer, nullable=False, default=0)
    resolved_count = Column(Integer, nullable=False, default=0)
    conflict_count = Column(Integer, nullable=False, default=0)
    started_at = Column(String, nullable=False)
    finished_at = Column(String, nullable=True)
    triggered_by_actor = Column(String, nullable=False)
    notes = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_reconciliation_run_event_started", "event_id", "started_at"),
    )


class _ItemRow(_Base):
    __tablename__ = "reconciliation_item"
    item_id = Column(String, primary_key=True)
    run_id = Column(String, nullable=False)
    event_id = Column(String, nullable=False)
    ticket_number = Column(String, nullable=False)
    reconciliation_state = Column(String, nullable=False)
    local_result = Column(String, nullable=True)
    wix_result = Column(String, nullable=True)
    resolution_result = Column(String, nullable=True)
    detail_json = Column(Text, nullable=False)
    resolved_at = Column(String, nullable=True)
    conflict_resolution_notes = Column(Text, nullable=True)
    resolved_by_actor = Column(String, nullable=True)

    __table_args__ = (
        Index("idx_reconciliation_item_run", "run_id"),
    )


@dataclass(frozen=True)
class ReconciliationItem:
    item_id: str
    run_id: str
    event_id: str
    ticket_number: str
    reconciliation_state: ReconciliationState
    local_result: str | None
    wix_result: str | None
    resolution_result: str | None
    detail: dict[str, object]
    resolved_at: str | None
    conflict_resolution_notes: str | None
    resolved_by_actor: str | None


@dataclass(frozen=True)
class ReconciliationRun:
    run_id: str
    event_id: str
    status: str
    reconciliation_state: ReconciliationState
    drift_count: int
    resolved_count: int
    conflict_count: int
    started_at: str
    finished_at: str | None
    triggered_by_actor: str
    notes: str | None


@dataclass(frozen=True)
class ReconciliationReport:
    run: ReconciliationRun
    items: list[ReconciliationItem]


class ReconciliationService:
    def __init__(self, db_path: str | None = None, db_url: str | None = None) -> None:
        settings = get_settings()
        if db_path is not None:
            url = f"sqlite:///{db_path}"
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        else:
            url = db_url or settings.database_url
        self._engine = make_engine(url)
        self._session_factory = make_session_factory(self._engine)
        self._manifest = get_ticket_manifest_service()
        self._queue = get_offline_queue_service()
        _Base.metadata.create_all(self._engine)

    def _now_iso(self) -> str:
        return datetime.utcnow().isoformat() + "Z"

    def _to_run(self, row: _RunRow) -> ReconciliationRun:
        return ReconciliationRun(
            run_id=row.run_id,
            event_id=row.event_id,
            status=row.status,
            reconciliation_state=row.reconciliation_state,
            drift_count=int(row.drift_count),
            resolved_count=int(row.resolved_count),
            conflict_count=int(row.conflict_count),
            started_at=row.started_at,
            finished_at=row.finished_at,
            triggered_by_actor=row.triggered_by_actor,
            notes=row.notes,
        )

    def _to_item(self, row: _ItemRow) -> ReconciliationItem:
        return ReconciliationItem(
            item_id=row.item_id,
            run_id=row.run_id,
            event_id=row.event_id,
            ticket_number=row.ticket_number,
            reconciliation_state=row.reconciliation_state,
            local_result=row.local_result,
            wix_result=row.wix_result,
            resolution_result=row.resolution_result,
            detail=json.loads(row.detail_json),
            resolved_at=row.resolved_at,
            conflict_resolution_notes=row.conflict_resolution_notes,
            resolved_by_actor=row.resolved_by_actor,
        )

    def _parse_wix_checked_in_at(self, value: object | None) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except ValueError:
                return None
        return None

    def _is_conflict(self, *, local_ticket: ManifestTicketRecord, wix_checked_in_at: float | None) -> bool:
        if local_ticket.last_seen_scan_at is None or wix_checked_in_at is None:
            return False
        return abs(local_ticket.last_seen_scan_at - wix_checked_in_at) > 120

    def run_reconciliation(self, *, event_id: str, actor: str = "system", notes: str | None = None) -> ReconciliationReport:
        started_at = self._now_iso()
        run_id = str(uuid4())

        with self._session_factory() as session:
            session.add(_RunRow(
                run_id=run_id,
                event_id=event_id,
                status="running",
                reconciliation_state="in_sync",
                drift_count=0,
                resolved_count=0,
                conflict_count=0,
                started_at=started_at,
                triggered_by_actor=actor,
                notes=notes,
            ))
            session.commit()

        # Retry pending jobs before classifying unresolved drift.
        self._queue.process_pending_once(max_items=100)
        pending_jobs = self._queue.list_pending_jobs(event_id=event_id, limit=500)
        pending_tickets = {job.ticket_number.strip().upper() for job in pending_jobs}

        local_tickets = {row.ticket_number: row for row in self._manifest.list_all_tickets(event_id=event_id)}
        wix_rows = get_wix_client().list_tickets(event_id=event_id, limit=500)
        wix_tickets = {str(row.get("ticket_number", "")).strip().upper(): row for row in wix_rows if row.get("ticket_number")}

        ticket_numbers = sorted(set(local_tickets).union(wix_tickets).union(pending_tickets))

        items: list[ReconciliationItem] = []
        drift_count = 0
        resolved_count = 0
        conflict_count = 0
        has_local_pending = False
        has_local_only = False
        has_wix_only = False

        for ticket_number in ticket_numbers:
            local_ticket = local_tickets.get(ticket_number)
            wix_ticket = wix_tickets.get(ticket_number)

            local_checked = local_ticket is not None and local_ticket.manifest_state == "checked_in"
            wix_checked = bool(wix_ticket and wix_ticket.get("checked_in"))
            local_pending = ticket_number in pending_tickets

            reconciliation_state: ReconciliationState = "in_sync"
            local_result = "checked_in" if local_checked else "not_checked_in"
            wix_result = "checked_in" if wix_checked else "not_checked_in"
            resolution_result = "none"
            resolved_at: str | None = None
            conflict_resolution_notes: str | None = None
            resolved_by_actor: str | None = None
            detail: dict[str, object] = {
                "local_pending": local_pending,
                "local_last_seen_scan_at": local_ticket.last_seen_scan_at if local_ticket else None,
                "wix_checked_in_at": wix_ticket.get("checked_in_at") if wix_ticket else None,
            }

            if local_pending and not wix_checked:
                reconciliation_state = "local_pending"
                resolution_result = "retry_pending"
                detail["action"] = "retry_pending_queue"
                drift_count += 1
                has_local_pending = True
            elif local_checked and wix_checked:
                wix_checked_in_at = self._parse_wix_checked_in_at(wix_ticket.get("checked_in_at") if wix_ticket else None)
                if local_ticket is not None and self._is_conflict(local_ticket=local_ticket, wix_checked_in_at=wix_checked_in_at):
                    reconciliation_state = "conflict"
                    resolution_result = "needs_manual_review"
                    detail["action"] = "manual_review_required"
                    drift_count += 1
                    conflict_count += 1
                else:
                    reconciliation_state = "in_sync"
                    resolution_result = "already_in_sync"
            elif local_checked and not wix_checked:
                reconciliation_state = "local_only"
                self._manifest.mark_not_checked_in(event_id=event_id, ticket_number=ticket_number)
                resolution_result = "wix_wins_local_reset"
                resolved_at = self._now_iso()
                resolved_by_actor = actor
                conflict_resolution_notes = "Wix source-of-truth applied: local state reset to not_checked_in."
                detail["action"] = "set_local_not_checked_in"
                drift_count += 1
                resolved_count += 1
                has_local_only = True
            elif (not local_checked) and wix_checked:
                reconciliation_state = "wix_only"
                self._manifest.mark_checked_in(event_id=event_id, ticket_number=ticket_number)
                resolution_result = "wix_wins_local_updated"
                resolved_at = self._now_iso()
                resolved_by_actor = actor
                conflict_resolution_notes = "Wix source-of-truth applied: local state set to checked_in."
                detail["action"] = "set_local_checked_in"
                drift_count += 1
                resolved_count += 1
                has_wix_only = True

            item = ReconciliationItem(
                item_id=str(uuid4()),
                run_id=run_id,
                event_id=event_id,
                ticket_number=ticket_number,
                reconciliation_state=reconciliation_state,
                local_result=local_result,
                wix_result=wix_result,
                resolution_result=resolution_result,
                detail=detail,
                resolved_at=resolved_at,
                conflict_resolution_notes=conflict_resolution_notes,
                resolved_by_actor=resolved_by_actor,
            )
            items.append(item)

        if conflict_count > 0:
            overall_state = "conflict"
        elif has_local_pending:
            overall_state = "local_pending"
        elif has_local_only:
            overall_state = "local_only"
        elif has_wix_only:
            overall_state = "wix_only"
        else:
            overall_state = "in_sync"

        finished_at = self._now_iso()
        with self._session_factory() as session:
            for item in items:
                session.add(_ItemRow(
                    item_id=item.item_id,
                    run_id=item.run_id,
                    event_id=item.event_id,
                    ticket_number=item.ticket_number,
                    reconciliation_state=item.reconciliation_state,
                    local_result=item.local_result,
                    wix_result=item.wix_result,
                    resolution_result=item.resolution_result,
                    detail_json=json.dumps(item.detail, separators=(",", ":")),
                    resolved_at=item.resolved_at,
                    conflict_resolution_notes=item.conflict_resolution_notes,
                    resolved_by_actor=item.resolved_by_actor,
                ))
            run_row = session.get(_RunRow, run_id)
            if run_row is not None:
                run_row.status = "completed"
                run_row.reconciliation_state = overall_state
                run_row.drift_count = drift_count
                run_row.resolved_count = resolved_count
                run_row.conflict_count = conflict_count
                run_row.finished_at = finished_at
            session.commit()

        run = self.get_run(run_id=run_id)
        if run is None:
            raise RuntimeError("Failed to load reconciliation run after execution")
        return ReconciliationReport(run=run, items=items)

    def get_run(self, *, run_id: str) -> ReconciliationRun | None:
        with self._session_factory() as session:
            row = session.get(_RunRow, run_id)
        if row is None:
            return None
        return self._to_run(row)

    def list_runs(self, *, event_id: str, limit: int = 20) -> list[ReconciliationRun]:
        from sqlalchemy import select, desc
        with self._session_factory() as session:
            rows = session.execute(
                select(_RunRow)
                .where(_RunRow.event_id == event_id)
                .order_by(desc(_RunRow.started_at))
                .limit(max(1, min(limit, 100)))
            ).scalars().all()
        return [self._to_run(r) for r in rows]

    def list_conflicts(self, *, event_id: str, run_id: str | None = None, limit: int = 100) -> list[ReconciliationItem]:
        from sqlalchemy import select, desc
        with self._session_factory() as session:
            effective_run_id = run_id
            if effective_run_id is None:
                latest = session.execute(
                    select(_RunRow.run_id)
                    .where(_RunRow.event_id == event_id)
                    .order_by(desc(_RunRow.started_at))
                    .limit(1)
                ).scalar_one_or_none()
                if latest is None:
                    return []
                effective_run_id = latest

            rows = session.execute(
                select(_ItemRow)
                .where(_ItemRow.run_id == effective_run_id)
                .where(_ItemRow.reconciliation_state == "conflict")
                .order_by(_ItemRow.ticket_number)
                .limit(max(1, min(limit, 200)))
            ).scalars().all()
        return [self._to_item(r) for r in rows]

    def resolve_conflict(
        self,
        *,
        item_id: str,
        actor: str,
        resolution: str,
        note: str | None,
    ) -> ReconciliationItem:
        if resolution not in {"accept_wix", "keep_local"}:
            raise ValueError("Unsupported resolution. Expected accept_wix or keep_local.")

        from sqlalchemy import select, func
        with self._session_factory() as session:
            row = session.get(_ItemRow, item_id)
            if row is None:
                raise ValueError("Reconciliation item not found")
            item = self._to_item(row)
            if item.reconciliation_state != "conflict":
                raise ValueError("Only conflict items can be resolved manually")

            if resolution == "accept_wix":
                if item.wix_result == "checked_in":
                    self._manifest.mark_checked_in(event_id=item.event_id, ticket_number=item.ticket_number)
                else:
                    self._manifest.mark_not_checked_in(event_id=item.event_id, ticket_number=item.ticket_number)
            else:
                if item.local_result == "checked_in":
                    self._manifest.mark_checked_in(event_id=item.event_id, ticket_number=item.ticket_number)
                else:
                    self._manifest.mark_not_checked_in(event_id=item.event_id, ticket_number=item.ticket_number)

            resolved_at = self._now_iso()
            resolution_result = "manual_accept_wix" if resolution == "accept_wix" else "manual_keep_local"
            row.reconciliation_state = "in_sync"
            row.resolution_result = resolution_result
            row.resolved_at = resolved_at
            row.conflict_resolution_notes = note or ""
            row.resolved_by_actor = actor

            unresolved = session.execute(
                select(func.count())
                .select_from(_ItemRow)
                .where(_ItemRow.run_id == item.run_id)
                .where(_ItemRow.reconciliation_state == "conflict")
            ).scalar_one()

            run_row = session.get(_RunRow, item.run_id)
            if run_row is not None:
                if unresolved == 0:
                    run_row.conflict_count = 0
                    if run_row.drift_count == run_row.resolved_count + 1:
                        run_row.reconciliation_state = "in_sync"
                    run_row.resolved_count = run_row.resolved_count + 1
                else:
                    run_row.conflict_count = int(unresolved)
                    run_row.resolved_count = run_row.resolved_count + 1

            session.commit()
            # Refresh the row after commit
            updated = session.get(_ItemRow, item_id)
            if updated is None:
                raise RuntimeError("Conflict item disappeared after resolution")
            return self._to_item(updated)


_reconciliation_service: ReconciliationService | None = None


def get_reconciliation_service() -> ReconciliationService:
    global _reconciliation_service
    if _reconciliation_service is None:
        _reconciliation_service = ReconciliationService()
    return _reconciliation_service