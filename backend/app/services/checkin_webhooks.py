from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from time import time

from app.core.config import get_settings
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


class CheckinWebhookService:
    def __init__(self, db_file: Path | None = None) -> None:
        self._db_file = db_file or Path("./data/checkin_webhooks.db")
        self._db_file.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_db()

    def _initialize_db(self) -> None:
        with sqlite3.connect(self._db_file) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS webhook_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wix_request_id TEXT,
                    wix_event_id TEXT NOT NULL,
                    ticket_number TEXT NOT NULL,
                    source TEXT NOT NULL,
                    checked_in_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    signature_valid INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    received_at REAL NOT NULL,
                    retried_from_id INTEGER
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS scan_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    ticket_number TEXT NOT NULL,
                    source TEXT NOT NULL,
                    result TEXT NOT NULL,
                    wix_request_id TEXT,
                    created_at REAL NOT NULL,
                    UNIQUE(event_id, ticket_number, source, result)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS checkin_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    ticket_number TEXT NOT NULL,
                    source TEXT NOT NULL,
                    wix_ticket_id TEXT,
                    wix_request_id TEXT,
                    checked_in_at TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(event_id, ticket_number)
                )
                """
            )
            connection.commit()

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
        with sqlite3.connect(self._db_file) as connection:
            cursor = connection.execute(
                """
                INSERT INTO webhook_deliveries (
                    wix_request_id,
                    wix_event_id,
                    ticket_number,
                    source,
                    checked_in_at,
                    payload,
                    signature_valid,
                    status,
                    error_message,
                    received_at,
                    retried_from_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.wix_request_id,
                    payload.wix_event_id,
                    payload.ticket_number,
                    payload.source,
                    payload.checked_in_at,
                    json.dumps(raw_payload, separators=(",", ":")),
                    1 if signature_valid else 0,
                    status,
                    error_message,
                    time(),
                    retried_from_id,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def _insert_scan_and_checkin(self, payload: WebhookPayload) -> tuple[bool, str]:
        now = time()
        event_id = payload.wix_event_id
        ticket = payload.ticket_number.strip().upper()

        with sqlite3.connect(self._db_file) as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO scan_events (event_id, ticket_number, source, result, wix_request_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (event_id, ticket, payload.source, "checked_in", payload.wix_request_id, now),
                )
            except sqlite3.IntegrityError:
                pass

            try:
                connection.execute(
                    """
                    INSERT INTO checkin_records (
                        event_id,
                        ticket_number,
                        source,
                        wix_ticket_id,
                        wix_request_id,
                        checked_in_at,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        ticket,
                        payload.source,
                        payload.wix_ticket_id,
                        payload.wix_request_id,
                        payload.checked_in_at,
                        now,
                    ),
                )
                connection.commit()
                return True, "recorded"
            except sqlite3.IntegrityError:
                connection.commit()
                return False, "duplicate"

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
        with sqlite3.connect(self._db_file) as connection:
            rows = connection.execute(
                """
                SELECT id, wix_request_id, wix_event_id, ticket_number, source, checked_in_at,
                       signature_valid, status, error_message, received_at, retried_from_id
                FROM webhook_deliveries
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, min(limit, 500)),),
            ).fetchall()

        return [
            {
                "id": int(row[0]),
                "wix_request_id": row[1],
                "wix_event_id": row[2],
                "ticket_number": row[3],
                "source": row[4],
                "checked_in_at": row[5],
                "signature_valid": bool(row[6]),
                "status": row[7],
                "error_message": row[8],
                "received_at": float(row[9]),
                "retried_from_id": int(row[10]) if row[10] is not None else None,
            }
            for row in rows
        ]

    def retry_delivery(self, *, delivery_id: int) -> WebhookProcessResult:
        with sqlite3.connect(self._db_file) as connection:
            row = connection.execute(
                "SELECT payload FROM webhook_deliveries WHERE id = ?",
                (delivery_id,),
            ).fetchone()

        if row is None:
            raise KeyError("delivery_not_found")

        raw_payload = json.loads(row[0])
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
        with sqlite3.connect(self._db_file) as connection:
            connection.execute("DELETE FROM webhook_deliveries")
            connection.execute("DELETE FROM scan_events")
            connection.execute("DELETE FROM checkin_records")
            connection.commit()


_webhook_service: CheckinWebhookService | None = None


def get_checkin_webhook_service() -> CheckinWebhookService:
    global _webhook_service
    if _webhook_service is None:
        _webhook_service = CheckinWebhookService()
    return _webhook_service
