from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from time import time

from app.core.config import Settings, get_settings
from app.services.ticket_manifest import get_ticket_manifest_service


@dataclass(frozen=True)
class WixSyncControlRecord:
    event_id: str
    enabled: bool
    interval_seconds: int
    last_successful_sync_at: float | None
    last_attempt_at: float | None
    current_lag_seconds: int | None
    last_error: str | None
    updated_at: float


class WixSyncControlService:
    def __init__(self, *, db_path: str, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._db_path = str(Path(db_path))
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS wix_sync_controls (
                    event_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL,
                    interval_seconds INTEGER NOT NULL,
                    last_successful_sync_at REAL,
                    last_attempt_at REAL,
                    last_error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.commit()

    def _to_record(self, row: sqlite3.Row, now_ts: float) -> WixSyncControlRecord:
        last_successful = float(row["last_successful_sync_at"]) if row["last_successful_sync_at"] is not None else None
        lag_seconds = int(max(0, now_ts - last_successful)) if last_successful is not None else None
        return WixSyncControlRecord(
            event_id=row["event_id"],
            enabled=bool(row["enabled"]),
            interval_seconds=int(row["interval_seconds"]),
            last_successful_sync_at=last_successful,
            last_attempt_at=float(row["last_attempt_at"]) if row["last_attempt_at"] is not None else None,
            current_lag_seconds=lag_seconds,
            last_error=row["last_error"],
            updated_at=float(row["updated_at"]),
        )

    def get_control(self, *, event_id: str, now_ts: float | None = None) -> WixSyncControlRecord:
        current = now_ts or time()
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM wix_sync_controls
                WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()

        if row is None:
            return WixSyncControlRecord(
                event_id=event_id,
                enabled=False,
                interval_seconds=60,
                last_successful_sync_at=None,
                last_attempt_at=None,
                current_lag_seconds=None,
                last_error=None,
                updated_at=current,
            )

        return self._to_record(row, current)

    def upsert_control(
        self,
        *,
        event_id: str,
        enabled: bool,
        interval_seconds: int,
    ) -> WixSyncControlRecord:
        safe_interval = max(30, min(300, int(interval_seconds)))
        now_ts = time()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO wix_sync_controls (
                    event_id,
                    enabled,
                    interval_seconds,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    interval_seconds = excluded.interval_seconds,
                    updated_at = excluded.updated_at
                """,
                (
                    event_id,
                    1 if enabled else 0,
                    safe_interval,
                    now_ts,
                    now_ts,
                ),
            )
            conn.commit()

        return self.get_control(event_id=event_id, now_ts=now_ts)

    def list_controls(self, *, limit: int = 100, now_ts: float | None = None) -> list[WixSyncControlRecord]:
        current = now_ts or time()
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM wix_sync_controls
                ORDER BY event_id ASC
                LIMIT ?
                """,
                (max(1, min(limit, 200)),),
            ).fetchall()

        return [self._to_record(row, current) for row in rows]

    def process_due_syncs(self, *, now_ts: float | None = None, max_items: int = 25) -> int:
        current = now_ts or time()
        processed = 0

        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            due_rows = conn.execute(
                """
                SELECT *
                FROM wix_sync_controls
                WHERE enabled = 1
                  AND (
                    last_attempt_at IS NULL
                    OR (? - last_attempt_at) >= interval_seconds
                  )
                ORDER BY COALESCE(last_attempt_at, 0) ASC
                LIMIT ?
                """,
                (current, max(1, min(max_items, 100))),
            ).fetchall()

        if not due_rows:
            return 0

        manifest_service = get_ticket_manifest_service()
        for row in due_rows:
            event_id = row["event_id"]
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    UPDATE wix_sync_controls
                    SET last_attempt_at = ?,
                        updated_at = ?
                    WHERE event_id = ?
                    """,
                    (current, current, event_id),
                )
                conn.commit()

            try:
                manifest_service.sync_event_from_wix(event_id)
            except Exception as exc:  # pragma: no cover - exercised via tests with deterministic failures
                with sqlite3.connect(self._db_path) as conn:
                    conn.execute(
                        """
                        UPDATE wix_sync_controls
                        SET last_error = ?,
                            updated_at = ?
                        WHERE event_id = ?
                        """,
                        (str(exc)[:500], current, event_id),
                    )
                    conn.commit()
                continue

            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    UPDATE wix_sync_controls
                    SET last_successful_sync_at = ?,
                        last_error = NULL,
                        updated_at = ?
                    WHERE event_id = ?
                    """,
                    (current, current, event_id),
                )
                conn.commit()

            processed += 1

        return processed


_sync_control_service: WixSyncControlService | None = None


def set_sync_control_service(service: WixSyncControlService | None) -> None:
    global _sync_control_service
    _sync_control_service = service


def get_sync_control_service() -> WixSyncControlService:
    global _sync_control_service
    if _sync_control_service is None:
        settings = get_settings()
        _sync_control_service = WixSyncControlService(db_path=settings.sync_controls_db_path, settings=settings)
    return _sync_control_service
