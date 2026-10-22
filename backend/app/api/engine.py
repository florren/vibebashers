"""Роутер тега `engine` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка T-106."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.errors import NotImplementedYet

router = APIRouter(tags=["engine"])


@router.get("/api/agent/runs", summary="Запуски агента (живая трассировка)")
async def get_agent_runs(request: Request) -> Any:
    raise NotImplementedYet("T-106")


@router.get(
    "/api/agent/runs/{id}", summary="Запуск с деревом шагов (промпты, ответы, инструменты, токены, латентность)"
)
async def get_agent_runs_id(request: Request) -> Any:
    raise NotImplementedYet("T-106")


@router.get("/api/agent/graph", summary="Схема графа LangGraph (узлы, рёбра) для подсветки текущего узла")
async def get_agent_graph(request: Request) -> Any:
    raise NotImplementedYet("T-106")


@router.post(
    "/api/agent/compare", summary="Панель «ИИ против правил» — один текст через LLM-профиль и mock параллельно"
)
async def post_agent_compare(request: Request) -> Any:
    raise NotImplementedYet("T-106")


@router.get("/api/engine/entity-graph", summary="Граф сущностей клиент–сигнал–инцидент–система–команда (React Flow)")
async def get_engine_entity_graph(request: Request) -> Any:
    raise NotImplementedYet("T-106")


@router.get("/api/engine/db/tables", summary="Счётчики строк по таблицам (реальное время)")
async def get_engine_db_tables(request: Request) -> Any:
    raise NotImplementedYet("T-106")


@router.get("/api/engine/db/tables/{name}/rows", summary="Последние записи таблицы (только чтение, allow-list таблиц)")
async def get_engine_db_tables_name_rows(request: Request) -> Any:
    raise NotImplementedYet("T-106")


@router.get("/api/engine/db/activity", summary="Лента INSERT/UPDATE/DELETE из db_activity_log")
async def get_engine_db_activity(request: Request) -> Any:
    raise NotImplementedYet("T-106")
