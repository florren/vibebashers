"""Дымовой прогон LLM-цепочки: `python -m app.llm.smoke [--text ...] [--schema agent/classification] [--context fast_path]`.

Выводит через structlog: провайдер, попытки failover, usage и объект ответа. Работает без сети (mock) и с ключами из .env."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from app.config import get_settings
from app.contracts.registry import deref
from app.llm.base import LLMProfile, Message
from app.llm.failover import build_chain, default_profile, profile_by_code
from app.logging import configure_logging, get_logger

log = get_logger(__name__)

PROFILE_CHOICES = ("or_nemotron_ultra", "or_owl_alpha", "or_gpt_oss_120b", "local_openai")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--text", default="Спасибо, что списали комиссию за QR-оплату, которой «нет» по тарифу)) Отличный сервис."
    )
    ap.add_argument("--schema", default="agent/classification")
    ap.add_argument("--context", default="default", choices=["fast_path", "detector", "default"])
    ap.add_argument("--profile", default=None, choices=list(PROFILE_CHOICES))
    return ap.parse_args(argv)


def resolve_profile(settings: Any, profile_code: str | None) -> LLMProfile:
    """Без --profile поведение прежнее: профиль основного провайдера из настроек."""
    if profile_code:
        return profile_by_code(settings, profile_code)
    return default_profile(settings)


async def run(text: str, schema_name: str, context: str, profile_code: str | None = None) -> int:
    s = get_settings()
    configure_logging(s.app_env)
    chain = build_chain(s)
    profile = resolve_profile(s, profile_code)
    messages: list[Message] = [
        {"role": "system", "content": "Ты — агент банка по работе с клиентскими сигналами. Классифицируй обращение."},
        {"role": "user", "content": text},
    ]
    res = await chain.complete_structured(messages, deref(schema_name), profile, context=context)
    log.info(
        "smoke_result",
        provider=res.provider,
        chain=chain.names,
        attempts=[a.__dict__ for a in res.attempts],
        usage=res.usage.as_dict(),
    )
    log.info("smoke_object", obj=json.dumps(res.obj, ensure_ascii=False))
    return 0 if res.obj else 1


def main() -> None:
    a = parse_args()
    raise SystemExit(asyncio.run(run(a.text, a.schema, a.context, a.profile)))


if __name__ == "__main__":
    main()
