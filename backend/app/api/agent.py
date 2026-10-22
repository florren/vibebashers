"""Роутер тега `agent` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка T-214."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.errors import NotImplementedYet

router = APIRouter(tags=["agent"])


@router.get(
    "/api/agent/runs/{id}/decision-chain",
    summary="[ДТЗ FR-3.5] Компактная цепочка решений «инструмент → аргументы → почему» (JSON или Markdown)",
)
async def get_agent_runs_id_decision_chain(request: Request) -> Any:
    raise NotImplementedYet("T-214")
