from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path
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
from app.services.worker_health import get_worker_health_service
from app.api.routes.checkins import set_scan_idempotency_service


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
    interval = 30
    manifest_service = get_ticket_manifest_service()
    worker_health = get_worker_health_service()
    worker_health.pulse("manifest_sync_worker")
    while True:
        await asyncio.sleep(interval)
        manifest_service.sync_tracked_events_once()
        worker_health.pulse("manifest_sync_worker")


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    # Initialize scan idempotency service
    settings = get_settings()
    database_url = getattr(settings, "database_url", None)
    if not database_url:
        default_scan_db = Path("./data/scan_idempotency.db")
        default_scan_db.parent.mkdir(parents=True, exist_ok=True)
        database_url = f"sqlite:///{default_scan_db.resolve()}"
    startup_logger.info("scan_idempotency initialized with db_url=%s", database_url)
    scan_idempotency = ScanIdempotencyService(db_url=database_url)
    set_scan_idempotency_service(scan_idempotency)

    # Initialize event block config service
    event_block_svc = EventBlockConfigService(db_path=settings.event_block_config_db_path)
    set_event_block_config_service(event_block_svc)
    startup_logger.info("event_block_config initialized with db_path=%s", settings.event_block_config_db_path)

    cleanup_task = asyncio.create_task(_cleanup_loop())
    queue_worker_task = asyncio.create_task(_offline_queue_worker_loop())
    manifest_sync_task = asyncio.create_task(_manifest_sync_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        queue_worker_task.cancel()
        manifest_sync_task.cancel()
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
