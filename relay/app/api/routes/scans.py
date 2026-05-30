from __future__ import annotations

from hashlib import sha1
from uuid import uuid4

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from app.services.cloud_forwarder import get_cloud_forwarder
from app.services.relay_idempotency import RelayIdempotencyService
from app.services.relay_queue_service import get_relay_queue

router = APIRouter(prefix="/relay")

# Global relay idempotency service (initialized in main.py lifespan)
_relay_idempotency: RelayIdempotencyService | None = None


def get_relay_idempotency() -> RelayIdempotencyService | None:
    """Get relay idempotency service."""
    return _relay_idempotency


def set_relay_idempotency(service: RelayIdempotencyService) -> None:
    """Set relay idempotency service."""
    global _relay_idempotency
    _relay_idempotency = service


class RelaySubmitRequest(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    ticket_number: str = Field(min_length=1, max_length=128)
    scan_event_id: str = Field(min_length=36, max_length=36, description="UUIDv4 scan event ID from frontend")
    payload: str = Field(min_length=1, max_length=512)


class RelayScansResponse(BaseModel):
    acknowledged: bool
    outcome: str
    message: str
    relay_request_id: str
    cloud_forwarded: bool
    queued_locally: bool
    cloud_contract_outcome: str | None = None
    cloud_details: dict[str, object] = Field(default_factory=dict)


class QueueStatsResponse(BaseModel):
    pending: int
    dlq: int
    total_queued: int


class DeadLetterRecord(BaseModel):
    id: str
    queued_scan_id: str
    event_id: str
    ticket_number: str
    reason: str
    final_error: str | None
    created_at: str


class DeadLetterListResponse(BaseModel):
    entries: list[DeadLetterRecord]
    total: int


@router.post("/scans", response_model=RelayScansResponse)
def submit_scan(
    request: RelaySubmitRequest,
    x_correlation_id: str | None = Header(default=None),
) -> RelayScansResponse:
    """Accept a scan from local station, check for duplicates, forward to cloud, or queue if unreachable."""
    relay_request_id = str(uuid4())
    correlation_id = x_correlation_id or relay_request_id

    # Check relay idempotency ledger
    relay_idem = get_relay_idempotency()
    if relay_idem:
        existing = relay_idem.find_by_scan_event_id(request.scan_event_id)
        if existing:
            # Duplicate detected; return cached outcome
            return RelayScansResponse(
                acknowledged=True,
                outcome=f"relay_duplicate ({existing.outcome})",
                message=f"Scan already processed with outcome: {existing.outcome}",
                relay_request_id=relay_request_id,
                cloud_forwarded=existing.outcome == "forwarded",
                queued_locally=existing.outcome == "queued",
                cloud_details={"cached_outcome": existing.outcome},
            )

    forwarder = get_cloud_forwarder()
    forward_result = forwarder.forward_scan(
        event_id=request.event_id,
        ticket_number=request.ticket_number,
        relay_request_id=relay_request_id,
        payload=request.payload,
        correlation_id=correlation_id,
        scan_event_id=request.scan_event_id,
    )

    cloud_forwarded = forward_result.get("outcome") == "forwarded"
    queued_locally = False

    # Record in relay idempotency ledger
    if relay_idem:
        outcome = "forwarded" if cloud_forwarded else "queued"
        relay_idem.record_scan(
            scan_event_id=request.scan_event_id,
            relay_id=relay_request_id,
            outcome=outcome,
        )

    # If cloud forwarding failed and we have a queue, enqueue locally
    relay_queue = get_relay_queue()
    if not cloud_forwarded and forward_result.get("retryable", True) and relay_queue:
        queue_id = relay_queue.enqueue_scan(
            event_id=request.event_id,
            ticket_number=request.ticket_number,
            relay_id=relay_request_id,
            payload=request.payload,
            correlation_id=correlation_id,
            scan_event_id=request.scan_event_id,
        )
        queued_locally = True

        return RelayScansResponse(
            acknowledged=True,
            outcome="relay_queued",
            message="Cloud backend unreachable. Scan stored locally for later forwarding.",
            relay_request_id=relay_request_id,
            cloud_forwarded=False,
            queued_locally=True,
            cloud_contract_outcome=forward_result.get("contract_outcome"),
            cloud_details={"queue_id": queue_id},
        )

    return RelayScansResponse(
        acknowledged=True,
        outcome=forward_result.get("outcome", "unknown"),
        message=forward_result.get("message", "Scan processed"),
        relay_request_id=relay_request_id,
        cloud_forwarded=cloud_forwarded,
        queued_locally=queued_locally,
        cloud_contract_outcome=forward_result.get("contract_outcome"),
        cloud_details={k: v for k, v in forward_result.items() if k not in ("outcome", "message", "acknowledged")},
    )


@router.get("/queue/stats", response_model=QueueStatsResponse)
def get_queue_stats() -> QueueStatsResponse:
    """Get queue statistics."""
    relay_queue = get_relay_queue()
    if not relay_queue:
        return QueueStatsResponse(pending=0, dlq=0, total_queued=0)

    stats = relay_queue.get_queue_stats()
    return QueueStatsResponse(**stats)


@router.get("/queue/dlq", response_model=DeadLetterListResponse)
def get_dlq_entries(limit: int = 50) -> DeadLetterListResponse:
    """Get dead-letter queue entries for operator review."""
    relay_queue = get_relay_queue()
    if not relay_queue:
        return DeadLetterListResponse(entries=[], total=0)

    dlq_entries = relay_queue.get_dlq_entries(limit=limit)
    return DeadLetterListResponse(
        entries=[
            DeadLetterRecord(
                id=entry.id,
                queued_scan_id=entry.queued_scan_id,
                event_id=entry.event_id,
                ticket_number=entry.ticket_number,
                reason=entry.reason,
                final_error=entry.final_error,
                created_at=entry.created_at,
            )
            for entry in dlq_entries
        ],
        total=len(dlq_entries),
    )
