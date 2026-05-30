from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.cloud_forwarder import get_cloud_forwarder

router = APIRouter(prefix="/health")


class HealthResponse(BaseModel):
    status: str
    relay_ready: bool
    cloud_reachable: bool
    cloud_details: dict[str, object] = Field(default_factory=dict)


@router.get("", response_model=HealthResponse)
def health_check() -> HealthResponse:
    forwarder = get_cloud_forwarder()
    cloud_health = forwarder.get_cloud_health()
    cloud_reachable = cloud_health.get("cloud_reachable", False)

    return HealthResponse(
        status="healthy" if cloud_reachable else "degraded",
        relay_ready=True,
        cloud_reachable=bool(cloud_reachable),
        cloud_details=cloud_health,
    )
