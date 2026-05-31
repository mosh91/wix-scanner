"""Audit trail service for event and block reset actions."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

_reset_audit_service: ResetAuditService | None = None


def get_reset_audit_service() -> ResetAuditService:
    if _reset_audit_service is None:
        raise RuntimeError("ResetAuditService is not initialized.")
    return _reset_audit_service


def set_reset_audit_service(service: ResetAuditService | None) -> None:
    global _reset_audit_service
    _reset_audit_service = service


@dataclass(frozen=True)
class ResetAuditRecord:
    reset_id: str
    scope: str          # "event" or "block"
    scope_id: str       # wix_event_id or block_id
    actor: str
    reason: str
    records_cleared: int
    performed_at: str   # ISO-8601 UTC


class ResetAuditService:
    """SQLite-backed audit trail for reset actions."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reset_audit (
                    reset_id     TEXT PRIMARY KEY,
                    scope        TEXT NOT NULL,
                    scope_id     TEXT NOT NULL,
                    actor        TEXT NOT NULL,
                    reason       TEXT NOT NULL,
                    records_cleared INTEGER NOT NULL DEFAULT 0,
                    performed_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reset_audit_scope_id ON reset_audit(scope_id)"
            )
            conn.commit()

    def record_reset(
        self,
        scope: str,
        scope_id: str,
        actor: str,
        reason: str,
        records_cleared: int,
    ) -> ResetAuditRecord:
        reset_id = str(uuid4())
        performed_at = datetime.now(UTC).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT INTO reset_audit
                   (reset_id, scope, scope_id, actor, reason, records_cleared, performed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (reset_id, scope, scope_id, actor, reason, records_cleared, performed_at),
            )
            conn.commit()
        return ResetAuditRecord(
            reset_id=reset_id,
            scope=scope,
            scope_id=scope_id,
            actor=actor,
            reason=reason,
            records_cleared=records_cleared,
            performed_at=performed_at,
        )

    def list_audit(self, limit: int = 100) -> list[ResetAuditRecord]:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM reset_audit ORDER BY performed_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            ResetAuditRecord(
                reset_id=row["reset_id"],
                scope=row["scope"],
                scope_id=row["scope_id"],
                actor=row["actor"],
                reason=row["reason"],
                records_cleared=row["records_cleared"],
                performed_at=row["performed_at"],
            )
            for row in rows
        ]
