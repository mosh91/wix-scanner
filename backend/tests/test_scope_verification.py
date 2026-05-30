from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services.site_event_binding import SiteEventBindingService, WixBindingVerifier, set_site_event_binding_service
from app.services.wix_scope_audit import WixScopeAuditService, set_wix_scope_audit_service


@pytest.fixture
def admin_scope_client(backend_client, temp_db_dir):
    settings = get_settings()
    binding_db = Path(temp_db_dir) / "site_event_bindings.db"

    binding_service = SiteEventBindingService(db_path=str(binding_db), verifier=WixBindingVerifier(settings))
    set_site_event_binding_service(binding_service)

    scope_service = WixScopeAuditService(
        settings=settings,
        binding_service=binding_service,
        db_path=str(binding_db),
    )
    set_wix_scope_audit_service(scope_service)

    return backend_client, binding_db


def _create_binding(client, wix_site_id: str, wix_event_id: str, verify_immediately: bool = True) -> dict[str, object]:
    response = client.post(
        "/api/admin/site-event-bindings",
        json={
            "wix_site_id": wix_site_id,
            "wix_event_id": wix_event_id,
            "actor": "admin-user",
            "verify_immediately": verify_immediately,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_scope_verification_green_when_permissions_complete(admin_scope_client):
    client, _ = admin_scope_client
    binding = _create_binding(client, "site-scope-green-01", "event-scope-green-01", verify_immediately=True)

    verify = client.post(
        f"/api/admin/site-event-bindings/{binding['binding_id']}/scopes/verify",
        json={"actor": "security-admin"},
    )

    assert verify.status_code == 200
    body = verify.json()
    assert body["status"] == "green"
    assert body["missing_scopes"] == []
    assert sorted(body["required_scopes"]) == [
        "WIX_EVENTS.CHECK-IN",
        "WIX_EVENTS.READ_EVENTS",
        "WIX_EVENTS.READ_TICKETS",
    ]


def test_scope_verification_warning_when_scope_missing(admin_scope_client):
    client, _ = admin_scope_client
    binding = _create_binding(client, "site-scope-missing-scopes", "event-scope-warn-01", verify_immediately=True)

    verify = client.post(
        f"/api/admin/site-event-bindings/{binding['binding_id']}/scopes/verify",
        json={"actor": "security-admin"},
    )

    assert verify.status_code == 200
    body = verify.json()
    assert body["status"] == "warning"
    assert "WIX_EVENTS.READ_TICKETS" in body["missing_scopes"]
    assert body["alert_reason"] is not None


def test_scope_reverification_transitions_warning_to_green(admin_scope_client):
    client, binding_db = admin_scope_client
    binding = _create_binding(client, "site-reverify-missing-scopes", "event-reverify-01", verify_immediately=True)

    first_verify = client.post(
        f"/api/admin/site-event-bindings/{binding['binding_id']}/scopes/verify",
        json={"actor": "security-admin"},
    )
    assert first_verify.status_code == 200
    assert first_verify.json()["status"] == "warning"

    with sqlite3.connect(binding_db) as conn:
        conn.execute(
            "UPDATE wix_site_event_binding SET wix_site_id = ? WHERE binding_id = ?",
            ("site-reverify-fixed-01", binding["binding_id"]),
        )
        conn.commit()

    second_verify = client.post(
        f"/api/admin/site-event-bindings/{binding['binding_id']}/scopes/verify",
        json={"actor": "security-admin"},
    )
    assert second_verify.status_code == 200
    assert second_verify.json()["status"] == "green"

    latest = client.get("/api/admin/scopes/latest")
    assert latest.status_code == 200
    rows = latest.json()
    target = next(row for row in rows if row["binding_id"] == binding["binding_id"])
    assert target["status"] == "green"


def test_scope_verification_blocked_if_binding_unverified(admin_scope_client):
    client, _ = admin_scope_client
    binding = _create_binding(client, "badsite", "event-unverified-01", verify_immediately=True)
    assert binding["status"] == "unverified"

    verify = client.post(
        f"/api/admin/site-event-bindings/{binding['binding_id']}/scopes/verify",
        json={"actor": "security-admin"},
    )

    assert verify.status_code == 409
    assert "verified site-event binding" in verify.json()["detail"]
