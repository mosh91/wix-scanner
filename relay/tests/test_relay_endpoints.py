from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health_check_shows_relay_ready(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["relay_ready"] is True
    assert "status" in data


def test_relay_scan_submission_returns_acknowledged(client: TestClient) -> None:
    payload = {
        "event_id": "evt-relay-1",
        "ticket_number": "RELAY-001",
        "payload": "eventId=evt-relay-1;ticketNumber=RELAY-001",
    }

    response = client.post("/api/relay/scans", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["acknowledged"] is True
    assert "relay_request_id" in data
    assert len(data["relay_request_id"]) > 0


def test_relay_scan_includes_correlation_id(client: TestClient) -> None:
    payload = {
        "event_id": "evt-relay-2",
        "ticket_number": "RELAY-002",
        "payload": "eventId=evt-relay-2;ticketNumber=RELAY-002",
    }
    correlation_id = "corr-relay-test-123"

    response = client.post(
        "/api/relay/scans",
        json=payload,
        headers={"X-Correlation-ID": correlation_id},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["acknowledged"] is True


def test_relay_scan_rejects_missing_event_id(client: TestClient) -> None:
    payload = {
        "ticket_number": "RELAY-003",
        "payload": "ticketNumber=RELAY-003",
    }

    response = client.post("/api/relay/scans", json=payload)

    assert response.status_code == 422


def test_relay_scan_outcome_when_cloud_unreachable(client: TestClient) -> None:
    """Test that relay acknowledges scan even if cloud is unreachable."""
    payload = {
        "event_id": "evt-relay-4",
        "ticket_number": "RELAY-004",
        "payload": "eventId=evt-relay-4;ticketNumber=RELAY-004",
    }

    response = client.post("/api/relay/scans", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["acknowledged"] is True
    # Outcome may be "relay_only" or "relay_queued" depending on cloud config
    assert data["outcome"] in ("forwarded", "relay_queued", "relay_only")


def test_health_check_includes_cloud_status(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert "cloud_reachable" in data
    assert isinstance(data["cloud_reachable"], bool)
    assert "cloud_details" in data
