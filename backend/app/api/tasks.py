"""Роутер тега `tasks` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка T-079."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.errors import NotImplementedYet

router = APIRouter(tags=["tasks"])


@router.get("/api/tasks", summary="Задачи (подарки, звонки, ручные проверки, напоминания об отчётах)")
async def get_tasks(request: Request) -> Any:
    raise NotImplementedYet("T-079")


@router.post(
    "/api/tasks/{id}", summary="Подтвердить / изменить / отклонить задачу (например, заменить привилегию в подарке)"
)
async def post_tasks_id(request: Request) -> Any:
    raise NotImplementedYet("T-079")
