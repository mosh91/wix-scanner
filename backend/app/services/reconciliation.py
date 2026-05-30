from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import time
from uuid import uuid4

from app.core.config import get_settings
from app.services.offline_queue import get_offline_queue_service
from app.services.ticket_manifest import ManifestTicketRecord, get_ticket_manifest_service
from app.services.wix_client import get_wix_client

ReconciliationState = str


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
    def __init__(self, db_path: str | None = None) -> None:
        settings = get_settings()
        self._db_path = Path(db_path or settings.reconciliation_db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._manifest = get_ticket_manifest_service()
        self._queue = get_offline_queue_service()
        self._init_db()

    def _now_iso(self) -> str:
        return datetime.utcnow().isoformat() + "Z"

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reconciliation_run (
                    run_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reconciliation_state TEXT NOT NULL,
                    drift_count INTEGER NOT NULL,
                    resolved_count INTEGER NOT NULL,
                    conflict_count INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    triggered_by_actor TEXT NOT NULL,
                    notes TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reconciliation_item (
                    item_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    ticket_number TEXT NOT NULL,
                    reconciliation_state TEXT NOT NULL,
                    local_result TEXT,
                    wix_result TEXT,
                    resolution_result TEXT,
                    detail_json TEXT NOT NULL,
                    resolved_at TEXT,
                    conflict_resolution_notes TEXT,
                    resolved_by_actor TEXT,
                    FOREIGN KEY(run_id) REFERENCES reconciliation_run(run_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_reconciliation_run_event_started
                ON reconciliation_run (event_id, started_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_reconciliation_item_run
                ON reconciliation_item (run_id)
                """
            )
            conn.commit()

    def _to_run(self, row: sqlite3.Row) -> ReconciliationRun:
        return ReconciliationRun(
            run_id=row["run_id"],
            event_id=row["event_id"],
            status=row["status"],
            reconciliation_state=row["reconciliation_state"],
            drift_count=int(row["drift_count"]),
            resolved_count=int(row["resolved_count"]),
            conflict_count=int(row["conflict_count"]),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            triggered_by_actor=row["triggered_by_actor"],
            notes=row["notes"],
        )

    def _to_item(self, row: sqlite3.Row) -> ReconciliationItem:
        return ReconciliationItem(
            item_id=row["item_id"],
            run_id=row["run_id"],
            event_id=row["event_id"],
            ticket_number=row["ticket_number"],
            reconciliation_state=row["reconciliation_state"],
            local_result=row["local_result"],
            wix_result=row["wix_result"],
            resolution_result=row["resolution_result"],
            detail=json.loads(row["detail_json"]),
            resolved_at=row["resolved_at"],
            conflict_resolution_notes=row["conflict_resolution_notes"],
            resolved_by_actor=row["resolved_by_actor"],
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

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO reconciliation_run (
                    run_id,
                    event_id,
                    status,
                    reconciliation_state,
                    drift_count,
                    resolved_count,
                    conflict_count,
                    started_at,
                    triggered_by_actor,
                    notes
                ) VALUES (?, ?, 'running', 'in_sync', 0, 0, 0, ?, ?, ?)
                """,
                (run_id, event_id, started_at, actor, notes),
            )
            conn.commit()

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
        with sqlite3.connect(self._db_path) as conn:
            conn.executemany(
                """
                INSERT INTO reconciliation_item (
                    item_id,
                    run_id,
                    event_id,
                    ticket_number,
                    reconciliation_state,
                    local_result,
                    wix_result,
                    resolution_result,
                    detail_json,
                    resolved_at,
                    conflict_resolution_notes,
                    resolved_by_actor
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.item_id,
                        item.run_id,
                        item.event_id,
                        item.ticket_number,
                        item.reconciliation_state,
                        item.local_result,
                        item.wix_result,
                        item.resolution_result,
                        json.dumps(item.detail, separators=(",", ":")),
                        item.resolved_at,
                        item.conflict_resolution_notes,
                        item.resolved_by_actor,
                    )
                    for item in items
                ],
            )
            conn.execute(
                """
                UPDATE reconciliation_run
                SET status = 'completed',
                    reconciliation_state = ?,
                    drift_count = ?,
                    resolved_count = ?,
                    conflict_count = ?,
                    finished_at = ?
                WHERE run_id = ?
                """,
                (overall_state, drift_count, resolved_count, conflict_count, finished_at, run_id),
            )
            conn.commit()

        run = self.get_run(run_id=run_id)
        if run is None:
            raise RuntimeError("Failed to load reconciliation run after execution")
        return ReconciliationReport(run=run, items=items)

    def get_run(self, *, run_id: str) -> ReconciliationRun | None:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM reconciliation_run WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return self._to_run(row)

    def list_runs(self, *, event_id: str, limit: int = 20) -> list[ReconciliationRun]:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM reconciliation_run
                WHERE event_id = ?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (event_id, max(1, min(limit, 100))),
            ).fetchall()
        return [self._to_run(row) for row in rows]

    def list_conflicts(self, *, event_id: str, run_id: str | None = None, limit: int = 100) -> list[ReconciliationItem]:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            effective_run_id = run_id
            if effective_run_id is None:
                latest = conn.execute(
                    """
                    SELECT run_id
                    FROM reconciliation_run
                    WHERE event_id = ?
                    ORDER BY started_at DESC
                    LIMIT 1
                    """,
                    (event_id,),
                ).fetchone()
                if latest is None:
                    return []
                effective_run_id = latest["run_id"]

            rows = conn.execute(
                """
                SELECT *
                FROM reconciliation_item
                WHERE run_id = ?
                  AND reconciliation_state = 'conflict'
                ORDER BY ticket_number ASC
                LIMIT ?
                """,
                (effective_run_id, max(1, min(limit, 200))),
            ).fetchall()
        return [self._to_item(row) for row in rows]

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

        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM reconciliation_item WHERE item_id = ?",
                (item_id,),
            ).fetchone()
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
            merged_note = note or ""
            conn.execute(
                """
                UPDATE reconciliation_item
                SET reconciliation_state = 'in_sync',
                    resolution_result = ?,
                    resolved_at = ?,
                    conflict_resolution_notes = ?,
                    resolved_by_actor = ?
                WHERE item_id = ?
                """,
                (resolution_result, resolved_at, merged_note, actor, item_id),
            )

            unresolved = conn.execute(
                """
                SELECT COUNT(*)
                FROM reconciliation_item
                WHERE run_id = ?
                  AND reconciliation_state = 'conflict'
                """,
                (item.run_id,),
            ).fetchone()[0]

            if unresolved == 0:
                conn.execute(
                    """
                    UPDATE reconciliation_run
                    SET conflict_count = 0,
                        reconciliation_state = CASE
                            WHEN drift_count = resolved_count + 1 THEN 'in_sync'
                            ELSE reconciliation_state
                        END,
                        resolved_count = resolved_count + 1
                    WHERE run_id = ?
                    """,
                    (item.run_id,),
                )
            else:
                conn.execute(
                    """
                    UPDATE reconciliation_run
                    SET conflict_count = ?,
                        resolved_count = resolved_count + 1
                    WHERE run_id = ?
                    """,
                    (int(unresolved), item.run_id),
                )

            conn.commit()

            updated_row = conn.execute(
                "SELECT * FROM reconciliation_item WHERE item_id = ?",
                (item_id,),
            ).fetchone()
            if updated_row is None:
                raise RuntimeError("Conflict item disappeared after resolution")
            return self._to_item(updated_row)


_reconciliation_service: ReconciliationService | None = None


def get_reconciliation_service() -> ReconciliationService:
    global _reconciliation_service
    if _reconciliation_service is None:
        _reconciliation_service = ReconciliationService()
    return _reconciliation_service