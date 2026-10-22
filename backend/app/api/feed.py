"""Роутер тега `feed` (T-176): ручной публичный ответ и статистика живого контура."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api._compliance_support import run_context
from app.api.common import db, resolve_run_id
from app.feed import service as feed_svc

router = APIRouter(tags=["feed"])


class ReplyBody(BaseModel):
    text: str = Field(min_length=5, max_length=1500)
    incident_id: int | None = None


@router.post(
    "/api/feed/{post_id}/reply",
    summary="Ручной публичный ответ сотрудника CX (после HITL или вместо агента)",
    status_code=201,
)
async def post_feed_post_id_reply(request: Request, post_id: int, body: ReplyBody) -> Any:
    async with db() as conn:
        run_id, sim_time = await run_context(request, conn)
        try:
            res = await feed_svc.publish_reply(
                conn,
                run_id=run_id,
                post_id=post_id,
                text=body.text,
                author="human",
                sim_time=sim_time,
                incident_id=body.incident_id,
            )
        except feed_svc.FeedError as exc:
            raise HTTPException(status_code=404 if "не найден" in str(exc) else 422, detail=str(exc)) from exc
        row = await (
            await conn.execute(
                "select id, run_id, post_id, incident_id, agent_run_id, author, text, published_at, latency_ms, llm_source from external_replies where id = %s",
                (res["reply_id"],),
            )
        ).fetchone()
    return JSONResponse(jsonable_encoder(row), status_code=201)


@router.get("/api/feed/stats", summary="Статистика живого контура (v_feed_latency)")
async def get_feed_stats(run_id: str | None = Query(None)) -> Any:
    async with db() as conn:
        rid = await resolve_run_id(conn, run_id)
        stats = await feed_svc.feed_stats(conn, rid)
    return JSONResponse(jsonable_encoder(stats))
