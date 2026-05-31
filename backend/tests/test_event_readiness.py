from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services.credential_lifecycle import CredentialLifecycleService
from app.services.site_event_binding import SiteEventBindingService, WixBindingVerifier, set_site_event_binding_service
from app.services.ticket_manifest import TicketManifestService
from app.services.wix_scope_audit import WixScopeAuditService, set_wix_scope_audit_service
from app.services.worker_health import WorkerHealthService


@pytest.fixture
def readiness_client(backend_client, temp_db_dir, monkeypatch):
    settings = get_settings()
    binding_db = Path(temp_db_dir) / "site_event_bindings.db"
    credential_db = Path(temp_db_dir) / "credential_lifecycle.db"
    manifest_db = Path(temp_db_dir) / "ticket_manifest.db"

    binding_service = SiteEventBindingService(db_path=str(binding_db), verifier=WixBindingVerifier(settings))
    set_site_event_binding_service(binding_service)

    credential_service = CredentialLifecycleService(settings=settings, db_path=str(credential_db))
    import app.services.credential_lifecycle as credential_module

    monkeypatch.setattr(credential_module, "_service_instance", credential_service)

    scope_service = WixScopeAuditService(settings=settings, binding_service=binding_service, db_path=str(binding_db))
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

    return client_with_services(backend_client, binding_service, credential_service)



def client_with_services(client, binding_service, credential_service):
    return {
        "client": client,
        "binding_service": binding_service,
        "credential_service": credential_service,
    }



def _prime_event(client, event_id: str, site_id: str = "site-readiness-01") -> dict[str, object]:
    binding_response = client.post(
        "/api/admin/site-event-bindings",
        json={
            "wix_site_id": site_id,
            "wix_event_id": event_id,
            "actor": "admin-user",
            "verify_immediately": True,
        },
    )
    assert binding_response.status_code == 201
    binding = binding_response.json()

    scope_response = client.post(
        f"/api/admin/site-event-bindings/{binding['binding_id']}/scopes/verify",
        json={"actor": "security-admin"},
    )
    assert scope_response.status_code == 200

    sync_response = client.post("/api/manifest/sync", json={"event_id": event_id})
    assert sync_response.status_code == 200

    return binding



def test_event_readiness_is_ready_when_all_dependencies_are_healthy(readiness_client):
    client = readiness_client["client"]
    credential_service = readiness_client["credential_service"]
    event_id = "event-readiness-ready"

    _prime_event(client, event_id)

    credential = credential_service.create_credential(profile_name="readiness-cred", auth_mode="oauth", actor="admin")
    credential_service.validate_credential(credential.credential_id, actor="admin")
    credential_service.activate_credential(credential.credential_id, actor="admin")

    response = client.get(f"/api/admin/events/{event_id}/readiness")
    assert response.status_code == 200
    body = response.json()
    assert body["overall_status"] == "ready"
    assert body["failed_checks"] == []
    assert any(component["status"] == "ready" for component in body["component_statuses"])



def test_event_readiness_degrades_for_expiring_credentials_and_requires_acknowledgement(readiness_client):
    client = readiness_client["client"]
    credential_service = readiness_client["credential_service"]
    event_id = "event-readiness-degraded"

    _prime_event(client, event_id, site_id="site-readiness-degraded")

    expires_soon = (datetime.now(UTC) + timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
    credential = credential_service.create_credential(
        profile_name="expiring-cred",
        auth_mode="oauth",
        actor="admin",
        expires_at=expires_soon,
    )
    credential_service.validate_credential(credential.credential_id, actor="admin")
    credential_service.activate_credential(credential.credential_id, actor="admin")

    readiness = client.get(f"/api/admin/events/{event_id}/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["overall_status"] == "degraded"

    blocked = client.post(
        f"/api/admin/events/{event_id}/activate",
        json={"actor": "admin-user", "readiness_acknowledged": False},
    )
    assert blocked.status_code == 409
    assert "acknowledged" in blocked.json()["detail"]["message"].lower()

    allowed = client.post(
        f"/api/admin/events/{event_id}/activate",
        json={"actor": "admin-user", "readiness_acknowledged": True},
    )
    assert allowed.status_code == 200
    assert allowed.json()["readiness_status"] == "degraded"
    assert allowed.json()["readiness_acknowledged"] is True



def test_event_readiness_is_critical_when_binding_is_missing(readiness_client):
    client = readiness_client["client"]

    response = client.get("/api/admin/events/event-missing-binding/readiness")
    assert response.status_code == 200
    body = response.json()
    assert body["overall_status"] == "critical"
    assert "binding" in body["failed_checks"]