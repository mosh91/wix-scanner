"""Admin reset endpoints — clear check-in deduplication state with audit trail."""

from __future__ import annotations

from datetime import datetime, UTC

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.api.routes.checkins import get_scan_idempotency_service
from app.core.config import get_settings
from app.services.event_block_config import get_event_block_config_service
from app.services.reset_audit import get_reset_audit_service

router = APIRouter(prefix="/admin/resets")


# ── Request / Response models ─────────────────────────────────────────────────


class ResetRequest(BaseModel):
    confirmation: bool
    reason: str = Field(min_length=3, max_length=512)
    actor: str = Field(min_length=2, max_length=128)


class ResetResponse(BaseModel):
    reset_id: str
    scope: str
    scope_id: str
    actor: str
    reason: str
    records_cleared: int
    performed_at: str


class AuditRecordResponse(BaseModel):
    reset_id: str
    scope: str
    scope_id: str
    actor: str
    reason: str
    records_cleared: int
    performed_at: str


# ── Auth guard ────────────────────────────────────────────────────────────────


def _require_admin(authorization: str | None) -> None:
    if not authorization:
        raise HTTPException(status_code=403, detail="Forbidden")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or token != get_settings().admin_api_key:
        raise HTTPException(status_code=403, detail="Forbidden")


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/event/{wix_event_id}", response_model=ResetResponse)
def reset_event(
    wix_event_id: str,
    body: ResetRequest,
    authorization: str | None = Header(default=None),
) -> ResetResponse:
    """Reset all check-in deduplication records for an event."""
    _require_admin(authorization)
    if not body.confirmation:
        raise HTTPException(
            status_code=422,
            detail="confirmation must be true to execute a reset",
        )

    scan_svc = get_scan_idempotency_service()
    if scan_svc is None:
        raise HTTPException(status_code=503, detail="Scan service unavailable")

    records_cleared = scan_svc.delete_by_event_id(wix_event_id)

    audit_svc = get_reset_audit_service()
    entry = audit_svc.record_reset(
        scope="event",
        scope_id=wix_event_id,
        actor=body.actor,
        reason=body.reason,
        records_cleared=records_cleared,
    )

    return ResetResponse(
        reset_id=entry.reset_id,
        scope=entry.scope,
        scope_id=entry.scope_id,
        actor=entry.actor,
        reason=entry.reason,
        records_cleared=entry.records_cleared,
        performed_at=entry.performed_at,
    )


@router.post("/block/{block_id}", response_model=ResetResponse)
def reset_block(
    block_id: str,
    body: ResetRequest,
    authorization: str | None = Header(default=None),
) -> ResetResponse:
    """Reset check-in deduplication records for a specific time block window."""
    _require_admin(authorization)
    if not body.confirmation:
        raise HTTPException(
            status_code=422,
            detail="confirmation must be true to execute a reset",
        )

    ebc = get_event_block_config_service()
    block = ebc.get_block(block_id)
    if block is None:
        raise HTTPException(status_code=404, detail=f"Block {block_id!r} not found")

    event = ebc.get_event(block.event_id)
    if event is None:
        raise HTTPException(
            status_code=404, detail=f"Event for block {block_id!r} not found"
        )

    starts_at = datetime.fromisoformat(block.starts_at)
    ends_at = datetime.fromisoformat(block.ends_at)
    # Make timezone-aware if naive (treat as UTC)
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=UTC)
    if ends_at.tzinfo is None:
        ends_at = ends_at.replace(tzinfo=UTC)

    scan_svc = get_scan_idempotency_service()
    if scan_svc is None:
        raise HTTPException(status_code=503, detail="Scan service unavailable")

    records_cleared = scan_svc.delete_by_timerange(event.wix_event_id, starts_at, ends_at)

    audit_svc = get_reset_audit_service()
    entry = audit_svc.record_reset(
        scope="block",
        scope_id=block_id,
        actor=body.actor,
        reason=body.reason,
        records_cleared=records_cleared,
    )

    return ResetResponse(
        reset_id=entry.reset_id,
        scope=entry.scope,
        scope_id=entry.scope_id,
        actor=entry.actor,
        reason=entry.reason,
        records_cleared=entry.records_cleared,
        performed_at=entry.performed_at,
    )


@router.get("/audit", response_model=list[AuditRecordResponse])
def list_audit(
    authorization: str | None = Header(default=None),
    limit: int = 100,
) -> list[AuditRecordResponse]:
    """Return recent reset audit entries (most recent first)."""
    _require_admin(authorization)
    audit_svc = get_reset_audit_service()
    records = audit_svc.list_audit(limit=min(limit, 500))
    return [
        AuditRecordResponse(
            reset_id=r.reset_id,
            scope=r.scope,
            scope_id=r.scope_id,
            actor=r.actor,
            reason=r.reason,
            records_cleared=r.records_cleared,
            performed_at=r.performed_at,
        )
        for r in records
    ]
