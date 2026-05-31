from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services.credential_lifecycle import (
    AuthMode,
    CredentialLifecycleEvent,
    CredentialLifecycleRecord,
    get_credential_lifecycle_service,
)

router = APIRouter(prefix="/admin")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class CreateCredentialRequest(BaseModel):
    profile_name: str = Field(min_length=2, max_length=128)
    auth_mode: AuthMode
    actor: str = Field(default="operator-ui", min_length=2, max_length=128)
    expires_at: str | None = Field(default=None)


class ValidateCredentialRequest(BaseModel):
    actor: str = Field(default="operator-ui", min_length=2, max_length=128)


class ActivateCredentialRequest(BaseModel):
    actor: str = Field(default="operator-ui", min_length=2, max_length=128)


class RevokeCredentialRequest(BaseModel):
    actor: str = Field(default="operator-ui", min_length=2, max_length=128)
    note: str | None = Field(default=None)


class RotateCredentialRequest(BaseModel):
    new_profile_name: str = Field(min_length=2, max_length=128)
    new_auth_mode: AuthMode
    actor: str = Field(default="operator-ui", min_length=2, max_length=128)
    new_expires_at: str | None = Field(default=None)


class CredentialResponse(BaseModel):
    credential_id: str
    profile_name: str
    auth_mode: str
    lifecycle_state: str
    created_at: str
    validated_at: str | None
    activated_at: str | None
    last_validated_at: str | None
    validation_error: str | None
    expires_at: str | None
    rotation_note: str | None
    created_by_actor: str


class CredentialEventResponse(BaseModel):
    event_id: str
    credential_id: str
    from_state: str | None
    to_state: str
    actor: str
    event_note: str | None
    occurred_at: str


class RotateCredentialResponse(BaseModel):
    new_credential: CredentialResponse
    revoked_credential: CredentialResponse


class AuthStrategyResponse(BaseModel):
    strategy: dict[str, dict[str, str]]
    environment: str
    configured_auth_mode: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_response(record: CredentialLifecycleRecord) -> CredentialResponse:
    return CredentialResponse(
        credential_id=record.credential_id,
        profile_name=record.profile_name,
        auth_mode=record.auth_mode,
        lifecycle_state=record.lifecycle_state,
        created_at=record.created_at,
        validated_at=record.validated_at,
        activated_at=record.activated_at,
        last_validated_at=record.last_validated_at,
        validation_error=record.validation_error,
        expires_at=record.expires_at,
        rotation_note=record.rotation_note,
        created_by_actor=record.created_by_actor,
    )


def _event_to_response(event: CredentialLifecycleEvent) -> CredentialEventResponse:
    return CredentialEventResponse(
        event_id=event.event_id,
        credential_id=event.credential_id,
        from_state=event.from_state,
        to_state=event.to_state,
        actor=event.actor,
        event_note=event.event_note,
        occurred_at=event.occurred_at,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/credentials",
    response_model=CredentialResponse,
    summary="Register a new credential profile",
)
def create_credential(body: CreateCredentialRequest) -> CredentialResponse:
    svc = get_credential_lifecycle_service()
    record = svc.create_credential(
        profile_name=body.profile_name,
        auth_mode=body.auth_mode,
        actor=body.actor,
        expires_at=body.expires_at,
    )
    return _to_response(record)


@router.get(
    "/credentials",
    response_model=list[CredentialResponse],
    summary="List all credential profiles and their lifecycle states",
)
def list_credentials() -> list[CredentialResponse]:
    svc = get_credential_lifecycle_service()
    return [_to_response(r) for r in svc.list_credentials()]


@router.get(
    "/credentials/{credential_id}",
    response_model=CredentialResponse,
    summary="Get a credential profile by ID",
)
def get_credential(credential_id: str) -> CredentialResponse:
    svc = get_credential_lifecycle_service()
    record = svc.get_credential(credential_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Credential '{credential_id}' not found")
    return _to_response(record)


@router.post(
    "/credentials/{credential_id}/validate",
    response_model=CredentialResponse,
    summary="Validate a credential against the Wix API",
)
def validate_credential(credential_id: str, body: ValidateCredentialRequest) -> CredentialResponse:
    svc = get_credential_lifecycle_service()
    try:
        record = svc.validate_credential(credential_id, actor=body.actor)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Credential '{credential_id}' not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _to_response(record)


@router.post(
    "/credentials/{credential_id}/activate",
    response_model=CredentialResponse,
    summary="Activate a validated credential",
)
def activate_credential(credential_id: str, body: ActivateCredentialRequest) -> CredentialResponse:
    svc = get_credential_lifecycle_service()
    try:
        record = svc.activate_credential(credential_id, actor=body.actor)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Credential '{credential_id}' not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _to_response(record)


@router.post(
    "/credentials/{credential_id}/rotate",
    response_model=RotateCredentialResponse,
    summary="Rotate a credential — issues new, validates it, revokes old",
)
def rotate_credential(credential_id: str, body: RotateCredentialRequest) -> RotateCredentialResponse:
    svc = get_credential_lifecycle_service()
    try:
        new_record, revoked = svc.rotate_credential(
            credential_id,
            new_profile_name=body.new_profile_name,
            new_auth_mode=body.new_auth_mode,
            actor=body.actor,
            new_expires_at=body.new_expires_at,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Credential '{credential_id}' not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return RotateCredentialResponse(
        new_credential=_to_response(new_record),
        revoked_credential=_to_response(revoked),
    )


@router.post(
    "/credentials/{credential_id}/revoke",
    response_model=CredentialResponse,
    summary="Revoke a credential",
)
def revoke_credential(credential_id: str, body: RevokeCredentialRequest) -> CredentialResponse:
    svc = get_credential_lifecycle_service()
    try:
        record = svc.revoke_credential(credential_id, actor=body.actor, note=body.note)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Credential '{credential_id}' not found")
    return _to_response(record)


@router.get(
    "/credentials/{credential_id}/events",
    response_model=list[CredentialEventResponse],
    summary="List lifecycle events (audit trail) for a credential",
)
def list_credential_events(credential_id: str) -> list[CredentialEventResponse]:
    svc = get_credential_lifecycle_service()
    record = svc.get_credential(credential_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Credential '{credential_id}' not found")
    return [_event_to_response(e) for e in svc.list_events(credential_id)]


@router.get(
    "/credentials/auth-strategy/decision-table",
    response_model=AuthStrategyResponse,
    summary="Get auth-mode decision table (which endpoints use OAuth vs API key)",
)
def get_auth_strategy() -> AuthStrategyResponse:
    svc = get_credential_lifecycle_service()
    settings = get_settings()
    return AuthStrategyResponse(
        strategy=svc.get_auth_strategy(),
        environment=settings.environment,
        configured_auth_mode=settings.auth_mode,
    )


@router.post(
    "/credentials/auth-strategy/validate-consistency",
    summary="Validate auth mode is consistent (no mixed modes in production)",
    status_code=200,
)
def validate_auth_consistency() -> dict[str, str]:
    svc = get_credential_lifecycle_service()
    settings = get_settings()
    try:
        svc.validate_no_mixed_modes(settings.environment)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"status": "ok"}
