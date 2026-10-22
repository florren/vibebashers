"""Роутер тега `hitl` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка T-077."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.errors import NotImplementedYet

router = APIRouter(tags=["hitl"])


@router.get("/api/hitl/queue", summary="Очередь «Требует решения»")
async def get_hitl_queue(request: Request) -> Any:
    raise NotImplementedYet("T-077")


@router.get("/api/hitl/{id}", summary="Карточка HITL (сигнал, контекст, предложение агента, варианты)")
async def get_hitl_id(request: Request) -> Any:
    raise NotImplementedYet("T-077")


@router.post("/api/hitl/{id}", summary="Решение человека — возвращается в граф агента")
async def post_hitl_id(request: Request) -> Any:
    raise NotImplementedYet("T-077")
