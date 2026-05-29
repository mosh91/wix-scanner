from __future__ import annotations

from enum import Enum
from hashlib import sha1
from threading import Lock

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.services.qr_parser import QRParseError, parse_qr_payload
from app.services.scan_runtime import scan_runtime_store

router = APIRouter(prefix="/checkins")


class ScanStatus(str, Enum):
    checked_in = "CHECKED_IN"
    invalid_ticket = "INVALID_TICKET"
    already_checked_in = "ALREADY_CHECKED_IN"


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


_idempotency_lock = Lock()
_idempotency_responses: dict[str, ScanResponse] = {}


@router.post("/scan", response_model=ScanResponse)
def scan_ticket(request: ScanRequest) -> ScanResponse:
    started_at = scan_runtime_store.start_request()

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
        event_id = parsed.event_id
        block_id = parsed.block_id
        operation_type = parsed.operation_type
        ticket_number = parsed.ticket_number

        if "DUP" in ticket_number:
            status = ScanStatus.already_checked_in
            accepted = False
            reason = "Ticket ya procesado"
            error_code = "ALREADY_CHECKED_IN"
            wix_status = "duplicate"
        else:
            status = ScanStatus.checked_in
            accepted = True
            reason = None
            error_code = ""
            wix_status = "checked_in"

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
    )

    with _idempotency_lock:
        _idempotency_responses[idempotency_key] = response

    return response
