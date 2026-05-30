from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.services.checkin_webhooks import WebhookPayload, get_checkin_webhook_service
from app.services.event_broadcast import event_broadcast_service

router = APIRouter(prefix="/webhooks/wix")


class WixMobileCheckinPayload(BaseModel):
    ticket_number: str = Field(min_length=3, max_length=64)
    wix_ticket_id: str = Field(min_length=3, max_length=128)
    wix_event_id: str = Field(min_length=3, max_length=128)
    checked_in_at: str = Field(min_length=5, max_length=128)
    source: Literal["wix_mobile"]
    wix_request_id: str = Field(min_length=3, max_length=128)


class WebhookAckResponse(BaseModel):
    acknowledged: bool
    outcome: str
    message: str
    delivery_id: int


class WebhookDeliveryRecord(BaseModel):
    id: int
    wix_request_id: str | None
    wix_event_id: str
    ticket_number: str
    source: str
    checked_in_at: str
    signature_valid: bool
    status: str
    error_message: str | None
    received_at: float
    retried_from_id: int | None


@router.post("/checkins", response_model=WebhookAckResponse)
async def wix_mobile_checkin_webhook(
    payload: WixMobileCheckinPayload,
    request: Request,
    x_wix_signature: str | None = Header(default=None),
) -> WebhookAckResponse:
    service = get_checkin_webhook_service()
    raw = await request.body()
    if not service.verify_signature(raw_body=raw, header_signature=x_wix_signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    raw_payload = payload.model_dump()
    result = service.process_payload(
        payload=WebhookPayload(**raw_payload),
        raw_payload=raw_payload,
        signature_valid=True,
    )

    await event_broadcast_service.broadcast(
        event_id=payload.wix_event_id,
        payload={
            "kind": "wix_mobile_checkin",
            "event_id": payload.wix_event_id,
            "ticket_number": payload.ticket_number.upper(),
            "wix_request_id": payload.wix_request_id,
            "outcome": result.outcome,
            "delivery_id": result.delivery_id,
            "checked_in_at": payload.checked_in_at,
        },
    )

    return WebhookAckResponse(
        acknowledged=True,
        outcome=result.outcome,
        message=result.message,
        delivery_id=result.delivery_id,
    )


@router.get("/checkins/history", response_model=list[WebhookDeliveryRecord])
def get_wix_checkin_webhook_history(limit: int = Query(default=50, ge=1, le=500)) -> list[WebhookDeliveryRecord]:
    records = get_checkin_webhook_service().list_deliveries(limit=limit)
    return [WebhookDeliveryRecord.model_validate(item) for item in records]


@router.post("/checkins/history/{delivery_id}/retry", response_model=WebhookAckResponse)
async def retry_wix_checkin_webhook_delivery(delivery_id: int) -> WebhookAckResponse:
    service = get_checkin_webhook_service()
    try:
        result = service.retry_delivery(delivery_id=delivery_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Delivery not found") from exc

    # Load retried payload metadata for broadcasting context.
    latest = service.list_deliveries(limit=1)
    if latest:
        record = latest[0]
        await event_broadcast_service.broadcast(
            event_id=str(record["wix_event_id"]),
            payload={
                "kind": "wix_mobile_checkin_retry",
                "event_id": record["wix_event_id"],
                "ticket_number": record["ticket_number"],
                "delivery_id": record["id"],
                "retried_from_id": delivery_id,
                "outcome": result.outcome,
            },
        )

    return WebhookAckResponse(
        acknowledged=True,
        outcome=result.outcome,
        message="Retry processed",
        delivery_id=result.delivery_id,
    )
