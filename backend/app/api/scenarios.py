"""Роутер тега `scenarios` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка T-042."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.errors import NotImplementedYet

router = APIRouter(tags=["scenarios"])


@router.get("/api/scenarios", summary="Список демо-сценариев")
async def get_scenarios(request: Request) -> Any:
    raise NotImplementedYet("T-042")


@router.post("/api/scenarios/{id}/run", summary="Запустить сценарий как отдельный запуск эмуляции (ТЗ 4.6, 18)")
async def post_scenarios_id_run(request: Request) -> Any:
    raise NotImplementedYet("T-042")
