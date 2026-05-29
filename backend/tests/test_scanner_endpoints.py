from __future__ import annotations

from time import time

from fastapi.testclient import TestClient

from app.main import app


# ---------------------------------------------------------------------------
# P1-US-02 (existing tests — kept in place)
# ---------------------------------------------------------------------------


def test_scan_endpoint_checked_in_flow() -> None:
    client = TestClient(app)

    response = client.post("/api/checkins/scan", json={"payload": "TICKET-12345"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "CHECKED_IN"
    assert body["accepted"] is True
    assert body["ticket_number"] == "TICKET-12345"
    assert body["wix_status"] == "checked_in"
    assert body["response_time_ms"] > 0


def test_scan_endpoint_invalid_ticket() -> None:
    client = TestClient(app)

    response = client.post("/api/checkins/scan", json={"payload": "INVALID-anything"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "INVALID_TICKET"
    assert body["accepted"] is False
    assert body["error_code"] == "INVALID_TICKET"


def test_scanner_health_endpoint_reports_metrics() -> None:
    client = TestClient(app)

    client.post("/api/checkins/scan", json={"payload": "TICKET-HEALTH-1"})
    response = client.get("/api/health/scanner")

    assert response.status_code == 200
    body = response.json()
    assert "backend_status" in body
    assert "last_20_response_times" in body
    assert isinstance(body["last_20_response_times"], list)


def test_query_metrics_endpoint_returns_persisted_rows() -> None:
    client = TestClient(app)

    client.post(
        "/api/checkins/scan",
        json={
            "payload": "TICKET-METRICS-1",
            "session_id": "session-a",
            "operator_id": "operator-a",
            "source": "hid",
            "scanner_status": "connected",
        },
    )
    response = client.get("/api/metrics/scans", params={"session_id": "session-a", "limit": 10})

    assert response.status_code == 200
    rows = response.json()
    assert isinstance(rows, list)
    assert len(rows) >= 1
    assert rows[0]["session_id"] == "session-a"


# ---------------------------------------------------------------------------
# P1-US-02b — new tests
# ---------------------------------------------------------------------------


def test_scanner_health_includes_latency_percentiles() -> None:
    """Health endpoint must return p50, p95, and p99 latency percentiles."""
    client = TestClient(app)

    # Generate a few scans so percentile calculation has data
    for i in range(5):
        client.post("/api/checkins/scan", json={"payload": f"TICKET-PCT-{i}"})

    response = client.get("/api/health/scanner")

    assert response.status_code == 200
    body = response.json()
    assert "p50_ms" in body
    assert "p95_ms" in body
    assert "p99_ms" in body
    assert isinstance(body["p50_ms"], (int, float))
    assert body["p50_ms"] >= 0
    assert body["p95_ms"] >= body["p50_ms"]
    assert body["p99_ms"] >= body["p95_ms"]


def test_scan_metric_records_latency_percentile() -> None:
    """Each persisted metric row must contain a latency_percentile value."""
    client = TestClient(app)

    client.post(
        "/api/checkins/scan",
        json={
            "payload": "TICKET-LATPCT-1",
            "session_id": "session-latpct",
            "operator_id": "op-latpct",
        },
    )
    response = client.get("/api/metrics/scans", params={"session_id": "session-latpct", "limit": 5})

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) >= 1
    assert "latency_percentile" in rows[0]
    assert 0.0 <= rows[0]["latency_percentile"] <= 100.0


def test_metrics_query_date_range_filter() -> None:
    """Metrics query endpoint filters correctly using start_ts / end_ts."""
    client = TestClient(app)

    before = time()
    client.post(
        "/api/checkins/scan",
        json={
            "payload": "TICKET-DATE-1",
            "session_id": "session-date",
            "operator_id": "op-date",
        },
    )
    after = time()

    # Within range — should return the row
    response_in = client.get(
        "/api/metrics/scans",
        params={"session_id": "session-date", "start_ts": before - 1, "end_ts": after + 1, "limit": 10},
    )
    assert response_in.status_code == 200
    assert len(response_in.json()) >= 1

    # Future range — should return nothing
    response_out = client.get(
        "/api/metrics/scans",
        params={"session_id": "session-date", "start_ts": after + 9999, "limit": 10},
    )
    assert response_out.status_code == 200
    assert response_out.json() == []


def test_response_time_header_present() -> None:
    """RequestTimingMiddleware must add X-Response-Time-Ms header to all responses."""
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert "x-response-time-ms" in response.headers
    assert int(response.headers["x-response-time-ms"]) >= 0


def test_websocket_health_push() -> None:
    """WebSocket /ws/health must push a valid health payload on connect."""
    client = TestClient(app)

    with client.websocket_connect("/api/ws/health") as ws:
        data = ws.receive_json()

    assert "backend_status" in data
    assert "p50_ms" in data
    assert "p95_ms" in data
    assert "p99_ms" in data
    assert "success_rate" in data
    assert "last_check_ts" in data


def test_cleanup_old_metrics_returns_counts() -> None:
    """cleanup_old_metrics() must return a dict with 'archived' and 'purged' keys."""
    from app.services.scan_runtime import scan_runtime_store

    result = scan_runtime_store.cleanup_old_metrics()

    assert isinstance(result, dict)
    assert "archived" in result
    assert "purged" in result
    assert result["archived"] >= 0
    assert result["purged"] >= 0

