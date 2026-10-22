"""/ws/stream — единый WebSocket (OpenAPI 1.4.0). Heartbeat каждые 20 с. /ws/audio/{session_id} — карточка T-181."""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.realtime.hub import TOPICS, hub

router = APIRouter()
HEARTBEAT_S = 20


@router.websocket("/ws/stream")
async def ws_stream(ws: WebSocket) -> None:
    client = await hub.connect(ws)

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_S)
            await ws.send_text(hub.message("system", "heartbeat", {"clients": hub.size}))

    hb = asyncio.create_task(heartbeat())
    try:
        await ws.send_text(hub.message("system", "hello", {"topics": sorted(TOPICS)}))
        while True:
            raw = await ws.receive_text()
            await hub.handle_command(client, raw)
    except WebSocketDisconnect:
        pass
    finally:
        hb.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await hb
        await hub.disconnect(ws)


@router.websocket("/ws/audio/{session_id}")
async def ws_audio(ws: WebSocket, session_id: int) -> None:
    await ws.accept()
    await ws.close(code=1011, reason="STT не реализован: карточка T-181")
