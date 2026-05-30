from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import patch

from app.core.config import get_settings
from app.services.relay_contract import RelayContractEnvelope, build_signature
from app.services.wix_client import WixCheckinResult


def _build_relay_request(*, version: str | None = None) -> tuple[dict[str, object], dict[str, str]]:
    settings = get_settings()
    protocol_version = version or settings.relay_protocol_version
    correlation_id = "corr-relay-contract-1"
    relay_id = "relay-dev-1"
    relay_request_id = "relay-req-123"
    sent_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
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
            "sent_at": sent_at,
            "event_id": "demo-event",
            "ticket_number": "T001",
        },
    }
    envelope = RelayContractEnvelope(
        relay_id=relay_id,
        relay_request_id=relay_request_id,
        correlation_id=correlation_id,
        protocol_version=protocol_version,
        sent_at=sent_at,
        event_id="demo-event",
        ticket_number="T001",
        payload=payload,
        scan_event_id=scan_event_id,
    )
    headers = {
        "Authorization": f"Bearer {settings.relay_auth_token}",
        "X-Correlation-ID": correlation_id,
        "X-Relay-ID": relay_id,
        "X-Relay-Request-ID": relay_request_id,
        "X-Relay-Protocol-Version": protocol_version,
        "X-Relay-Sent-At": sent_at,
        "X-Relay-Signature": build_signature(settings.relay_signing_secret, envelope),
    }
    return body, headers


class TestRelayContract:
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
