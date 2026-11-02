"""Stateless aiogram adapter: диалог и дедупликация принадлежат backend."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from aiogram import Dispatcher, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, Update

from cx_tgbot.backend import BackendClient, BackendUnavailable

log = structlog.get_logger(__name__)
Sleep = Callable[[float], Awaitable[None]]


class BackendRejected(RuntimeError):
    def __init__(self, status: int | None) -> None:
        self.status = status
        super().__init__("telegram_backend_rejected_update")


async def forward(client: BackendClient, event: dict[str, Any], sleep: Sleep = asyncio.sleep) -> None:
    """Не подтверждаем Telegram update, пока backend недоступен.

    При timeout повторяется тот же update_id; durable receipt исключает вторую
    обработку. Постоянная ошибка требует остановки polling без нового offset.
    """
    while True:
        try:
            result = await client.submit(event)
        except BackendUnavailable as exc:
            if exc.status is not None and exc.status < 500 and exc.status != 429:
                raise BackendRejected(exc.status) from None
            log.warning("telegram_backend_retry", status=exc.status)
            await sleep(2)
            continue
        if (
            result.get("accepted") is not True
            or type(result.get("update_id")) is not int
            or result["update_id"] != event["update_id"]
        ):
            raise BackendRejected(200)
        return


def dispatcher(client: BackendClient, *, sleep: Sleep = asyncio.sleep) -> Dispatcher:
    router = Router(name="backend_transport")

    @router.message()
    async def message_turn(message: Message, event_update: Update) -> None:
        if message.chat.type != ChatType.PRIVATE or (message.from_user and message.from_user.is_bot):
            return
        language = message.from_user.language_code if message.from_user else None
        await forward(
            client,
            {
                "chat_id": message.chat.id,
                "kind": "message",
                "text": message.text or "",
                "payload": {
                    "message_id": message.message_id,
                    "language_code": "en" if language and language.startswith("en") else "ru",
                },
                "update_id": event_update.update_id,
            },
            sleep,
        )

    @router.callback_query()
    async def callback_turn(callback: CallbackQuery, event_update: Update) -> None:
        message = callback.message
        if (
            message is None
            or message.chat.type != ChatType.PRIVATE
            or callback.data is None
            or callback.from_user.is_bot
        ):
            return
        await forward(
            client,
            {
                "chat_id": message.chat.id,
                "kind": "callback",
                "text": "",
                "update_id": event_update.update_id,
                "payload": {
                    "message_id": message.message_id,
                    "callback_data": callback.data,
                    "language_code": "en" if (callback.from_user.language_code or "").startswith("en") else "ru",
                },
            },
            sleep,
        )
        try:
            await callback.answer(cache_time=0)
        except TelegramAPIError as exc:
            # Ошибка spinner ack не отменяет уже зафиксированный backend receipt.
            log.warning("telegram_callback_ack_failed", error_type=type(exc).__name__)

    result = Dispatcher(disable_fsm=True)
    result.include_router(router)
    return result
