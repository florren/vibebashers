"""Роутер тега `setup` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка T-009."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.errors import NotImplementedYet

router = APIRouter(tags=["setup"])


@router.get("/api/setup/status", summary="Состояние мастера")
async def get_setup_status(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.post("/api/setup", summary="Завершить мастер («Готово»)")
async def post_setup(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.put("/api/setup", summary="Сохранить шаг(и) мастера")
async def put_setup(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.post("/api/setup/test-llm", summary="Проверить подключение к LLM-профилю (кнопка «Проверить подключение»)")
async def post_setup_test_llm(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.post("/api/setup/test-tgbot", summary="Проверить токен Telegram-бота (getMe)")
async def post_setup_test_tgbot(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.get("/api/setup/generate", summary="Прогресс генерации и матрица покрытия")
async def get_setup_generate(request: Request) -> Any:
    raise NotImplementedYet("T-009")


@router.post("/api/setup/generate", summary="Запустить генерацию синтетических данных (профиль lite/demo/stress)")
async def post_setup_generate(request: Request) -> Any:
    raise NotImplementedYet("T-009")
