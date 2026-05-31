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


def test_create_binding_starts_pending_or_verified(admin_client):
    response = admin_client.post(
        "/api/admin/site-event-bindings",
        json={
            "wix_site_id": "site-main-01",
            "wix_event_id": "event-main-01",
            "actor": "admin-user",
            "verify_immediately": True,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["wix_site_id"] == "site-main-01"
    assert body["wix_event_id"] == "event-main-01"
    assert body["status"] == "verified"
    assert body["app_installation_status"] == "installed"
    assert body["binding_verified_at"] is not None
    assert body["verified_by_actor"] == "admin-user"


def test_create_binding_app_not_installed_stays_pending(admin_client):
    response = admin_client.post(
        "/api/admin/site-event-bindings",
        json={
            "wix_site_id": "site-main-noapp",
            "wix_event_id": "event-main-02",
            "actor": "admin-user",
            "verify_immediately": True,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["app_installation_status"] == "uninstalled"
    assert body["last_verification_error"] == "Wix app not installed on site."


def test_verify_binding_transitions_and_stores_actor(admin_client):
    create_response = admin_client.post(
        "/api/admin/site-event-bindings",
        json={
            "wix_site_id": "site-secondary-01",
            "wix_event_id": "event-secondary-01",
            "actor": "creator",
            "verify_immediately": False,
        },
    )
    binding_id = create_response.json()["binding_id"]

    verify_response = admin_client.post(
        f"/api/admin/site-event-bindings/{binding_id}/verify",
        json={"actor": "verifier-user"},
    )

    assert verify_response.status_code == 200
    body = verify_response.json()
    assert body["status"] == "verified"
    assert body["verified_by_actor"] == "verifier-user"
    assert body["verification_evidence"]["checked_by_actor"] == "verifier-user"


def test_event_activation_rejected_without_verified_binding(admin_client):
    admin_client.post(
        "/api/admin/site-event-bindings",
        json={
            "wix_site_id": "badsite",
            "wix_event_id": "event-missing-01",
            "actor": "admin-user",
            "verify_immediately": True,
        },
    )

    response = admin_client.post(
        "/api/admin/events/event-missing-01/activate",
        json={"actor": "admin-user"},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["message"].lower().startswith("event activation blocked")
    assert "binding" in detail["failed_checks"]


def test_event_activation_allowed_with_verified_binding(admin_client):
    binding_response = admin_client.post(
        "/api/admin/site-event-bindings",
        json={
            "wix_site_id": "site-activation-01",
            "wix_event_id": "event-activation-01",
            "actor": "admin-user",
            "verify_immediately": True,
        },
    )
    binding_id = binding_response.json()["binding_id"]

    credential_response = admin_client.post(
        "/api/admin/credentials",
        json={"profile_name": "activation-cred", "auth_mode": "oauth", "actor": "admin-user"},
    )
    credential_id = credential_response.json()["credential_id"]
    admin_client.post(f"/api/admin/credentials/{credential_id}/validate", json={"actor": "admin-user"})
    admin_client.post(f"/api/admin/credentials/{credential_id}/activate", json={"actor": "admin-user"})

    admin_client.post(
        f"/api/admin/site-event-bindings/{binding_id}/scopes/verify",
        json={"actor": "security-admin"},
    )

    admin_client.post("/api/manifest/sync", json={"event_id": "event-activation-01"})

    response = admin_client.post(
        "/api/admin/events/event-activation-01/activate",
        json={"actor": "admin-user", "readiness_acknowledged": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["wix_event_id"] == "event-activation-01"
    assert body["status"] == "active"
    assert body["activated_by_actor"] == "admin-user"
    assert body["readiness_status"] == "ready"


def test_list_verified_events_returns_only_verified(admin_client):
    admin_client.post(
        "/api/admin/site-event-bindings",
        json={
            "wix_site_id": "site-verified-01",
            "wix_event_id": "event-verified-01",
            "actor": "admin-user",
            "verify_immediately": True,
        },
    )
    admin_client.post(
        "/api/admin/site-event-bindings",
        json={
            "wix_site_id": "site-pending-noapp",
            "wix_event_id": "event-pending-01",
            "actor": "admin-user",
            "verify_immediately": True,
        },
    )

    response = admin_client.get("/api/admin/events")

    assert response.status_code == 200
    events = response.json()
    assert any(item["wix_event_id"] == "event-verified-01" for item in events)
    assert all(item["wix_event_id"] != "event-pending-01" for item in events)
