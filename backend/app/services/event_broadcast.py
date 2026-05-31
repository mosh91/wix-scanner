from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class EventBroadcastService:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, *, event_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[event_id].add(websocket)

    async def disconnect(self, *, event_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            bucket = self._connections.get(event_id)
            if not bucket:
                return
            bucket.discard(websocket)
            if not bucket:
                self._connections.pop(event_id, None)

    async def broadcast(self, *, event_id: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self._connections.get(event_id, set()))
        if not targets:
            return

        body = json.dumps(payload)
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(body)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                bucket = self._connections.get(event_id)
                if bucket is None:
                    return
                for ws in dead:
                    bucket.discard(ws)
                if not bucket:
                    self._connections.pop(event_id, None)


event_broadcast_service = EventBroadcastService()
