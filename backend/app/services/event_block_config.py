from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from sqlalchemy import Column, String, Integer, Text, Boolean, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase

from app.db import make_engine, make_session_factory

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
    event_id: str  # Maps to id column in database
    wix_event_id: str
    name: str
    timezone: str
    status: EventStatus
    allow_block_overlap: bool
    sync_enabled: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class EventBlockRecord:
    block_id: str  # Maps to id column in database
    event_id: str
    block_code: str
    name: str
    starts_at: str
    ends_at: str
    grace_period_minutes: int
    allow_overlap: bool
    priority: int
    is_active: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ConfigVersionRecord:
    version_id: str  # Maps to id column in database
    event_id: str
    version_number: int
    config_snapshot: dict
    created_at: str
    created_by: str | None


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


# ── ORM models ───────────────────────────────────────────────────────────────


class _Base(DeclarativeBase):
    pass


class _EventConfigRow(_Base):
    __tablename__ = "event"
    __table_args__ = (UniqueConstraint("wix_event_id"),)
    id = Column(String, primary_key=True)  # UUID
    wix_event_id = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    timezone = Column(String, nullable=False, default="UTC")
    status = Column(String, nullable=False, default="draft")
    allow_block_overlap = Column(Boolean, nullable=False, default=False)
    sync_enabled = Column(Boolean, nullable=False, default=True)
    sync_interval_seconds = Column(Integer, nullable=False, default=120)
    created_by = Column(String, nullable=True)  # UUID
    updated_by = Column(String, nullable=True)  # UUID
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class _EventBlockRow(_Base):
    __tablename__ = "event_block"
    __table_args__ = (UniqueConstraint("event_id", "block_code", name="event_block_unique_code"),)
    id = Column(String, primary_key=True)  # UUID
    event_id = Column(String, nullable=False)  # UUID
    block_code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    starts_at = Column(String, nullable=False)
    ends_at = Column(String, nullable=False)
    grace_period_minutes = Column(Integer, nullable=False, default=0)
    allow_overlap = Column(Boolean, nullable=False, default=False)
    priority = Column(Integer, nullable=False, default=100)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String, nullable=True)  # UUID
    updated_by = Column(String, nullable=True)  # UUID
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class _EventConfigVersionRow(_Base):
    __tablename__ = "event_config_version"
    __table_args__ = (UniqueConstraint("event_id", "version_number", name="event_config_version_unique"),)
    id = Column(String, primary_key=True)  # UUID
    event_id = Column(String, nullable=False)  # UUID
    version_number = Column(Integer, nullable=False)
    config_snapshot = Column(Text, nullable=False)  # JSONB
    created_by = Column(String, nullable=True)  # UUID
    created_at = Column(String, nullable=False)


# ── Service ───────────────────────────────────────────────────────────────────


class EventBlockConfigService:
    """Persists event and block configuration with version snapshots."""

    def __init__(self, db_path: str | None = None, db_url: str | None = None) -> None:
        from app.core.config import get_settings
        if db_path is not None:
            url = f"sqlite:///{db_path}"
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        else:
            url = db_url or get_settings().database_url
        self._engine = make_engine(url)
        self._session_factory = make_session_factory(self._engine)
        _Base.metadata.create_all(self._engine)

    # ── Schema ───────────────────────────────────────────────────────────────

    # (Schema managed via SQLAlchemy metadata / create_all in __init__)

    # ── Internal helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _to_str(v) -> str | None:
        if v is None:
            return None
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return str(v)

    def _row_to_event(self, row: _EventConfigRow) -> EventRecord:
        return EventRecord(
            event_id=str(row.id),  # Map database id to event_id
            wix_event_id=row.wix_event_id,
            name=row.name,
            timezone=row.timezone,
            status=row.status,
            allow_block_overlap=bool(row.allow_block_overlap),
            sync_enabled=bool(row.sync_enabled),
            created_at=self._to_str(row.created_at),
            updated_at=self._to_str(row.updated_at),
        )

    def _row_to_block(self, row: _EventBlockRow) -> EventBlockRecord:
        return EventBlockRecord(
            block_id=str(row.id),  # Map database id to block_id
            event_id=str(row.event_id),
            block_code=row.block_code,
            name=row.name,
            starts_at=self._to_str(row.starts_at),
            ends_at=self._to_str(row.ends_at),
            grace_period_minutes=row.grace_period_minutes,
            allow_overlap=bool(row.allow_overlap),
            priority=row.priority,
            is_active=bool(row.is_active),
            created_at=self._to_str(row.created_at),
            updated_at=self._to_str(row.updated_at),
        )

    def _snapshot_event(self, session, event_id: str, version: int, actor: str) -> None:
        from sqlalchemy import select
        blocks = session.execute(
            select(_EventBlockRow).where(_EventBlockRow.event_id == event_id)
        ).scalars().all()
        event_row = session.execute(
            select(_EventConfigRow).where(_EventConfigRow.id == event_id)
        ).scalar_one_or_none()

        def _to_str(v):
            return str(v) if v is not None else None

        snapshot = {
            "event": {c.name: _to_str(getattr(event_row, c.name)) for c in _EventConfigRow.__table__.columns} if event_row else {},
            "blocks": [{c.name: _to_str(getattr(b, c.name)) for c in _EventBlockRow.__table__.columns} for b in blocks],
        }
        session.add(_EventConfigVersionRow(
            id=str(uuid4()),
            event_id=event_id,
            version_number=version,
            config_snapshot=json.dumps(snapshot),
            created_by=None,  # Actor string is not a UUID
            created_at=self._now(),
        ))

    def _next_version_number(self, session, event_id: str) -> int:
        from sqlalchemy import select, func
        latest = session.execute(
            select(func.max(_EventConfigVersionRow.version_number))
            .where(_EventConfigVersionRow.event_id == event_id)
        ).scalar_one_or_none()
        return int(latest or 0) + 1

    # ── Overlap detection ────────────────────────────────────────────────────

    def _check_overlap(
        self,
        session,
        event_id: str,
        starts_at: str,
        ends_at: str,
        exclude_block_id: str | None = None,
    ) -> bool:
        """Return True if any active block in the event overlaps [starts_at, ends_at)."""
        from sqlalchemy import select
        rows = session.execute(
            select(_EventBlockRow)
            .where(_EventBlockRow.event_id == event_id)
            .where(_EventBlockRow.is_active == True)
        ).scalars().all()
        new_start = datetime.fromisoformat(starts_at)
        new_end = datetime.fromisoformat(ends_at)
        for row in rows:
            if exclude_block_id and row.id == exclude_block_id:
                continue
            existing_start = datetime.fromisoformat(row.starts_at)
            existing_end = datetime.fromisoformat(row.ends_at)
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
        from sqlalchemy import select
        event_id = str(uuid4())
        now = self._now()
        with self._session_factory() as session:
            row = _EventConfigRow(
                id=event_id,
                wix_event_id=wix_event_id,
                name=name,
                timezone=timezone,
                status="draft",
                allow_block_overlap=allow_block_overlap,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
            self._snapshot_event(session, event_id, 1, actor)
            session.commit()
            result = session.execute(
                select(_EventConfigRow).where(_EventConfigRow.id == event_id)
            ).scalar_one()
            return self._row_to_event(result)

    def get_event_by_wix_event_id(self, wix_event_id: str) -> EventRecord | None:
        from sqlalchemy import select
        with self._session_factory() as session:
            row = session.execute(
                select(_EventConfigRow).where(_EventConfigRow.wix_event_id == wix_event_id)
            ).scalar_one_or_none()
        return self._row_to_event(row) if row else None

    def upsert_event(
        self,
        *,
        wix_event_id: str,
        name: str,
        timezone: str = "UTC",
        allow_block_overlap: bool = False,
        actor: str = "system",
    ) -> tuple[EventRecord, bool]:
        existing = self.get_event_by_wix_event_id(wix_event_id)
        if existing is not None:
            updated = self.update_event(
                existing.event_id,
                name=name,
                timezone=timezone,
                allow_block_overlap=allow_block_overlap,
                actor=actor,
            )
            return updated, False

        created = self.create_event(
            wix_event_id=wix_event_id,
            name=name,
            timezone=timezone,
            allow_block_overlap=allow_block_overlap,
            actor=actor,
        )
        return created, True

    def get_event(self, event_id: str) -> EventRecord | None:
        from sqlalchemy import select
        with self._session_factory() as session:
            row = session.execute(
                select(_EventConfigRow).where(_EventConfigRow.id == event_id)
            ).scalar_one_or_none()
        return self._row_to_event(row) if row else None

    def list_events(self) -> list[EventRecord]:
        from sqlalchemy import select, desc
        with self._session_factory() as session:
            rows = session.execute(
                select(_EventConfigRow).order_by(desc(_EventConfigRow.created_at))
            ).scalars().all()
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
        from sqlalchemy import select
        with self._session_factory() as session:
            row = session.execute(
                select(_EventConfigRow).where(_EventConfigRow.id == event_id)
            ).scalar_one_or_none()
            if not row:
                raise KeyError(f"Event {event_id!r} not found.")
            now = self._now()
            if name is not None:
                row.name = name
            if timezone is not None:
                row.timezone = timezone
            if status is not None:
                row.status = status
            if allow_block_overlap is not None:
                row.allow_block_overlap = allow_block_overlap
            row.updated_by = None  # No real user UUID
            row.updated_at = now
            self._snapshot_event(session, event_id, self._next_version_number(session, event_id), actor)
            session.commit()
            updated = session.execute(
                select(_EventConfigRow).where(_EventConfigRow.id == event_id)
            ).scalar_one()
            return self._row_to_event(updated)

    def delete_event(self, event_id: str) -> None:
        from sqlalchemy import select, delete
        with self._session_factory() as session:
            session.execute(delete(_EventConfigRow).where(_EventConfigRow.id == event_id))
            session.commit()

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

        from sqlalchemy import select
        block_id = str(uuid4())
        now = self._now()

        with self._session_factory() as session:
            event_row = session.execute(
                select(_EventConfigRow).where(_EventConfigRow.id == event_id)
            ).scalar_one_or_none()
            if not event_row:
                raise KeyError(f"Event {event_id!r} not found.")

            if not event_row.allow_block_overlap and not allow_overlap:
                if self._check_overlap(session, event_id, starts_at, ends_at):
                    raise BlockValidationError(
                        "Block overlaps an existing active block and overlap is disabled for this event."
                    )

            block_row = _EventBlockRow(
                id=block_id,  # Use block_id as the id field
                event_id=event_id,
                block_code=block_code,
                name=name,
                starts_at=starts_at,
                ends_at=ends_at,
                grace_period_minutes=grace_period_minutes,
                allow_overlap=allow_overlap,
                priority=priority,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            session.add(block_row)
            event_row.updated_at = now
            event_row.updated_by = actor
            self._snapshot_event(session, event_id, self._next_version_number(session, event_id), actor)
            session.commit()
            result = session.execute(
                select(_EventBlockRow).where(_EventBlockRow.id == block_id)
            ).scalar_one()
            return self._row_to_block(result)

    def get_block(self, block_id: str) -> EventBlockRecord | None:
        from sqlalchemy import select
        with self._session_factory() as session:
            row = session.execute(
                select(_EventBlockRow).where(_EventBlockRow.id == block_id)
            ).scalar_one_or_none()
        return self._row_to_block(row) if row else None

    def list_blocks(self, event_id: str) -> list[EventBlockRecord]:
        from sqlalchemy import select, asc
        with self._session_factory() as session:
            rows = session.execute(
                select(_EventBlockRow)
                .where(_EventBlockRow.event_id == event_id)
                .order_by(asc(_EventBlockRow.priority), asc(_EventBlockRow.starts_at))
            ).scalars().all()
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
        from sqlalchemy import select
        with self._session_factory() as session:
            block_row = session.execute(
                select(_EventBlockRow).where(_EventBlockRow.id == block_id)
            ).scalar_one_or_none()
            if not block_row:
                raise KeyError(f"Block {block_id!r} not found.")

            eff_starts = starts_at or block_row.starts_at
            eff_ends = ends_at or block_row.ends_at
            _validate_time_range(eff_starts, eff_ends)

            if grace_period_minutes is not None:
                _validate_grace_period(grace_period_minutes)
            if priority is not None:
                _validate_priority(priority)

            event_row = session.execute(
                select(_EventConfigRow).where(_EventConfigRow.id == block_row.event_id)
            ).scalar_one_or_none()

            eff_allow_overlap = allow_overlap if allow_overlap is not None else bool(block_row.allow_overlap)
            if event_row and not event_row.allow_block_overlap and not eff_allow_overlap:
                if self._check_overlap(session, block_row.event_id, eff_starts, eff_ends, exclude_block_id=block_id):
                    raise BlockValidationError(
                        "Updated block overlaps an existing active block and overlap is disabled."
                    )

            now = self._now()
            if name is not None:
                block_row.name = name
            if starts_at is not None:
                block_row.starts_at = starts_at
            if ends_at is not None:
                block_row.ends_at = ends_at
            if grace_period_minutes is not None:
                block_row.grace_period_minutes = grace_period_minutes
            if allow_overlap is not None:
                block_row.allow_overlap = allow_overlap
            if priority is not None:
                block_row.priority = priority
            if is_active is not None:
                block_row.is_active = is_active
            block_row.updated_at = now
            block_row.updated_by = actor
            if event_row:
                event_row.updated_at = now
                event_row.updated_by = actor
                self._snapshot_event(
                    session,
                    block_row.event_id,
                    self._next_version_number(session, block_row.event_id),
                    actor,
                )

            session.commit()
            updated = session.execute(
                select(_EventBlockRow).where(_EventBlockRow.id == block_id)
            ).scalar_one()
            return self._row_to_block(updated)

    def delete_block(self, block_id: str, actor: str = "system") -> None:
        from sqlalchemy import select, delete
        with self._session_factory() as session:
            block_row = session.execute(
                select(_EventBlockRow).where(_EventBlockRow.id == block_id)
            ).scalar_one_or_none()
            if not block_row:
                raise KeyError(f"Block {block_id!r} not found.")
            event_id = block_row.event_id
            session.execute(delete(_EventBlockRow).where(_EventBlockRow.id == block_id))
            event_row = session.execute(
                select(_EventConfigRow).where(_EventConfigRow.id == event_id)
            ).scalar_one_or_none()
            if event_row:
                now = self._now()
                event_row.updated_at = now
                event_row.updated_by = actor
                self._snapshot_event(session, event_id, self._next_version_number(session, event_id), actor)
            session.commit()

    # ── Block selection ───────────────────────────────────────────────────────

    def select_block_for_wix_event(
        self,
        wix_event_id: str,
        scan_timestamp: datetime,
    ) -> EventBlockRecord | None:
        from datetime import timedelta
        from sqlalchemy import select
        with self._session_factory() as session:
            event_row = session.execute(
                select(_EventConfigRow).where(_EventConfigRow.wix_event_id == wix_event_id)
            ).scalar_one_or_none()
            if not event_row:
                return None
            event_id = event_row.id  # Use id as event_id
            rows = session.execute(
                select(_EventBlockRow)
                .where(_EventBlockRow.event_id == event_id)
                .where(_EventBlockRow.is_active == True)
            ).scalars().all()
            blocks = [self._row_to_block(r) for r in rows]

        eligible: list[EventBlockRecord] = []
        for block in blocks:
            start = datetime.fromisoformat(block.starts_at)
            end = datetime.fromisoformat(block.ends_at)
            effective_start = start - timedelta(minutes=block.grace_period_minutes)
            if effective_start <= scan_timestamp < end:
                eligible.append(block)

        if not eligible:
            return None

        eligible.sort(key=lambda b: (b.priority, b.starts_at, b.block_id))
        return eligible[0]

    def list_config_versions(self, event_id: str) -> list[ConfigVersionRecord]:
        from sqlalchemy import select, desc
        with self._session_factory() as session:
            rows = session.execute(
                select(_EventConfigVersionRow)
                .where(_EventConfigVersionRow.event_id == event_id)
                .order_by(desc(_EventConfigVersionRow.version_number))
            ).scalars().all()
        return [
            ConfigVersionRecord(
                version_id=r.id,  # Map id to version_id
                event_id=r.event_id,
                version_number=r.version_number,
                config_snapshot=json.loads(r.config_snapshot),
                created_at=r.created_at,
                created_by=r.created_by,
            )
            for r in rows
        ]
