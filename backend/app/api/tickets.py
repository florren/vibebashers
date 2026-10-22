"""Роутер тега `tickets` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка T-214."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.errors import NotImplementedYet

router = APIRouter(tags=["tickets"])


@router.get("/api/tickets", summary="[ДТЗ FR-3.2] Тикетница: представление v_tickets над инцидентами в терминах ДТЗ")
async def get_tickets(request: Request) -> Any:
    raise NotImplementedYet("T-214")


@router.get("/api/tickets/{ticket_id}", summary="Тикет с цепочкой решений агента и эскалациями")
async def get_tickets_ticket_id(request: Request) -> Any:
    raise NotImplementedYet("T-214")
