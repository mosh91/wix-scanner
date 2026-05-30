from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.services.site_event_binding import (
    AppInstallationStatus,
    BindingStatus,
    EventActivationRecord,
    WixSiteEventBindingRecord,
    get_site_event_binding_service,
)

router = APIRouter(prefix="/admin")


class SiteEventBindingCreateRequest(BaseModel):
    wix_site_id: str = Field(min_length=3, max_length=128)
    wix_event_id: str = Field(min_length=3, max_length=128)
    credential_profile_id: str | None = Field(default=None, max_length=128)
    sync_policy_profile_id: str | None = Field(default=None, max_length=128)
    actor: str = Field(default="system", min_length=2, max_length=128)
    verify_immediately: bool = True


class SiteEventBindingResponse(BaseModel):
    binding_id: str
    wix_site_id: str
    wix_event_id: str
    status: BindingStatus
    app_installation_status: AppInstallationStatus
    credential_profile_id: str | None
    sync_policy_profile_id: str | None
    binding_created_at: str
    binding_verified_at: str | None
    verified_by_actor: str | None
    last_verification_error: str | None
    verification_evidence: dict[str, object]


class SiteEventBindingVerifyRequest(BaseModel):
    actor: str = Field(default="system", min_length=2, max_length=128)


class VerifiedEventResponse(BaseModel):
    wix_event_id: str
    wix_site_id: str


class EventActivationRequest(BaseModel):
    actor: str = Field(default="system", min_length=2, max_length=128)
    readiness_acknowledged: bool = False


class EventActivationResponse(BaseModel):
    wix_event_id: str
    status: str
    activated_at: str
    activated_by_actor: str
    readiness_status: str
    readiness_acknowledged: bool
    readiness_failed_checks: list[str]
    readiness_recommended_actions: list[str]


def _to_binding_response(record: WixSiteEventBindingRecord) -> SiteEventBindingResponse:
    return SiteEventBindingResponse(
        binding_id=record.binding_id,
        wix_site_id=record.wix_site_id,
        wix_event_id=record.wix_event_id,
        status=record.status,
        app_installation_status=record.app_installation_status,
        credential_profile_id=record.credential_profile_id,
        sync_policy_profile_id=record.sync_policy_profile_id,
        binding_created_at=record.binding_created_at,
        binding_verified_at=record.binding_verified_at,
        verified_by_actor=record.verified_by_actor,
        last_verification_error=record.last_verification_error,
        verification_evidence=record.verification_evidence,
    )


@router.post(
    "/site-event-bindings",
    response_model=SiteEventBindingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Wix site-event binding",
)
def create_site_event_binding(request: SiteEventBindingCreateRequest) -> SiteEventBindingResponse:
    service = get_site_event_binding_service()
    try:
        record = service.create_binding(
            wix_site_id=request.wix_site_id,
            wix_event_id=request.wix_event_id,
            credential_profile_id=request.credential_profile_id,
            sync_policy_profile_id=request.sync_policy_profile_id,
            created_by_actor=request.actor,
            verify_immediately=request.verify_immediately,
        )
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_binding_response(record)


@router.post(
    "/site-event-bindings/{binding_id}/verify",
    response_model=SiteEventBindingResponse,
    summary="Run verification task for a binding",
)
def verify_site_event_binding(
    binding_id: str,
    request: SiteEventBindingVerifyRequest,
) -> SiteEventBindingResponse:
    service = get_site_event_binding_service()
    try:
        record = service.verify_binding(binding_id=binding_id, verified_by_actor=request.actor)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_binding_response(record)


@router.get(
    "/site-event-bindings",
    response_model=list[SiteEventBindingResponse],
    summary="List Wix site-event bindings",
)
def list_site_event_bindings(
    status_filter: BindingStatus | None = Query(default=None, alias="status"),
) -> list[SiteEventBindingResponse]:
    service = get_site_event_binding_service()
    return [_to_binding_response(record) for record in service.list_bindings(status=status_filter)]


@router.get(
    "/events",
    response_model=list[VerifiedEventResponse],
    summary="List events from verified bindings",
)
def list_verified_events() -> list[VerifiedEventResponse]:
    service = get_site_event_binding_service()
    return [VerifiedEventResponse(**event) for event in service.get_verified_events()]


@router.post(
    "/events/{wix_event_id}/activate",
    response_model=EventActivationResponse,
    summary="Activate event only if verified binding exists",
)
def activate_event(
    wix_event_id: str,
    request: EventActivationRequest,
) -> EventActivationResponse:
    from app.services.event_readiness import get_event_readiness_service

    readiness_service = get_event_readiness_service()
    report = readiness_service.evaluate(event_id=wix_event_id, readiness_acknowledged=request.readiness_acknowledged)

    if report.overall_status == "critical":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Event activation blocked by critical readiness checks.",
                "failed_checks": report.failed_checks,
                "recommended_actions": report.recommended_actions,
            },
        )
    if report.overall_status == "degraded" and not request.readiness_acknowledged:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Event readiness is degraded and must be acknowledged before activation.",
                "failed_checks": report.failed_checks,
                "recommended_actions": report.recommended_actions,
            },
        )

    service = get_site_event_binding_service()
    try:
        activation = service.activate_event_with_readiness(
            wix_event_id=wix_event_id,
            actor=request.actor,
            readiness_status=report.overall_status,
            readiness_acknowledged=request.readiness_acknowledged,
            readiness_failed_checks=report.failed_checks,
            readiness_recommended_actions=report.recommended_actions,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return EventActivationResponse(
        wix_event_id=activation.wix_event_id,
        status=activation.status,
        activated_at=activation.activated_at,
        activated_by_actor=activation.activated_by_actor,
        readiness_status=activation.readiness_status,
        readiness_acknowledged=activation.readiness_acknowledged,
        readiness_failed_checks=activation.readiness_failed_checks,
        readiness_recommended_actions=activation.readiness_recommended_actions,
    )
