from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.ticket_manifest import get_ticket_manifest_service

router = APIRouter(prefix="/manifest")


class ManifestSyncRequest(BaseModel):
    event_id: str = Field(min_length=3, max_length=128)


class ManifestSyncResponse(BaseModel):
    event_id: str
    total_tickets: int
    checked_in_tickets: int
    stale: bool
    last_known_sync_ts: float
    source_revision: str


class ManifestTicketLookupResponse(BaseModel):
    event_id: str
    ticket_number: str
    manifest_state: str
    last_known_sync_ts: float
    source_revision: str
    last_seen_scan_at: float | None


@router.post("/sync", response_model=ManifestSyncResponse)
def sync_manifest(request: ManifestSyncRequest) -> ManifestSyncResponse:
    status = get_ticket_manifest_service().sync_event_from_wix(request.event_id)
    return ManifestSyncResponse(
        event_id=status.event_id,
        total_tickets=status.total_tickets,
        checked_in_tickets=status.checked_in_tickets,
        stale=status.stale,
        last_known_sync_ts=status.last_known_sync_ts,
        source_revision=status.source_revision,
    )


@router.get("/events/{event_id}/status", response_model=ManifestSyncResponse)
def get_manifest_status(event_id: str) -> ManifestSyncResponse:
    status = get_ticket_manifest_service().status(event_id=event_id)
    return ManifestSyncResponse(
        event_id=status.event_id,
        total_tickets=status.total_tickets,
        checked_in_tickets=status.checked_in_tickets,
        stale=status.stale,
        last_known_sync_ts=status.last_known_sync_ts,
        source_revision=status.source_revision,
    )


@router.get("/events/{event_id}/tickets/{ticket_number}", response_model=ManifestTicketLookupResponse)
def get_manifest_ticket(event_id: str, ticket_number: str) -> ManifestTicketLookupResponse:
    record = get_ticket_manifest_service().get_ticket(event_id=event_id, ticket_number=ticket_number)
    if record is None:
        raise HTTPException(status_code=404, detail="Ticket not found in local manifest cache")

    return ManifestTicketLookupResponse(
        event_id=record.event_id,
        ticket_number=record.ticket_number,
        manifest_state=record.manifest_state,
        last_known_sync_ts=record.last_known_sync_ts,
        source_revision=record.source_revision,
        last_seen_scan_at=record.last_seen_scan_at,
    )
