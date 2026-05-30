from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.services.credential_lifecycle import (
    AUTH_STRATEGY,
    CredentialLifecycleService,
    get_credential_lifecycle_service,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_settings(tmp_path: Path) -> Settings:
    return Settings(
        wix_mock_mode=True,
        credential_lifecycle_db_path=str(tmp_path / "cred_lifecycle.db"),
        environment="development",
        auth_mode="api_key",
        credential_expiry_warning_hours=24,
    )


@pytest.fixture
def prod_settings(tmp_path: Path) -> Settings:
    return Settings(
        wix_mock_mode=True,
        credential_lifecycle_db_path=str(tmp_path / "cred_lifecycle_prod.db"),
        environment="production",
        auth_mode="oauth",
        credential_expiry_warning_hours=24,
    )


@pytest.fixture
def lifecycle_service(mock_settings: Settings) -> CredentialLifecycleService:
    return CredentialLifecycleService(
        settings=mock_settings,
        db_path=mock_settings.credential_lifecycle_db_path,
    )


@pytest.fixture
def prod_lifecycle_service(prod_settings: Settings) -> CredentialLifecycleService:
    return CredentialLifecycleService(
        settings=prod_settings,
        db_path=prod_settings.credential_lifecycle_db_path,
    )


# ---------------------------------------------------------------------------
# AC1: Auth-strategy decision table is documented
# ---------------------------------------------------------------------------


def test_auth_strategy_contains_all_endpoint_types(lifecycle_service: CredentialLifecycleService) -> None:
    strategy = lifecycle_service.get_auth_strategy()
    for endpoint in ("check_in", "ticket_read", "event_read", "sync"):
        assert endpoint in strategy, f"Missing endpoint type: {endpoint}"


def test_auth_strategy_production_uses_oauth(lifecycle_service: CredentialLifecycleService) -> None:
    strategy = lifecycle_service.get_auth_strategy()
    for endpoint, config in strategy.items():
        assert config["production_mode"] == "oauth", (
            f"Endpoint '{endpoint}' must use oauth in production"
        )


def test_auth_strategy_staging_allows_api_key(lifecycle_service: CredentialLifecycleService) -> None:
    strategy = lifecycle_service.get_auth_strategy()
    for endpoint, config in strategy.items():
        assert config["staging_mode"] == "api_key", (
            f"Endpoint '{endpoint}' must allow api_key in staging"
        )


# ---------------------------------------------------------------------------
# AC2: Credential created → validated when API calls succeed
# ---------------------------------------------------------------------------


def test_credential_create_sets_state_created(lifecycle_service: CredentialLifecycleService) -> None:
    record = lifecycle_service.create_credential(
        profile_name="test-profile",
        auth_mode="api_key",
        actor="test-actor",
    )
    assert record.lifecycle_state == "created"
    assert record.auth_mode == "api_key"
    assert record.profile_name == "test-profile"
    assert record.created_by_actor == "test-actor"


def test_validate_credential_transitions_to_validated_on_success(lifecycle_service: CredentialLifecycleService) -> None:
    record = lifecycle_service.create_credential(
        profile_name="valid-profile",
        auth_mode="api_key",
        actor="test-actor",
    )
    validated = lifecycle_service.validate_credential(record.credential_id, actor="test-actor")
    assert validated.lifecycle_state == "validated"
    assert validated.validated_at is not None
    assert validated.last_validated_at is not None
    assert validated.validation_error is None


def test_validate_credential_with_fail_prefix_transitions_to_failed(lifecycle_service: CredentialLifecycleService) -> None:
    """Mock mode: credential IDs starting with 'cred-fail-' always fail validation."""
    # We need to insert a record with a specific ID prefix to test mock fail behavior.
    # First create normally, then we modify the credential_id in the DB.
    import sqlite3

    record = lifecycle_service.create_credential(
        profile_name="fail-profile",
        auth_mode="api_key",
        actor="test-actor",
    )
    # Override the credential_id to trigger mock failure
    fail_id = f"cred-fail-{record.credential_id}"
    with sqlite3.connect(lifecycle_service._db_path) as conn:
        conn.execute(
            "UPDATE credential_lifecycle SET credential_id = ? WHERE credential_id = ?",
            (fail_id, record.credential_id),
        )
        conn.execute(
            "UPDATE credential_lifecycle_events SET credential_id = ? WHERE credential_id = ?",
            (fail_id, record.credential_id),
        )
        conn.commit()

    failed = lifecycle_service.validate_credential(fail_id, actor="test-actor")
    assert failed.lifecycle_state == "failed"
    assert failed.validation_error is not None


def test_validate_credential_emits_lifecycle_event(lifecycle_service: CredentialLifecycleService) -> None:
    record = lifecycle_service.create_credential(
        profile_name="event-profile",
        auth_mode="oauth",
        actor="test-actor",
    )
    lifecycle_service.validate_credential(record.credential_id, actor="test-actor")
    events = lifecycle_service.list_events(record.credential_id)
    event_states = [(e.from_state, e.to_state) for e in events]
    assert (None, "created") in event_states
    assert any(e.to_state == "validated" for e in events)


# ---------------------------------------------------------------------------
# AC3: Active credential approaching expiry → transitions to expiring_soon
# ---------------------------------------------------------------------------


def test_check_expiry_transitions_to_expiring_soon_when_within_window(lifecycle_service: CredentialLifecycleService) -> None:
    # Create a credential that expires in 12 hours (within the 24h window)
    expires_in_12h = (datetime.now(UTC) + timedelta(hours=12)).isoformat().replace("+00:00", "Z")
    record = lifecycle_service.create_credential(
        profile_name="expiring-profile",
        auth_mode="api_key",
        actor="test-actor",
        expires_at=expires_in_12h,
    )
    record = lifecycle_service.validate_credential(record.credential_id, actor="test-actor")
    record = lifecycle_service.activate_credential(record.credential_id, actor="test-actor")
    assert record.lifecycle_state == "active"

    checked = lifecycle_service.check_expiry(record.credential_id, warning_hours=24)
    assert checked.lifecycle_state == "expiring_soon"


def test_check_expiry_does_not_transition_if_not_within_window(lifecycle_service: CredentialLifecycleService) -> None:
    # Expires in 48 hours — outside the 24h warning window
    expires_in_48h = (datetime.now(UTC) + timedelta(hours=48)).isoformat().replace("+00:00", "Z")
    record = lifecycle_service.create_credential(
        profile_name="safe-profile",
        auth_mode="api_key",
        actor="test-actor",
        expires_at=expires_in_48h,
    )
    record = lifecycle_service.validate_credential(record.credential_id, actor="test-actor")
    record = lifecycle_service.activate_credential(record.credential_id, actor="test-actor")

    checked = lifecycle_service.check_expiry(record.credential_id, warning_hours=24)
    assert checked.lifecycle_state == "active"


def test_check_expiry_no_op_if_no_expiry_set(lifecycle_service: CredentialLifecycleService) -> None:
    record = lifecycle_service.create_credential(
        profile_name="no-expiry-profile",
        auth_mode="api_key",
        actor="test-actor",
    )
    record = lifecycle_service.validate_credential(record.credential_id, actor="test-actor")
    record = lifecycle_service.activate_credential(record.credential_id, actor="test-actor")

    checked = lifecycle_service.check_expiry(record.credential_id, warning_hours=24)
    assert checked.lifecycle_state == "active"


# ---------------------------------------------------------------------------
# AC4: expiring_soon credential → rotate → new active, old revoked
# ---------------------------------------------------------------------------


def test_rotate_credential_issues_new_and_revokes_old(lifecycle_service: CredentialLifecycleService) -> None:
    expires_soon = (datetime.now(UTC) + timedelta(hours=6)).isoformat().replace("+00:00", "Z")
    old_record = lifecycle_service.create_credential(
        profile_name="old-profile",
        auth_mode="api_key",
        actor="test-actor",
        expires_at=expires_soon,
    )
    old_record = lifecycle_service.validate_credential(old_record.credential_id, actor="test-actor")
    old_record = lifecycle_service.activate_credential(old_record.credential_id, actor="test-actor")
    old_record = lifecycle_service.check_expiry(old_record.credential_id, warning_hours=24)
    assert old_record.lifecycle_state == "expiring_soon"

    new_record, revoked = lifecycle_service.rotate_credential(
        old_record.credential_id,
        new_profile_name="new-profile",
        new_auth_mode="api_key",
        actor="test-actor",
    )

    assert new_record.lifecycle_state == "active"
    assert revoked.lifecycle_state == "revoked"
    assert revoked.credential_id == old_record.credential_id
    assert new_record.credential_id != old_record.credential_id


def test_rotate_credential_emits_revoke_event_on_old(lifecycle_service: CredentialLifecycleService) -> None:
    old_record = lifecycle_service.create_credential(
        profile_name="rotate-old",
        auth_mode="api_key",
        actor="test-actor",
    )
    old_record = lifecycle_service.validate_credential(old_record.credential_id, actor="test-actor")
    old_record = lifecycle_service.activate_credential(old_record.credential_id, actor="test-actor")

    lifecycle_service.rotate_credential(
        old_record.credential_id,
        new_profile_name="rotate-new",
        new_auth_mode="api_key",
        actor="test-actor",
    )

    events = lifecycle_service.list_events(old_record.credential_id)
    assert any(e.to_state == "revoked" for e in events)


# ---------------------------------------------------------------------------
# AC5: Mixed auth modes in production → rejected
# ---------------------------------------------------------------------------


def test_validate_no_mixed_modes_passes_for_single_auth_mode(prod_lifecycle_service: CredentialLifecycleService) -> None:
    # All active credentials use oauth → should pass
    r = prod_lifecycle_service.create_credential(
        profile_name="prod-cred-1", auth_mode="oauth", actor="admin"
    )
    r = prod_lifecycle_service.validate_credential(r.credential_id, actor="admin")
    prod_lifecycle_service.activate_credential(r.credential_id, actor="admin")

    # Should not raise
    prod_lifecycle_service.validate_no_mixed_modes("production")


def test_validate_no_mixed_modes_raises_for_mixed_auth_modes_in_production(prod_lifecycle_service: CredentialLifecycleService) -> None:
    # Create one oauth credential (active) and one api_key credential (active)
    r1 = prod_lifecycle_service.create_credential(
        profile_name="prod-oauth", auth_mode="oauth", actor="admin"
    )
    r1 = prod_lifecycle_service.validate_credential(r1.credential_id, actor="admin")
    prod_lifecycle_service.activate_credential(r1.credential_id, actor="admin")

    r2 = prod_lifecycle_service.create_credential(
        profile_name="prod-apikey", auth_mode="api_key", actor="admin"
    )
    r2 = prod_lifecycle_service.validate_credential(r2.credential_id, actor="admin")
    prod_lifecycle_service.activate_credential(r2.credential_id, actor="admin")

    with pytest.raises(ValueError, match="mixed auth modes"):
        prod_lifecycle_service.validate_no_mixed_modes("production")


def test_validate_no_mixed_modes_passes_for_non_production(lifecycle_service: CredentialLifecycleService) -> None:
    # Non-production environments can mix modes
    r1 = lifecycle_service.create_credential(
        profile_name="dev-oauth", auth_mode="oauth", actor="admin"
    )
    r1 = lifecycle_service.validate_credential(r1.credential_id, actor="admin")
    lifecycle_service.activate_credential(r1.credential_id, actor="admin")

    r2 = lifecycle_service.create_credential(
        profile_name="dev-apikey", auth_mode="api_key", actor="admin"
    )
    r2 = lifecycle_service.validate_credential(r2.credential_id, actor="admin")
    lifecycle_service.activate_credential(r2.credential_id, actor="admin")

    # Should not raise in development
    lifecycle_service.validate_no_mixed_modes("development")


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """API test client with isolated credential lifecycle service."""
    import app.api.routes.admin_credentials as admin_creds_module
    import app.services.credential_lifecycle as lifecycle_module

    test_settings = Settings(
        wix_mock_mode=True,
        credential_lifecycle_db_path=str(tmp_path / "api_test_cred.db"),
        environment="development",
        auth_mode="api_key",
        credential_expiry_warning_hours=24,
    )
    svc = CredentialLifecycleService(
        settings=test_settings,
        db_path=test_settings.credential_lifecycle_db_path,
    )
    monkeypatch.setattr(lifecycle_module, "_service_instance", svc)

    from fastapi.testclient import TestClient
    from app.main import app

    return TestClient(app)


def test_api_create_credential(api_client: TestClient) -> None:
    resp = api_client.post(
        "/api/admin/credentials",
        json={"profile_name": "api-profile", "auth_mode": "api_key", "actor": "test"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["lifecycle_state"] == "created"
    assert data["auth_mode"] == "api_key"


def test_api_validate_and_activate_credential(api_client: TestClient) -> None:
    create_resp = api_client.post(
        "/api/admin/credentials",
        json={"profile_name": "api-profile", "auth_mode": "oauth", "actor": "test"},
    )
    cred_id = create_resp.json()["credential_id"]

    validate_resp = api_client.post(
        f"/api/admin/credentials/{cred_id}/validate",
        json={"actor": "test"},
    )
    assert validate_resp.status_code == 200
    assert validate_resp.json()["lifecycle_state"] == "validated"

    activate_resp = api_client.post(
        f"/api/admin/credentials/{cred_id}/activate",
        json={"actor": "test"},
    )
    assert activate_resp.status_code == 200
    assert activate_resp.json()["lifecycle_state"] == "active"


def test_api_list_credentials(api_client: TestClient) -> None:
    api_client.post(
        "/api/admin/credentials",
        json={"profile_name": "list-profile", "auth_mode": "api_key", "actor": "test"},
    )
    resp = api_client.get("/api/admin/credentials")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


def test_api_get_credential_not_found(api_client: TestClient) -> None:
    resp = api_client.get("/api/admin/credentials/nonexistent-id")
    assert resp.status_code == 404


def test_api_auth_strategy_decision_table(api_client: TestClient) -> None:
    resp = api_client.get("/api/admin/credentials/auth-strategy/decision-table")
    assert resp.status_code == 200
    data = resp.json()
    assert "strategy" in data
    assert "check_in" in data["strategy"]
    assert data["strategy"]["check_in"]["production_mode"] == "oauth"


def test_api_revoke_credential(api_client: TestClient) -> None:
    create_resp = api_client.post(
        "/api/admin/credentials",
        json={"profile_name": "revoke-profile", "auth_mode": "api_key", "actor": "test"},
    )
    cred_id = create_resp.json()["credential_id"]
    revoke_resp = api_client.post(
        f"/api/admin/credentials/{cred_id}/revoke",
        json={"actor": "admin", "note": "manual revocation"},
    )
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["lifecycle_state"] == "revoked"


def test_api_rotate_credential(api_client: TestClient) -> None:
    # Create, validate, activate an old credential
    create_resp = api_client.post(
        "/api/admin/credentials",
        json={"profile_name": "old-cred", "auth_mode": "api_key", "actor": "test"},
    )
    cred_id = create_resp.json()["credential_id"]
    api_client.post(f"/api/admin/credentials/{cred_id}/validate", json={"actor": "test"})
    api_client.post(f"/api/admin/credentials/{cred_id}/activate", json={"actor": "test"})

    rotate_resp = api_client.post(
        f"/api/admin/credentials/{cred_id}/rotate",
        json={"new_profile_name": "new-cred", "new_auth_mode": "api_key", "actor": "test"},
    )
    assert rotate_resp.status_code == 200
    data = rotate_resp.json()
    assert data["new_credential"]["lifecycle_state"] == "active"
    assert data["revoked_credential"]["lifecycle_state"] == "revoked"


def test_api_list_credential_events(api_client: TestClient) -> None:
    create_resp = api_client.post(
        "/api/admin/credentials",
        json={"profile_name": "events-profile", "auth_mode": "api_key", "actor": "test"},
    )
    cred_id = create_resp.json()["credential_id"]
    api_client.post(f"/api/admin/credentials/{cred_id}/validate", json={"actor": "test"})

    events_resp = api_client.get(f"/api/admin/credentials/{cred_id}/events")
    assert events_resp.status_code == 200
    events = events_resp.json()
    assert len(events) >= 2
    state_sequence = [e["to_state"] for e in events]
    assert "created" in state_sequence
    assert "validated" in state_sequence


def test_api_validate_consistency_mixed_modes_in_production(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Production environment with mixed auth modes returns 422."""
    import app.services.credential_lifecycle as lifecycle_module
    from app.core.config import Settings

    prod_settings = Settings(
        wix_mock_mode=True,
        credential_lifecycle_db_path=str(tmp_path / "mixed_test.db"),
        environment="production",
        auth_mode="oauth",
        credential_expiry_warning_hours=24,
    )
    svc = CredentialLifecycleService(
        settings=prod_settings,
        db_path=prod_settings.credential_lifecycle_db_path,
    )
    # Add two active credentials with different auth modes
    r1 = svc.create_credential(profile_name="p1", auth_mode="oauth", actor="admin")
    r1 = svc.validate_credential(r1.credential_id, actor="admin")
    svc.activate_credential(r1.credential_id, actor="admin")
    r2 = svc.create_credential(profile_name="p2", auth_mode="api_key", actor="admin")
    r2 = svc.validate_credential(r2.credential_id, actor="admin")
    svc.activate_credential(r2.credential_id, actor="admin")

    monkeypatch.setattr(lifecycle_module, "_service_instance", svc)
    monkeypatch.setattr("app.api.routes.admin_credentials.get_settings", lambda: prod_settings)

    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    resp = client.post("/api/admin/credentials/auth-strategy/validate-consistency")
    assert resp.status_code == 422
