from fastapi import APIRouter

from app.api.routes.admin_bindings import router as admin_bindings_router
from app.api.routes.admin_credentials import router as admin_credentials_router
from app.api.routes.admin_event_blocks import router as admin_event_blocks_router
from app.api.routes.admin_reset import router as admin_reset_router
from app.api.routes.admin_readiness import router as admin_readiness_router
from app.api.routes.admin_reconciliation import router as admin_reconciliation_router
from app.api.routes.admin_scopes import router as admin_scopes_router
from app.api.routes.admin_sync_controls import router as admin_sync_controls_router
from app.api.routes.bootstrap import router as bootstrap_router
from app.api.routes.checkins import router as checkins_router
from app.api.routes.health import router as health_router
from app.api.routes.manifest import router as manifest_router
from app.api.routes.metrics import router as metrics_router
from app.api.routes.scanner_health import router as scanner_health_router
from app.api.routes.wix_webhooks import router as wix_webhooks_router
from app.api.routes.ws_checkins import router as ws_checkins_router
from app.api.routes.ws_health import router as ws_health_router

api_router = APIRouter()
api_router.include_router(admin_bindings_router, tags=["admin-bindings"])
api_router.include_router(admin_event_blocks_router, tags=["admin-event-blocks"])
api_router.include_router(admin_readiness_router, tags=["admin-readiness"])
api_router.include_router(admin_reconciliation_router, tags=["admin-reconciliation"])
api_router.include_router(admin_scopes_router, tags=["admin-scopes"])
api_router.include_router(admin_sync_controls_router, tags=["admin-sync-controls"])
api_router.include_router(admin_credentials_router, tags=["admin-credentials"])
api_router.include_router(admin_reset_router, tags=["admin-reset"])
api_router.include_router(health_router, tags=["health"])
api_router.include_router(scanner_health_router, tags=["scanner-health"])
api_router.include_router(checkins_router, tags=["checkins"])
api_router.include_router(metrics_router, tags=["metrics"])
api_router.include_router(ws_health_router, tags=["ws-health"])
api_router.include_router(ws_checkins_router, tags=["ws-checkins"])
api_router.include_router(bootstrap_router, tags=["bootstrap"])
api_router.include_router(manifest_router, tags=["manifest"])
api_router.include_router(wix_webhooks_router, tags=["wix-webhooks"])

