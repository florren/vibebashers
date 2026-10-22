"""Роутер тега `escalations` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка T-213."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.errors import NotImplementedYet

router = APIRouter(tags=["escalations"])


@router.get("/api/escalations", summary="[ДТЗ FR-3.4] Очередь эскалаций руководителю")
async def get_escalations(request: Request) -> Any:
    raise NotImplementedYet("T-213")


@router.post("/api/escalations", summary="Ручная эскалация оператором (created_by = human)")
async def post_escalations(request: Request) -> Any:
    raise NotImplementedYet("T-213")


@router.get("/api/escalations/{id}", summary="Эскалация с контекстом (сигнал, тикет, цепочка решений)")
async def get_escalations_id(request: Request) -> Any:
    raise NotImplementedYet("T-213")


@router.post(
    "/api/escalations/{id}/ack",
    summary="Руководитель принял эскалацию (acknowledged) или закрыл (resolved | dismissed) с резолюцией",
)
async def post_escalations_id_ack(request: Request) -> Any:
    raise NotImplementedYet("T-213")
