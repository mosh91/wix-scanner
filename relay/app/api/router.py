from __future__ import annotations

from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.api.routes.scans import router as scans_router

api_router = APIRouter()

api_router.include_router(health_router, tags=["health"])
api_router.include_router(scans_router, tags=["relay"])
