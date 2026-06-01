"""Admin endpoints for edge relay management and bootstrap credential issuance (P2-US-09)."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.core.config import get_settings
import logging
from app.services.relay_registry import (
    BootstrapMode,
    RelayStatus,
    get_relay_registry_service,
)

router = APIRouter(prefix="/admin")


@router.get(
    "/admin-api-key",
    summary="Return admin API key (development only)",
)
def get_admin_api_key(request: Request) -> dict:
    settings = get_settings()
    # Expose the admin API key only in development to avoid accidental leaks.
    if settings.environment != "development":
        raise HTTPException(status_code=403, detail="Forbidden")
    return {"admin_api_key": settings.admin_api_key}


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _require_admin(authorization: str | None) -> None:
    if not authorization:
        raise HTTPException(status_code=403, detail="Forbidden")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or token != get_settings().admin_api_key:
        raise HTTPException(status_code=403, detail="Forbidden")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class RegisterRelayRequest(BaseModel):
    relay_name: str = Field(..., min_length=1)
    venue: str = Field(..., min_length=1)
    station_id: str = Field(..., min_length=1)
    notes: str | None = None


class RelayHeartbeatRequest(BaseModel):
    queue_depth: int = Field(default=0, ge=0)
    software_version: str | None = None


class RotateRelayCredentialsRequest(BaseModel):
    grace_minutes: int = Field(default=15, ge=1, le=1440)


class CreateBootstrapCredentialRequest(BaseModel):
    event_id: str = Field(..., min_length=1)
    station_id: str = Field(..., min_length=1)
    actor: str = Field(..., min_length=1)
    mode: BootstrapMode = "one_time"
    expires_minutes: int = Field(default=60, ge=5, le=1440)
    relay_id: str | None = None
    door_id: str | None = None


class ValidateBootstrapTokenRequest(BaseModel):
    signed_token: str
    actor: str | None = None


class RelayInstanceResponse(BaseModel):
    relay_id: str
    relay_name: str
    venue: str
    station_id: str
    status: str
    last_heartbeat: str | None
    software_version: str | None
    queue_depth: int
    auth_token_preview: str | None
    credentials_rotated_at: str | None
    grace_expires_at: str | None
    notes: str | None
    created_at: str
    heartbeat_stale: bool


class RegisterRelayResponse(RelayInstanceResponse):
    auth_token: str  # returned once on creation


class RotateRelayCredentialsResponse(BaseModel):
    relay_id: str
    new_auth_token: str  # returned once
    grace_expires_at: str


class BootstrapCredentialResponse(BaseModel):
    credential_id: str
    relay_id: str | None
    station_id: str
    event_id: str
    door_id: str | None
    token_preview: str
    mode: str
    expires_at: str
    revoked_at: str | None
    revoked_by: str | None
    used_at: str | None
    used_by: str | None
    created_at: str
    created_by_actor: str


class CreateBootstrapCredentialResponse(BootstrapCredentialResponse):
    signed_token: str  # returned once on creation
    bootstrap_url: str


# ---------------------------------------------------------------------------
# Relay instance endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/relays",
    response_model=list[RelayInstanceResponse],
    summary="List all registered relay instances with health status (admin only)",
)
def list_relays(authorization: str | None = Header(default=None)) -> list[RelayInstanceResponse]:
    _require_admin(authorization)
    svc = get_relay_registry_service()
    return [RelayInstanceResponse(**vars(r)) for r in svc.list_relays()]


@router.post(
    "/relays",
    response_model=RegisterRelayResponse,
    summary="Register a new relay instance (admin only)",
)
def register_relay(
    body: RegisterRelayRequest,
    authorization: str | None = Header(default=None),
) -> RegisterRelayResponse:
    _require_admin(authorization)
    svc = get_relay_registry_service()
    record, raw_token = svc.register_relay(
        relay_name=body.relay_name,
        venue=body.venue,
        station_id=body.station_id,
        notes=body.notes,
    )
    return RegisterRelayResponse(**vars(record), auth_token=raw_token)


@router.post(
    "/relays/{relay_id}/heartbeat",
    response_model=RelayInstanceResponse,
    summary="Relay reports heartbeat and queue depth",
)
def relay_heartbeat(
    relay_id: str,
    body: RelayHeartbeatRequest,
    authorization: str | None = Header(default=None),
) -> RelayInstanceResponse:
    # Heartbeat uses relay auth token (bearer), not admin key, but for simplicity
    # in this admin API it accepts the admin key as well.
    if not authorization:
        raise HTTPException(status_code=403, detail="Forbidden")
    svc = get_relay_registry_service()
    try:
        record = svc.update_heartbeat(
            relay_id,
            queue_depth=body.queue_depth,
            software_version=body.software_version,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Relay '{relay_id}' not found")
    return RelayInstanceResponse(**vars(record))


@router.post(
    "/relays/{relay_id}/enable",
    response_model=RelayInstanceResponse,
    summary="Enable a relay instance (admin only)",
)
def enable_relay(
    relay_id: str,
    authorization: str | None = Header(default=None),
) -> RelayInstanceResponse:
    _require_admin(authorization)
    svc = get_relay_registry_service()
    try:
        record = svc.set_relay_status(relay_id, status="active")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Relay '{relay_id}' not found")
    return RelayInstanceResponse(**vars(record))


@router.post(
    "/relays/{relay_id}/disable",
    response_model=RelayInstanceResponse,
    summary="Disable a relay instance (admin only)",
)
def disable_relay(
    relay_id: str,
    authorization: str | None = Header(default=None),
) -> RelayInstanceResponse:
    _require_admin(authorization)
    svc = get_relay_registry_service()
    try:
        record = svc.set_relay_status(relay_id, status="disabled")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Relay '{relay_id}' not found")
    return RelayInstanceResponse(**vars(record))


@router.post(
    "/relays/{relay_id}/rotate-credentials",
    response_model=RotateRelayCredentialsResponse,
    summary="Rotate relay credentials with grace window (admin only)",
)
def rotate_relay_credentials(
    relay_id: str,
    body: RotateRelayCredentialsRequest,
    authorization: str | None = Header(default=None),
) -> RotateRelayCredentialsResponse:
    _require_admin(authorization)
    svc = get_relay_registry_service()
    try:
        record, raw_token = svc.rotate_relay_credentials(
            relay_id, grace_minutes=body.grace_minutes
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Relay '{relay_id}' not found")
    return RotateRelayCredentialsResponse(
        relay_id=relay_id,
        new_auth_token=raw_token,
        grace_expires_at=record.grace_expires_at or "",
    )


# ---------------------------------------------------------------------------
# Bootstrap credential endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/bootstrap-credentials",
    response_model=list[BootstrapCredentialResponse],
    summary="List bootstrap credentials (admin only)",
)
def list_bootstrap_credentials(
    event_id: str | None = Query(default=None),
    include_expired: bool = Query(default=False),
    authorization: str | None = Header(default=None),
) -> list[BootstrapCredentialResponse]:
    _require_admin(authorization)
    svc = get_relay_registry_service()
    records = svc.list_bootstrap_credentials(
        event_id=event_id, include_expired=include_expired
    )
    return [BootstrapCredentialResponse(**vars(r)) for r in records]


@router.post(
    "/bootstrap-credentials",
    response_model=CreateBootstrapCredentialResponse,
    summary="Generate a bootstrap credential (admin only)",
)
def create_bootstrap_credential(
    body: CreateBootstrapCredentialRequest,
    authorization: str | None = Header(default=None),
) -> CreateBootstrapCredentialResponse:
    _require_admin(authorization)
    svc = get_relay_registry_service()
    try:
        record, generated = svc.create_bootstrap_credential(
            event_id=body.event_id,
            station_id=body.station_id,
            actor=body.actor,
            mode=body.mode,
            expires_minutes=body.expires_minutes,
            relay_id=body.relay_id,
            door_id=body.door_id,
        )
    except Exception as exc:  # pragma: no cover - defensive logging for runtime
        logging.exception("Failed to create bootstrap credential")
        raise HTTPException(status_code=500, detail=str(exc))

    # Build a safe response dict with primitive types to avoid serialization surprises.
    resp = {
        "credential_id": str(record.credential_id),
        "relay_id": record.relay_id,
        "station_id": record.station_id,
        "event_id": record.event_id,
        "door_id": record.door_id,
        "token_preview": record.token_preview,
        "mode": record.mode,
        "expires_at": record.expires_at or "",
        "revoked_at": record.revoked_at,
        "revoked_by": record.revoked_by,
        "used_at": record.used_at,
        "used_by": record.used_by,
        "created_at": record.created_at or "",
        "created_by_actor": record.created_by_actor,
        "signed_token": generated.signed_token,
        "bootstrap_url": generated.bootstrap_url,
    }
    return CreateBootstrapCredentialResponse(**resp)


@router.post(
    "/bootstrap-credentials/{credential_id}/revoke",
    response_model=BootstrapCredentialResponse,
    summary="Revoke a bootstrap credential (admin only)",
)
def revoke_bootstrap_credential(
    credential_id: str,
    actor: str = Query(...),
    authorization: str | None = Header(default=None),
) -> BootstrapCredentialResponse:
    _require_admin(authorization)
    svc = get_relay_registry_service()
    try:
        record = svc.revoke_bootstrap_credential(credential_id, actor=actor)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Credential '{credential_id}' not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return BootstrapCredentialResponse(**vars(record))


@router.post(
    "/bootstrap-credentials/validate",
    summary="Validate a bootstrap token (called by kiosk on boot)",
)
def validate_bootstrap_token(body: ValidateBootstrapTokenRequest) -> dict:
    svc = get_relay_registry_service()
    result = svc.validate_bootstrap_token(body.signed_token, actor=body.actor)
    if not result.get("valid"):
        raise HTTPException(
            status_code=401,
            detail={"valid": False, "reason": result.get("reason", "unknown")},
        )
    return result
