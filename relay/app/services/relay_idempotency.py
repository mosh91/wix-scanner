"""Relay-level idempotency ledger for duplicate scan prevention."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


@dataclass
class RelayIdempotencyRecord:
    """Record of a processed scan event at relay."""

    scan_event_id: str
    relay_id: str
    outcome: str  # "forwarded", "failed", "queued"
    error_message: Optional[str]
    created_at: datetime


class RelayIdempotencyService:
    """Manages idempotency ledger for relay to prevent duplicate forwards."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize idempotency table if not exists."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS relay_idempotency (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scan_event_id TEXT NOT NULL UNIQUE,
                    relay_id TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    error_message TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_relay_idem_event_id
                ON relay_idempotency(scan_event_id)
                """
            )
            conn.commit()

    def record_scan(
        self,
        scan_event_id: str,
        relay_id: str,
        outcome: str,
        error_message: Optional[str] = None,
    ) -> RelayIdempotencyRecord:
        """Record a scan event outcome."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO relay_idempotency (scan_event_id, relay_id, outcome, error_message)
                VALUES (?, ?, ?, ?)
                """,
                (scan_event_id, relay_id, outcome, error_message),
            )
            conn.commit()

        return RelayIdempotencyRecord(
            scan_event_id=scan_event_id,
            relay_id=relay_id,
            outcome=outcome,
            error_message=error_message,
            created_at=datetime.utcnow(),
        )

    def find_by_scan_event_id(
        self, scan_event_id: str
    ) -> Optional[RelayIdempotencyRecord]:
        """Look up a previous scan event by scan_event_id."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT scan_event_id, relay_id, outcome, error_message, created_at
                FROM relay_idempotency
                WHERE scan_event_id = ?
                """,
                (scan_event_id,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        return RelayIdempotencyRecord(
            scan_event_id=row[0],
            relay_id=row[1],
            outcome=row[2],
            error_message=row[3],
            created_at=datetime.fromisoformat(row[4]),
        )

    def cleanup_old_records(self, days_old: int = 7) -> int:
        """Remove idempotency records older than days_old."""
        cutoff = datetime.utcnow() - timedelta(days=days_old)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                DELETE FROM relay_idempotency
                WHERE created_at < ?
                """,
                (cutoff.isoformat(),),
            )
            conn.commit()
            return cursor.rowcount
