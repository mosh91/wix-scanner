from __future__ import annotations

from hashlib import sha1
from uuid import uuid4

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from app.services.cloud_forwarder import get_cloud_forwarder

router = APIRouter(prefix="/relay")


class RelaySubmitRequest(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    ticket_number: str = Field(min_length=1, max_length=128)
    payload: str = Field(min_length=1, max_length=512)


class RelaySubmitResponse(BaseModel):
    acknowledged: bool
    outcome: str
    message: str
    relay_request_id: str


class RelayScansResponse(BaseModel):
    acknowledged: bool
    outcome: str
    message: str
    relay_request_id: str
    cloud_forwarded: bool
    cloud_details: dict[str, object] = Field(default_factory=dict)


@router.post("/scans", response_model=RelayScansResponse)
def submit_scan(
    request: RelaySubmitRequest,
    x_correlation_id: str | None = Header(default=None),
) -> RelayScansResponse:
    """Accept a scan from local station and forward to cloud backend."""
    relay_request_id = str(uuid4())
    correlation_id = x_correlation_id or relay_request_id

    forwarder = get_cloud_forwarder()
    forward_result = forwarder.forward_scan(
        event_id=request.event_id,
        ticket_number=request.ticket_number,
        relay_id=relay_request_id,
        payload=request.payload,
        correlation_id=correlation_id,
    )

    cloud_forwarded = forward_result.get("outcome") == "forwarded"
    return RelayScansResponse(
        acknowledged=True,
        outcome=forward_result.get("outcome", "unknown"),
        message=forward_result.get("message", "Scan processed"),
        relay_request_id=relay_request_id,
        cloud_forwarded=cloud_forwarded,
        cloud_details={k: v for k, v in forward_result.items() if k not in ("outcome", "message", "acknowledged")},
    )
