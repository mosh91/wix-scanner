from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services.offline_queue import OfflineQueueService, PendingCheckinJob
from app.services.reconciliation import ReconciliationService
from app.services.ticket_manifest import TicketManifestService


@pytest.fixture
def reconciliation_client(backend_client, temp_db_dir, monkeypatch):
    settings = get_settings()

    manifest_service = TicketManifestService(database_file=Path(temp_db_dir) / "ticket_manifest.db")
    import app.services.ticket_manifest as manifest_module

    monkeypatch.setattr(manifest_module, "_manifest_service", manifest_service)

    queue_service = OfflineQueueService(settings)
    queue_service.reset_for_tests()
    import app.services.offline_queue as queue_module

    monkeypatch.setattr(queue_module, "_offline_queue_service", queue_service)

    reconciliation_service = ReconciliationService(db_path=str(Path(temp_db_dir) / "reconciliation.db"))
    import app.services.reconciliation as reconciliation_module

    monkeypatch.setattr(reconciliation_module, "_reconciliation_service", reconciliation_service)

    return {
        "client": backend_client,
        "manifest": manifest_service,
        "queue": queue_service,
    }


def test_reconciliation_in_sync_when_wix_and_local_match(reconciliation_client, monkeypatch):
    client = reconciliation_client["client"]
    manifest = reconciliation_client["manifest"]
    event_id = "event-recon-sync"

    manifest.mark_not_checked_in(event_id=event_id, ticket_number="SYNC-EVEN-001")

    class FakeWixClient:
        def list_tickets(self, *, event_id: str, limit: int = 500):
            return [{"ticket_number": "SYNC-EVEN-001", "checked_in": False, "checked_in_at": None}]

        def check_in_ticket(self, **kwargs):
            raise RuntimeError("not used")

    import app.services.reconciliation as reconciliation_module

    monkeypatch.setattr(reconciliation_module, "get_wix_client", lambda: FakeWixClient())

    response = client.post(f"/api/admin/events/{event_id}/reconciliation/run", json={"actor": "qa-user"})

    assert response.status_code == 200
    body = response.json()
    assert body["run"]["reconciliation_state"] == "in_sync"
    assert body["run"]["drift_count"] == 0


def test_reconciliation_keeps_local_pending_and_retries_queue(reconciliation_client, monkeypatch):
    client = reconciliation_client["client"]
    queue = reconciliation_client["queue"]
    event_id = "event-pending-01"
    ticket_number = "RATE-EVEN-003"

    queue.remember_manifest_ticket(event_id=event_id, ticket_number=ticket_number)
    queue.enqueue_checkin(
        PendingCheckinJob(
            event_id=event_id,
            ticket_number=ticket_number,
            block_id="general",
            operation_type="checkin",
            idempotency_key="idem-1",
            correlation_id="corr-1",
        )
    )
    monkeypatch.setattr(queue, "process_pending_once", lambda max_items=100: 0)

    class FakeWixClient:
        def list_tickets(self, *, event_id: str, limit: int = 500):
            return [{"ticket_number": ticket_number, "checked_in": False, "checked_in_at": None}]

        def check_in_ticket(self, **kwargs):
            from app.services.wix_client import WixCheckinResult

            return WixCheckinResult(
                outcome="rate_limited",
                wix_status="rate_limited",
                reason="Wix devolvio rate-limit.",
                error_code="WIX_RATE_LIMITED",
                attempts=1,
                http_status=429,
            )

    import app.services.reconciliation as reconciliation_module

    monkeypatch.setattr(reconciliation_module, "get_wix_client", lambda: FakeWixClient())

    response = client.post(f"/api/admin/events/{event_id}/reconciliation/run", json={"actor": "qa-user"})

    assert response.status_code == 200
    body = response.json()
    assert body["run"]["reconciliation_state"] == "local_pending"
    assert any(item["reconciliation_state"] == "local_pending" for item in body["items"])

    pending_after = queue.list_pending_jobs(event_id=event_id)
    assert pending_after
    assert pending_after[0].attempts == 0


def test_reconciliation_wix_only_updates_local_manifest(reconciliation_client, monkeypatch):
    client = reconciliation_client["client"]
    manifest = reconciliation_client["manifest"]
    event_id = "event-wix-only"
    ticket_number = "WIX-ONLY-01"

    class FakeWixClient:
        def list_tickets(self, *, event_id: str, limit: int = 500):
            return [{"ticket_number": ticket_number, "checked_in": True, "checked_in_at": "2026-05-30T10:00:00Z"}]

        def check_in_ticket(self, **kwargs):
            raise RuntimeError("not used")

    import app.services.reconciliation as reconciliation_module

    monkeypatch.setattr(reconciliation_module, "get_wix_client", lambda: FakeWixClient())

    response = client.post(f"/api/admin/events/{event_id}/reconciliation/run", json={"actor": "qa-user"})

    assert response.status_code == 200
    body = response.json()
    assert body["run"]["reconciliation_state"] == "wix_only"

    local_ticket = manifest.get_ticket(event_id=event_id, ticket_number=ticket_number)
    assert local_ticket is not None
    assert local_ticket.manifest_state == "checked_in"


def test_reconciliation_conflict_console_and_manual_override(reconciliation_client, monkeypatch):
    client = reconciliation_client["client"]
    manifest = reconciliation_client["manifest"]
    event_id = "event-conflict-01"
    ticket_number = "CONFLICT-01"

    manifest.mark_checked_in(event_id=event_id, ticket_number=ticket_number)

    class FakeWixClient:
        def list_tickets(self, *, event_id: str, limit: int = 500):
            return [{"ticket_number": ticket_number, "checked_in": True, "checked_in_at": "2020-01-01T00:00:00Z"}]

        def check_in_ticket(self, **kwargs):
            raise RuntimeError("not used")

    import app.services.reconciliation as reconciliation_module

    monkeypatch.setattr(reconciliation_module, "get_wix_client", lambda: FakeWixClient())

    run_response = client.post(f"/api/admin/events/{event_id}/reconciliation/run", json={"actor": "qa-user"})
    assert run_response.status_code == 200
    run_body = run_response.json()
    assert run_body["run"]["reconciliation_state"] == "conflict"

    conflict_list = client.get(f"/api/admin/events/{event_id}/reconciliation/conflicts")
    assert conflict_list.status_code == 200
    conflicts = conflict_list.json()
    assert len(conflicts) == 1
    item_id = conflicts[0]["item_id"]

    resolved = client.post(
        f"/api/admin/reconciliation/items/{item_id}/resolve",
        json={"actor": "manager-user", "resolution": "accept_wix", "note": "Reviewed with lead"},
    )
    assert resolved.status_code == 200
    resolved_body = resolved.json()
    assert resolved_body["reconciliation_state"] == "in_sync"
    assert resolved_body["resolution_result"] == "manual_accept_wix"
    assert resolved_body["resolved_by_actor"] == "manager-user"

    ticket = manifest.get_ticket(event_id=event_id, ticket_number=ticket_number)
    assert ticket is not None
    assert ticket.manifest_state == "checked_in"