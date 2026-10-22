"""Роутер тега `incidents` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка T-089."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.errors import NotImplementedYet

router = APIRouter(tags=["incidents"])


@router.get("/api/incidents", summary="Инциденты (доска/таблица)")
async def get_incidents(request: Request) -> Any:
    raise NotImplementedYet("T-089")


@router.get("/api/incidents/{id}", summary="Карточка инцидента (сводка + клиент 360 + SLA + экономика)")
async def get_incidents_id(request: Request) -> Any:
    raise NotImplementedYet("T-089")


@router.get("/api/incidents/{id}/history", summary="История статусов")
async def get_incidents_id_history(request: Request) -> Any:
    raise NotImplementedYet("T-089")


@router.get(
    "/api/incidents/{id}/artifacts",
    summary="Документы команды (RCA, решение о фиксе, промежуточные отчёты, релиз, проверка)",
)
async def get_incidents_id_artifacts(request: Request) -> Any:
    raise NotImplementedYet("T-089")


@router.get("/api/incidents/{id}/signals", summary="Связанные сигналы и логи систем")
async def get_incidents_id_signals(request: Request) -> Any:
    raise NotImplementedYet("T-089")


@router.get("/api/incidents/{id}/communications", summary="Коммуникации с клиентом и реакции двойника")
async def get_incidents_id_communications(request: Request) -> Any:
    raise NotImplementedYet("T-089")


@router.get("/api/incidents/{id}/economics", summary="Развёрнутый расчёт dCLTV по инциденту (все множители)")
async def get_incidents_id_economics(request: Request) -> Any:
    raise NotImplementedYet("T-089")


@router.post("/api/incidents/{id}/actions", summary="Действие сотрудника CX над инцидентом")
async def post_incidents_id_actions(request: Request) -> Any:
    raise NotImplementedYet("T-089")


@router.get("/api/teams/load", summary="Нагрузка команд и соблюдение SLA (вкладка «Команды»)")
async def get_teams_load(request: Request) -> Any:
    raise NotImplementedYet("T-089")
