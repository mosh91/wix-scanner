from __future__ import annotations

from enum import Enum
from hashlib import sha1

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

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
    ticket_number: str
    reason: str | None = None
    error_code: str
    wix_status: str
    response_time_ms: int
    idempotency_key: str


def _normalize_ticket(payload: str) -> str:
    normalized = payload.strip().upper()
    if "INVALID" in normalized:
        return "INVALID"
    if "DUP" in normalized:
        return f"DUP-{normalized[-8:]}"
    return normalized[-24:]


@router.post("/scan", response_model=ScanResponse)
def scan_ticket(request: ScanRequest) -> ScanResponse:
    started_at = scan_runtime_store.start_request()
    ticket_number = _normalize_ticket(request.payload)

    if ticket_number == "INVALID":
        status = ScanStatus.invalid_ticket
        accepted = False
        reason = "Formato de ticket no valido"
        error_code = "INVALID_TICKET"
        wix_status = "rejected"
    elif ticket_number.startswith("DUP-"):
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

    idempotency_seed = f"demo-event:{ticket_number}:scan"
    idempotency_key = sha1(idempotency_seed.encode("utf-8")).hexdigest()

    return ScanResponse(
        status=status,
        accepted=accepted,
        ticket_number=ticket_number,
        reason=reason,
        error_code=error_code,
        wix_status=wix_status,
        response_time_ms=latency_ms,
        idempotency_key=idempotency_key,
    )
