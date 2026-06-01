from __future__ import annotations

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.services.wix_autobind import WixAutobindResult, WixAutobindService

router = APIRouter(prefix="/admin")


class AutobindRequest(BaseModel):
    actor: str = Field(default="operator-ui", min_length=2, max_length=128)
    include_drafts: bool = False


class AutobindResponse(BaseModel):
    site_id: str
    site_display_name: str | None
    app_instance_id: str
    events_found: int
    events_imported: int
    bindings_created: int
    bindings_verified: int
    existing_bindings: int
    event_ids: list[str]
    binding_ids: list[str]


def _to_response(result: WixAutobindResult) -> AutobindResponse:
    return AutobindResponse(
        site_id=result.site_id,
        site_display_name=result.site_display_name,
        app_instance_id=result.app_instance_id,
        events_found=result.events_found,
        events_imported=result.events_imported,
        bindings_created=result.bindings_created,
        bindings_verified=result.bindings_verified,
        existing_bindings=result.existing_bindings,
        event_ids=result.event_ids,
        binding_ids=result.binding_ids,
    )


@router.post(
    "/integrations/autobind",
    response_model=AutobindResponse,
    status_code=status.HTTP_200_OK,
    summary="Autobind the current Wix site and events",
)
def autobind_integrations(request: AutobindRequest) -> AutobindResponse:
    service = WixAutobindService()
    result = service.autobind(actor=request.actor, include_drafts=request.include_drafts)
    return _to_response(result)
