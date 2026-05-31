from __future__ import annotations

from enum import Enum
from hashlib import sha1
import logging
from threading import Lock
from typing import NoReturn
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings
from app.services.qr_parser import QRParseError, parse_qr_payload
from app.services.offline_queue import PendingCheckinJob, get_offline_queue_service
from app.services.relay_contract import (
    SUPPORTED_RELAY_PROTOCOL_VERSION,
    RelayContractEnvelope,
    is_timestamp_fresh,
    verify_signature,
)
from app.services.scan_idempotency import ScanIdempotencyService
from app.services.scan_runtime import scan_runtime_store
from app.services.ticket_manifest import get_ticket_manifest_service
from app.services.wix_client import get_wix_client

router = APIRouter(prefix="/checkins")
logger = logging.getLogger(__name__)


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
    scan_event_id: str | None = Field(default=None, description="UUIDv4 from frontend for deduplication")
    # Bootstrap session context — supplied by an enrolled kiosk
    active_event_id: str | None = Field(default=None)
    active_station_id: str | None = Field(default=None)
    relay_metadata: "RelayMetadata | None" = None

    model_config = ConfigDict(str_strip_whitespace=True)


class RelayMetadata(BaseModel):
    relay_id: str = Field(min_length=1, max_length=128)
    relay_request_id: str = Field(min_length=1, max_length=128)
    protocol_version: str = Field(min_length=1, max_length=32)
    sent_at: str = Field(min_length=1, max_length=64)
    event_id: str = Field(min_length=1, max_length=128)
    ticket_number: str = Field(min_length=1, max_length=128)


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
_scan_idempotency_service: ScanIdempotencyService | None = None


def get_scan_idempotency_service() -> ScanIdempotencyService | None:
    """Get the scan idempotency service."""
    return _scan_idempotency_service


def set_scan_idempotency_service(service: ScanIdempotencyService) -> None:
    """Set the scan idempotency service."""
    global _scan_idempotency_service
    _scan_idempotency_service = service


def _raise_relay_contract_error(
    *,
    response: Response,
    status_code: int,
    detail: str,
    ack_outcome: str,
) -> NoReturn:
    raise HTTPException(
        status_code=status_code,
        detail=detail,
        headers={
            "X-Relay-Ack-Outcome": ack_outcome,
            "X-Relay-Protocol-Version": SUPPORTED_RELAY_PROTOCOL_VERSION,
        },
    )


def _set_relay_ack_headers(response: Response, ack_outcome: str) -> None:
    response.headers["X-Relay-Ack-Outcome"] = ack_outcome
    response.headers["X-Relay-Protocol-Version"] = SUPPORTED_RELAY_PROTOCOL_VERSION


def _verify_relay_contract(
    *,
    request: ScanRequest,
    response: Response,
    authorization: str | None,
    correlation_id: str,
    x_relay_id: str | None,
    x_relay_request_id: str | None,
    x_relay_protocol_version: str | None,
    x_relay_sent_at: str | None,
    x_relay_signature: str | None,
) -> None:
    if x_relay_id is None and request.source != "relay":
        return

    settings = get_settings()
    if authorization != f"Bearer {settings.relay_auth_token}":
        logger.warning("relay.contract.invalid_auth", extra={"relay_id": x_relay_id})
        _raise_relay_contract_error(
            response=response,
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Relay authentication failed.",
            ack_outcome="invalid",
        )

    if request.relay_metadata is None:
        _raise_relay_contract_error(
            response=response,
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Relay metadata missing from relay request.",
            ack_outcome="invalid",
        )

    relay_metadata = request.relay_metadata
    if x_relay_protocol_version != SUPPORTED_RELAY_PROTOCOL_VERSION or relay_metadata.protocol_version != SUPPORTED_RELAY_PROTOCOL_VERSION:
        logger.warning(
            "relay.contract.version_mismatch",
            extra={"relay_id": x_relay_id, "requested_version": x_relay_protocol_version},
        )
        _raise_relay_contract_error(
            response=response,
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Unsupported relay protocol version: {x_relay_protocol_version or relay_metadata.protocol_version}.",
            ack_outcome="conflict",
        )

    if not x_relay_signature:
        _raise_relay_contract_error(
            response=response,
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Relay signature missing.",
            ack_outcome="invalid",
        )

    if not x_relay_sent_at or x_relay_sent_at != relay_metadata.sent_at or not is_timestamp_fresh(x_relay_sent_at):
        _raise_relay_contract_error(
            response=response,
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Relay timestamp is missing or outside the allowed skew window.",
            ack_outcome="invalid",
        )

    if request.scan_event_id is None:
        _raise_relay_contract_error(
            response=response,
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Relay requests must include scan_event_id.",
            ack_outcome="invalid",
        )

    if x_relay_id != relay_metadata.relay_id or x_relay_request_id != relay_metadata.relay_request_id:
        _raise_relay_contract_error(
            response=response,
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Relay header metadata does not match request body.",
            ack_outcome="invalid",
        )

    if request.active_event_id != relay_metadata.event_id:
        _raise_relay_contract_error(
            response=response,
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Relay event context mismatch.",
            ack_outcome="invalid",
        )

    envelope = RelayContractEnvelope(
        relay_id=relay_metadata.relay_id,
        relay_request_id=relay_metadata.relay_request_id,
        correlation_id=correlation_id,
        protocol_version=relay_metadata.protocol_version,
        sent_at=relay_metadata.sent_at,
        event_id=relay_metadata.event_id,
        ticket_number=relay_metadata.ticket_number,
        payload=request.payload,
        scan_event_id=request.scan_event_id,
    )
    if not verify_signature(settings.relay_signing_secret, envelope, x_relay_signature):
        logger.warning("relay.contract.invalid_signature", extra={"relay_id": x_relay_id})
        _raise_relay_contract_error(
            response=response,
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Relay signature verification failed.",
            ack_outcome="invalid",
        )


@router.post("/manifest/cache", response_model=ManifestSeedResponse)
def seed_manifest_cache(request: ManifestSeedRequest) -> ManifestSeedResponse:
    normalized = [ticket.strip().upper() for ticket in request.ticket_numbers if ticket.strip()]
    get_offline_queue_service().remember_manifest_tickets(event_id=request.event_id, ticket_numbers=normalized)
    return ManifestSeedResponse(event_id=request.event_id, seeded_count=len(normalized))


@router.post("/scan", response_model=ScanResponse)
def scan_ticket(
    request: ScanRequest,
    response: Response,
    x_correlation_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    x_relay_id: str | None = Header(default=None),
    x_relay_request_id: str | None = Header(default=None),
    x_relay_protocol_version: str | None = Header(default=None),
    x_relay_sent_at: str | None = Header(default=None),
    x_relay_signature: str | None = Header(default=None),
) -> ScanResponse:
    started_at = scan_runtime_store.start_request()
    correlation_id = x_correlation_id or str(uuid4())

    _verify_relay_contract(
        request=request,
        response=response,
        authorization=authorization,
        correlation_id=correlation_id,
        x_relay_id=x_relay_id,
        x_relay_request_id=x_relay_request_id,
        x_relay_protocol_version=x_relay_protocol_version,
        x_relay_sent_at=x_relay_sent_at,
        x_relay_signature=x_relay_signature,
    )

    # Check for duplicate using scan_event_id if available
    if request.scan_event_id:
        idem_service = get_scan_idempotency_service()
        if idem_service:
            dup_check = idem_service.check_duplicate(
                event_id=request.active_event_id or "demo-event",
                ticket_number="",  # Will be populated after parsing
                scan_event_id=request.scan_event_id,
            )
            if dup_check.is_duplicate and dup_check.previous_outcome:
                duplicate_record = idem_service.get_record(request.scan_event_id)
                duplicate_event_id = (
                    str(duplicate_record.event_id)
                    if duplicate_record
                    else request.active_event_id or "demo-event"
                )
                duplicate_ticket_number = (
                    str(duplicate_record.ticket_number) if duplicate_record else ""
                )
                duplicate_status = (
                    ScanStatus[dup_check.previous_outcome.lower()]
                    if dup_check.previous_outcome in [s.value for s in ScanStatus]
                    else ScanStatus.invalid_ticket
                )
                if request.source == "relay":
                    _set_relay_ack_headers(response, "duplicate")
                # Return cached outcome for duplicate
                return ScanResponse(
                    status=duplicate_status,
                    accepted=duplicate_status in {ScanStatus.checked_in, ScanStatus.queued_offline},
                    event_id=duplicate_event_id,
                    block_id="general",
                    operation_type="checkin",
                    ticket_number=duplicate_ticket_number,
                    reason="Duplicate scan event detected",
                    error_code="DUPLICATE_EVENT",
                    wix_status="duplicate",
                    response_time_ms=0,
                    idempotency_key="",
                    correlation_id=correlation_id,
                )

    try:
        parsed = parse_qr_payload(request.payload, active_event_id=request.active_event_id)
    except QRParseError as exc:
        scan_status = ScanStatus.invalid_ticket
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
        manifest = get_ticket_manifest_service()
        event_id = parsed.event_id
        block_id = parsed.block_id
        operation_type = parsed.operation_type
        ticket_number = parsed.ticket_number
        if request.relay_metadata is not None and request.relay_metadata.ticket_number != ticket_number:
            _raise_relay_contract_error(
                response=response,
                status_code=status.HTTP_409_CONFLICT,
                detail="Relay ticket context does not match parsed payload.",
                ack_outcome="conflict",
            )
        wix_idempotency = sha1(f"{event_id}:{ticket_number}:{block_id}:{operation_type}".encode("utf-8")).hexdigest()
        manifest.track_event(event_id)

        manifest_record = manifest.get_ticket(event_id=event_id, ticket_number=ticket_number)
        if manifest_record is not None and manifest_record.manifest_state == "checked_in":
            offline_queue.mark_processed(event_id=event_id, ticket_number=ticket_number)
            scan_status = ScanStatus.already_checked_in
            accepted = False
            reason = "Ticket ya registrado via sincronizacion local."
            error_code = "ALREADY_CHECKED_IN"
            wix_status = "duplicate"
        else:
            wix_result = get_wix_client().check_in_ticket(
                event_id=event_id,
                ticket_number=ticket_number,
                idempotency_key=wix_idempotency,
                correlation_id=correlation_id,
            )

            if wix_result.outcome == "checked_in":
                offline_queue.mark_processed(event_id=event_id, ticket_number=ticket_number)
                offline_queue.remember_manifest_ticket(event_id=event_id, ticket_number=ticket_number)
                manifest.mark_checked_in(event_id=event_id, ticket_number=ticket_number)
                scan_status = ScanStatus.checked_in
                accepted = True
                reason = wix_result.reason
                error_code = wix_result.error_code
                wix_status = wix_result.wix_status
            elif wix_result.outcome == "already_checked_in":
                offline_queue.mark_processed(event_id=event_id, ticket_number=ticket_number)
                offline_queue.remember_manifest_ticket(event_id=event_id, ticket_number=ticket_number)
                manifest.mark_checked_in(event_id=event_id, ticket_number=ticket_number)
                scan_status = ScanStatus.already_checked_in
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
                        scan_status = ScanStatus.queued_offline
                        accepted = True
                        reason = "Ticket validado localmente. Check-in encolado para sincronizacion."
                        error_code = "QUEUED_OFFLINE"
                        wix_status = "queued_offline"
                    elif enqueue.reason == "already_processed":
                        scan_status = ScanStatus.already_checked_in
                        accepted = False
                        reason = "Ticket ya procesado previamente."
                        error_code = "ALREADY_CHECKED_IN"
                        wix_status = "duplicate"
                    else:
                        scan_status = ScanStatus.queued_offline
                        accepted = True
                        reason = "Ticket ya en cola offline."
                        error_code = "ALREADY_QUEUED"
                        wix_status = "queued_offline"
                else:
                    scan_status = ScanStatus.invalid_ticket
                    accepted = False
                    reason = "No se encontro ticket en cache local para operar offline."
                    error_code = wix_result.error_code
                    wix_status = wix_result.wix_status
            elif wix_result.outcome in {"auth_error"}:
                scan_status = ScanStatus.invalid_ticket
                accepted = False
                reason = wix_result.reason
                error_code = wix_result.error_code
                wix_status = wix_result.wix_status
            else:
                scan_status = ScanStatus.invalid_ticket
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
        status=scan_status.value,
        error_code=error_code,
        scanner_status=request.scanner_status,
        ticket_number=ticket_number,
        source=request.source,
        wix_status=wix_status,
        reason=reason,
    )

    scan_response = ScanResponse(
        status=scan_status,
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

    if request.source == "relay":
        ack_outcome = "accepted"
        if scan_status == ScanStatus.invalid_ticket:
            ack_outcome = "invalid"
        elif scan_status == ScanStatus.already_checked_in:
            ack_outcome = "conflict"
        _set_relay_ack_headers(response, ack_outcome)

    with _idempotency_lock:
        _idempotency_responses[idempotency_key] = scan_response

    # Record in scan dedup ledger if scan_event_id provided
    if request.scan_event_id:
        idem_service = get_scan_idempotency_service()
        if idem_service:
            idem_service.record_scan(
                event_id=event_id,
                ticket_number=ticket_number,
                scan_event_id=request.scan_event_id,
                outcome=scan_status.value,
                source=request.source,
                error_message=reason,
            )

    return scan_response
