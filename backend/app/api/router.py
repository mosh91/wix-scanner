from fastapi import APIRouter

from app.api.routes.bootstrap import router as bootstrap_router
from app.api.routes.checkins import router as checkins_router
from app.api.routes.health import router as health_router
from app.api.routes.manifest import router as manifest_router
from app.api.routes.metrics import router as metrics_router
from app.api.routes.scanner_health import router as scanner_health_router
from app.api.routes.ws_health import router as ws_health_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(scanner_health_router, tags=["scanner-health"])
api_router.include_router(checkins_router, tags=["checkins"])
api_router.include_router(metrics_router, tags=["metrics"])
api_router.include_router(ws_health_router, tags=["ws-health"])
api_router.include_router(bootstrap_router, tags=["bootstrap"])
api_router.include_router(manifest_router, tags=["manifest"])

