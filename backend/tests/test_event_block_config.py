from __future__ import annotations

from pathlib import Path

import pytest

from app.services.event_block_config import (
    BlockValidationError,
    EventBlockConfigService,
    set_event_block_config_service,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def event_blocks_client(backend_client, temp_db_dir, monkeypatch):
    db = Path(temp_db_dir) / "event_block_config.db"
    svc = EventBlockConfigService(db_path=str(db))
    set_event_block_config_service(svc)
    return backend_client


# ── Helper ────────────────────────────────────────────────────────────────────


def _create_event(client, *, wix_event_id="event-001", allow_block_overlap=False):
    resp = client.post(
        "/api/admin/event-blocks/events",
        json={
            "wix_event_id": wix_event_id,
            "name": "Test Event",
            "timezone": "America/New_York",
            "allow_block_overlap": allow_block_overlap,
            "actor": "test-admin",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_block(client, event_id, *, block_code="BLK-A", starts_at, ends_at, allow_overlap=False):
    resp = client.post(
        f"/api/admin/event-blocks/events/{event_id}/blocks",
        json={
            "block_code": block_code,
            "name": f"Block {block_code}",
            "starts_at": starts_at,
            "ends_at": ends_at,
            "allow_overlap": allow_overlap,
            "actor": "test-admin",
        },
    )
    return resp


# ── AC-1: valid block is stored and retrievable ───────────────────────────────


def test_valid_block_stored_and_retrievable(event_blocks_client):
    event = _create_event(event_blocks_client)
    event_id = event["event_id"]

    create_resp = _create_block(
        event_blocks_client,
        event_id,
        block_code="MORNING",
        starts_at="2026-06-01T08:00:00+00:00",
        ends_at="2026-06-01T12:00:00+00:00",
    )
    assert create_resp.status_code == 201
    block = create_resp.json()
    assert block["block_code"] == "MORNING"
    assert block["event_id"] == event_id
    assert block["starts_at"] == "2026-06-01T08:00:00+00:00"
    assert block["ends_at"] == "2026-06-01T12:00:00+00:00"
    block_id = block["block_id"]

    # Retrieve via list endpoint
    list_resp = event_blocks_client.get(f"/api/admin/event-blocks/events/{event_id}/blocks")
    assert list_resp.status_code == 200
    blocks = list_resp.json()
    assert any(b["block_id"] == block_id for b in blocks)

    # Retrieve single block
    get_resp = event_blocks_client.get(f"/api/admin/event-blocks/blocks/{block_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["block_id"] == block_id


# ── AC-2: invalid time range (start >= end) rejected with validation message ──


def test_invalid_time_range_start_equals_end_rejected(event_blocks_client):
    event = _create_event(event_blocks_client, wix_event_id="event-002")
    event_id = event["event_id"]

    resp = _create_block(
        event_blocks_client,
        event_id,
        block_code="BAD-EQ",
        starts_at="2026-06-01T09:00:00+00:00",
        ends_at="2026-06-01T09:00:00+00:00",
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "starts_at" in detail or "before" in detail


def test_invalid_time_range_start_after_end_rejected(event_blocks_client):
    event = _create_event(event_blocks_client, wix_event_id="event-003")
    event_id = event["event_id"]

    resp = _create_block(
        event_blocks_client,
        event_id,
        block_code="BAD-GT",
        starts_at="2026-06-01T10:00:00+00:00",
        ends_at="2026-06-01T09:00:00+00:00",
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "starts_at" in detail or "before" in detail


# ── AC-3: overlap disabled → overlapping block is rejected ───────────────────


def test_overlap_disabled_overlapping_block_rejected(event_blocks_client):
    event = _create_event(event_blocks_client, wix_event_id="event-004", allow_block_overlap=False)
    event_id = event["event_id"]

    # Create first block
    resp1 = _create_block(
        event_blocks_client,
        event_id,
        block_code="BLK-1",
        starts_at="2026-06-01T09:00:00+00:00",
        ends_at="2026-06-01T11:00:00+00:00",
    )
    assert resp1.status_code == 201

    # Create overlapping second block
    resp2 = _create_block(
        event_blocks_client,
        event_id,
        block_code="BLK-2",
        starts_at="2026-06-01T10:00:00+00:00",
        ends_at="2026-06-01T12:00:00+00:00",
    )
    assert resp2.status_code == 422
    assert "overlap" in resp2.json()["detail"].lower()


# ── AC-extra: overlap allowed → overlapping block accepted ───────────────────


def test_overlap_allowed_overlapping_block_accepted(event_blocks_client):
    event = _create_event(event_blocks_client, wix_event_id="event-005", allow_block_overlap=True)
    event_id = event["event_id"]

    resp1 = _create_block(
        event_blocks_client,
        event_id,
        block_code="BLK-A",
        starts_at="2026-06-01T09:00:00+00:00",
        ends_at="2026-06-01T11:00:00+00:00",
    )
    assert resp1.status_code == 201

    resp2 = _create_block(
        event_blocks_client,
        event_id,
        block_code="BLK-B",
        starts_at="2026-06-01T10:00:00+00:00",
        ends_at="2026-06-01T12:00:00+00:00",
    )
    assert resp2.status_code == 201


# ── Update and delete operations ─────────────────────────────────────────────


def test_update_block_changes_name_and_bumps_version(event_blocks_client):
    event = _create_event(event_blocks_client, wix_event_id="event-006")
    event_id = event["event_id"]
    block = _create_block(
        event_blocks_client,
        event_id,
        block_code="UPD-BLK",
        starts_at="2026-06-01T08:00:00+00:00",
        ends_at="2026-06-01T10:00:00+00:00",
    ).json()
    block_id = block["block_id"]
    original_version = block["version"]

    update_resp = event_blocks_client.put(
        f"/api/admin/event-blocks/blocks/{block_id}",
        json={"name": "Updated Name", "actor": "test-admin"},
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["name"] == "Updated Name"
    assert updated["version"] > original_version


def test_delete_block_removes_it(event_blocks_client):
    event = _create_event(event_blocks_client, wix_event_id="event-007")
    event_id = event["event_id"]
    block = _create_block(
        event_blocks_client,
        event_id,
        block_code="DEL-BLK",
        starts_at="2026-06-01T08:00:00+00:00",
        ends_at="2026-06-01T10:00:00+00:00",
    ).json()
    block_id = block["block_id"]

    del_resp = event_blocks_client.delete(f"/api/admin/event-blocks/blocks/{block_id}")
    assert del_resp.status_code == 204

    get_resp = event_blocks_client.get(f"/api/admin/event-blocks/blocks/{block_id}")
    assert get_resp.status_code == 404


# ── Version metadata ──────────────────────────────────────────────────────────


def test_version_metadata_increments_on_block_add(event_blocks_client):
    event = _create_event(event_blocks_client, wix_event_id="event-008")
    event_id = event["event_id"]
    initial_version = event["version"]

    _create_block(
        event_blocks_client,
        event_id,
        block_code="VER-BLK",
        starts_at="2026-06-01T08:00:00+00:00",
        ends_at="2026-06-01T10:00:00+00:00",
    )

    event_resp = event_blocks_client.get(f"/api/admin/event-blocks/events/{event_id}")
    assert event_resp.status_code == 200
    assert event_resp.json()["version"] > initial_version


def test_config_version_history_recorded(event_blocks_client):
    event = _create_event(event_blocks_client, wix_event_id="event-009")
    event_id = event["event_id"]

    _create_block(
        event_blocks_client,
        event_id,
        block_code="HIST-BLK",
        starts_at="2026-06-01T08:00:00+00:00",
        ends_at="2026-06-01T10:00:00+00:00",
    )

    versions_resp = event_blocks_client.get(f"/api/admin/event-blocks/events/{event_id}/versions")
    assert versions_resp.status_code == 200
    versions = versions_resp.json()
    assert len(versions) >= 2  # creation + block-add each bump version
    version_numbers = [v["version_number"] for v in versions]
    assert sorted(set(version_numbers)) == sorted(set(version_numbers))  # no duplicates
