from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.auth_settings import AuthTokenStatusRecord, get_auth_settings_service

router = APIRouter(prefix="/admin/auth-settings")


class TokenStatusResponse(BaseModel):
    auth_mode: str
    token_status: str
    credential_id: str | None
    profile_name: str | None
    expires_at: str | None
    last_refresh_at: str | None
    last_tested_at: str | None
    last_error: str | None


class TokenActionRequest(BaseModel):
    actor: str = Field(default="operator-ui", min_length=2, max_length=128)


def _to_response(record: AuthTokenStatusRecord) -> TokenStatusResponse:
    return TokenStatusResponse(
        auth_mode=record.auth_mode,
        token_status=record.token_status,
        credential_id=record.credential_id,
        profile_name=record.profile_name,
        expires_at=record.expires_at,
        last_refresh_at=record.last_refresh_at,
        last_tested_at=record.last_tested_at,
        last_error=record.last_error,
    )


@router.get("/token", response_model=TokenStatusResponse, summary="Get token auth settings status")
def get_token_status() -> TokenStatusResponse:
    return _to_response(get_auth_settings_service().get_token_status())


@router.post("/token/refresh", response_model=TokenStatusResponse, summary="Manually refresh token")
def refresh_token(body: TokenActionRequest) -> TokenStatusResponse:
    try:
        record = get_auth_settings_service().refresh_token(actor=body.actor)
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_response(record)


@router.post("/token/test-connection", response_model=TokenStatusResponse, summary="Test Wix connection")
def test_connection(_: TokenActionRequest) -> TokenStatusResponse:
    try:
        record = get_auth_settings_service().test_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_response(record)
