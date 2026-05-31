from __future__ import annotations

from pathlib import Path

import pytest

from app.services.sync_controls import WixSyncControlService, set_sync_control_service


class _FakeManifestService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def sync_event_from_wix(self, event_id: str):
        self.calls.append(event_id)
        return {
            "event_id": event_id,
        }


@pytest.fixture
def sync_client(backend_client, temp_db_dir, monkeypatch):
    sync_db = Path(temp_db_dir) / "sync_controls.db"
    service = WixSyncControlService(db_path=str(sync_db))
    set_sync_control_service(service)

    fake_manifest = _FakeManifestService()
    import app.services.ticket_manifest as manifest_module

    monkeypatch.setattr(manifest_module, "_manifest_service", fake_manifest)

    yield {
        "client": backend_client,
        "service": service,
        "manifest": fake_manifest,
    }

    set_sync_control_service(None)


def test_sync_enabled_schedules_by_configured_interval(sync_client):
    service = sync_client["service"]
    manifest = sync_client["manifest"]

    service.upsert_control(event_id="event-sync-1", enabled=True, interval_seconds=60)

    processed_first = service.process_due_syncs(now_ts=1_000.0)
    processed_second = service.process_due_syncs(now_ts=1_020.0)
    processed_third = service.process_due_syncs(now_ts=1_061.0)

    assert processed_first == 1
    assert processed_second == 0
    assert processed_third == 1
    assert manifest.calls == ["event-sync-1", "event-sync-1"]


def test_sync_disabled_skips_worker_execution(sync_client):
    service = sync_client["service"]
    manifest = sync_client["manifest"]

    service.upsert_control(event_id="event-sync-2", enabled=False, interval_seconds=60)
    processed = service.process_due_syncs(now_ts=2_000.0)

    assert processed == 0
    assert manifest.calls == []


def test_successful_sync_updates_last_timestamp(sync_client):
    service = sync_client["service"]

    service.upsert_control(event_id="event-sync-3", enabled=True, interval_seconds=60)
    service.process_due_syncs(now_ts=3_210.0)

    record = service.get_control(event_id="event-sync-3", now_ts=3_210.0)
    assert record.last_successful_sync_at == pytest.approx(3_210.0)
    assert record.last_attempt_at == pytest.approx(3_210.0)
    assert record.last_error is None


def test_sync_control_api_round_trip(sync_client):
    client = sync_client["client"]

    create_response = client.put(
        "/api/admin/sync-controls/events/event-api-1",
        json={"enabled": True, "interval_seconds": 120},
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["event_id"] == "event-api-1"
    assert created["enabled"] is True
    assert created["interval_seconds"] == 120

    get_response = client.get("/api/admin/sync-controls/events/event-api-1")
    assert get_response.status_code == 200
    loaded = get_response.json()
    assert loaded["event_id"] == "event-api-1"
    assert loaded["enabled"] is True
    assert loaded["interval_seconds"] == 120

    list_response = client.get("/api/admin/sync-controls/events")
    assert list_response.status_code == 200
    rows = list_response.json()
    assert any(row["event_id"] == "event-api-1" for row in rows)
