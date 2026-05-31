"""Audit trail service for event and block reset actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import get_settings
from app.db import make_engine

Base = declarative_base()

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


class _ResetAuditRow(Base):
    __tablename__ = "reset_audit"

    reset_id = Column(String, primary_key=True)
    scope = Column(String, nullable=False)
    scope_id = Column(String, nullable=False, index=True)
    actor = Column(String, nullable=False)
    reason = Column(String, nullable=False)
    records_cleared = Column(Integer, nullable=False, default=0)
    performed_at = Column(String, nullable=False)


class ResetAuditService:
    """SQLAlchemy-backed audit trail for reset actions (Postgres in production, SQLite in tests)."""

    def __init__(self, db_path: str | None = None, db_url: str | None = None) -> None:
        if db_url:
            url = db_url
        elif db_path:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            url = f"sqlite:///{Path(db_path).resolve()}"
        else:
            url = get_settings().database_url
        self._engine = make_engine(url)
        Base.metadata.create_all(self._engine)
        self._Session = sessionmaker(bind=self._engine, autoflush=False, autocommit=False)

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
        with self._Session() as session:
            session.add(
                _ResetAuditRow(
                    reset_id=reset_id,
                    scope=scope,
                    scope_id=scope_id,
                    actor=actor,
                    reason=reason,
                    records_cleared=records_cleared,
                    performed_at=performed_at,
                )
            )
            session.commit()
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
        with self._Session() as session:
            rows = (
                session.query(_ResetAuditRow)
                .order_by(_ResetAuditRow.performed_at.desc())
                .limit(limit)
                .all()
            )
        return [
            ResetAuditRecord(
                reset_id=r.reset_id,
                scope=r.scope,
                scope_id=r.scope_id,
                actor=r.actor,
                reason=r.reason,
                records_cleared=r.records_cleared,
                performed_at=r.performed_at,
            )
            for r in rows
        ]

    def list_audit_for_scope(self, scope_id: str, limit: int = 50) -> list[ResetAuditRecord]:
        with self._Session() as session:
            rows = (
                session.query(_ResetAuditRow)
                .filter(_ResetAuditRow.scope_id == scope_id)
                .order_by(_ResetAuditRow.performed_at.desc())
                .limit(limit)
                .all()
            )
        return [
            ResetAuditRecord(
                reset_id=r.reset_id,
                scope=r.scope,
                scope_id=r.scope_id,
                actor=r.actor,
                reason=r.reason,
                records_cleared=r.records_cleared,
                performed_at=r.performed_at,
            )
            for r in rows
        ]
