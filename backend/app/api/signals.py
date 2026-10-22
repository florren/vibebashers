"""Роутер тега `signals` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка T-087."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.errors import NotImplementedYet

router = APIRouter(tags=["signals"])


@router.get("/api/signals", summary="Лента сигналов с фильтрами")
async def get_signals(request: Request) -> Any:
    raise NotImplementedYet("T-087")


@router.post("/api/signals", summary="Жюри-режим — ввести сообщение клиента вручную")
async def post_signals(request: Request) -> Any:
    raise NotImplementedYet("T-087")


@router.get("/api/signals/{id}", summary="Сигнал с классификацией, решением, связанными инцидентами и запусками агента")
async def get_signals_id(request: Request) -> Any:
    raise NotImplementedYet("T-087")


@router.get("/api/signals/deferred", summary="Отложенные («спящие») обращения с причиной и временем пробуждения")
async def get_signals_deferred(request: Request) -> Any:
    raise NotImplementedYet("T-087")
