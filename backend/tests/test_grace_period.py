"""
P2-US-02: Early check-in grace period rules
Acceptance criteria:
  AC1 – Scan timestamp within [start - grace, end) → block assigned.
  AC2 – Multiple eligible blocks → deterministic priority ordering applied.
  AC3 – Invalid grace value → save is blocked (422).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.services.event_block_config import EventBlockConfigService, set_event_block_config_service


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def grace_client(backend_client, temp_db_dir):
    """TestClient wired to an isolated EventBlockConfigService."""
    db = Path(temp_db_dir) / "grace_period.db"
    svc = EventBlockConfigService(db_path=str(db))
    set_event_block_config_service(svc)
    yield backend_client, svc
    set_event_block_config_service(None)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ── AC-1: Scan within grace window → block selected ───────────────────────────


def test_block_selected_for_scan_within_grace_window(grace_client):
    """Scan 15 min before starts_at with 30-min grace → block returned."""
    _, svc = grace_client
    now = datetime.now(UTC)
    starts_at = _iso(now + timedelta(minutes=20))
    ends_at = _iso(now + timedelta(hours=3))

    event = svc.create_event(wix_event_id="wix-grace-ac1a", name="Grace AC1A")
    svc.create_block(
        event.event_id,
        block_code="MORNING",
        name="Morning Block",
        starts_at=starts_at,
        ends_at=ends_at,
        grace_period_minutes=30,  # effective_start = now - 10 min → scan qualifies
    )

    selected = svc.select_block_for_wix_event("wix-grace-ac1a", now)
    assert selected is not None
    assert selected.block_code == "MORNING"


def test_block_not_selected_when_scan_before_grace_window(grace_client):
    """Scan 60 min before starts_at with 30-min grace → no block."""
    _, svc = grace_client
    now = datetime.now(UTC)
    starts_at = _iso(now + timedelta(hours=2))
    ends_at = _iso(now + timedelta(hours=4))

    event = svc.create_event(wix_event_id="wix-grace-ac1b", name="Grace AC1B")
    svc.create_block(
        event.event_id,
        block_code="AFTERNOON",
        name="Afternoon Block",
        starts_at=starts_at,
        ends_at=ends_at,
        grace_period_minutes=30,  # effective_start = now + 90 min → scan too early
    )

    selected = svc.select_block_for_wix_event("wix-grace-ac1b", now)
    assert selected is None


def test_block_not_selected_when_scan_after_ends_at(grace_client):
    """Scan after ends_at → no block."""
    _, svc = grace_client
    now = datetime.now(UTC)
    starts_at = _iso(now - timedelta(hours=3))
    ends_at = _iso(now - timedelta(hours=1))

    event = svc.create_event(wix_event_id="wix-grace-ac1c", name="Grace AC1C")
    svc.create_block(
        event.event_id,
        block_code="PAST",
        name="Past Block",
        starts_at=starts_at,
        ends_at=ends_at,
        grace_period_minutes=30,
    )

    selected = svc.select_block_for_wix_event("wix-grace-ac1c", now)
    assert selected is None


def test_grace_period_zero_requires_scan_at_or_after_start(grace_client):
    """With grace=0, scan exactly at starts_at → assigned; 1 min before → not assigned."""
    _, svc = grace_client
    now = datetime.now(UTC)
    starts_at_dt = now
    ends_at_dt = now + timedelta(hours=2)

    event = svc.create_event(wix_event_id="wix-grace-zero", name="Grace Zero")
    svc.create_block(
        event.event_id,
        block_code="EXACT",
        name="Exact Start Block",
        starts_at=_iso(starts_at_dt),
        ends_at=_iso(ends_at_dt),
        grace_period_minutes=0,
    )

    # scan at starts_at (effective_start == starts_at)
    assert svc.select_block_for_wix_event("wix-grace-zero", starts_at_dt) is not None
    # scan 1 min before starts_at
    assert svc.select_block_for_wix_event("wix-grace-zero", starts_at_dt - timedelta(minutes=1)) is None


# ── AC-2: Multiple eligible blocks → deterministic priority ordering ──────────


def test_deterministic_priority_applied_for_multiple_eligible_blocks(grace_client):
    """Two overlapping active blocks; lower priority number wins."""
    _, svc = grace_client
    now = datetime.now(UTC)
    starts_at = _iso(now - timedelta(minutes=30))
    ends_at = _iso(now + timedelta(hours=2))

    event = svc.create_event(wix_event_id="wix-prio-ac2", name="Priority AC2", allow_block_overlap=True)

    svc.create_block(
        event.event_id,
        block_code="VIP",
        name="VIP Block",
        starts_at=starts_at,
        ends_at=ends_at,
        priority=10,
        allow_overlap=True,
    )
    svc.create_block(
        event.event_id,
        block_code="GENERAL",
        name="General Block",
        starts_at=starts_at,
        ends_at=ends_at,
        priority=100,
        allow_overlap=True,
    )

    selected = svc.select_block_for_wix_event("wix-prio-ac2", now)
    assert selected is not None
    assert selected.block_code == "VIP"  # lower priority number wins


def test_deterministic_tiebreaker_by_starts_at_then_block_id(grace_client):
    """Same priority → earlier starts_at wins."""
    _, svc = grace_client
    now = datetime.now(UTC)
    early_start = _iso(now - timedelta(hours=1))
    late_start = _iso(now - timedelta(minutes=10))
    ends_at = _iso(now + timedelta(hours=2))

    event = svc.create_event(wix_event_id="wix-tie-ac2", name="Tie AC2", allow_block_overlap=True)

    svc.create_block(
        event.event_id,
        block_code="LATE",
        name="Late Block",
        starts_at=late_start,
        ends_at=ends_at,
        priority=50,
        allow_overlap=True,
    )
    svc.create_block(
        event.event_id,
        block_code="EARLY",
        name="Early Block",
        starts_at=early_start,
        ends_at=ends_at,
        priority=50,
        allow_overlap=True,
    )

    selected = svc.select_block_for_wix_event("wix-tie-ac2", now)
    assert selected is not None
    assert selected.block_code == "EARLY"


# ── AC-3: Invalid grace value → save is blocked (422) ────────────────────────


def test_invalid_grace_period_above_max_rejected_via_api(grace_client):
    """grace_period_minutes > 120 → HTTP 422."""
    client, svc = grace_client
    event = svc.create_event(wix_event_id="wix-inv-grace", name="Invalid Grace")
    now = datetime.now(UTC)
    resp = client.post(
        f"/api/admin/event-blocks/events/{event.event_id}/blocks",
        json={
            "block_code": "BAD",
            "name": "Bad Block",
            "starts_at": _iso(now + timedelta(hours=1)),
            "ends_at": _iso(now + timedelta(hours=3)),
            "grace_period_minutes": 121,
        },
    )
    assert resp.status_code == 422


def test_negative_grace_period_rejected_via_api(grace_client):
    """grace_period_minutes < 0 → HTTP 422."""
    client, svc = grace_client
    event = svc.create_event(wix_event_id="wix-neg-grace", name="Negative Grace")
    now = datetime.now(UTC)
    resp = client.post(
        f"/api/admin/event-blocks/events/{event.event_id}/blocks",
        json={
            "block_code": "NEG",
            "name": "Neg Block",
            "starts_at": _iso(now + timedelta(hours=1)),
            "ends_at": _iso(now + timedelta(hours=3)),
            "grace_period_minutes": -1,
        },
    )
    assert resp.status_code == 422


def test_grace_period_at_boundary_120_is_accepted(grace_client):
    """grace_period_minutes == 120 (max) → block created (201)."""
    client, svc = grace_client
    event = svc.create_event(wix_event_id="wix-max-grace", name="Max Grace")
    now = datetime.now(UTC)
    resp = client.post(
        f"/api/admin/event-blocks/events/{event.event_id}/blocks",
        json={
            "block_code": "MAX",
            "name": "Max Block",
            "starts_at": _iso(now + timedelta(hours=3)),
            "ends_at": _iso(now + timedelta(hours=5)),
            "grace_period_minutes": 120,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["grace_period_minutes"] == 120


# ── AC-1 (integration): selected_block present in scan response ───────────────


def test_selected_block_present_in_scan_response(grace_client):
    """POST /api/checkins/scan → selected_block populated when block is active."""
    client, svc = grace_client
    now = datetime.now(UTC)
    starts_at = _iso(now - timedelta(minutes=5))
    ends_at = _iso(now + timedelta(hours=2))

    # Use the wix_event_id as the active_event_id in the scan request.
    wix_event_id = "wix-scan-ac1"
    event = svc.create_event(wix_event_id=wix_event_id, name="Scan AC1 Event")
    svc.create_block(
        event.event_id,
        block_code="SESSION-A",
        name="Session A",
        starts_at=starts_at,
        ends_at=ends_at,
        grace_period_minutes=30,
    )

    resp = client.post(
        "/api/checkins/scan",
        json={
            "payload": "TICKET-0001",
            "source": "hid",
            "active_event_id": wix_event_id,
        },
    )
    # Scan may fail (invalid ticket) but the selected_block field must be present.
    data = resp.json()
    assert "selected_block" in data
    assert data["selected_block"] is not None
    assert data["selected_block"]["block_code"] == "SESSION-A"
