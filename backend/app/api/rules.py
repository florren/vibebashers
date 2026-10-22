"""Роутер тега `rules` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка T-172."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.errors import NotImplementedYet

router = APIRouter(tags=["rules"])


@router.get("/api/rules", summary="Список бизнес-правил")
async def get_rules(request: Request) -> Any:
    raise NotImplementedYet("T-172")


@router.put(
    "/api/rules",
    summary="Полная замена набора правил (экран /settings → Правила); версия каждого изменённого правила увеличивается",
)
async def put_rules(request: Request) -> Any:
    raise NotImplementedYet("T-172")


@router.post("/api/rules/evaluate", summary="Проверить правила для операции/клиента (отладка, панель Log)")
async def post_rules_evaluate(request: Request) -> Any:
    raise NotImplementedYet("T-172")


@router.get("/api/rules/evaluations", summary="История срабатываний правил")
async def get_rules_evaluations(request: Request) -> Any:
    raise NotImplementedYet("T-172")
