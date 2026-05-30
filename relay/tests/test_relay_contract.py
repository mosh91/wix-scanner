from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.services.cloud_forwarder import CloudForwarder
from app.services.relay_forwarder import RelayForwarder
from app.services.relay_queue import RelayQueueService


class TestRelayContractForwarder:
    def test_forward_scan_sends_signed_contract(self, monkeypatch):
        captured: dict[str, object] = {}
        settings = Settings(
            cloud_base_url="http://backend:8000/api",
            relay_auth_token="relay-token",
            relay_signing_secret="relay-signing-secret",
            relay_instance_id="relay-edge-1",
            relay_protocol_version="2026-05-29",
        )
        forwarder = CloudForwarder(settings)

        def fake_post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers or {}
            captured["json"] = json or {}
            return httpx.Response(
                200,
                headers={"X-Relay-Ack-Outcome": "accepted"},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx.Client, "post", fake_post)

        result = forwarder.forward_scan(
            event_id="demo-event",
            ticket_number="T001",
            relay_request_id="relay-request-1",
            payload='{"eventId":"demo-event","ticketNumber":"T001"}',
            correlation_id="corr-123",
            scan_event_id="550e8400-e29b-41d4-a716-446655440000",
        )

        headers = captured["headers"]
        body = captured["json"]
        assert captured["url"] == "http://backend:8000/api/checkins/scan"
        assert headers["Authorization"] == "Bearer relay-token"
        assert headers["X-Relay-ID"] == "relay-edge-1"
        assert headers["X-Relay-Request-ID"] == "relay-request-1"
        assert headers["X-Relay-Protocol-Version"] == "2026-05-29"
        assert headers["X-Relay-Signature"]
        assert body["source"] == "relay"
        assert body["active_event_id"] == "demo-event"
        assert body["relay_metadata"]["ticket_number"] == "T001"
        assert result["outcome"] == "forwarded"
        assert result["contract_outcome"] == "accepted"

    def test_forward_scan_marks_contract_rejection_non_retryable(self, monkeypatch):
        settings = Settings(
            cloud_base_url="http://backend:8000/api",
            relay_auth_token="relay-token",
            relay_signing_secret="relay-signing-secret",
            relay_instance_id="relay-edge-1",
            relay_protocol_version="2026-05-29",
        )
        forwarder = CloudForwarder(settings)

        def fake_post(self, url, headers=None, json=None):
            return httpx.Response(
                409,
                json={"detail": "Unsupported relay protocol version: 2025-01-01."},
                headers={"X-Relay-Ack-Outcome": "conflict"},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx.Client, "post", fake_post)

        result = forwarder.forward_scan(
            event_id="demo-event",
            ticket_number="T001",
            relay_request_id="relay-request-1",
            payload='{"eventId":"demo-event","ticketNumber":"T001"}',
            correlation_id="corr-123",
            scan_event_id="550e8400-e29b-41d4-a716-446655440000",
        )

        assert result["outcome"] == "relay_rejected"
        assert result["retryable"] is False
        assert result["contract_outcome"] == "conflict"

    @pytest.mark.asyncio
    async def test_relay_forwarder_moves_contract_rejection_to_dlq(self, tmp_path):
        queue = RelayQueueService(db_path=str(tmp_path / "relay.db"), max_attempts=3)
        queue.enqueue_scan(
            event_id="demo-event",
            ticket_number="T001",
            relay_id="relay-request-1",
            payload='{"eventId":"demo-event","ticketNumber":"T001"}',
            correlation_id="corr-123",
            scan_event_id="550e8400-e29b-41d4-a716-446655440000",
        )

        class RejectingForwarder:
            def forward_scan(self, **kwargs):
                return {
                    "outcome": "relay_rejected",
                    "retryable": False,
                    "message": "Unsupported relay protocol version: 2025-01-01.",
                }

        forwarder = RelayForwarder(queue, RejectingForwarder(), base_backoff_ms=1, max_backoff_ms=2)
        stats = await forwarder.process_once()

        assert stats["moved_to_dlq"] == 1
        assert queue.get_queue_stats()["pending"] == 0
        assert queue.get_dlq_entries(limit=10)[0].reason == "contract_rejected"
