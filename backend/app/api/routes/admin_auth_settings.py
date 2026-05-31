from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.auth_settings import ApiKeySettingsRecord, ApiKeyValidationRecord, AuthTokenStatusRecord, get_auth_settings_service

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


class ApiKeyStatusResponse(BaseModel):
    auth_mode: str
    api_key_configured: bool
    wix_account_id: str | None
    last_rotated_at: str | None
    last_validated_at: str | None
    last_validation_error: str | None
    updated_at: str | None
    updated_by_actor: str | None


class ApiKeyUpsertRequest(BaseModel):
    api_key: str = Field(min_length=8, max_length=4096)
    wix_account_id: str = Field(min_length=2, max_length=128)
    actor: str = Field(default="operator-ui", min_length=2, max_length=128)


class ApiKeyTestRequest(BaseModel):
    api_key: str = Field(min_length=8, max_length=4096)
    wix_account_id: str | None = Field(default=None, min_length=2, max_length=128)
    actor: str = Field(default="operator-ui", min_length=2, max_length=128)


class ApiKeyValidationResponse(BaseModel):
    ok: bool
    message: str
    tested_at: str
    wix_account_id: str | None


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


def _to_api_key_response(record: ApiKeySettingsRecord) -> ApiKeyStatusResponse:
    return ApiKeyStatusResponse(
        auth_mode=record.auth_mode,
        api_key_configured=record.api_key_configured,
        wix_account_id=record.wix_account_id,
        last_rotated_at=record.last_rotated_at,
        last_validated_at=record.last_validated_at,
        last_validation_error=record.last_validation_error,
        updated_at=record.updated_at,
        updated_by_actor=record.updated_by_actor,
    )


def _to_api_key_validation_response(record: ApiKeyValidationRecord) -> ApiKeyValidationResponse:
    return ApiKeyValidationResponse(
        ok=record.ok,
        message=record.message,
        tested_at=record.tested_at,
        wix_account_id=record.wix_account_id,
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


@router.get("/api-key", response_model=ApiKeyStatusResponse, summary="Get API key settings status")
def get_api_key_status() -> ApiKeyStatusResponse:
    return _to_api_key_response(get_auth_settings_service().get_api_key_status())


@router.post("/api-key/test-connection", response_model=ApiKeyValidationResponse, summary="Test API key connection")
def test_api_key_connection(body: ApiKeyTestRequest) -> ApiKeyValidationResponse:
    record = get_auth_settings_service().test_api_key_connection(
        api_key=body.api_key,
        wix_account_id=body.wix_account_id,
        actor=body.actor,
    )
    return _to_api_key_validation_response(record)


@router.put("/api-key", response_model=ApiKeyStatusResponse, summary="Save API key settings")
def save_api_key_settings(body: ApiKeyUpsertRequest) -> ApiKeyStatusResponse:
    try:
        record = get_auth_settings_service().save_api_key_settings(
            api_key=body.api_key,
            wix_account_id=body.wix_account_id,
            actor=body.actor,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_api_key_response(record)
