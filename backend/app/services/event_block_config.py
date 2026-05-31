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


# ── ORM models ───────────────────────────────────────────────────────────────


class _Base(DeclarativeBase):
    pass


class _EventConfigRow(_Base):
    __tablename__ = "event_config"
    __table_args__ = (UniqueConstraint("event_id"), UniqueConstraint("wix_event_id"))
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String, nullable=False, unique=True)
    wix_event_id = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    timezone = Column(String, nullable=False, default="UTC")
    status = Column(String, nullable=False, default="draft")
    allow_block_overlap = Column(Integer, nullable=False, default=0)
    version = Column(Integer, nullable=False, default=1)
    actor = Column(String, nullable=False, default="system")
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class _EventBlockRow(_Base):
    __tablename__ = "event_block"
    __table_args__ = (UniqueConstraint("event_id", "block_code", name="event_block_unique_code"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    block_id = Column(String, nullable=False, unique=True)
    event_id = Column(String, nullable=False)
    block_code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    starts_at = Column(String, nullable=False)
    ends_at = Column(String, nullable=False)
    grace_period_minutes = Column(Integer, nullable=False, default=0)
    allow_overlap = Column(Integer, nullable=False, default=0)
    priority = Column(Integer, nullable=False, default=100)
    is_active = Column(Integer, nullable=False, default=1)
    version = Column(Integer, nullable=False, default=1)
    actor = Column(String, nullable=False, default="system")
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class _EventConfigVersionRow(_Base):
    __tablename__ = "event_config_version"
    __table_args__ = (UniqueConstraint("event_id", "version_number", name="event_config_version_unique"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    version_id = Column(String, nullable=False, unique=True)
    event_id = Column(String, nullable=False)
    version_number = Column(Integer, nullable=False)
    config_snapshot = Column(Text, nullable=False)
    actor = Column(String, nullable=False, default="system")
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

    def _row_to_event(self, row: _EventConfigRow) -> EventRecord:
        return EventRecord(
            event_id=row.event_id,
            wix_event_id=row.wix_event_id,
            name=row.name,
            timezone=row.timezone,
            status=row.status,
            allow_block_overlap=bool(row.allow_block_overlap),
            version=row.version,
            created_at=row.created_at,
            updated_at=row.updated_at,
            actor=row.actor,
        )

    def _row_to_block(self, row: _EventBlockRow) -> EventBlockRecord:
        return EventBlockRecord(
            block_id=row.block_id,
            event_id=row.event_id,
            block_code=row.block_code,
            name=row.name,
            starts_at=row.starts_at,
            ends_at=row.ends_at,
            grace_period_minutes=row.grace_period_minutes,
            allow_overlap=bool(row.allow_overlap),
            priority=row.priority,
            is_active=bool(row.is_active),
            version=row.version,
            created_at=row.created_at,
            updated_at=row.updated_at,
            actor=row.actor,
        )

    def _snapshot_event(self, session, event_id: str, version: int, actor: str) -> None:
        from sqlalchemy import select
        blocks = session.execute(
            select(_EventBlockRow).where(_EventBlockRow.event_id == event_id)
        ).scalars().all()
        event_row = session.execute(
            select(_EventConfigRow).where(_EventConfigRow.event_id == event_id)
        ).scalar_one_or_none()
        snapshot = {
            "event": {c.name: getattr(event_row, c.name) for c in _EventConfigRow.__table__.columns} if event_row else {},
            "blocks": [{c.name: getattr(b, c.name) for c in _EventBlockRow.__table__.columns} for b in blocks],
        }
        session.add(_EventConfigVersionRow(
            version_id=str(uuid4()),
            event_id=event_id,
            version_number=version,
            config_snapshot=json.dumps(snapshot),
            actor=actor,
            created_at=self._now(),
        ))

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
            .where(_EventBlockRow.is_active == 1)
        ).scalars().all()
        new_start = datetime.fromisoformat(starts_at)
        new_end = datetime.fromisoformat(ends_at)
        for row in rows:
            if exclude_block_id and row.block_id == exclude_block_id:
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
                event_id=event_id,
                wix_event_id=wix_event_id,
                name=name,
                timezone=timezone,
                status="draft",
                allow_block_overlap=int(allow_block_overlap),
                version=1,
                actor=actor,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
            self._snapshot_event(session, event_id, 1, actor)
            session.commit()
            result = session.execute(
                select(_EventConfigRow).where(_EventConfigRow.event_id == event_id)
            ).scalar_one()
            return self._row_to_event(result)

    def get_event(self, event_id: str) -> EventRecord | None:
        from sqlalchemy import select
        with self._session_factory() as session:
            row = session.execute(
                select(_EventConfigRow).where(_EventConfigRow.event_id == event_id)
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
                select(_EventConfigRow).where(_EventConfigRow.event_id == event_id)
            ).scalar_one_or_none()
            if not row:
                raise KeyError(f"Event {event_id!r} not found.")
            now = self._now()
            new_version = row.version + 1
            if name is not None:
                row.name = name
            if timezone is not None:
                row.timezone = timezone
            if status is not None:
                row.status = status
            if allow_block_overlap is not None:
                row.allow_block_overlap = int(allow_block_overlap)
            row.version = new_version
            row.actor = actor
            row.updated_at = now
            self._snapshot_event(session, event_id, new_version, actor)
            session.commit()
            updated = session.execute(
                select(_EventConfigRow).where(_EventConfigRow.event_id == event_id)
            ).scalar_one()
            return self._row_to_event(updated)

    def delete_event(self, event_id: str) -> None:
        from sqlalchemy import select, delete
        with self._session_factory() as session:
            session.execute(delete(_EventConfigRow).where(_EventConfigRow.event_id == event_id))
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
                select(_EventConfigRow).where(_EventConfigRow.event_id == event_id)
            ).scalar_one_or_none()
            if not event_row:
                raise KeyError(f"Event {event_id!r} not found.")

            if not event_row.allow_block_overlap and not allow_overlap:
                if self._check_overlap(session, event_id, starts_at, ends_at):
                    raise BlockValidationError(
                        "Block overlaps an existing active block and overlap is disabled for this event."
                    )

            block_row = _EventBlockRow(
                block_id=block_id,
                event_id=event_id,
                block_code=block_code,
                name=name,
                starts_at=starts_at,
                ends_at=ends_at,
                grace_period_minutes=grace_period_minutes,
                allow_overlap=int(allow_overlap),
                priority=priority,
                is_active=1,
                version=1,
                actor=actor,
                created_at=now,
                updated_at=now,
            )
            session.add(block_row)
            new_event_version = event_row.version + 1
            event_row.version = new_event_version
            event_row.actor = actor
            event_row.updated_at = now
            session.flush()
            self._snapshot_event(session, event_id, new_event_version, actor)
            session.commit()
            result = session.execute(
                select(_EventBlockRow).where(_EventBlockRow.block_id == block_id)
            ).scalar_one()
            return self._row_to_block(result)

    def get_block(self, block_id: str) -> EventBlockRecord | None:
        from sqlalchemy import select
        with self._session_factory() as session:
            row = session.execute(
                select(_EventBlockRow).where(_EventBlockRow.block_id == block_id)
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
                select(_EventBlockRow).where(_EventBlockRow.block_id == block_id)
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
                select(_EventConfigRow).where(_EventConfigRow.event_id == block_row.event_id)
            ).scalar_one_or_none()

            eff_allow_overlap = allow_overlap if allow_overlap is not None else bool(block_row.allow_overlap)
            if event_row and not event_row.allow_block_overlap and not eff_allow_overlap:
                if self._check_overlap(session, block_row.event_id, eff_starts, eff_ends, exclude_block_id=block_id):
                    raise BlockValidationError(
                        "Updated block overlaps an existing active block and overlap is disabled."
                    )

            now = self._now()
            new_version = block_row.version + 1
            if name is not None:
                block_row.name = name
            if starts_at is not None:
                block_row.starts_at = starts_at
            if ends_at is not None:
                block_row.ends_at = ends_at
            if grace_period_minutes is not None:
                block_row.grace_period_minutes = grace_period_minutes
            if allow_overlap is not None:
                block_row.allow_overlap = int(allow_overlap)
            if priority is not None:
                block_row.priority = priority
            if is_active is not None:
                block_row.is_active = int(is_active)
            block_row.version = new_version
            block_row.actor = actor
            block_row.updated_at = now

            if event_row:
                new_event_version = event_row.version + 1
                event_row.version = new_event_version
                event_row.actor = actor
                event_row.updated_at = now
                self._snapshot_event(session, block_row.event_id, new_event_version, actor)

            session.commit()
            updated = session.execute(
                select(_EventBlockRow).where(_EventBlockRow.block_id == block_id)
            ).scalar_one()
            return self._row_to_block(updated)

    def delete_block(self, block_id: str, actor: str = "system") -> None:
        from sqlalchemy import select, delete
        with self._session_factory() as session:
            block_row = session.execute(
                select(_EventBlockRow).where(_EventBlockRow.block_id == block_id)
            ).scalar_one_or_none()
            if not block_row:
                raise KeyError(f"Block {block_id!r} not found.")
            event_id = block_row.event_id
            session.execute(delete(_EventBlockRow).where(_EventBlockRow.block_id == block_id))
            event_row = session.execute(
                select(_EventConfigRow).where(_EventConfigRow.event_id == event_id)
            ).scalar_one_or_none()
            if event_row:
                now = self._now()
                new_event_version = event_row.version + 1
                event_row.version = new_event_version
                event_row.actor = actor
                event_row.updated_at = now
                self._snapshot_event(session, event_id, new_event_version, actor)
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
            event_id = event_row.event_id
            rows = session.execute(
                select(_EventBlockRow)
                .where(_EventBlockRow.event_id == event_id)
                .where(_EventBlockRow.is_active == 1)
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
                version_id=r.version_id,
                event_id=r.event_id,
                version_number=r.version_number,
                config_snapshot=json.loads(r.config_snapshot),
                created_at=r.created_at,
                actor=r.actor,
            )
            for r in rows
        ]
