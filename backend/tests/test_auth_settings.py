from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services.auth_settings import AuthSettingsService, set_auth_settings_service
from app.services.credential_lifecycle import CredentialLifecycleService


@pytest.fixture
def auth_settings_client(backend_client, temp_db_dir, monkeypatch):
    settings = get_settings()
    credential_db = Path(temp_db_dir) / "credential_lifecycle.db"
    auth_settings_db = Path(temp_db_dir) / "auth_settings.db"

    credential_service = CredentialLifecycleService(settings=settings, db_path=str(credential_db))
    import app.services.credential_lifecycle as credential_module

    monkeypatch.setattr(credential_module, "_service_instance", credential_service)

    auth_service = AuthSettingsService(settings=settings, db_path=str(auth_settings_db))
    set_auth_settings_service(auth_service)

    yield {
        "client": backend_client,
        "credential_service": credential_service,
    }

    set_auth_settings_service(None)


def _create_active_oauth_credential(credential_service: CredentialLifecycleService):
    created = credential_service.create_credential(
        profile_name="oauth-main",
        auth_mode="oauth",
        actor="admin",
        expires_at="2030-01-01T00:00:00Z",
    )
    validated = credential_service.validate_credential(created.credential_id, actor="admin")
    assert validated.lifecycle_state == "validated"
    activated = credential_service.activate_credential(created.credential_id, actor="admin")
    assert activated.lifecycle_state in {"active", "expiring_soon"}
    return activated


def test_token_mode_screen_returns_metadata_without_token_value(auth_settings_client):
    client = auth_settings_client["client"]
    credential_service = auth_settings_client["credential_service"]

    _create_active_oauth_credential(credential_service)

    response = client.get("/api/admin/auth-settings/token")
    assert response.status_code == 200
    body = response.json()
    assert body["auth_mode"] in {"oauth", "api_key"}
    assert body["token_status"] in {"healthy", "expiring_soon", "expired", "invalid", "missing", "unknown"}
    assert "token" not in body
    assert "api_token" not in body


def test_manual_refresh_updates_status_and_expiry(auth_settings_client):
    client = auth_settings_client["client"]
    credential_service = auth_settings_client["credential_service"]

    active = _create_active_oauth_credential(credential_service)
    before = client.get("/api/admin/auth-settings/token").json()

    refresh = client.post("/api/admin/auth-settings/token/refresh", json={"actor": "security-admin"})
    assert refresh.status_code == 200
    after = refresh.json()

    assert after["credential_id"] == active.credential_id
    assert after["last_refresh_at"] is not None
    assert after["expires_at"] is not None
    assert after["expires_at"] != before["expires_at"]


def test_connection_failure_returns_actionable_error(auth_settings_client):
    client = auth_settings_client["client"]

    response = client.post("/api/admin/auth-settings/token/test-connection", json={"actor": "operator-ui"})
    assert response.status_code == 422
    assert "No active OAuth credential" in response.json()["detail"]
