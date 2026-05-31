from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

EventStatus = Literal["draft", "active", "archived"]

_event_block_service: EventBlockConfigService | None = None


def get_event_block_config_service() -> EventBlockConfigService:
    if _event_block_service is None:
        raise RuntimeError("EventBlockConfigService is not initialized.")
    return _event_block_service


def set_event_block_config_service(service: EventBlockConfigService) -> None:
    global _event_block_service
    _event_block_service = service


# ── Data records ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EventRecord:
    event_id: str
    wix_event_id: str
    name: str
    timezone: str
    status: EventStatus
    allow_block_overlap: bool
    version: int
    created_at: str
    updated_at: str
    actor: str


@dataclass(frozen=True)
class EventBlockRecord:
    block_id: str
    event_id: str
    block_code: str
    name: str
    starts_at: str
    ends_at: str
    grace_period_minutes: int
    allow_overlap: bool
    priority: int
    is_active: bool
    version: int
    created_at: str
    updated_at: str
    actor: str


@dataclass(frozen=True)
class ConfigVersionRecord:
    version_id: str
    event_id: str
    version_number: int
    config_snapshot: dict
    created_at: str
    actor: str


# ── Validation helpers ────────────────────────────────────────────────────────


class BlockValidationError(ValueError):
    pass


def _validate_time_range(starts_at: str, ends_at: str) -> None:
    """Raise BlockValidationError when start >= end."""
    try:
        start = datetime.fromisoformat(starts_at)
        end = datetime.fromisoformat(ends_at)
    except ValueError as exc:
        raise BlockValidationError(f"Invalid ISO datetime: {exc}") from exc
    if start >= end:
        raise BlockValidationError(
            f"Block starts_at ({starts_at}) must be strictly before ends_at ({ends_at})."
        )


def _validate_grace_period(grace_period_minutes: int) -> None:
    if not (0 <= grace_period_minutes <= 120):
        raise BlockValidationError("grace_period_minutes must be between 0 and 120.")


def _validate_priority(priority: int) -> None:
    if priority < 0:
        raise BlockValidationError("priority must be a non-negative integer.")


# ── Service ───────────────────────────────────────────────────────────────────


class EventBlockConfigService:
    """Persists event and block configuration in SQLite with version snapshots."""

    def __init__(self, db_path: str) -> None:
        self._db_path = str(Path(db_path))
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── Schema ───────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS event_config (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    wix_event_id TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    timezone TEXT NOT NULL DEFAULT 'UTC',
                    status TEXT NOT NULL DEFAULT 'draft',
                    allow_block_overlap INTEGER NOT NULL DEFAULT 0,
                    version INTEGER NOT NULL DEFAULT 1,
                    actor TEXT NOT NULL DEFAULT 'system',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS event_block (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    block_id TEXT NOT NULL UNIQUE,
                    event_id TEXT NOT NULL REFERENCES event_config(event_id) ON DELETE CASCADE,
                    block_code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    starts_at TEXT NOT NULL,
                    ends_at TEXT NOT NULL,
                    grace_period_minutes INTEGER NOT NULL DEFAULT 0,
                    allow_overlap INTEGER NOT NULL DEFAULT 0,
                    priority INTEGER NOT NULL DEFAULT 100,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    version INTEGER NOT NULL DEFAULT 1,
                    actor TEXT NOT NULL DEFAULT 'system',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CONSTRAINT event_block_unique_code UNIQUE (event_id, block_code)
                );

                CREATE TABLE IF NOT EXISTS event_config_version (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version_id TEXT NOT NULL UNIQUE,
                    event_id TEXT NOT NULL,
                    version_number INTEGER NOT NULL,
                    config_snapshot TEXT NOT NULL,
                    actor TEXT NOT NULL DEFAULT 'system',
                    created_at TEXT NOT NULL,
                    CONSTRAINT event_config_version_unique UNIQUE (event_id, version_number)
                );
                """
            )

    # ── Internal helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def _row_to_event(self, row: sqlite3.Row) -> EventRecord:
        return EventRecord(
            event_id=row["event_id"],
            wix_event_id=row["wix_event_id"],
            name=row["name"],
            timezone=row["timezone"],
            status=row["status"],
            allow_block_overlap=bool(row["allow_block_overlap"]),
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            actor=row["actor"],
        )

    def _row_to_block(self, row: sqlite3.Row) -> EventBlockRecord:
        return EventBlockRecord(
            block_id=row["block_id"],
            event_id=row["event_id"],
            block_code=row["block_code"],
            name=row["name"],
            starts_at=row["starts_at"],
            ends_at=row["ends_at"],
            grace_period_minutes=row["grace_period_minutes"],
            allow_overlap=bool(row["allow_overlap"]),
            priority=row["priority"],
            is_active=bool(row["is_active"]),
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            actor=row["actor"],
        )

    def _snapshot_event(
        self, conn: sqlite3.Connection, event_id: str, version: int, actor: str
    ) -> None:
        blocks_rows = conn.execute(
            "SELECT * FROM event_block WHERE event_id = ?", (event_id,)
        ).fetchall()
        event_row = conn.execute(
            "SELECT * FROM event_config WHERE event_id = ?", (event_id,)
        ).fetchone()
        snapshot: dict = {
            "event": dict(event_row) if event_row else {},
            "blocks": [dict(r) for r in blocks_rows],
        }
        conn.execute(
            """
            INSERT INTO event_config_version
                (version_id, event_id, version_number, config_snapshot, actor, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(uuid4()), event_id, version, json.dumps(snapshot), actor, self._now()),
        )

    # ── Overlap detection ────────────────────────────────────────────────────

    def _check_overlap(
        self,
        conn: sqlite3.Connection,
        event_id: str,
        starts_at: str,
        ends_at: str,
        exclude_block_id: str | None = None,
    ) -> bool:
        """Return True if any active block in the event overlaps [starts_at, ends_at)."""
        rows = conn.execute(
            """
            SELECT block_id, starts_at, ends_at FROM event_block
            WHERE event_id = ? AND is_active = 1
            """,
            (event_id,),
        ).fetchall()
        new_start = datetime.fromisoformat(starts_at)
        new_end = datetime.fromisoformat(ends_at)
        for row in rows:
            if exclude_block_id and row["block_id"] == exclude_block_id:
                continue
            existing_start = datetime.fromisoformat(row["starts_at"])
            existing_end = datetime.fromisoformat(row["ends_at"])
            # Overlap: new_start < existing_end AND new_end > existing_start
            if new_start < existing_end and new_end > existing_start:
                return True
        return False

    # ── Event CRUD ───────────────────────────────────────────────────────────

    def create_event(
        self,
        *,
        wix_event_id: str,
        name: str,
        timezone: str = "UTC",
        allow_block_overlap: bool = False,
        actor: str = "system",
    ) -> EventRecord:
        event_id = str(uuid4())
        now = self._now()
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT INTO event_config
                    (event_id, wix_event_id, name, timezone, status, allow_block_overlap,
                     version, actor, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'draft', ?, 1, ?, ?, ?)
                """,
                (
                    event_id,
                    wix_event_id,
                    name,
                    timezone,
                    int(allow_block_overlap),
                    actor,
                    now,
                    now,
                ),
            )
            self._snapshot_event(conn, event_id, 1, actor)
            row = conn.execute(
                "SELECT * FROM event_config WHERE event_id = ?", (event_id,)
            ).fetchone()
        return self._row_to_event(row)

    def get_event(self, event_id: str) -> EventRecord | None:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM event_config WHERE event_id = ?", (event_id,)
            ).fetchone()
        return self._row_to_event(row) if row else None

    def list_events(self) -> list[EventRecord]:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM event_config ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def update_event(
        self,
        event_id: str,
        *,
        name: str | None = None,
        timezone: str | None = None,
        status: EventStatus | None = None,
        allow_block_overlap: bool | None = None,
        actor: str = "system",
    ) -> EventRecord:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM event_config WHERE event_id = ?", (event_id,)
            ).fetchone()
            if not row:
                raise KeyError(f"Event {event_id!r} not found.")
            now = self._now()
            new_version = row["version"] + 1
            conn.execute(
                """
                UPDATE event_config SET
                    name = COALESCE(?, name),
                    timezone = COALESCE(?, timezone),
                    status = COALESCE(?, status),
                    allow_block_overlap = CASE WHEN ? IS NOT NULL THEN ? ELSE allow_block_overlap END,
                    version = ?,
                    actor = ?,
                    updated_at = ?
                WHERE event_id = ?
                """,
                (
                    name,
                    timezone,
                    status,
                    1 if allow_block_overlap is not None else None,
                    int(allow_block_overlap) if allow_block_overlap is not None else None,
                    new_version,
                    actor,
                    now,
                    event_id,
                ),
            )
            self._snapshot_event(conn, event_id, new_version, actor)
            updated = conn.execute(
                "SELECT * FROM event_config WHERE event_id = ?", (event_id,)
            ).fetchone()
        return self._row_to_event(updated)

    def delete_event(self, event_id: str) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "DELETE FROM event_config WHERE event_id = ?", (event_id,)
            )

    # ── Block CRUD ───────────────────────────────────────────────────────────

    def create_block(
        self,
        event_id: str,
        *,
        block_code: str,
        name: str,
        starts_at: str,
        ends_at: str,
        grace_period_minutes: int = 0,
        allow_overlap: bool = False,
        priority: int = 100,
        actor: str = "system",
    ) -> EventBlockRecord:
        _validate_time_range(starts_at, ends_at)
        _validate_grace_period(grace_period_minutes)
        _validate_priority(priority)

        block_id = str(uuid4())
        now = self._now()

        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            event_row = conn.execute(
                "SELECT * FROM event_config WHERE event_id = ?", (event_id,)
            ).fetchone()
            if not event_row:
                raise KeyError(f"Event {event_id!r} not found.")

            # Overlap check
            if not event_row["allow_block_overlap"] and not allow_overlap:
                if self._check_overlap(conn, event_id, starts_at, ends_at):
                    raise BlockValidationError(
                        "Block overlaps an existing active block and overlap is disabled for this event."
                    )

            conn.execute(
                """
                INSERT INTO event_block
                    (block_id, event_id, block_code, name, starts_at, ends_at,
                     grace_period_minutes, allow_overlap, priority, is_active,
                     version, actor, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?)
                """,
                (
                    block_id,
                    event_id,
                    block_code,
                    name,
                    starts_at,
                    ends_at,
                    grace_period_minutes,
                    int(allow_overlap),
                    priority,
                    actor,
                    now,
                    now,
                ),
            )
            # bump event version
            new_event_version = event_row["version"] + 1
            conn.execute(
                "UPDATE event_config SET version = ?, actor = ?, updated_at = ? WHERE event_id = ?",
                (new_event_version, actor, now, event_id),
            )
            self._snapshot_event(conn, event_id, new_event_version, actor)
            row = conn.execute(
                "SELECT * FROM event_block WHERE block_id = ?", (block_id,)
            ).fetchone()
        return self._row_to_block(row)

    def get_block(self, block_id: str) -> EventBlockRecord | None:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM event_block WHERE block_id = ?", (block_id,)
            ).fetchone()
        return self._row_to_block(row) if row else None

    def list_blocks(self, event_id: str) -> list[EventBlockRecord]:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM event_block WHERE event_id = ? ORDER BY priority ASC, starts_at ASC",
                (event_id,),
            ).fetchall()
        return [self._row_to_block(r) for r in rows]

    def update_block(
        self,
        block_id: str,
        *,
        name: str | None = None,
        starts_at: str | None = None,
        ends_at: str | None = None,
        grace_period_minutes: int | None = None,
        allow_overlap: bool | None = None,
        priority: int | None = None,
        is_active: bool | None = None,
        actor: str = "system",
    ) -> EventBlockRecord:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            block_row = conn.execute(
                "SELECT * FROM event_block WHERE block_id = ?", (block_id,)
            ).fetchone()
            if not block_row:
                raise KeyError(f"Block {block_id!r} not found.")

            # Resolve effective values for validation
            eff_starts = starts_at or block_row["starts_at"]
            eff_ends = ends_at or block_row["ends_at"]
            _validate_time_range(eff_starts, eff_ends)

            if grace_period_minutes is not None:
                _validate_grace_period(grace_period_minutes)
            if priority is not None:
                _validate_priority(priority)

            event_row = conn.execute(
                "SELECT * FROM event_config WHERE event_id = ?", (block_row["event_id"],)
            ).fetchone()

            eff_allow_overlap = allow_overlap if allow_overlap is not None else bool(block_row["allow_overlap"])
            if not event_row["allow_block_overlap"] and not eff_allow_overlap:
                if self._check_overlap(
                    conn, block_row["event_id"], eff_starts, eff_ends, exclude_block_id=block_id
                ):
                    raise BlockValidationError(
                        "Updated block overlaps an existing active block and overlap is disabled."
                    )

            now = self._now()
            new_version = block_row["version"] + 1
            conn.execute(
                """
                UPDATE event_block SET
                    name = COALESCE(?, name),
                    starts_at = COALESCE(?, starts_at),
                    ends_at = COALESCE(?, ends_at),
                    grace_period_minutes = COALESCE(?, grace_period_minutes),
                    allow_overlap = CASE WHEN ? IS NOT NULL THEN ? ELSE allow_overlap END,
                    priority = COALESCE(?, priority),
                    is_active = CASE WHEN ? IS NOT NULL THEN ? ELSE is_active END,
                    version = ?,
                    actor = ?,
                    updated_at = ?
                WHERE block_id = ?
                """,
                (
                    name,
                    starts_at,
                    ends_at,
                    grace_period_minutes,
                    1 if allow_overlap is not None else None,
                    int(allow_overlap) if allow_overlap is not None else None,
                    priority,
                    1 if is_active is not None else None,
                    int(is_active) if is_active is not None else None,
                    new_version,
                    actor,
                    now,
                    block_id,
                ),
            )
            # bump event version
            new_event_version = event_row["version"] + 1
            conn.execute(
                "UPDATE event_config SET version = ?, actor = ?, updated_at = ? WHERE event_id = ?",
                (new_event_version, actor, now, block_row["event_id"]),
            )
            self._snapshot_event(conn, block_row["event_id"], new_event_version, actor)
            updated = conn.execute(
                "SELECT * FROM event_block WHERE block_id = ?", (block_id,)
            ).fetchone()
        return self._row_to_block(updated)

    def delete_block(self, block_id: str, actor: str = "system") -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            block_row = conn.execute(
                "SELECT * FROM event_block WHERE block_id = ?", (block_id,)
            ).fetchone()
            if not block_row:
                raise KeyError(f"Block {block_id!r} not found.")
            event_id = block_row["event_id"]
            conn.execute("DELETE FROM event_block WHERE block_id = ?", (block_id,))
            event_row = conn.execute(
                "SELECT * FROM event_config WHERE event_id = ?", (event_id,)
            ).fetchone()
            if event_row:
                now = self._now()
                new_event_version = event_row["version"] + 1
                conn.execute(
                    "UPDATE event_config SET version = ?, actor = ?, updated_at = ? WHERE event_id = ?",
                    (new_event_version, actor, now, event_id),
                )
                self._snapshot_event(conn, event_id, new_event_version, actor)

    def list_config_versions(self, event_id: str) -> list[ConfigVersionRecord]:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM event_config_version
                WHERE event_id = ?
                ORDER BY version_number DESC
                """,
                (event_id,),
            ).fetchall()
        return [
            ConfigVersionRecord(
                version_id=r["version_id"],
                event_id=r["event_id"],
                version_number=r["version_number"],
                config_snapshot=json.loads(r["config_snapshot"]),
                created_at=r["created_at"],
                actor=r["actor"],
            )
            for r in rows
        ]
