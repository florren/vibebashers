"""Роутер тега `feed` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка T-176."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.errors import NotImplementedYet

router = APIRouter(tags=["feed"])


@router.post("/api/feed/{post_id}/reply", summary="Ручной публичный ответ сотрудника CX (после HITL или вместо агента)")
async def post_feed_post_id_reply(request: Request) -> Any:
    raise NotImplementedYet("T-176")


@router.get("/api/feed/stats", summary="Статистика живого контура (v_feed_latency)")
async def get_feed_stats(request: Request) -> Any:
    raise NotImplementedYet("T-176")
