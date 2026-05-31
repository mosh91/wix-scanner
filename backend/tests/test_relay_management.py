"""Acceptance tests for P2-US-09: Edge Relay Management Screen.

Acceptance criteria:
  AC1 – Register relay → appears in list with health fields populated
  AC2 – Rotate credentials → new token preview differs; grace_expires_at set
  AC3 – Heartbeat staleness flag is exposed via the list endpoint
  AC4 – Generate bootstrap credential → validate returns event_id / station_id
  AC5 – bootstrap_url contains signed_token
  AC6 – Revoked bootstrap credential → validate returns 401 with reason=revoked
  AC7 – Expired bootstrap credential → validate returns 401 with reason=expired
  AC8 – Admin-only endpoints return 403 without key / with wrong key
"""
from __future__ import annotations

import sys
from pathlib import Path
import tempfile
from unittest.mock import patch
from datetime import datetime, timezone, timedelta

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import get_settings
from app.services.relay_registry import RelayRegistryService, set_relay_registry_service


ADMIN_TOKEN = get_settings().admin_api_key
ADMIN_HEADERS = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
API = get_settings().api_v1_prefix


@pytest.fixture()
def client_and_service():
    """Fresh isolated relay registry service per test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "relay_registry_test.db")
        svc = RelayRegistryService(db_path=db_path)
        set_relay_registry_service(svc)
        client = TestClient(app)
        yield client, svc
        set_relay_registry_service(None)


# ---------------------------------------------------------------------------
# AC1 – Register relay appears in list
# ---------------------------------------------------------------------------

def test_registered_relay_appears_in_list(client_and_service):
    client, _ = client_and_service

    payload = {
        "relay_name": "Door A",
        "venue": "Main Hall",
        "station_id": "station-01",
    }
    resp = client.post(f"{API}/admin/relays", json=payload, headers=ADMIN_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["relay_name"] == "Door A"
    assert "auth_token" in data
    assert data["auth_token"]  # non-empty

    relay_id = data["relay_id"]

    list_resp = client.get(f"{API}/admin/relays", headers=ADMIN_HEADERS)
    assert list_resp.status_code == 200, list_resp.text
    relays = list_resp.json()
    assert any(r["relay_id"] == relay_id for r in relays)
    relay = next(r for r in relays if r["relay_id"] == relay_id)
    assert relay["venue"] == "Main Hall"
    assert relay["station_id"] == "station-01"
    assert relay["status"] == "active"
    assert "heartbeat_stale" in relay


# ---------------------------------------------------------------------------
# AC2 – Rotate credentials → new preview differs, grace window set
# ---------------------------------------------------------------------------

def test_rotate_credentials_invalidates_token_preview(client_and_service):
    client, _ = client_and_service

    reg = client.post(
        f"{API}/admin/relays",
        json={"relay_name": "Door B", "venue": "VIP", "station_id": "station-02"},
        headers=ADMIN_HEADERS,
    )
    assert reg.status_code == 200, reg.text
    reg = reg.json()
    relay_id = reg["relay_id"]
    old_preview = reg["auth_token_preview"]

    rotate_resp = client.post(
        f"{API}/admin/relays/{relay_id}/rotate-credentials",
        json={"grace_minutes": 10},
        headers=ADMIN_HEADERS,
    )
    assert rotate_resp.status_code == 200, rotate_resp.text
    rot = rotate_resp.json()
    assert "new_auth_token" in rot
    assert rot["new_auth_token"]
    assert rot["grace_expires_at"]

    # After rotation the list preview should differ from old preview
    detail_resp = client.get(f"{API}/admin/relays", headers=ADMIN_HEADERS)
    relay = next(r for r in detail_resp.json() if r["relay_id"] == relay_id)
    assert relay["auth_token_preview"] != old_preview


# ---------------------------------------------------------------------------
# AC3 – Heartbeat staleness flag
# ---------------------------------------------------------------------------

def test_heartbeat_stale_flag_no_heartbeat(client_and_service):
    """A relay that never sent a heartbeat reports heartbeat_stale=True."""
    client, _ = client_and_service

    reg = client.post(
        f"{API}/admin/relays",
        json={"relay_name": "Door C", "venue": "Lobby", "station_id": "station-03"},
        headers=ADMIN_HEADERS,
    )
    assert reg.status_code == 200, reg.text
    reg = reg.json()
    relay_id = reg["relay_id"]

    list_resp = client.get(f"{API}/admin/relays", headers=ADMIN_HEADERS)
    relay = next(r for r in list_resp.json() if r["relay_id"] == relay_id)
    assert relay["heartbeat_stale"] is True


def test_heartbeat_stale_flag_recent(client_and_service):
    """A relay that just sent a heartbeat reports heartbeat_stale=False."""
    client, _ = client_and_service

    reg = client.post(
        f"{API}/admin/relays",
        json={"relay_name": "Door D", "venue": "Side", "station_id": "station-04"},
        headers=ADMIN_HEADERS,
    )
    assert reg.status_code == 200, reg.text
    reg = reg.json()
    relay_id = reg["relay_id"]

    hb = client.post(
        f"{API}/admin/relays/{relay_id}/heartbeat",
        json={"queue_depth": 0, "software_version": "1.0.0"},
        headers=ADMIN_HEADERS,
    )
    assert hb.status_code == 200, hb.text

    list_resp = client.get(f"{API}/admin/relays", headers=ADMIN_HEADERS)
    relay = next(r for r in list_resp.json() if r["relay_id"] == relay_id)
    assert relay["heartbeat_stale"] is False


# ---------------------------------------------------------------------------
# AC4 – Bootstrap credential validate returns event_id / station_id
# ---------------------------------------------------------------------------

def test_bootstrap_credential_validate_success(client_and_service):
    client, _ = client_and_service

    gen_resp = client.post(
        f"{API}/admin/bootstrap-credentials",
        json={
            "event_id": "evt-001",
            "station_id": "door-a",
            "actor": "admin",
            "mode": "one_time",
            "expires_minutes": 60,
        },
        headers=ADMIN_HEADERS,
    )
    assert gen_resp.status_code == 200, gen_resp.text
    cred = gen_resp.json()
    assert "signed_token" in cred
    assert "bootstrap_url" in cred

    val_resp = client.post(
        f"{API}/admin/bootstrap-credentials/validate",
        json={"signed_token": cred["signed_token"]},
    )
    val = val_resp.json()
    assert val["event_id"] == "evt-001"
    assert val["station_id"] == "door-a"


# ---------------------------------------------------------------------------
# AC5 – bootstrap_url contains signed_token
# ---------------------------------------------------------------------------

def test_bootstrap_url_contains_signed_token(client_and_service):
    client, _ = client_and_service

    gen_resp = client.post(
        f"{API}/admin/bootstrap-credentials",
        json={
            "event_id": "evt-002",
            "station_id": "door-b",
            "actor": "admin",
            "mode": "reusable_with_expiry",
            "expires_minutes": 120,
        },
        headers=ADMIN_HEADERS,
    )
    assert gen_resp.status_code == 200, gen_resp.text
    cred = gen_resp.json()
    assert cred["signed_token"] in cred["bootstrap_url"]


# ---------------------------------------------------------------------------
# AC6 – Revoked bootstrap credential → 401 with reason=revoked
# ---------------------------------------------------------------------------

def test_revoked_bootstrap_credential_denied(client_and_service):
    client, _ = client_and_service

    cred = client.post(
        f"{API}/admin/bootstrap-credentials",
        json={
            "event_id": "evt-003",
            "station_id": "door-c",
            "actor": "admin",
            "mode": "reusable_with_expiry",
            "expires_minutes": 60,
        },
        headers=ADMIN_HEADERS,
    )
    assert cred.status_code == 200, cred.text
    cred = cred.json()

    rev = client.post(
        f"{API}/admin/bootstrap-credentials/{cred['credential_id']}/revoke",
        params={"actor": "admin"},
        headers=ADMIN_HEADERS,
    )
    assert rev.status_code == 200, rev.text

    val = client.post(
        f"{API}/admin/bootstrap-credentials/validate",
        json={"signed_token": cred["signed_token"]},
    )
    assert val.status_code == 401
    assert val.json()["detail"]["reason"] == "revoked"


# ---------------------------------------------------------------------------
# AC7 – Expired bootstrap credential → 401 with reason=expired
# ---------------------------------------------------------------------------

def test_expired_bootstrap_credential_denied(client_and_service):
    client, svc = client_and_service

    # Generate with minimum expiry
    cred = client.post(
        f"{API}/admin/bootstrap-credentials",
        json={
            "event_id": "evt-004",
            "station_id": "door-d",
            "actor": "admin",
            "mode": "reusable_with_expiry",
            "expires_minutes": 5,
        },
        headers=ADMIN_HEADERS,
    )
    assert cred.status_code == 200, cred.text
    cred = cred.json()

    # Simulate validation at a time far in the future
    future = datetime.now(timezone.utc) + timedelta(hours=24)
    with patch("app.services.relay_registry.datetime") as mock_dt:
        mock_dt.now.return_value = future
        mock_dt.fromisoformat = datetime.fromisoformat
        val = client.post(
            f"{API}/admin/bootstrap-credentials/validate",
            json={"signed_token": cred["signed_token"]},
        )
    assert val.status_code == 401
    assert val.json()["detail"]["reason"] == "expired"


# ---------------------------------------------------------------------------
# AC8 – Admin endpoints require valid key
# ---------------------------------------------------------------------------

def test_relay_management_admin_key_missing(client_and_service):
    client, _ = client_and_service

    resp = client.get(f"{API}/admin/relays")
    assert resp.status_code == 403


def test_relay_management_admin_key_wrong(client_and_service):
    client, _ = client_and_service

    resp = client.get(
        f"{API}/admin/relays",
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert resp.status_code == 403


def test_bootstrap_list_admin_key_required(client_and_service):
    client, _ = client_and_service

    resp = client.get(f"{API}/admin/bootstrap-credentials")
    assert resp.status_code == 403
