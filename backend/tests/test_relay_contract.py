from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from app.api.routes.checkins import _idempotency_responses
from app.core.config import get_settings
from app.services.checkin_webhooks import get_checkin_webhook_service
from app.services.offline_queue import get_offline_queue_service
from app.services.relay_contract import RelayContractEnvelope, build_signature
from app.services.ticket_manifest import get_ticket_manifest_service
from app.services.wix_client import WixCheckinResult


def _build_relay_request(
    *,
    version: str | None = None,
    sent_at: str | None = None,
    relay_ticket_number: str = "T001",
) -> tuple[dict[str, object], dict[str, str]]:
    settings = get_settings()
    protocol_version = version or settings.relay_protocol_version
    correlation_id = "corr-relay-contract-1"
    relay_id = "relay-dev-1"
    relay_request_id = "relay-req-123"
    sent_at_value = sent_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    payload = json.dumps({"eventId": "demo-event", "ticketNumber": "T001"})
    scan_event_id = "550e8400-e29b-41d4-a716-446655440099"

    body = {
        "payload": payload,
        "source": "relay",
        "active_event_id": "demo-event",
        "scan_event_id": scan_event_id,
        "relay_metadata": {
            "relay_id": relay_id,
            "relay_request_id": relay_request_id,
            "protocol_version": protocol_version,
            "sent_at": sent_at_value,
            "event_id": "demo-event",
            "ticket_number": relay_ticket_number,
        },
    }
    envelope = RelayContractEnvelope(
        relay_id=relay_id,
        relay_request_id=relay_request_id,
        correlation_id=correlation_id,
        protocol_version=protocol_version,
        sent_at=sent_at_value,
        event_id="demo-event",
        ticket_number=relay_ticket_number,
        payload=payload,
        scan_event_id=scan_event_id,
    )
    headers = {
        "Authorization": f"Bearer {settings.relay_auth_token}",
        "X-Correlation-ID": correlation_id,
        "X-Relay-ID": relay_id,
        "X-Relay-Request-ID": relay_request_id,
        "X-Relay-Protocol-Version": protocol_version,
        "X-Relay-Sent-At": sent_at_value,
        "X-Relay-Signature": build_signature(settings.relay_signing_secret, envelope),
    }
    return body, headers


class TestRelayContract:
    @pytest.fixture(autouse=True)
    def _reset_state(self) -> None:
        get_offline_queue_service().reset_for_tests()
        get_ticket_manifest_service().reset_for_tests()
        get_checkin_webhook_service().reset_for_tests()
        _idempotency_responses.clear()

    def test_signed_relay_request_is_accepted(self, backend_client):
        body, headers = _build_relay_request()

        with patch("app.services.wix_client.WixClient.check_in_ticket") as mock_wix:
            mock_wix.return_value = WixCheckinResult(
                outcome="checked_in",
                wix_status="CHECKED_IN",
                reason=None,
                error_code="",
                attempts=1,
            )
            response = backend_client.post("/api/checkins/scan", json=body, headers=headers)

        assert response.status_code == 200
        assert response.headers["X-Relay-Ack-Outcome"] == "accepted"
        assert response.headers["X-Relay-Protocol-Version"] == get_settings().relay_protocol_version
        assert response.json()["status"] == "CHECKED_IN"
        assert mock_wix.call_count == 1

    def test_missing_relay_signature_is_rejected(self, backend_client):
        body, headers = _build_relay_request()
        headers.pop("X-Relay-Signature")

        response = backend_client.post("/api/checkins/scan", json=body, headers=headers)

        assert response.status_code == 401
        assert response.headers["X-Relay-Ack-Outcome"] == "invalid"
        assert response.json()["detail"] == "Relay signature missing."

    def test_protocol_version_mismatch_returns_conflict(self, backend_client):
        body, headers = _build_relay_request(version="2025-01-01")

        response = backend_client.post("/api/checkins/scan", json=body, headers=headers)

        assert response.status_code == 409
        assert response.headers["X-Relay-Ack-Outcome"] == "conflict"
        assert "Unsupported relay protocol version" in response.json()["detail"]

    def test_relay_ticket_context_mismatch_returns_conflict(self, backend_client):
        body, headers = _build_relay_request(relay_ticket_number="T999")

        response = backend_client.post("/api/checkins/scan", json=body, headers=headers)

        assert response.status_code == 409
        assert response.headers["X-Relay-Ack-Outcome"] == "conflict"
        assert response.json()["detail"] == "Relay ticket context does not match parsed payload."

    def test_duplicate_scan_event_replays_ticket_context(self, backend_client):
        body, headers = _build_relay_request()

        with patch("app.services.wix_client.WixClient.check_in_ticket") as mock_wix:
            mock_wix.return_value = WixCheckinResult(
                outcome="checked_in",
                wix_status="CHECKED_IN",
                reason=None,
                error_code="",
                attempts=1,
            )
            first = backend_client.post("/api/checkins/scan", json=body, headers=headers)
            second = backend_client.post("/api/checkins/scan", json=body, headers=headers)

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.headers["X-Relay-Ack-Outcome"] == "duplicate"
        duplicate_body = second.json()
        assert duplicate_body["status"] == "CHECKED_IN"
        assert duplicate_body["accepted"] is True
        assert duplicate_body["event_id"] == "demo-event"
        assert duplicate_body["ticket_number"] == "T001"
        assert duplicate_body["reason"] == "Duplicate scan event detected"

    @pytest.mark.parametrize("sent_at", ["not-a-timestamp", "2026-05-30T12:34:56"])
    def test_invalid_relay_timestamp_is_rejected(self, backend_client, sent_at: str):
        body, headers = _build_relay_request(sent_at=sent_at)

        response = backend_client.post("/api/checkins/scan", json=body, headers=headers)

        assert response.status_code == 401
        assert response.headers["X-Relay-Ack-Outcome"] == "invalid"
        assert response.json()["detail"] == "Relay timestamp is missing or outside the allowed skew window."
