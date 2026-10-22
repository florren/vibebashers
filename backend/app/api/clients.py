"""Роутер тега `clients` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка T-091."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.errors import NotImplementedYet

router = APIRouter(tags=["clients"])


@router.get("/api/clients", summary="Поиск клиента (для жюри-режима и фильтров)")
async def get_clients(request: Request) -> Any:
    raise NotImplementedYet("T-091")


@router.get(
    "/api/clients/{id}/360",
    summary="Клиент 360 — профиль, продукты, операции, сигналы, инциденты, состояние и стиль коммуникации",
)
async def get_clients_id_360(request: Request) -> Any:
    raise NotImplementedYet("T-091")
