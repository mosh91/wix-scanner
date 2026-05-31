from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.services.sync_controls import WixSyncControlRecord, get_sync_control_service

router = APIRouter(prefix="/admin/sync-controls")


class WixSyncControlRequest(BaseModel):
    enabled: bool
    interval_seconds: int = Field(default=60, ge=30, le=300)


class WixSyncControlResponse(BaseModel):
    event_id: str
    enabled: bool
    interval_seconds: int
    last_successful_sync_at: float | None
    last_attempt_at: float | None
    current_lag_seconds: int | None
    last_error: str | None
    updated_at: float



def _to_response(record: WixSyncControlRecord) -> WixSyncControlResponse:
    return WixSyncControlResponse(
        event_id=record.event_id,
        enabled=record.enabled,
        interval_seconds=record.interval_seconds,
        last_successful_sync_at=record.last_successful_sync_at,
        last_attempt_at=record.last_attempt_at,
        current_lag_seconds=record.current_lag_seconds,
        last_error=record.last_error,
        updated_at=record.updated_at,
    )


@router.get("/events/{event_id}", response_model=WixSyncControlResponse)
def get_event_sync_control(event_id: str) -> WixSyncControlResponse:
    record = get_sync_control_service().get_control(event_id=event_id)
    return _to_response(record)


@router.put("/events/{event_id}", response_model=WixSyncControlResponse)
def upsert_event_sync_control(event_id: str, request: WixSyncControlRequest) -> WixSyncControlResponse:
    record = get_sync_control_service().upsert_control(
        event_id=event_id,
        enabled=request.enabled,
        interval_seconds=request.interval_seconds,
    )
    return _to_response(record)


@router.get("/events", response_model=list[WixSyncControlResponse])
def list_event_sync_controls(limit: int = Query(default=100, ge=1, le=200)) -> list[WixSyncControlResponse]:
    records = get_sync_control_service().list_controls(limit=limit)
    return [_to_response(record) for record in records]
