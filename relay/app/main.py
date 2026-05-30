from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.services.cloud_forwarder import get_cloud_forwarder
from app.services.relay_forwarder import RelayForwarder
from app.services.relay_queue import RelayQueueService
from app.services.relay_queue_service import set_relay_queue

logger = logging.getLogger(__name__)
settings = get_settings()

# Global forwarder task (simplified for single-instance relay)
_forwarder_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    global _forwarder_task

    # Startup
    relay_queue = RelayQueueService(db_path=settings.queue_db_path)
    set_relay_queue(relay_queue)

    relay_forwarder = RelayForwarder(
        queue_service=relay_queue,
        cloud_forwarder=get_cloud_forwarder(),
        base_backoff_ms=settings.forwarder_backoff_base_ms,
        max_backoff_ms=settings.forwarder_backoff_max_ms,
    )

    # Start background forwarder loop
    _forwarder_task = asyncio.create_task(relay_forwarder.run_loop(poll_interval_s=settings.forwarder_poll_interval_s))
    logger.info("relay.app.forwarder_started")

    yield

    # Shutdown
    relay_forwarder.stop()
    if _forwarder_task:
        _forwarder_task.cancel()
        try:
            await _forwarder_task
        except asyncio.CancelledError:
            pass
    logger.info("relay.app.forwarder_stopped")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    openapi_url=f"{settings.api_v1_prefix}/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)


if __name__ == "__main__":
    main()
