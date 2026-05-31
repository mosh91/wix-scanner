from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.core.config import Settings


@dataclass
class QueuedScanEvent:
    """Pending scan waiting to be forwarded to cloud."""
    id: str
    event_id: str
    ticket_number: str
    relay_id: str
    payload: str
    correlation_id: str
    scan_event_id: str | None = None
    attempt_count: int = 0
    last_error: str | None = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class DeadLetterEntry:
    """Scan that failed after max retries."""
    id: str
    queued_scan_id: str
    event_id: str
    ticket_number: str
    reason: str
    final_error: str
    created_at: str


class RelayQueueService:
    """Durable SQLite-backed queue for relay scans during WAN outages."""

    def __init__(self, db_path: str | Path = "./data/relay_queue.db", max_attempts: int = 5) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._max_attempts = max_attempts
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        """Create tables if they don't exist."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS queued_scans (
                    id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    ticket_number TEXT NOT NULL,
                    relay_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    scan_event_id TEXT,
                    attempt_count INTEGER DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dead_letters (
                    id TEXT PRIMARY KEY,
                    queued_scan_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    ticket_number TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    final_error TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(queued_scan_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def enqueue_scan(
        self,
        event_id: str,
        ticket_number: str,
        relay_id: str,
        payload: str,
        correlation_id: str,
        scan_event_id: str | None = None,
    ) -> str:
        """Queue a scan for forwarding. Returns queue entry ID."""
        queue_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO queued_scans
                (id, event_id, ticket_number, relay_id, payload, correlation_id, scan_event_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (queue_id, event_id, ticket_number, relay_id, payload, correlation_id, scan_event_id, now, now),
            )
            conn.commit()

        return queue_id

    def get_pending_scans(self, limit: int = 10) -> list[QueuedScanEvent]:
        """Fetch up to N scans that haven't been forwarded yet."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM queued_scans
                WHERE attempt_count < ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (self._max_attempts, limit),
            ).fetchall()

        return [
            QueuedScanEvent(
                id=row["id"],
                event_id=row["event_id"],
                ticket_number=row["ticket_number"],
                relay_id=row["relay_id"],
                payload=row["payload"],
                correlation_id=row["correlation_id"],
                scan_event_id=row["scan_event_id"] if "scan_event_id" in row.keys() else None,
                attempt_count=row["attempt_count"],
                last_error=row["last_error"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def mark_scan_forwarded(self, queue_id: str) -> None:
        """Mark scan as successfully forwarded and remove from queue."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM queued_scans WHERE id = ?", (queue_id,))
            conn.commit()

    def increment_attempt(self, queue_id: str, error: str | None = None) -> None:
        """Increment attempt count and store error message."""
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                UPDATE queued_scans
                SET attempt_count = attempt_count + 1, last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (error, now, queue_id),
            )
            conn.commit()

    def move_to_dlq(self, queue_id: str, reason: str, final_error: str) -> str:
        """Move scan to dead-letter queue after max retries."""
        dlq_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        with sqlite3.connect(self._db_path) as conn:
            # Get scan details
            conn.row_factory = sqlite3.Row
            scan = conn.execute("SELECT * FROM queued_scans WHERE id = ?", (queue_id,)).fetchone()

            if scan:
                # Insert into DLQ
                conn.execute(
                    """
                    INSERT INTO dead_letters
                    (id, queued_scan_id, event_id, ticket_number, reason, final_error, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (dlq_id, queue_id, scan["event_id"], scan["ticket_number"], reason, final_error, now),
                )
                # Remove from queue
                conn.execute("DELETE FROM queued_scans WHERE id = ?", (queue_id,))
                conn.commit()

        return dlq_id

    def get_dlq_entries(self, limit: int = 100) -> list[DeadLetterEntry]:
        """Fetch DLQ entries for operator review."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM dead_letters
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            DeadLetterEntry(
                id=row["id"],
                queued_scan_id=row["queued_scan_id"],
                event_id=row["event_id"],
                ticket_number=row["ticket_number"],
                reason=row["reason"],
                final_error=row["final_error"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def get_queue_stats(self) -> dict[str, int]:
        """Get queue and DLQ statistics."""
        with sqlite3.connect(self._db_path) as conn:
            pending_count = conn.execute(
                "SELECT COUNT(*) FROM queued_scans WHERE attempt_count < ?", (self._max_attempts,)
            ).fetchone()[0]
            dlq_count = conn.execute("SELECT COUNT(*) FROM dead_letters").fetchone()[0]
            total_queued = conn.execute("SELECT COUNT(*) FROM queued_scans").fetchone()[0]

        return {
            "pending": pending_count,
            "dlq": dlq_count,
            "total_queued": total_queued,
        }

    def clear_old_dlq_entries(self, days_old: int = 7) -> int:
        """Clean up DLQ entries older than N days. Returns count deleted."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM dead_letters WHERE created_at < ?",
                (cutoff,),
            )
            conn.commit()
            return cursor.rowcount
