from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.services.event_block_config import EventBlockConfigService, set_event_block_config_service
from app.services.offline_queue import get_offline_queue_service
from app.middleware.request_timing import RequestTimingMiddleware
from app.services.scan_idempotency import ScanIdempotencyService
from app.services.scan_runtime import scan_runtime_store
from app.services.ticket_manifest import get_ticket_manifest_service
from app.services.sync_controls import WixSyncControlService, get_sync_control_service, set_sync_control_service
from app.services.worker_health import get_worker_health_service
from app.api.routes.checkins import set_scan_idempotency_service
from app.services.reset_audit import ResetAuditService, set_reset_audit_service
from app.services.wix_oauth import WixOAuthService, get_wix_oauth_service, set_wix_oauth_service


logger = logging.getLogger(__name__)
startup_logger = logging.getLogger("uvicorn.error")


async def _cleanup_loop() -> None:
    """Hourly background task: archive raw metrics >24h and purge archive >30d."""
    while True:
        await asyncio.sleep(3600)
        scan_runtime_store.cleanup_old_metrics()


async def _offline_queue_worker_loop() -> None:
    interval = max(1, get_settings().offline_queue_worker_interval_s)
    queue_service = get_offline_queue_service()
    worker_health = get_worker_health_service()
    worker_health.pulse("offline_queue_worker")
    while True:
        await asyncio.sleep(interval)
        queue_service.process_pending_once(max_items=20)
        worker_health.pulse("offline_queue_worker")


async def _manifest_sync_loop() -> None:
    interval = max(1, get_settings().manifest_sync_worker_interval_s)
    sync_controls = get_sync_control_service()
    # Ensure service is initialized even before first control is enabled.
    get_ticket_manifest_service()
    worker_health = get_worker_health_service()
    worker_health.pulse("manifest_sync_worker")
    while True:
        await asyncio.sleep(interval)
        sync_controls.process_due_syncs(max_items=25)
        worker_health.pulse("manifest_sync_worker")


async def _oauth_token_refresh_loop() -> None:
    """Proactively keep the Wix OAuth token fresh (checks every 60 s, refreshes when ≤60 s remain)."""
    while True:
        await asyncio.sleep(60)
        try:
            service = get_wix_oauth_service()
            if service.is_configured():
                service.get_access_token()  # auto-refreshes when near expiry
        except Exception as exc:  # noqa: BLE001
            logger.warning("oauth.background_refresh.failed", extra={"error": str(exc)})


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    # Initialize scan idempotency service
    settings = get_settings()
    startup_logger.info("scan_idempotency initialized with db_url=%s", settings.database_url)
    scan_idempotency = ScanIdempotencyService(db_url=settings.database_url)
    set_scan_idempotency_service(scan_idempotency)

    # Initialize event block config service
    event_block_svc = EventBlockConfigService()
    set_event_block_config_service(event_block_svc)
    startup_logger.info("event_block_config initialized")

    # Initialize reset audit service (Postgres)
    reset_audit_svc = ResetAuditService()
    set_reset_audit_service(reset_audit_svc)
    startup_logger.info("reset_audit initialized with database_url=%s", settings.database_url)

    # Initialize sync controls service (Postgres)
    sync_controls_svc = WixSyncControlService(settings=settings)
    set_sync_control_service(sync_controls_svc)
    startup_logger.info("sync_controls initialized with database_url=%s", settings.database_url)

    # Initialize Wix OAuth service (used when credential_provider_mode = "oauth")
    oauth_svc = WixOAuthService(settings)
    set_wix_oauth_service(oauth_svc)
    startup_logger.info(
        "wix_oauth initialized (configured=%s)",
        oauth_svc.is_configured(),
    )

    cleanup_task = asyncio.create_task(_cleanup_loop())
    queue_worker_task = asyncio.create_task(_offline_queue_worker_loop())
    manifest_sync_task = asyncio.create_task(_manifest_sync_loop())
    oauth_refresh_task: asyncio.Task | None = None
    if settings.credential_provider_mode == "oauth":
        oauth_refresh_task = asyncio.create_task(_oauth_token_refresh_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        queue_worker_task.cancel()
        manifest_sync_task.cancel()
        if oauth_refresh_task is not None:
            oauth_refresh_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        try:
            await queue_worker_task
        except asyncio.CancelledError:
            pass
        try:
            await manifest_sync_task
        except asyncio.CancelledError:
            pass
        if oauth_refresh_task is not None:
            try:
                await oauth_refresh_task
            except asyncio.CancelledError:
                pass


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    openapi_url=f"{settings.api_v1_prefix}/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(RequestTimingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
