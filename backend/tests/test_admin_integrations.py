from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services.credential_lifecycle import CredentialLifecycleService
from app.services.site_event_binding import SiteEventBindingService, WixBindingVerifier, set_site_event_binding_service
from app.services.ticket_manifest import TicketManifestService
from app.services.wix_scope_audit import WixScopeAuditService, set_wix_scope_audit_service
from app.services.worker_health import WorkerHealthService


@pytest.fixture
def admin_client(backend_client, temp_db_dir, monkeypatch):
    monkeypatch.setenv("WIX_SCANNER_WIX_MOCK_MODE", "true")
    get_settings.cache_clear()
    settings = get_settings()
    binding_db = Path(temp_db_dir) / "site_event_bindings.db"
    credential_db = Path(temp_db_dir) / "credential_lifecycle.db"
    manifest_db = Path(temp_db_dir) / "ticket_manifest.db"

    service = SiteEventBindingService(db_path=str(binding_db), verifier=WixBindingVerifier(settings))
    set_site_event_binding_service(service)

    credential_service = CredentialLifecycleService(settings=settings, db_path=str(credential_db))
    import app.services.credential_lifecycle as credential_module
    monkeypatch.setattr(credential_module, "_service_instance", credential_service)

    scope_service = WixScopeAuditService(settings=settings, binding_service=service, db_path=str(binding_db))
    set_wix_scope_audit_service(scope_service)

    manifest_service = TicketManifestService(database_file=manifest_db)
    import app.services.ticket_manifest as manifest_module
    monkeypatch.setattr(manifest_module, "_manifest_service", manifest_service)

    worker_health = WorkerHealthService()
    worker_health.pulse("offline_queue_worker")
    worker_health.pulse("manifest_sync_worker")
    import app.services.worker_health as worker_module
    monkeypatch.setattr(worker_module, "_worker_health_service", worker_health)

    import app.services.event_readiness as readiness_module
    monkeypatch.setattr(readiness_module, "_event_readiness_service", None)

    return backend_client


def test_autobind_integrations_seeds_events_and_bindings(admin_client):
    response = admin_client.post(
        "/api/admin/integrations/autobind",
        json={"actor": "operator-ui"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["site_id"] == "site-demo-01"
    assert body["site_display_name"] == "Demo Site"
    assert body["events_found"] == 2
    assert body["events_imported"] == 2
    assert body["bindings_created"] == 2
    assert body["bindings_verified"] == 2
    assert body["existing_bindings"] == 0
    assert body["event_ids"] == ["event-demo-01", "event-demo-02"]
    assert len(body["binding_ids"]) == 2

    events_response = admin_client.get("/api/admin/events")
    assert events_response.status_code == 200
    events = events_response.json()
    assert {item["wix_event_id"] for item in events} >= {"event-demo-01", "event-demo-02"}

    bindings_response = admin_client.get("/api/admin/site-event-bindings")
    assert bindings_response.status_code == 200
    bindings = bindings_response.json()
    assert {item["wix_event_id"] for item in bindings} >= {"event-demo-01", "event-demo-02"}


def test_autobind_integrations_reuses_existing_bindings(admin_client):
    first = admin_client.post(
        "/api/admin/integrations/autobind",
        json={"actor": "operator-ui"},
    )
    assert first.status_code == 200

    second = admin_client.post(
        "/api/admin/integrations/autobind",
        json={"actor": "operator-ui"},
    )

    assert second.status_code == 200
    body = second.json()
    assert body["events_found"] == 2
    assert body["events_imported"] == 0
    assert body["bindings_created"] == 0
    assert body["bindings_verified"] == 2
    assert body["existing_bindings"] == 2