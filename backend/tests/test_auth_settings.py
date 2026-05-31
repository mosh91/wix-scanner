from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services.auth_settings import ApiKeyValidationRecord, AuthSettingsService, set_auth_settings_service
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
        "auth_settings_db": auth_settings_db,
        "auth_service": auth_service,
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


def test_api_key_save_persists_encrypted_settings_and_audit(auth_settings_client):
    client = auth_settings_client["client"]
    auth_settings_db = auth_settings_client["auth_settings_db"]

    response = client.put(
        "/api/admin/auth-settings/api-key",
        json={
            "api_key": "wix-api-key-123456",
            "wix_account_id": "acct-123",
            "actor": "operator-ui",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["api_key_configured"] is True
    assert body["wix_account_id"] == "acct-123"
    assert body["last_rotated_at"] is not None
    assert body["last_validated_at"] is not None

    with sqlite3.connect(auth_settings_db) as connection:
        row = connection.execute(
            "SELECT encrypted_api_key, encrypted_wix_account_id FROM auth_api_key_settings WHERE settings_key = ?",
            ("primary",),
        ).fetchone()
        audit_row = connection.execute(
            "SELECT action, outcome FROM auth_api_key_audit WHERE action = ? ORDER BY occurred_at DESC LIMIT 1",
            ("save",),
        ).fetchone()
    assert row is not None
    assert row[0] != "wix-api-key-123456"
    assert row[1] != "acct-123"
    assert audit_row == ("save", "success")


def test_api_key_save_rejects_failed_validation(auth_settings_client, monkeypatch):
    client = auth_settings_client["client"]
    auth_service = auth_settings_client["auth_service"]

    def _fail_test_api_key_connection(**_: object) -> ApiKeyValidationRecord:
        return ApiKeyValidationRecord(
            ok=False,
            message="Connection test failed with status 401.",
            tested_at="2026-01-01T00:00:00Z",
            wix_account_id="acct-999",
        )

    monkeypatch.setattr(auth_service, "_test_api_key_connection", _fail_test_api_key_connection)

    response = client.put(
        "/api/admin/auth-settings/api-key",
        json={
            "api_key": "wix-api-key-invalid",
            "wix_account_id": "acct-999",
            "actor": "operator-ui",
        },
    )
    assert response.status_code == 422
    assert "Connection test failed" in response.json()["detail"]
