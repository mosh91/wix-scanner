from __future__ import annotations

from enum import Enum
from hashlib import sha1
from threading import Lock
from uuid import uuid4

from fastapi import APIRouter, Header
from pydantic import BaseModel, ConfigDict, Field

from app.services.qr_parser import QRParseError, parse_qr_payload
from app.services.offline_queue import PendingCheckinJob, get_offline_queue_service
from app.services.scan_runtime import scan_runtime_store
from app.services.wix_client import get_wix_client

router = APIRouter(prefix="/checkins")


class ScanStatus(str, Enum):
    checked_in = "CHECKED_IN"
    invalid_ticket = "INVALID_TICKET"
    already_checked_in = "ALREADY_CHECKED_IN"
    queued_offline = "QUEUED_OFFLINE"


class ScanRequest(BaseModel):
    payload: str = Field(min_length=3, max_length=512)
    source: str = Field(default="hid")
    session_id: str = Field(default="session-local")
    operator_id: str = Field(default="operator-local")
    scanner_status: str = Field(default="connected")
    # Bootstrap session context — supplied by an enrolled kiosk
    active_event_id: str | None = Field(default=None)
    active_station_id: str | None = Field(default=None)

    model_config = ConfigDict(str_strip_whitespace=True)


class ScanResponse(BaseModel):
    status: ScanStatus
    accepted: bool
    event_id: str
    block_id: str
    operation_type: str
    ticket_number: str
    reason: str | None = None
    error_code: str
    wix_status: str
    response_time_ms: int
    idempotency_key: str
    correlation_id: str


class ManifestSeedRequest(BaseModel):
    event_id: str = Field(min_length=3, max_length=128)
    ticket_numbers: list[str] = Field(min_length=1, max_length=500)


class ManifestSeedResponse(BaseModel):
    event_id: str
    seeded_count: int


_idempotency_lock = Lock()
_idempotency_responses: dict[str, ScanResponse] = {}


@router.post("/manifest/cache", response_model=ManifestSeedResponse)
def seed_manifest_cache(request: ManifestSeedRequest) -> ManifestSeedResponse:
    normalized = [ticket.strip().upper() for ticket in request.ticket_numbers if ticket.strip()]
    get_offline_queue_service().remember_manifest_tickets(event_id=request.event_id, ticket_numbers=normalized)
    return ManifestSeedResponse(event_id=request.event_id, seeded_count=len(normalized))


@router.post("/scan", response_model=ScanResponse)
def scan_ticket(request: ScanRequest, x_correlation_id: str | None = Header(default=None)) -> ScanResponse:
    started_at = scan_runtime_store.start_request()
    correlation_id = x_correlation_id or str(uuid4())

    try:
        parsed = parse_qr_payload(request.payload, active_event_id=request.active_event_id)
    except QRParseError as exc:
        status = ScanStatus.invalid_ticket
        accepted = False
        reason = str(exc)
        error_code = "INVALID_TICKET"
        wix_status = "rejected"
        event_id = request.active_event_id or "demo-event"
        block_id = "general"
        operation_type = "checkin"
        ticket_number = f"INVALID-{sha1(request.payload.encode('utf-8')).hexdigest()[:12]}"
    else:
        offline_queue = get_offline_queue_service()
        event_id = parsed.event_id
        block_id = parsed.block_id
        operation_type = parsed.operation_type
        ticket_number = parsed.ticket_number
        wix_idempotency = sha1(f"{event_id}:{ticket_number}:{block_id}:{operation_type}".encode("utf-8")).hexdigest()

        wix_result = get_wix_client().check_in_ticket(
            event_id=event_id,
            ticket_number=ticket_number,
            idempotency_key=wix_idempotency,
            correlation_id=correlation_id,
        )

        if wix_result.outcome == "checked_in":
            offline_queue.mark_processed(event_id=event_id, ticket_number=ticket_number)
            offline_queue.remember_manifest_ticket(event_id=event_id, ticket_number=ticket_number)
            status = ScanStatus.checked_in
            accepted = True
            reason = wix_result.reason
            error_code = wix_result.error_code
            wix_status = wix_result.wix_status
        elif wix_result.outcome == "already_checked_in":
            offline_queue.mark_processed(event_id=event_id, ticket_number=ticket_number)
            offline_queue.remember_manifest_ticket(event_id=event_id, ticket_number=ticket_number)
            status = ScanStatus.already_checked_in
            accepted = False
            reason = wix_result.reason
            error_code = wix_result.error_code
            wix_status = wix_result.wix_status
        elif wix_result.outcome in {"rate_limited", "upstream_error", "transient_error"}:
            if offline_queue.is_manifest_ticket_known(event_id=event_id, ticket_number=ticket_number):
                enqueue = offline_queue.enqueue_checkin(
                    PendingCheckinJob(
                        event_id=event_id,
                        ticket_number=ticket_number,
                        block_id=block_id,
                        operation_type=operation_type,
                        idempotency_key=wix_idempotency,
                        correlation_id=correlation_id,
                    )
                )
                if enqueue.enqueued:
                    status = ScanStatus.queued_offline
                    accepted = True
                    reason = "Ticket validado localmente. Check-in encolado para sincronizacion."
                    error_code = "QUEUED_OFFLINE"
                    wix_status = "queued_offline"
                elif enqueue.reason == "already_processed":
                    status = ScanStatus.already_checked_in
                    accepted = False
                    reason = "Ticket ya procesado previamente."
                    error_code = "ALREADY_CHECKED_IN"
                    wix_status = "duplicate"
                else:
                    status = ScanStatus.queued_offline
                    accepted = True
                    reason = "Ticket ya en cola offline."
                    error_code = "ALREADY_QUEUED"
                    wix_status = "queued_offline"
            else:
                status = ScanStatus.invalid_ticket
                accepted = False
                reason = "No se encontro ticket en cache local para operar offline."
                error_code = wix_result.error_code
                wix_status = wix_result.wix_status
        elif wix_result.outcome in {"auth_error"}:
            status = ScanStatus.invalid_ticket
            accepted = False
            reason = wix_result.reason
            error_code = wix_result.error_code
            wix_status = wix_result.wix_status
        else:
            status = ScanStatus.invalid_ticket
            accepted = False
            reason = wix_result.reason
            error_code = wix_result.error_code
            wix_status = wix_result.wix_status

    idempotency_seed = f"{event_id}:{ticket_number}:{block_id}:{operation_type}"
    idempotency_key = sha1(idempotency_seed.encode("utf-8")).hexdigest()

    # Replay the previously computed response for identical idempotency key.
    with _idempotency_lock:
        existing = _idempotency_responses.get(idempotency_key)
    if existing is not None:
        return existing

    latency_ms = scan_runtime_store.finish_request(
        started_at=started_at,
        session_id=request.session_id,
        operator_id=request.operator_id,
        success=accepted,
        status=status.value,
        error_code=error_code,
        scanner_status=request.scanner_status,
        ticket_number=ticket_number,
        source=request.source,
        wix_status=wix_status,
        reason=reason,
    )

    response = ScanResponse(
        status=status,
        accepted=accepted,
        event_id=event_id,
        block_id=block_id,
        operation_type=operation_type,
        ticket_number=ticket_number,
        reason=reason,
        error_code=error_code,
        wix_status=wix_status,
        response_time_ms=latency_ms,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )

    with _idempotency_lock:
        _idempotency_responses[idempotency_key] = response

    return response
