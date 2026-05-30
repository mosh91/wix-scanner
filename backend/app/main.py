from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.services.offline_queue import get_offline_queue_service
from app.middleware.request_timing import RequestTimingMiddleware
from app.services.scan_idempotency import ScanIdempotencyService
from app.services.scan_runtime import scan_runtime_store
from app.services.ticket_manifest import get_ticket_manifest_service
from app.api.routes.checkins import set_scan_idempotency_service


async def _cleanup_loop() -> None:
    """Hourly background task: archive raw metrics >24h and purge archive >30d."""
    while True:
        await asyncio.sleep(3600)
        scan_runtime_store.cleanup_old_metrics()


async def _offline_queue_worker_loop() -> None:
    interval = max(1, get_settings().offline_queue_worker_interval_s)
    queue_service = get_offline_queue_service()
    while True:
        await asyncio.sleep(interval)
        queue_service.process_pending_once(max_items=20)


async def _manifest_sync_loop() -> None:
    interval = 30
    manifest_service = get_ticket_manifest_service()
    while True:
        await asyncio.sleep(interval)
        manifest_service.sync_tracked_events_once()


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    # Initialize scan idempotency service
    settings = get_settings()
    scan_idempotency = ScanIdempotencyService(db_url=settings.database_url)
    set_scan_idempotency_service(scan_idempotency)

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
