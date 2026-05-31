from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.event_broadcast import event_broadcast_service

router = APIRouter()


@router.websocket("/ws/events/{event_id}")
async def ws_event_checkins(websocket: WebSocket, event_id: str) -> None:
    await event_broadcast_service.connect(event_id=event_id, websocket=websocket)
    try:
        while True:
            # Keep socket open; clients may optionally send keepalive messages.
            await websocket.receive_text()
    except WebSocketDisconnect:
        await event_broadcast_service.disconnect(event_id=event_id, websocket=websocket)
