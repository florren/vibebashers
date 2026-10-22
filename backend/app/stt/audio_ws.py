"""`/ws/audio/{session_id}` (T-181/T-182): hello → ready; бинарные кадры PCM16 LE 16 кГц (1–2 канала) или текстовые сообщения
{type: text|speaker|end}; ответы по `events/compliance/stt_result.schema.json` (partial | final | error | ready). Тишина 90 с → сессия закрывается."""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.logging import get_logger
from app.stt.live import SILENCE_CLOSE_S, LiveSession

log = get_logger(__name__)
router = APIRouter()


def _err(session_id: int, text: str) -> dict[str, Any]:
    return {
        "type": "error",
        "session_id": session_id,
        "channel": 1,
        "text": "",
        "seq": None,
        "words": [],
        "confidence": None,
        "latency_ms": None,
        "provider": None,
        "error": text,
    }


@router.websocket("/ws/audio/{session_id}")
async def ws_audio(ws: WebSocket, session_id: int) -> None:
    await ws.accept()
    live: LiveSession | None = None
    try:
        hello_raw = await asyncio.wait_for(ws.receive_text(), timeout=15)
        hello = json.loads(hello_raw or "{}")
        if hello.get("type") != "hello":
            await ws.send_json(_err(session_id, "ожидается hello"))
            await ws.close(code=1008)
            return
        try:
            live = LiveSession(
                ws.app,
                session_id,
                provider_code=hello.get("provider"),
                sample_rate=int(hello.get("sample_rate") or 16000),
                channels=int(hello.get("channels") or 1),
            )
        except LookupError as exc:
            await ws.send_json(_err(session_id, f"STT-провайдер недоступен: {exc}"))
            await ws.close(code=1008)
            return
        try:
            s = await live.start()
        except LookupError:
            await ws.send_json(_err(session_id, "сессия не найдена"))
            await ws.close(code=1008)
            return
        except RuntimeError as exc:
            await ws.send_json(_err(session_id, str(exc)))
            await ws.close(code=1008)
            return
        if hello.get("speaker"):
            live.set_speaker(str(hello["speaker"]))
        ready = live._msg("ready", "", 1)
        ready.update(
            {
                "session_public_id": s.public_id,
                "diarization_mode": live.mode,
                "model": getattr(getattr(live.provider, "model_dir", None), "name", None),
            }
        )
        await ws.send_json(ready)
        log.info(
            "stt_session_started",
            session_id=session_id,
            provider=live.provider.code,
            mode=live.mode,
            channels=live.channels,
        )
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=SILENCE_CLOSE_S)
            except TimeoutError:
                await ws.send_json(_err(session_id, f"тишина дольше {int(SILENCE_CLOSE_S)} с — сессия закрыта"))
                break
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                for out in await live.feed_audio(msg["bytes"]):
                    await ws.send_json(out)
            elif msg.get("text") is not None:
                try:
                    data = json.loads(msg["text"])
                except json.JSONDecodeError:
                    await ws.send_json(_err(session_id, "ожидается JSON"))
                    continue
                typ = data.get("type")
                if typ == "speaker":
                    live.set_speaker(str(data.get("speaker") or "employee"))
                elif typ == "text":
                    for out in await live.feed_text(
                        str(data.get("text") or ""),
                        is_final=bool(data.get("is_final", True)),
                        speaker=data.get("speaker"),
                    ):
                        await ws.send_json(out)
                elif typ == "end":
                    break
                elif typ == "ping":
                    await ws.send_json({"type": "pong"})
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception as exc:  # noqa: BLE001
        log.exception("stt_ws_failed", session_id=session_id)
        with contextlib.suppress(Exception):
            await ws.send_json(_err(session_id, str(exc)[:300]))
    finally:
        if live is not None:
            try:
                res = await live.finish()
                if res is not None:
                    with contextlib.suppress(Exception):
                        for out in res["finals"]:
                            await ws.send_json(out)
                        await ws.send_json({"type": "closed", "session_id": session_id, "report": res["report"]})
            except Exception:  # noqa: BLE001
                log.exception("stt_session_finish_failed", session_id=session_id)
        with contextlib.suppress(Exception):
            await ws.close()
