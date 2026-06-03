from __future__ import annotations

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from app.services.wix_autobind import WixAutobindResult, WixAutobindService

router = APIRouter(prefix="/admin")


class AutobindRequest(BaseModel):
    actor: str = Field(default="operator-ui", min_length=2, max_length=128)
    include_drafts: bool = False
    dry_run: bool = False


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


class WixEventPreview(BaseModel):
    wix_event_id: str
    name: str


class ListWixEventsResponse(BaseModel):
    site_id: str
    site_display_name: str | None
    events: list[WixEventPreview]


@router.get(
    "/integrations/wix-events",
    response_model=ListWixEventsResponse,
    status_code=status.HTTP_200_OK,
    summary="List events from Wix without importing them locally",
)
def list_wix_events(include_drafts: bool = Query(default=False)) -> ListWixEventsResponse:
    service = WixAutobindService()
    site_id, site_display_name, events = service.list_wix_events(include_drafts=include_drafts)
    return ListWixEventsResponse(
        site_id=site_id,
        site_display_name=site_display_name,
        events=[WixEventPreview(**e) for e in events],
    )


@router.post(
    "/integrations/autobind",
    response_model=AutobindResponse,
    status_code=status.HTTP_200_OK,
    summary="Autobind the current Wix site and events",
)
def autobind_integrations(request: AutobindRequest) -> AutobindResponse:
    service = WixAutobindService()
    result = service.autobind(actor=request.actor, include_drafts=request.include_drafts, dry_run=request.dry_run)
    return _to_response(result)
