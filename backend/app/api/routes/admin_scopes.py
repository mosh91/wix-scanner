from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.wix_scope_audit import WixScopeAuditRecord, get_wix_scope_audit_service

router = APIRouter(prefix="/admin")


class ScopeVerifyRequest(BaseModel):
    actor: str = Field(default="system", min_length=2, max_length=128)


class ScopeAuditResponse(BaseModel):
    audit_id: str
    binding_id: str
    wix_site_id: str
    wix_event_id: str
    required_scopes: list[str]
    verified_scopes: list[str]
    missing_scopes: list[str]
    status: str
    alert_reason: str | None
    scopes_verified_at: str
    verified_by_actor: str
    created_at: str


def _to_response(record: WixScopeAuditRecord) -> ScopeAuditResponse:
    return ScopeAuditResponse(
        audit_id=record.audit_id,
        binding_id=record.binding_id,
        wix_site_id=record.wix_site_id,
        wix_event_id=record.wix_event_id,
        required_scopes=record.required_scopes,
        verified_scopes=record.verified_scopes,
        missing_scopes=record.missing_scopes,
        status=record.status,
        alert_reason=record.alert_reason,
        scopes_verified_at=record.scopes_verified_at,
        verified_by_actor=record.verified_by_actor,
        created_at=record.created_at,
    )


@router.post(
    "/site-event-bindings/{binding_id}/scopes/verify",
    response_model=ScopeAuditResponse,
    summary="Verify Wix app scopes for a binding",
)
def verify_scopes(binding_id: str, request: ScopeVerifyRequest) -> ScopeAuditResponse:
    service = get_wix_scope_audit_service()
    try:
        record = service.verify_scopes(binding_id=binding_id, actor=request.actor)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _to_response(record)


@router.get(
    "/scopes/latest",
    response_model=list[ScopeAuditResponse],
    summary="List latest Wix scope status per binding",
)
def list_latest_scope_status() -> list[ScopeAuditResponse]:
    service = get_wix_scope_audit_service()
    return [_to_response(record) for record in service.list_latest()]


@router.get(
    "/site-event-bindings/{binding_id}/scopes/history",
    response_model=list[ScopeAuditResponse],
    summary="List scope verification history for a binding",
)
def list_scope_history(binding_id: str, limit: int = Query(default=20, ge=1, le=100)) -> list[ScopeAuditResponse]:
    service = get_wix_scope_audit_service()
    return [_to_response(record) for record in service.list_history_for_binding(binding_id, limit=limit)]
