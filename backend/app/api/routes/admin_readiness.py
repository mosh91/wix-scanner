from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.event_readiness import EventReadinessReport, ReadinessComponentStatus, get_event_readiness_service

router = APIRouter(prefix="/admin")


class ReadinessComponentResponse(BaseModel):
    name: str
    status: str
    message: str
    details: dict[str, object]


class EventReadinessResponse(BaseModel):
    event_id: str
    overall_status: str
    component_statuses: list[ReadinessComponentResponse]
    failed_checks: list[str]
    recommended_actions: list[str]
    evaluated_at: str
    readiness_acknowledged: bool = False


def _to_component_response(component: ReadinessComponentStatus) -> ReadinessComponentResponse:
    return ReadinessComponentResponse(
        name=component.name,
        status=component.status,
        message=component.message,
        details=component.details,
    )


def _to_readiness_response(report: EventReadinessReport) -> EventReadinessResponse:
    return EventReadinessResponse(
        event_id=report.event_id,
        overall_status=report.overall_status,
        component_statuses=[_to_component_response(component) for component in report.component_statuses],
        failed_checks=report.failed_checks,
        recommended_actions=report.recommended_actions,
        evaluated_at=report.evaluated_at,
        readiness_acknowledged=report.readiness_acknowledged,
    )


@router.get(
    "/events/{event_id}/readiness",
    response_model=EventReadinessResponse,
    summary="Evaluate event readiness before activation",
)
def get_event_readiness(event_id: str) -> EventReadinessResponse:
    report = get_event_readiness_service().evaluate(event_id=event_id)
    return _to_readiness_response(report)