from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings

router = APIRouter(prefix="/health")


class HealthResponse(BaseModel):
    status: str
    service: str
    environment: str
    version: str


@router.get("", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        environment=settings.environment,
        version="0.1.0",
    )
