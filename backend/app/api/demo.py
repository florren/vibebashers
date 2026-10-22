"""Роутер тега `demo` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка T-194."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.errors import NotImplementedYet

router = APIRouter(tags=["demo"])


@router.get("/api/demo/status", summary="Состояние сети и провайдеров, текущие режимы LLM/STT")
async def get_demo_status(request: Request) -> Any:
    raise NotImplementedYet("T-194")


@router.post(
    "/api/demo/failover",
    summary="Ручное переключение режима (LLM live|replay|mock; STT mic|file|transcript; восстановить онлайн)",
)
async def post_demo_failover(request: Request) -> Any:
    raise NotImplementedYet("T-194")


@router.post(
    "/api/demo/play/{scenario_id}",
    summary="Запустить предзаписанный вход сценария (пост сценария 8, аудио/транскрипт сценария 9)",
)
async def post_demo_play_scenario_id(request: Request) -> Any:
    raise NotImplementedYet("T-194")


@router.get("/api/demo/assets", summary="Предзаписанные активы (аудио, транскрипты, посты, кассеты)")
async def get_demo_assets(request: Request) -> Any:
    raise NotImplementedYet("T-194")


@router.get("/api/cassettes", summary="Кассеты replay (сводка по сценариям и моделям)")
async def get_cassettes(request: Request) -> Any:
    raise NotImplementedYet("T-194")


@router.post("/api/cassettes/record", summary="Включить/выключить запись кассет (LLM_RECORD) для текущей сессии показа")
async def post_cassettes_record(request: Request) -> Any:
    raise NotImplementedYet("T-194")
