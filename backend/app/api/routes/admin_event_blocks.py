from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.services.event_block_config import (
    BlockValidationError,
    EventBlockRecord,
    EventRecord,
    EventStatus,
    get_event_block_config_service,
)

router = APIRouter(prefix="/admin/event-blocks")


# ── Request / Response models ─────────────────────────────────────────────────


class CreateEventRequest(BaseModel):
    wix_event_id: str = Field(min_length=3, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    timezone: str = Field(default="UTC", max_length=64)
    allow_block_overlap: bool = False
    actor: str = Field(default="system", min_length=2, max_length=128)


class UpdateEventRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    timezone: str | None = Field(default=None, max_length=64)
    status: EventStatus | None = None
    allow_block_overlap: bool | None = None
    actor: str = Field(default="system", min_length=2, max_length=128)


class EventResponse(BaseModel):
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


class CreateBlockRequest(BaseModel):
    block_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=256)
    starts_at: str = Field(description="ISO 8601 datetime")
    ends_at: str = Field(description="ISO 8601 datetime, must be after starts_at")
    grace_period_minutes: int = Field(default=0, ge=0, le=120)
    allow_overlap: bool = False
    priority: int = Field(default=100, ge=0)
    actor: str = Field(default="system", min_length=2, max_length=128)


class UpdateBlockRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    starts_at: str | None = None
    ends_at: str | None = None
    grace_period_minutes: int | None = Field(default=None, ge=0, le=120)
    allow_overlap: bool | None = None
    priority: int | None = Field(default=None, ge=0)
    is_active: bool | None = None
    actor: str = Field(default="system", min_length=2, max_length=128)


class BlockResponse(BaseModel):
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


class ConfigVersionResponse(BaseModel):
    version_id: str
    event_id: str
    version_number: int
    config_snapshot: dict
    created_at: str
    actor: str


# ── Converters ────────────────────────────────────────────────────────────────


def _event_to_response(r: EventRecord) -> EventResponse:
    return EventResponse(
        event_id=r.event_id,
        wix_event_id=r.wix_event_id,
        name=r.name,
        timezone=r.timezone,
        status=r.status,
        allow_block_overlap=r.allow_block_overlap,
        version=r.version,
        created_at=r.created_at,
        updated_at=r.updated_at,
        actor=r.actor,
    )


def _block_to_response(r: EventBlockRecord) -> BlockResponse:
    return BlockResponse(
        block_id=r.block_id,
        event_id=r.event_id,
        block_code=r.block_code,
        name=r.name,
        starts_at=r.starts_at,
        ends_at=r.ends_at,
        grace_period_minutes=r.grace_period_minutes,
        allow_overlap=r.allow_overlap,
        priority=r.priority,
        is_active=r.is_active,
        version=r.version,
        created_at=r.created_at,
        updated_at=r.updated_at,
        actor=r.actor,
    )


# ── Event endpoints ───────────────────────────────────────────────────────────


@router.post("/events", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
def create_event(request: CreateEventRequest) -> EventResponse:
    svc = get_event_block_config_service()
    try:
        record = svc.create_event(
            wix_event_id=request.wix_event_id,
            name=request.name,
            timezone=request.timezone,
            allow_block_overlap=request.allow_block_overlap,
            actor=request.actor,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _event_to_response(record)


@router.get("/events", response_model=list[EventResponse])
def list_events() -> list[EventResponse]:
    svc = get_event_block_config_service()
    return [_event_to_response(r) for r in svc.list_events()]


@router.get("/events/{event_id}", response_model=EventResponse)
def get_event(event_id: str) -> EventResponse:
    svc = get_event_block_config_service()
    record = svc.get_event(event_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Event {event_id!r} not found.")
    return _event_to_response(record)


@router.put("/events/{event_id}", response_model=EventResponse)
def update_event(event_id: str, request: UpdateEventRequest) -> EventResponse:
    svc = get_event_block_config_service()
    try:
        record = svc.update_event(
            event_id,
            name=request.name,
            timezone=request.timezone,
            status=request.status,
            allow_block_overlap=request.allow_block_overlap,
            actor=request.actor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _event_to_response(record)


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(event_id: str) -> None:
    svc = get_event_block_config_service()
    svc.delete_event(event_id)


# ── Block endpoints ───────────────────────────────────────────────────────────


@router.post(
    "/events/{event_id}/blocks",
    response_model=BlockResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_block(event_id: str, request: CreateBlockRequest) -> BlockResponse:
    svc = get_event_block_config_service()
    try:
        record = svc.create_block(
            event_id,
            block_code=request.block_code,
            name=request.name,
            starts_at=request.starts_at,
            ends_at=request.ends_at,
            grace_period_minutes=request.grace_period_minutes,
            allow_overlap=request.allow_overlap,
            priority=request.priority,
            actor=request.actor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BlockValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _block_to_response(record)


@router.get("/events/{event_id}/blocks", response_model=list[BlockResponse])
def list_blocks(event_id: str) -> list[BlockResponse]:
    svc = get_event_block_config_service()
    return [_block_to_response(r) for r in svc.list_blocks(event_id)]


@router.get("/blocks/{block_id}", response_model=BlockResponse)
def get_block(block_id: str) -> BlockResponse:
    svc = get_event_block_config_service()
    record = svc.get_block(block_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Block {block_id!r} not found.")
    return _block_to_response(record)


@router.put("/blocks/{block_id}", response_model=BlockResponse)
def update_block(block_id: str, request: UpdateBlockRequest) -> BlockResponse:
    svc = get_event_block_config_service()
    try:
        record = svc.update_block(
            block_id,
            name=request.name,
            starts_at=request.starts_at,
            ends_at=request.ends_at,
            grace_period_minutes=request.grace_period_minutes,
            allow_overlap=request.allow_overlap,
            priority=request.priority,
            is_active=request.is_active,
            actor=request.actor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BlockValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _block_to_response(record)


@router.delete("/blocks/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_block(block_id: str) -> None:
    svc = get_event_block_config_service()
    try:
        svc.delete_block(block_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ── Version history ───────────────────────────────────────────────────────────


@router.get("/events/{event_id}/versions", response_model=list[ConfigVersionResponse])
def list_config_versions(event_id: str) -> list[ConfigVersionResponse]:
    svc = get_event_block_config_service()
    versions = svc.list_config_versions(event_id)
    return [
        ConfigVersionResponse(
            version_id=v.version_id,
            event_id=v.event_id,
            version_number=v.version_number,
            config_snapshot=v.config_snapshot,
            created_at=v.created_at,
            actor=v.actor,
        )
        for v in versions
    ]
