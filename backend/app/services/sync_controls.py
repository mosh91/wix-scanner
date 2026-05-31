from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import time

from sqlalchemy import Boolean, Column, Float, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import Settings, get_settings
from app.db import make_engine
from app.services.ticket_manifest import get_ticket_manifest_service

Base = declarative_base()


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


class _WixSyncControl(Base):
    __tablename__ = "wix_sync_controls"

    event_id = Column(String, primary_key=True)
    enabled = Column(Boolean, nullable=False, default=False)
    interval_seconds = Column(Integer, nullable=False, default=60)
    last_successful_sync_at = Column(Float, nullable=True)
    last_attempt_at = Column(Float, nullable=True)
    last_error = Column(String, nullable=True)
    created_at = Column(Float, nullable=False)
    updated_at = Column(Float, nullable=False)


class WixSyncControlService:
    def __init__(
        self,
        *,
        db_path: str | None = None,
        db_url: str | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        if db_url:
            url = db_url
        elif db_path:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            url = f"sqlite:///{Path(db_path).resolve()}"
        else:
            url = self._settings.database_url
        self._engine = make_engine(url)
        Base.metadata.create_all(self._engine)
        self._Session = sessionmaker(bind=self._engine, autoflush=False, autocommit=False)

    def _to_record(self, row: _WixSyncControl, now_ts: float) -> WixSyncControlRecord:
        last_successful = float(row.last_successful_sync_at) if row.last_successful_sync_at is not None else None
        lag_seconds = int(max(0, now_ts - last_successful)) if last_successful is not None else None
        return WixSyncControlRecord(
            event_id=row.event_id,
            enabled=bool(row.enabled),
            interval_seconds=int(row.interval_seconds),
            last_successful_sync_at=last_successful,
            last_attempt_at=float(row.last_attempt_at) if row.last_attempt_at is not None else None,
            current_lag_seconds=lag_seconds,
            last_error=row.last_error,
            updated_at=float(row.updated_at),
        )

    def get_control(self, *, event_id: str, now_ts: float | None = None) -> WixSyncControlRecord:
        current = now_ts or time()
        with self._Session() as session:
            row = session.query(_WixSyncControl).filter_by(event_id=event_id).first()

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
        with self._Session() as session:
            row = session.query(_WixSyncControl).filter_by(event_id=event_id).first()
            if row is None:
                row = _WixSyncControl(
                    event_id=event_id,
                    enabled=enabled,
                    interval_seconds=safe_interval,
                    created_at=now_ts,
                    updated_at=now_ts,
                )
                session.add(row)
            else:
                row.enabled = enabled
                row.interval_seconds = safe_interval
                row.updated_at = now_ts
            session.commit()
            session.refresh(row)
            record = self._to_record(row, now_ts)
        return record

    def list_controls(self, *, limit: int = 100, now_ts: float | None = None) -> list[WixSyncControlRecord]:
        current = now_ts or time()
        with self._Session() as session:
            rows = (
                session.query(_WixSyncControl)
                .order_by(_WixSyncControl.event_id.asc())
                .limit(max(1, min(limit, 200)))
                .all()
            )
        return [self._to_record(r, current) for r in rows]

    def process_due_syncs(self, *, now_ts: float | None = None, max_items: int = 25) -> int:
        current = now_ts or time()
        processed = 0

        with self._Session() as session:
            due_rows = (
                session.query(_WixSyncControl)
                .filter(
                    _WixSyncControl.enabled.is_(True),
                    (
                        (_WixSyncControl.last_attempt_at.is_(None))
                        | ((current - _WixSyncControl.last_attempt_at) >= _WixSyncControl.interval_seconds)
                    ),
                )
                .order_by(_WixSyncControl.last_attempt_at.asc().nullsfirst())
                .limit(max(1, min(max_items, 100)))
                .all()
            )
            due_event_ids = [r.event_id for r in due_rows]

        if not due_event_ids:
            return 0

        manifest_service = get_ticket_manifest_service()
        for event_id in due_event_ids:
            with self._Session() as session:
                row = session.query(_WixSyncControl).filter_by(event_id=event_id).first()
                if row is None:
                    continue
                row.last_attempt_at = current
                row.updated_at = current
                session.commit()

            try:
                manifest_service.sync_event_from_wix(event_id)
            except Exception as exc:  # pragma: no cover
                with self._Session() as session:
                    row = session.query(_WixSyncControl).filter_by(event_id=event_id).first()
                    if row is not None:
                        row.last_error = str(exc)[:500]
                        row.updated_at = current
                        session.commit()
                continue

            with self._Session() as session:
                row = session.query(_WixSyncControl).filter_by(event_id=event_id).first()
                if row is not None:
                    row.last_successful_sync_at = current
                    row.last_error = None
                    row.updated_at = current
                    session.commit()

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
        _sync_control_service = WixSyncControlService(settings=settings)
    return _sync_control_service
