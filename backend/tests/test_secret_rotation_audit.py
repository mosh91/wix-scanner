"""Acceptance tests for P2-US-08: Secret Rotation and Audit Screen.

Acceptance criteria:
  1. rotation action creates a visible audit record immediately
  2. filters on audit log (actor, action, date) return matching records
  3. non-admin user gets access denied (403)
"""
from __future__ import annotations

import sys
from pathlib import Path
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import get_settings, Settings
from app.services.credential_lifecycle import (
    CredentialLifecycleService,
    set_credential_lifecycle_service,
)


ADMIN_TOKEN = get_settings().admin_api_key
ADMIN_HEADERS = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
WRONG_HEADERS = {"Authorization": "Bearer wrong-token"}


@pytest.fixture
def audit_client():
    """Test client with isolated credential lifecycle service."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        settings = Settings(
            wix_mock_mode=True,
            credential_lifecycle_db_path=str(tmp / "cred.db"),
            environment="development",
            auth_mode="api_key",
            credential_expiry_warning_hours=24,
            admin_api_key=ADMIN_TOKEN,
        )
        svc = CredentialLifecycleService(
            settings=settings,
            db_path=str(tmp / "cred.db"),
        )
        set_credential_lifecycle_service(svc)
        yield TestClient(app)


# ---------------------------------------------------------------------------
# Helper: create a credential via API
# ---------------------------------------------------------------------------

def _create_credential(client: TestClient, profile: str = "test-profile") -> str:
    """Create, validate, and activate a credential; return its credential_id."""
    resp = client.post(
        "/api/admin/credentials",
        json={
            "profile_name": profile,
            "auth_mode": "api_key",
            "actor": "test-actor",
        },
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code in (200, 201), resp.text
    cred_id = resp.json()["credential_id"]

    # Validate the credential (succeeds in mock mode)
    val_resp = client.post(
        f"/api/admin/credentials/{cred_id}/validate",
        json={"actor": "test-actor"},
        headers=ADMIN_HEADERS,
    )
    assert val_resp.status_code == 200, val_resp.text

    # Activate
    act_resp = client.post(
        f"/api/admin/credentials/{cred_id}/activate",
        json={"actor": "test-actor"},
        headers=ADMIN_HEADERS,
    )
    assert act_resp.status_code == 200, act_resp.text

    return cred_id


# ---------------------------------------------------------------------------
# Acceptance criterion 1: rotation creates a visible audit record
# ---------------------------------------------------------------------------

def test_audit_log_contains_rotation_event(audit_client: TestClient) -> None:
    cred_id = _create_credential(audit_client)

    # Rotate the credential
    rotate_resp = audit_client.post(
        f"/api/admin/credentials/{cred_id}/rotate",
        json={
            "new_profile_name": "rotated-profile",
            "new_auth_mode": "api_key",
            "actor": "test-actor",
        },
        headers=ADMIN_HEADERS,
    )
    assert rotate_resp.status_code == 200, rotate_resp.text

    # Fetch audit log
    audit_resp = audit_client.get("/api/admin/credentials/audit", headers=ADMIN_HEADERS)
    assert audit_resp.status_code == 200, audit_resp.text
    events = audit_resp.json()
    assert len(events) > 0

    # The original credential should have been revoked — find that event
    to_states = [e["to_state"] for e in events]
    assert "revoked" in to_states, f"Expected 'revoked' in audit events: {to_states}"


# ---------------------------------------------------------------------------
# Acceptance criterion 2a: filter by actor
# ---------------------------------------------------------------------------

def test_audit_log_filter_by_actor(audit_client: TestClient) -> None:
    # Create two credentials with different actors via service directly
    from app.services.credential_lifecycle import get_credential_lifecycle_service

    svc = get_credential_lifecycle_service()
    svc.create_credential(profile_name="p-alice", auth_mode="api_key", actor="alice")
    svc.create_credential(profile_name="p-bob", auth_mode="api_key", actor="bob")

    resp = audit_client.get(
        "/api/admin/credentials/audit",
        params={"actor": "alice"},
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    events = resp.json()
    assert all(e["actor"] == "alice" for e in events), events


# ---------------------------------------------------------------------------
# Acceptance criterion 2b: filter by action (to_state)
# ---------------------------------------------------------------------------

def test_audit_log_filter_by_action(audit_client: TestClient) -> None:
    cred_id = _create_credential(audit_client, profile="rotate-target")

    # Rotate so we get a "revoked" state event
    audit_client.post(
        f"/api/admin/credentials/{cred_id}/rotate",
        json={"new_profile_name": "after-rotate", "new_auth_mode": "api_key", "actor": "tester"},
        headers=ADMIN_HEADERS,
    )

    resp = audit_client.get(
        "/api/admin/credentials/audit",
        params={"action": "revoked"},
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    events = resp.json()
    assert len(events) > 0
    assert all(e["to_state"] == "revoked" for e in events), events


# ---------------------------------------------------------------------------
# Acceptance criterion 3: non-admin / wrong key → 403
# ---------------------------------------------------------------------------

def test_audit_log_requires_admin_key_missing(audit_client: TestClient) -> None:
    resp = audit_client.get("/api/admin/credentials/audit")
    assert resp.status_code == 403


def test_audit_log_requires_admin_key_wrong(audit_client: TestClient) -> None:
    resp = audit_client.get("/api/admin/credentials/audit", headers=WRONG_HEADERS)
    assert resp.status_code == 403


def test_audit_log_admin_key_correct(audit_client: TestClient) -> None:
    resp = audit_client.get("/api/admin/credentials/audit", headers=ADMIN_HEADERS)
    assert resp.status_code == 200
