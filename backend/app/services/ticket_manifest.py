from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import time

from app.core.config import get_settings
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


class TicketManifestService:
    def __init__(self, database_file: Path | None = None) -> None:
        self._database_file = database_file or Path("./data/ticket_manifest.db")
        self._database_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._tracked_event_ids: set[str] = set()
        self._initialize_database()

    def _initialize_database(self) -> None:
        with sqlite3.connect(self._database_file) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS event_ticket_manifest (
                    event_id TEXT NOT NULL,
                    ticket_number TEXT NOT NULL,
                    manifest_state TEXT NOT NULL,
                    last_known_sync_ts REAL NOT NULL,
                    source_revision TEXT NOT NULL,
                    last_seen_scan_at REAL,
                    PRIMARY KEY (event_id, ticket_number)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS event_manifest_sync (
                    event_id TEXT PRIMARY KEY,
                    last_known_sync_ts REAL NOT NULL,
                    source_revision TEXT NOT NULL,
                    total_tickets INTEGER NOT NULL,
                    checked_in_tickets INTEGER NOT NULL
                )
                """
            )
            connection.commit()

    def track_event(self, event_id: str) -> None:
        with self._lock:
            self._tracked_event_ids.add(event_id)

    def tracked_events(self) -> list[str]:
        with self._lock:
            return sorted(self._tracked_event_ids)

    def _sync_horizon_seconds(self) -> int:
        # Degraded if no successful sync in the last 30s by default.
        return 30

    def sync_event_from_wix(self, event_id: str) -> ManifestSyncStatus:
        self.track_event(event_id)
        client = get_wix_client()
        tickets = client.list_tickets(event_id=event_id)

        now = time()
        source_revision = f"{int(now)}:{len(tickets)}"
        total = len(tickets)
        checked_in = len([t for t in tickets if t.get("checked_in")])

        with sqlite3.connect(self._database_file) as connection:
            for item in tickets:
                ticket_number = str(item["ticket_number"]).upper()
                state = "checked_in" if bool(item.get("checked_in")) else "not_checked_in"
                connection.execute(
                    """
                    INSERT INTO event_ticket_manifest (
                        event_id,
                        ticket_number,
                        manifest_state,
                        last_known_sync_ts,
                        source_revision,
                        last_seen_scan_at
                    ) VALUES (?, ?, ?, ?, ?, COALESCE(
                        (SELECT last_seen_scan_at FROM event_ticket_manifest WHERE event_id = ? AND ticket_number = ?),
                        NULL
                    ))
                    ON CONFLICT(event_id, ticket_number) DO UPDATE SET
                        manifest_state = excluded.manifest_state,
                        last_known_sync_ts = excluded.last_known_sync_ts,
                        source_revision = excluded.source_revision
                    """,
                    (
                        event_id,
                        ticket_number,
                        state,
                        now,
                        source_revision,
                        event_id,
                        ticket_number,
                    ),
                )

            connection.execute(
                """
                INSERT INTO event_manifest_sync (
                    event_id,
                    last_known_sync_ts,
                    source_revision,
                    total_tickets,
                    checked_in_tickets
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    last_known_sync_ts = excluded.last_known_sync_ts,
                    source_revision = excluded.source_revision,
                    total_tickets = excluded.total_tickets,
                    checked_in_tickets = excluded.checked_in_tickets
                """,
                (event_id, now, source_revision, total, checked_in),
            )
            connection.commit()

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
        with sqlite3.connect(self._database_file) as connection:
            row = connection.execute(
                """
                SELECT event_id, ticket_number, manifest_state, last_known_sync_ts, source_revision, last_seen_scan_at
                FROM event_ticket_manifest
                WHERE event_id = ? AND ticket_number = ?
                """,
                (event_id, normalized_ticket),
            ).fetchone()

        if row is None:
            return None

        return ManifestTicketRecord(
            event_id=row[0],
            ticket_number=row[1],
            manifest_state=row[2],
            last_known_sync_ts=float(row[3]),
            source_revision=row[4],
            last_seen_scan_at=float(row[5]) if row[5] is not None else None,
        )

    def list_tickets(self, *, event_id: str, limit: int = 10) -> list[ManifestTicketRecord]:
        with sqlite3.connect(self._database_file) as connection:
            rows = connection.execute(
                """
                SELECT event_id, ticket_number, manifest_state, last_known_sync_ts, source_revision, last_seen_scan_at
                FROM event_ticket_manifest
                WHERE event_id = ?
                ORDER BY ticket_number ASC
                LIMIT ?
                """,
                (event_id, max(1, min(limit, 50))),
            ).fetchall()

        return [
            ManifestTicketRecord(
                event_id=row[0],
                ticket_number=row[1],
                manifest_state=row[2],
                last_known_sync_ts=float(row[3]),
                source_revision=row[4],
                last_seen_scan_at=float(row[5]) if row[5] is not None else None,
            )
            for row in rows
        ]

    def mark_checked_in(self, *, event_id: str, ticket_number: str) -> None:
        normalized_ticket = ticket_number.strip().upper()
        now = time()
        with sqlite3.connect(self._database_file) as connection:
            connection.execute(
                """
                UPDATE event_ticket_manifest
                SET manifest_state = 'checked_in', last_seen_scan_at = ?, last_known_sync_ts = ?
                WHERE event_id = ? AND ticket_number = ?
                """,
                (now, now, event_id, normalized_ticket),
            )
            connection.commit()

    def status(self, *, event_id: str) -> ManifestSyncStatus:
        with sqlite3.connect(self._database_file) as connection:
            row = connection.execute(
                """
                SELECT event_id, last_known_sync_ts, source_revision, total_tickets, checked_in_tickets
                FROM event_manifest_sync
                WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()

        if row is None:
            return ManifestSyncStatus(
                event_id=event_id,
                total_tickets=0,
                checked_in_tickets=0,
                stale=True,
                last_known_sync_ts=0.0,
                source_revision="none",
            )

        stale = (time() - float(row[1])) > self._sync_horizon_seconds()
        return ManifestSyncStatus(
            event_id=row[0],
            total_tickets=int(row[3]),
            checked_in_tickets=int(row[4]),
            stale=stale,
            last_known_sync_ts=float(row[1]),
            source_revision=row[2],
        )

    def reset_for_tests(self) -> None:
        with sqlite3.connect(self._database_file) as connection:
            connection.execute("DELETE FROM event_ticket_manifest")
            connection.execute("DELETE FROM event_manifest_sync")
            connection.commit()
        with self._lock:
            self._tracked_event_ids.clear()


_manifest_service: TicketManifestService | None = None


def get_ticket_manifest_service() -> TicketManifestService:
    global _manifest_service
    if _manifest_service is None:
        _manifest_service = TicketManifestService()
    return _manifest_service
