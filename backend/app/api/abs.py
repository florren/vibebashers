"""Роутер тега `abs` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка T-171."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.errors import NotImplementedYet

router = APIRouter(tags=["abs"])


@router.get("/api/abs/accounts/{client_id}", summary="Счета клиента и последние проводки (виджет «АБС (эмуляция)»)")
async def get_abs_accounts_client_id(request: Request) -> Any:
    raise NotImplementedYet("T-171")


@router.get("/api/abs/ledger", summary="Проводки с фильтрами (для экрана «Данные в БД» и проверок)")
async def get_abs_ledger(request: Request) -> Any:
    raise NotImplementedYet("T-171")


@router.post("/api/abs/refunds", summary="Возврат по решению человека (массовый или сверх лимита автономии)")
async def post_abs_refunds(request: Request) -> Any:
    raise NotImplementedYet("T-171")
