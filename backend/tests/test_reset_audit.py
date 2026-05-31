"""Acceptance tests for P2-US-03: batch reset and audit trail."""

from __future__ import annotations

import sys
from pathlib import Path
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import get_settings
from app.services.scan_idempotency import ScanIdempotencyService
from app.services.event_block_config import EventBlockConfigService, set_event_block_config_service
from app.services.reset_audit import ResetAuditService, set_reset_audit_service
from app.api.routes.checkins import set_scan_idempotency_service


ADMIN_TOKEN = get_settings().admin_api_key
ADMIN_HEADERS = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
WRONG_HEADERS = {"Authorization": "Bearer wrong-token"}


@pytest.fixture
def reset_client():
    """Test client with fresh ScanIdempotency, EventBlockConfig, and ResetAudit services."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        idem_svc = ScanIdempotencyService(db_url=f"sqlite:///{tmp / 'scan.db'}")
        set_scan_idempotency_service(idem_svc)

        ebc_svc = EventBlockConfigService(db_path=str(tmp / "event_block.db"))
        set_event_block_config_service(ebc_svc)

        audit_svc = ResetAuditService(db_path=str(tmp / "reset_audit.db"))
        set_reset_audit_service(audit_svc)

        client = TestClient(app)
        yield client, idem_svc, ebc_svc, audit_svc

        set_scan_idempotency_service(None)
        set_event_block_config_service(None)
        set_reset_audit_service(None)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _seed_scan(idem_svc: ScanIdempotencyService, wix_event_id: str, ticket: str = "T1") -> None:
    """Insert a scan record directly into the idempotency service."""
    idem_svc.record_scan(
        event_id=wix_event_id,
        ticket_number=ticket,
        scan_event_id=f"{wix_event_id}-{ticket}-scan",
        wix_check_in_id=f"wix-{ticket}",
        outcome="success",
        source="test",
    )


def _reset_event_body(confirmation: bool = True, reason: str = "test reset", actor: str = "tester") -> dict:
    return {"confirmation": confirmation, "reason": reason, "actor": actor}


# ── AC1: Authorized reset clears check-in state ───────────────────────────────


def test_authorized_event_reset_clears_checkin_state(reset_client):
    client, idem_svc, _, _ = reset_client
    wix_event_id = "wix-evt-001"

    _seed_scan(idem_svc, wix_event_id, "T1")
    _seed_scan(idem_svc, wix_event_id, "T2")

    # Confirm records exist before reset
    with idem_svc.SessionLocal() as session:
        from app.services.scan_idempotency import ScanIdempotencyRecord
        count_before = session.query(ScanIdempotencyRecord).filter_by(event_id=wix_event_id).count()
    assert count_before == 2

    resp = client.post(
        f"/api/admin/resets/event/{wix_event_id}",
        json=_reset_event_body(),
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["records_cleared"] == 2
    assert data["scope"] == "event"
    assert data["scope_id"] == wix_event_id

    # Records should be gone
    with idem_svc.SessionLocal() as session:
        from app.services.scan_idempotency import ScanIdempotencyRecord
        count_after = session.query(ScanIdempotencyRecord).filter_by(event_id=wix_event_id).count()
    assert count_after == 0


def test_reset_event_with_no_records_returns_zero(reset_client):
    client, _, _, _ = reset_client
    resp = client.post(
        "/api/admin/resets/event/nonexistent-event",
        json=_reset_event_body(),
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["records_cleared"] == 0


# ── AC2: Unauthorized requests are denied ─────────────────────────────────────


def test_unauthorized_event_reset_is_denied_wrong_token(reset_client):
    client, _, _, _ = reset_client
    resp = client.post(
        "/api/admin/resets/event/wix-evt-001",
        json=_reset_event_body(),
        headers=WRONG_HEADERS,
    )
    assert resp.status_code == 403


def test_unauthorized_event_reset_is_denied_no_token(reset_client):
    client, _, _, _ = reset_client
    resp = client.post(
        "/api/admin/resets/event/wix-evt-001",
        json=_reset_event_body(),
    )
    assert resp.status_code == 403


def test_unauthorized_audit_list_is_denied(reset_client):
    client, _, _, _ = reset_client
    resp = client.get("/api/admin/resets/audit", headers=WRONG_HEADERS)
    assert resp.status_code == 403


# ── AC1 guard: confirmation=False is rejected ─────────────────────────────────


def test_reset_requires_confirmation_true(reset_client):
    client, _, _, _ = reset_client
    resp = client.post(
        "/api/admin/resets/event/wix-evt-001",
        json=_reset_event_body(confirmation=False),
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 422


# ── AC3: Audit record is created with required fields ─────────────────────────


def test_audit_record_created_after_event_reset(reset_client):
    client, idem_svc, _, _ = reset_client
    wix_event_id = "wix-evt-audit"
    _seed_scan(idem_svc, wix_event_id, "T9")

    resp = client.post(
        f"/api/admin/resets/event/{wix_event_id}",
        json=_reset_event_body(reason="audit test reason", actor="audit-actor"),
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 200

    audit_resp = client.get("/api/admin/resets/audit", headers=ADMIN_HEADERS)
    assert audit_resp.status_code == 200
    entries = audit_resp.json()
    assert len(entries) >= 1

    entry = entries[0]
    assert entry["scope"] == "event"
    assert entry["scope_id"] == wix_event_id
    assert entry["actor"] == "audit-actor"
    assert entry["reason"] == "audit test reason"
    assert entry["records_cleared"] == 1
    assert "performed_at" in entry
    assert entry["reset_id"]


# ── Block-level reset ─────────────────────────────────────────────────────────


def test_block_level_reset_clears_scans_in_block_window(reset_client):
    client, idem_svc, ebc_svc, _ = reset_client
    wix_event_id = "wix-evt-block"

    # Create event and block in EventBlockConfigService
    event = ebc_svc.create_event(
        wix_event_id=wix_event_id,
        name="Block Reset Test Event",
        actor="tester",
    )
    block = ebc_svc.create_block(
        event_id=event.event_id,
        block_code="BLK1",
        name="Morning Block",
        starts_at="2025-01-01T09:00:00+00:00",
        ends_at="2025-01-01T12:00:00+00:00",
        actor="tester",
    )

    # Seed scans in the block window
    from datetime import datetime, UTC
    from app.services.scan_idempotency import ScanIdempotencyRecord
    for i in range(3):
        idem_svc.record_scan(
            event_id=wix_event_id,
            ticket_number=f"T{i}",
            scan_event_id=f"scan-blk-{i}",
            wix_check_in_id=f"wix-blk-{i}",
            outcome="success",
            source="test",
        )
    # Manually set created_at to inside the block window
    with idem_svc.SessionLocal() as session:
        inside_time = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        session.query(ScanIdempotencyRecord).filter_by(event_id=wix_event_id).update(
            {"created_at": inside_time}
        )
        session.commit()

    resp = client.post(
        f"/api/admin/resets/block/{block.block_id}",
        json=_reset_event_body(reason="block reset", actor="block-tester"),
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["records_cleared"] == 3
    assert data["scope"] == "block"
    assert data["scope_id"] == block.block_id


def test_block_level_reset_audit_record_has_scope_block(reset_client):
    client, idem_svc, ebc_svc, _ = reset_client
    wix_event_id = "wix-evt-blk-audit"

    event = ebc_svc.create_event(
        wix_event_id=wix_event_id,
        name="Audit Block Event",
        actor="tester",
    )
    block = ebc_svc.create_block(
        event_id=event.event_id,
        block_code="BLK2",
        name="Afternoon Block",
        starts_at="2025-02-01T13:00:00+00:00",
        ends_at="2025-02-01T17:00:00+00:00",
        actor="tester",
    )

    resp = client.post(
        f"/api/admin/resets/block/{block.block_id}",
        json=_reset_event_body(reason="block audit check", actor="blk-auditor"),
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 200, resp.text

    audit_resp = client.get("/api/admin/resets/audit", headers=ADMIN_HEADERS)
    assert audit_resp.status_code == 200
    entries = audit_resp.json()
    blk_entries = [e for e in entries if e["scope"] == "block"]
    assert len(blk_entries) >= 1
    e = blk_entries[0]
    assert e["scope_id"] == block.block_id
    assert e["actor"] == "blk-auditor"
    assert e["reason"] == "block audit check"
    assert "performed_at" in e


def test_block_reset_returns_404_for_unknown_block(reset_client):
    client, _, _, _ = reset_client
    resp = client.post(
        "/api/admin/resets/block/nonexistent-block-id",
        json=_reset_event_body(),
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 404
