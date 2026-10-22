"""Роутер тега `stt` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка T-181."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.errors import NotImplementedYet

router = APIRouter(tags=["stt"])


@router.get("/api/stt/providers", summary="Доступные STT-провайдеры, их возможности и состояние")
async def get_stt_providers(request: Request) -> Any:
    raise NotImplementedYet("T-181")


@router.post("/api/stt/test", summary="Проверка провайдера на коротком предзаписанном файле (мастер, шаг 4)")
async def post_stt_test(request: Request) -> Any:
    raise NotImplementedYet("T-181")
