from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.scan_runtime import scan_runtime_store

router = APIRouter()

_PUSH_INTERVAL_SECONDS = 5


@router.websocket("/ws/health")
async def ws_health(websocket: WebSocket) -> None:
    """Push real-time scanner health updates to the client every 5 seconds.

    Falls back gracefully: if the client disconnects the loop exits cleanly.
    The client can also use the REST ``GET /api/health/scanner`` endpoint as
    a polling fallback when WebSockets are unavailable.
    """
    await websocket.accept()
    try:
        while True:
            summary = scan_runtime_store.metrics_summary()
            payload = {
                "backend_status": str(summary.get("status", "yellow")),
                "in_flight": int(summary["in_flight"]),
                "success_rate": float(summary["success_rate"]),
                "last_20_response_times": list(summary["last_20_response_times"]),
                "min_ms": int(summary["min_ms"]),
                "max_ms": int(summary["max_ms"]),
                "avg_ms": float(summary["avg_ms"]),
                "p50_ms": float(summary["p50_ms"]),
                "p95_ms": float(summary["p95_ms"]),
                "p99_ms": float(summary["p99_ms"]),
                "last_check_ts": int(summary["last_check_ts"]),
            }
            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(_PUSH_INTERVAL_SECONDS)
    except WebSocketDisconnect:
        pass
