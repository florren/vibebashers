"""Long polling через публичные aiogram API с подтверждением после backend receipt."""

from __future__ import annotations

import asyncio

import structlog
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError, TelegramRetryAfter, TelegramServerError

from cx_tgbot.updates import BackendRejected, Sleep

log = structlog.get_logger(__name__)


async def poll(
    bot: Bot,
    dispatcher: Dispatcher,
    *,
    stop: asyncio.Event,
    sleep: Sleep = asyncio.sleep,
) -> int:
    """Offset живёт на стороне Telegram; после crash незавершённый batch повторяется.

    feed_update, в отличие от _process_update/start_polling, возвращает ошибку
    обработчика вызывающему коду. Не используем private SDK методы и не продвигаем
    offset после permanent backend error. Дубликаты принимает durable backend.
    """
    offset: int | None = None
    while not stop.is_set():
        try:
            updates = await bot.get_updates(
                offset=offset, limit=100, timeout=20, request_timeout=30, allowed_updates=["message", "callback_query"]
            )
        except TelegramRetryAfter as exc:
            log.warning("telegram_poll_rate_limited")
            await sleep(min(30, max(1, exc.retry_after)))
            continue
        except (TelegramNetworkError, TelegramServerError) as exc:
            log.warning("telegram_poll_retry", error_type=type(exc).__name__)
            await sleep(2)
            continue
        except TelegramAPIError as exc:
            log.error("telegram_poll_rejected", error_type=type(exc).__name__)
            return 2
        for update in updates:
            if stop.is_set():
                break
            try:
                await dispatcher.feed_update(bot, update)
            except BackendRejected as exc:
                log.error("telegram_backend_rejected", status=exc.status)
                return 2
            offset = update.update_id + 1
    return 0
