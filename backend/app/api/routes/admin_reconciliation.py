from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.reconciliation import ReconciliationItem, ReconciliationRun, get_reconciliation_service

router = APIRouter(prefix="/admin")


class ReconciliationRunResponse(BaseModel):
    run_id: str
    event_id: str
    status: str
    reconciliation_state: str
    drift_count: int
    resolved_count: int
    conflict_count: int
    started_at: str
    finished_at: str | None
    triggered_by_actor: str
    notes: str | None


class ReconciliationItemResponse(BaseModel):
    item_id: str
    run_id: str
    event_id: str
    ticket_number: str
    reconciliation_state: str
    local_result: str | None
    wix_result: str | None
    resolution_result: str | None
    detail: dict[str, object]
    resolved_at: str | None
    conflict_resolution_notes: str | None
    resolved_by_actor: str | None


class ReconciliationRunTriggerRequest(BaseModel):
    actor: str = Field(default="operator-ui", min_length=2, max_length=128)
    notes: str | None = Field(default=None, max_length=500)


class ConflictResolutionRequest(BaseModel):
    actor: str = Field(default="operator-ui", min_length=2, max_length=128)
    resolution: str = Field(description="accept_wix or keep_local")
    note: str | None = Field(default=None, max_length=500)


class ReconciliationRunWithItemsResponse(BaseModel):
    run: ReconciliationRunResponse
    items: list[ReconciliationItemResponse]


def _to_run_response(run: ReconciliationRun) -> ReconciliationRunResponse:
    return ReconciliationRunResponse(
        run_id=run.run_id,
        event_id=run.event_id,
        status=run.status,
        reconciliation_state=run.reconciliation_state,
        drift_count=run.drift_count,
        resolved_count=run.resolved_count,
        conflict_count=run.conflict_count,
        started_at=run.started_at,
        finished_at=run.finished_at,
        triggered_by_actor=run.triggered_by_actor,
        notes=run.notes,
    )


def _to_item_response(item: ReconciliationItem) -> ReconciliationItemResponse:
    return ReconciliationItemResponse(
        item_id=item.item_id,
        run_id=item.run_id,
        event_id=item.event_id,
        ticket_number=item.ticket_number,
        reconciliation_state=item.reconciliation_state,
        local_result=item.local_result,
        wix_result=item.wix_result,
        resolution_result=item.resolution_result,
        detail=item.detail,
        resolved_at=item.resolved_at,
        conflict_resolution_notes=item.conflict_resolution_notes,
        resolved_by_actor=item.resolved_by_actor,
    )


@router.post(
    "/events/{event_id}/reconciliation/run",
    response_model=ReconciliationRunWithItemsResponse,
    summary="Run reconciliation and return the classification report",
)
def run_reconciliation(
    event_id: str,
    request: ReconciliationRunTriggerRequest,
) -> ReconciliationRunWithItemsResponse:
    report = get_reconciliation_service().run_reconciliation(event_id=event_id, actor=request.actor, notes=request.notes)
    return ReconciliationRunWithItemsResponse(
        run=_to_run_response(report.run),
        items=[_to_item_response(item) for item in report.items],
    )


@router.get(
    "/events/{event_id}/reconciliation/runs",
    response_model=list[ReconciliationRunResponse],
    summary="List reconciliation runs for an event",
)
def list_reconciliation_runs(
    event_id: str,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[ReconciliationRunResponse]:
    runs = get_reconciliation_service().list_runs(event_id=event_id, limit=limit)
    return [_to_run_response(run) for run in runs]


@router.get(
    "/events/{event_id}/reconciliation/conflicts",
    response_model=list[ReconciliationItemResponse],
    summary="List conflict items for manual review",
)
def list_reconciliation_conflicts(
    event_id: str,
    run_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
) -> list[ReconciliationItemResponse]:
    items = get_reconciliation_service().list_conflicts(event_id=event_id, run_id=run_id, limit=limit)
    return [_to_item_response(item) for item in items]


@router.post(
    "/reconciliation/items/{item_id}/resolve",
    response_model=ReconciliationItemResponse,
    summary="Resolve one conflict item with manual override",
)
def resolve_reconciliation_conflict(item_id: str, request: ConflictResolutionRequest) -> ReconciliationItemResponse:
    try:
        item = get_reconciliation_service().resolve_conflict(
            item_id=item_id,
            actor=request.actor,
            resolution=request.resolution,
            note=request.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_item_response(item)