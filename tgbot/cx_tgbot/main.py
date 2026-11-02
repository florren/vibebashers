"""Отдельный transport process; без token/secret и в --offline нет сети."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx
import structlog
from aiogram import Bot
from aiogram.utils.token import TokenValidationError, validate_token

from cx_tgbot.backend import BackendClient
from cx_tgbot.polling import poll
from cx_tgbot.updates import dispatcher

log = structlog.get_logger(__name__)


class InvalidConfiguration(ValueError):
    pass


@dataclass(frozen=True)
class Configuration:
    token: str = field(repr=False)
    secret: bytes = field(repr=False)
    backend_url: str

    @classmethod
    def from_environment(cls, env: Mapping[str, str]) -> Configuration:
        if env.get("TGBOT_ENABLED", "false").lower() not in {"1", "true", "yes", "on"}:
            raise InvalidConfiguration("telegram_transport_disabled")
        token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
        secret = env.get("TGBOT_INTERNAL_SECRET", "").encode()
        backend_url = env.get("TGBOT_BACKEND_URL", "http://backend:8000").strip()
        try:
            validate_token(token)
        except (TokenValidationError, ValueError):
            raise InvalidConfiguration("telegram_token_missing_or_invalid") from None
        if len(secret) < 32:
            raise InvalidConfiguration("telegram_internal_secret_too_short")
        try:
            url = urlsplit(backend_url)
            valid = (
                url.scheme in {"http", "https"}
                and bool(url.hostname)
                and url.username is None
                and url.password is None
                and url.path in {"", "/"}
                and not url.query
                and not url.fragment
                and url.port != 0
            )
        except ValueError:
            valid = False
        if not valid:
            raise InvalidConfiguration("telegram_backend_origin_invalid") from None
        return cls(token, secret, backend_url.rstrip("/"))


class SDKRecordFilter(logging.Filter):
    """SDK records сохраняют уровень/источник, но не произвольный upstream echo.

    Bot API token входит в URL, а aiogram exception может содержать response.
    Не даём ему попасть в stderr ни через args, ни через traceback.
    Собственные события transport имеют только фиксированные имена/type/status.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name.startswith(("aiogram", "aiohttp", "httpx", "httpcore")):
            record.msg, record.args = "telegram_transport_sdk_event", ()
            record.exc_info, record.exc_text, record.stack_info = None, None, None
        return True


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.addFilter(SDKRecordFilter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    structlog.configure(
        processors=[structlog.processors.add_log_level, structlog.processors.JSONRenderer()],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )


async def run(config: Configuration) -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    owner = asyncio.current_task()

    def terminate() -> None:
        stop.set()
        if owner is not None:
            owner.cancel()

    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, terminate)
    try:
        # Backend origin задаётся оператором, redirect и proxy environment выключены.
        async with httpx.AsyncClient(
            base_url=config.backend_url, timeout=10, follow_redirects=False, trust_env=False
        ) as http:
            async with Bot(token=config.token) as bot:
                return await poll(bot, dispatcher(BackendClient(http, config.secret)), stop=stop)
    except asyncio.CancelledError:
        if not stop.is_set():
            raise
        log.info("telegram_transport_stopped")
        return 0
    finally:
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(signum)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Проверить offline exit без env и сети")
    args = parser.parse_args(argv)
    configure_logging()
    if args.offline:
        log.info("telegram_transport_offline")
        return 0
    try:
        config = Configuration.from_environment(os.environ)
    except InvalidConfiguration as exc:
        log.error("telegram_transport_configuration_invalid", code=str(exc))
        return 2
    try:
        return asyncio.run(run(config))
    except Exception as exc:
        # Ошибка останавливает polling без следующего offset; raw text/URL не выводятся.
        log.error("telegram_transport_failed", error_type=type(exc).__name__)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
