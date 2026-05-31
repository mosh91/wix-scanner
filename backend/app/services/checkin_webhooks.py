from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from pathlib import Path
from time import time

from sqlalchemy import Boolean, Column, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import get_settings
from app.db import make_engine
from app.services.ticket_manifest import get_ticket_manifest_service


@dataclass(frozen=True)
class WebhookPayload:
    ticket_number: str
    wix_ticket_id: str
    wix_event_id: str
    checked_in_at: str
    source: str
    wix_request_id: str


@dataclass(frozen=True)
class WebhookProcessResult:
    delivery_id: int
    outcome: str
    message: str


Base = declarative_base()


class _WebhookDeliveryRow(Base):
    __tablename__ = "webhook_deliveries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    wix_request_id = Column(String, nullable=True)
    wix_event_id = Column(String, nullable=False)
    ticket_number = Column(String, nullable=False)
    source = Column(String, nullable=False)
    checked_in_at = Column(String, nullable=False)
    payload = Column(Text, nullable=False)
    signature_valid = Column(Integer, nullable=False)
    status = Column(String, nullable=False)
    error_message = Column(String, nullable=True)
    received_at = Column(Float, nullable=False)
    retried_from_id = Column(Integer, nullable=True)


class _ScanEventRow(Base):
    __tablename__ = "scan_events"
    __table_args__ = (UniqueConstraint("event_id", "ticket_number", "source", "result"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String, nullable=False)
    ticket_number = Column(String, nullable=False)
    source = Column(String, nullable=False)
    result = Column(String, nullable=False)
    wix_request_id = Column(String, nullable=True)
    created_at = Column(Float, nullable=False)


class _CheckinRecordRow(Base):
    __tablename__ = "checkin_records"
    __table_args__ = (UniqueConstraint("event_id", "ticket_number"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String, nullable=False)
    ticket_number = Column(String, nullable=False)
    source = Column(String, nullable=False)
    wix_ticket_id = Column(String, nullable=True)
    wix_request_id = Column(String, nullable=True)
    checked_in_at = Column(String, nullable=False)
    created_at = Column(Float, nullable=False)


class CheckinWebhookService:
    def __init__(
        self,
        db_file: Path | None = None,
        db_url: str | None = None,
    ) -> None:
        if db_url:
            url = db_url
        elif db_file is not None:
            db_file.parent.mkdir(parents=True, exist_ok=True)
            url = f"sqlite:///{db_file.resolve()}"
        else:
            settings = get_settings()
            url = settings.database_url
        self._engine = make_engine(url)
        Base.metadata.create_all(self._engine)
        self._Session = sessionmaker(bind=self._engine, autoflush=False, autocommit=False)

    def verify_signature(self, *, raw_body: bytes, header_signature: str | None) -> bool:
        settings = get_settings()
        if not header_signature:
            return False
        digest = hmac.new(
            key=settings.wix_webhook_secret.encode("utf-8"),
            msg=raw_body,
            digestmod=hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(digest, header_signature.strip())

    def _insert_delivery(
        self,
        *,
        payload: WebhookPayload,
        raw_payload: dict[str, object],
        signature_valid: bool,
        status: str,
        error_message: str | None,
        retried_from_id: int | None,
    ) -> int:
        with self._Session() as session:
            row = _WebhookDeliveryRow(
                wix_request_id=payload.wix_request_id,
                wix_event_id=payload.wix_event_id,
                ticket_number=payload.ticket_number,
                source=payload.source,
                checked_in_at=payload.checked_in_at,
                payload=json.dumps(raw_payload, separators=(",", ":")),
                signature_valid=1 if signature_valid else 0,
                status=status,
                error_message=error_message,
                received_at=time(),
                retried_from_id=retried_from_id,
            )
            session.add(row)
            session.flush()
            delivery_id = int(row.id)
            session.commit()
        return delivery_id

    def _insert_scan_and_checkin(self, payload: WebhookPayload) -> tuple[bool, str]:
        now = time()
        event_id = payload.wix_event_id
        ticket = payload.ticket_number.strip().upper()

        with self._Session() as session:
            # Try insert scan event (ignore duplicate)
            existing_scan = (
                session.query(_ScanEventRow)
                .filter_by(event_id=event_id, ticket_number=ticket, source=payload.source, result="checked_in")
                .first()
            )
            if existing_scan is None:
                session.add(
                    _ScanEventRow(
                        event_id=event_id,
                        ticket_number=ticket,
                        source=payload.source,
                        result="checked_in",
                        wix_request_id=payload.wix_request_id,
                        created_at=now,
                    )
                )

            # Try insert checkin record (unique on event_id + ticket_number)
            existing_checkin = (
                session.query(_CheckinRecordRow)
                .filter_by(event_id=event_id, ticket_number=ticket)
                .first()
            )
            if existing_checkin is not None:
                session.commit()
                return False, "duplicate"

            session.add(
                _CheckinRecordRow(
                    event_id=event_id,
                    ticket_number=ticket,
                    source=payload.source,
                    wix_ticket_id=payload.wix_ticket_id,
                    wix_request_id=payload.wix_request_id,
                    checked_in_at=payload.checked_in_at,
                    created_at=now,
                )
            )
            session.commit()
        return True, "recorded"

    def process_payload(
        self,
        *,
        payload: WebhookPayload,
        raw_payload: dict[str, object],
        signature_valid: bool,
        retried_from_id: int | None = None,
    ) -> WebhookProcessResult:
        manifest = get_ticket_manifest_service()
        event_id = payload.wix_event_id
        ticket_number = payload.ticket_number.strip().upper()

        manifest_status = manifest.status(event_id=event_id)
        known_event = manifest_status.last_known_sync_ts > 0 or event_id in manifest.tracked_events()

        if not known_event:
            delivery_id = self._insert_delivery(
                payload=payload,
                raw_payload=raw_payload,
                signature_valid=signature_valid,
                status="IGNORED_UNKNOWN_EVENT",
                error_message="Unknown event id",
                retried_from_id=retried_from_id,
            )
            return WebhookProcessResult(
                delivery_id=delivery_id,
                outcome="ignored_unknown_event",
                message="Webhook acknowledged for unknown event",
            )

        manifest.track_event(event_id)
        manifest.mark_checked_in(event_id=event_id, ticket_number=ticket_number)
        inserted, insert_outcome = self._insert_scan_and_checkin(payload)

        status = "PROCESSED" if inserted else "DUPLICATE"
        delivery_id = self._insert_delivery(
            payload=payload,
            raw_payload=raw_payload,
            signature_valid=signature_valid,
            status=status,
            error_message=None,
            retried_from_id=retried_from_id,
        )

        return WebhookProcessResult(
            delivery_id=delivery_id,
            outcome=insert_outcome,
            message="Webhook processed",
        )

    def list_deliveries(self, *, limit: int = 50) -> list[dict[str, object]]:
        with self._Session() as session:
            rows = (
                session.query(_WebhookDeliveryRow)
                .order_by(_WebhookDeliveryRow.id.desc())
                .limit(max(1, min(limit, 500)))
                .all()
            )
        return [
            {
                "id": int(r.id),
                "wix_request_id": r.wix_request_id,
                "wix_event_id": r.wix_event_id,
                "ticket_number": r.ticket_number,
                "source": r.source,
                "checked_in_at": r.checked_in_at,
                "signature_valid": bool(r.signature_valid),
                "status": r.status,
                "error_message": r.error_message,
                "received_at": float(r.received_at),
                "retried_from_id": int(r.retried_from_id) if r.retried_from_id is not None else None,
            }
            for r in rows
        ]

    def retry_delivery(self, *, delivery_id: int) -> WebhookProcessResult:
        with self._Session() as session:
            row = session.query(_WebhookDeliveryRow).filter_by(id=delivery_id).first()

        if row is None:
            raise KeyError("delivery_not_found")

        raw_payload = json.loads(row.payload)
        payload = WebhookPayload(
            ticket_number=str(raw_payload["ticket_number"]),
            wix_ticket_id=str(raw_payload["wix_ticket_id"]),
            wix_event_id=str(raw_payload["wix_event_id"]),
            checked_in_at=str(raw_payload["checked_in_at"]),
            source=str(raw_payload["source"]),
            wix_request_id=str(raw_payload["wix_request_id"]),
        )
        return self.process_payload(
            payload=payload,
            raw_payload=raw_payload,
            signature_valid=True,
            retried_from_id=delivery_id,
        )

    def reset_for_tests(self) -> None:
        with self._Session() as session:
            session.query(_WebhookDeliveryRow).delete()
            session.query(_ScanEventRow).delete()
            session.query(_CheckinRecordRow).delete()
            session.commit()


_webhook_service: CheckinWebhookService | None = None


def get_checkin_webhook_service() -> CheckinWebhookService:
    global _webhook_service
    if _webhook_service is None:
        _webhook_service = CheckinWebhookService()
    return _webhook_service
