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


# ---------------------------------------------------------------------------
# P1-US-02c — bootstrap QR and kiosk session enrollment tests
# ---------------------------------------------------------------------------


def _generate_bootstrap_qr(
    client: TestClient,
    event_id: str = "event-test-001",
    station_id: str = "station-entrance-1",
    ttl_seconds: int = 3600,
    is_admin: bool = False,
) -> str:
    """Helper: use the dev generate endpoint to produce a valid QR payload."""
    resp = client.get(
        "/api/bootstrap/generate",
        params={
            "event_id": event_id,
            "station_id": station_id,
            "ttl_seconds": ttl_seconds,
            "is_admin": str(is_admin).lower(),
        },
    )
    assert resp.status_code == 200
    return resp.json()["qr_payload"]


def test_bootstrap_generate_returns_valid_payload() -> None:
    """Dev generate endpoint must return a properly formatted QR payload."""
    client = TestClient(app)
    payload = _generate_bootstrap_qr(client)
    assert payload.startswith("BOOTSTRAP:v1:")
    parts = payload[len("BOOTSTRAP:v1:"):].split(":")
    assert len(parts) == 4, "Payload must have 4 colon-separated fields after the prefix"


def test_bootstrap_validate_new_kiosk_enrolls_session() -> None:
    """A valid bootstrap QR with no prior event must return a session binding."""
    client = TestClient(app)
    qr = _generate_bootstrap_qr(client, event_id="evt-01", station_id="stn-01")

    resp = client.post("/api/bootstrap/validate", json={"payload": qr})

    assert resp.status_code == 200
    body = resp.json()
    assert body["event_id"] == "evt-01"
    assert body["station_id"] == "stn-01"
    assert "bootstrap_session_id" in body
    assert body["expires_at"] > 0
    assert body["is_admin_override"] is False


def test_bootstrap_validate_same_event_re_enrollment_allowed() -> None:
    """Re-enrolling to the same event/station must succeed without admin override."""
    client = TestClient(app)
    qr = _generate_bootstrap_qr(client, event_id="evt-same", station_id="stn-same")

    resp = client.post(
        "/api/bootstrap/validate",
        json={"payload": qr, "current_event_id": "evt-same"},
    )

    assert resp.status_code == 200
    assert resp.json()["event_id"] == "evt-same"


def test_bootstrap_validate_different_event_blocked_without_admin() -> None:
    """Switching to a different event without admin QR must return 409."""
    client = TestClient(app)
    qr = _generate_bootstrap_qr(client, event_id="evt-new", station_id="stn-new")

    resp = client.post(
        "/api/bootstrap/validate",
        json={"payload": qr, "current_event_id": "evt-old"},
    )

    assert resp.status_code == 409


def test_bootstrap_validate_admin_qr_allows_event_switch() -> None:
    """Admin bootstrap QR must bypass the event-switch guard."""
    client = TestClient(app)
    admin_qr = _generate_bootstrap_qr(
        client, event_id="evt-switched", station_id="stn-a", is_admin=True
    )

    resp = client.post(
        "/api/bootstrap/validate",
        json={"payload": admin_qr, "current_event_id": "evt-old"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["event_id"] == "evt-switched"
    assert body["is_admin_override"] is True


def test_bootstrap_validate_invalid_payload_returns_422() -> None:
    """Garbage or unsigned payloads must be rejected."""
    client = TestClient(app)

    resp = client.post("/api/bootstrap/validate", json={"payload": "BOOTSTRAP:v1:bad:data:0:fakehash"})
    assert resp.status_code == 422


def test_bootstrap_clear_session_succeeds() -> None:
    """Clearing a session must return 204 — even for an unknown session ID."""
    client = TestClient(app)
    qr = _generate_bootstrap_qr(client, event_id="evt-clear", station_id="stn-clear")
    enroll_resp = client.post("/api/bootstrap/validate", json={"payload": qr})
    session_id = enroll_resp.json()["bootstrap_session_id"]

    clear_resp = client.post("/api/bootstrap/clear", json={"bootstrap_session_id": session_id})
    assert clear_resp.status_code == 204


def test_bootstrap_generate_blocked_in_production() -> None:
    """Generate endpoint must be blocked when environment == 'production'."""
    from app.core.config import Settings, get_settings
    from app.main import app as fastapi_app

    class ProdSettings(Settings):
        environment: str = "production"

    fastapi_app.dependency_overrides[get_settings] = lambda: ProdSettings()
    try:
        prod_client = TestClient(fastapi_app)
        resp = prod_client.get(
            "/api/bootstrap/generate",
            params={"event_id": "e1", "station_id": "s1"},
        )
        assert resp.status_code == 403
    finally:
        fastapi_app.dependency_overrides.clear()


def test_scan_with_enrolled_context_accepted() -> None:
    """Scan request carrying active_event_id and active_station_id must be accepted."""
    client = TestClient(app)

    resp = client.post(
        "/api/checkins/scan",
        json={
            "payload": "TICKET-ENROLLED-1",
            "session_id": "session-enrolled",
            "operator_id": "operator-enrolled",
            "active_event_id": "evt-enrolled",
            "active_station_id": "stn-door-1",
        },
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "CHECKED_IN"


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


# ---------------------------------------------------------------------------
# P1-US-03 — QR parsing and check-in API contract
# ---------------------------------------------------------------------------


def test_scan_parses_event_and_ticket_from_key_value_payload() -> None:
    """Known key/value QR format should extract event/ticket/block context."""
    client = TestClient(app)

    response = client.post(
        "/api/checkins/scan",
        json={
            "payload": "eventId=evt-2026-001;ticketNumber=tkt-778899;blockId=door-a;operationType=checkin",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "CHECKED_IN"
    assert body["ticket_number"] == "TKT-778899"
    assert body["event_id"] == "evt-2026-001"
    assert body["block_id"] == "door-a"
    assert body["operation_type"] == "checkin"


def test_scan_parses_json_payload_contract() -> None:
    """JSON QR payload format should be supported as a known format."""
    client = TestClient(app)

    response = client.post(
        "/api/checkins/scan",
        json={
            "payload": '{"eventId":"evt-json-1","ticketNumber":"abc-123","blockId":"vip"}',
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "CHECKED_IN"
    assert body["event_id"] == "evt-json-1"
    assert body["ticket_number"] == "ABC-123"
    assert body["block_id"] == "vip"


def test_scan_malformed_payload_returns_invalid_ticket_with_reason() -> None:
    """Malformed known format (missing ticketNumber) returns INVALID_TICKET with clear reason."""
    client = TestClient(app)

    response = client.post(
        "/api/checkins/scan",
        json={"payload": "eventId=evt-only-no-ticket;blockId=door-b"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "INVALID_TICKET"
    assert body["error_code"] == "INVALID_TICKET"
    assert body["accepted"] is False
    assert isinstance(body["reason"], str)
    assert "ticketNumber" in body["reason"]


def test_scan_identical_requests_reuse_same_idempotency_result() -> None:
    """Repeated identical scan contract must return same idempotency key and same normalized result."""
    client = TestClient(app)

    payload = "eventId=evt-idem-1;ticketNumber=tkt-idem-001;blockId=main;operationType=checkin"
    response_one = client.post("/api/checkins/scan", json={"payload": payload})
    response_two = client.post("/api/checkins/scan", json={"payload": payload})

    assert response_one.status_code == 200
    assert response_two.status_code == 200

    body_one = response_one.json()
    body_two = response_two.json()
    assert body_one["idempotency_key"] == body_two["idempotency_key"]
    assert body_one["status"] == body_two["status"]
    assert body_one["ticket_number"] == body_two["ticket_number"]
    assert body_one["event_id"] == body_two["event_id"]


# ---------------------------------------------------------------------------
# P1-US-04 — Wix ticket check-in integration
# ---------------------------------------------------------------------------


def test_scan_forwards_correlation_id_in_response() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/checkins/scan",
        headers={"X-Correlation-ID": "corr-test-123"},
        json={"payload": "eventId=evt-corr;ticketNumber=tkt-corr-1"},
    )

    assert response.status_code == 200
    assert response.json()["correlation_id"] == "corr-test-123"


def test_scan_maps_wix_already_checked_in_to_internal_status() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/checkins/scan",
        json={"payload": "eventId=evt-dup;ticketNumber=dup-ticket-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ALREADY_CHECKED_IN"
    assert body["error_code"] == "ALREADY_CHECKED_IN"


def test_scan_classifies_wix_rate_limit_failures() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/checkins/scan",
        json={"payload": "eventId=evt-rate;ticketNumber=rate-ticket-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "INVALID_TICKET"
    assert body["error_code"] == "WIX_RATE_LIMITED"


def test_scan_parses_wix_events_url_format() -> None:
    """Wix Events check-in URL format should be parsed correctly: https://www.wixevents.com/check-in/{ticketNumber},{eventId}"""
    client = TestClient(app)

    url = "https://www.wixevents.com/check-in/30CS-1G2K-1NH1P,1d00a095-6f73-4311-a3dc-80a5fd6eaa99"
    response = client.post(
        "/api/checkins/scan",
        json={"payload": url},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "CHECKED_IN"
    assert body["ticket_number"] == "30CS-1G2K-1NH1P"
    assert body["event_id"] == "1d00a095-6f73-4311-a3dc-80a5fd6eaa99"
    assert body["accepted"] is True

