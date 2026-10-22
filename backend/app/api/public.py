"""Роутер тега `public` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка T-119."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.errors import NotImplementedYet

router = APIRouter(tags=["public"])


@router.post("/api/public/claim", summary="Лендинг потенциального/неидентифицированного клиента")
async def post_public_claim(request: Request) -> Any:
    raise NotImplementedYet("T-119")


@router.get("/api/public/captcha", summary="Арифметическая антибот-проверка")
async def get_public_captcha(request: Request) -> Any:
    raise NotImplementedYet("T-119")


@router.get("/api/public/track/{token}", summary="Таймлайн обращения понятным языком")
async def get_public_track_token(request: Request) -> Any:
    raise NotImplementedYet("T-119")


@router.post("/api/public/track/{token}", summary="«Дополнить обращение» (ответ на уточняющий вопрос агента)")
async def post_public_track_token(request: Request) -> Any:
    raise NotImplementedYet("T-119")


@router.get("/api/public/bot/qr", summary="QR-код на Telegram-бота для жюри-режима и README")
async def get_public_bot_qr(request: Request) -> Any:
    raise NotImplementedYet("T-119")


@router.post(
    "/api/internal/tgbot/inbound", summary="Внутренний приём сообщений от сервиса tgbot (только из docker-сети)"
)
async def post_internal_tgbot_inbound(request: Request) -> Any:
    raise NotImplementedYet("T-119")


@router.post("/api/public/reviews", summary="Публикация отзыва на эмуляторе внешней площадки (BRD FR 1.1)")
async def post_public_reviews(request: Request) -> Any:
    raise NotImplementedYet("T-119")


@router.get("/api/public/feed", summary="Лента эмулятора площадки (без роли)")
async def get_public_feed(request: Request) -> Any:
    raise NotImplementedYet("T-119")


@router.get("/api/public/feed/{post_id}", summary="Пост с веткой ответов и временем реакции агента")
async def get_public_feed_post_id(request: Request) -> Any:
    raise NotImplementedYet("T-119")


@router.get(
    "/api/public/mock-social-feed",
    summary="[ДТЗ FR-1.2] Встроенная mock-лента соцсети для polling-адаптера demo-профиля (массив сообщений единой схемы, курсор since)",
)
async def get_public_mock_social_feed(request: Request) -> Any:
    raise NotImplementedYet("T-119")
