"""T-048: бюджет платных OpenRouter-вызовов из settings.llm, отказ при неизвестном состоянии."""

from __future__ import annotations

import math
from typing import Any

import psycopg

from app.db.session import psycopg_dsn
from app.llm.base import ProviderError


def budget_value(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ProviderError("quota", "бюджет OpenRouter неизвестен или некорректен")
    return float(value)


async def load_openrouter_budget(default: float) -> float:
    """Отсутствующий override → ENV/default10; ошибка БД или некорректный override → запрет."""
    try:
        async with await psycopg.AsyncConnection.connect(psycopg_dsn(), connect_timeout=3) as conn:
            await conn.execute("set transaction read only")
            row = await (await conn.execute("select value from settings where key='llm'")).fetchone()
    except psycopg.Error as exc:
        raise ProviderError("quota", "не удалось проверить бюджет OpenRouter в настройках") from exc
    if row is None:
        return budget_value(default)
    settings = row[0]
    if not isinstance(settings, dict):
        raise ProviderError("quota", "настройки бюджета OpenRouter некорректны")
    return budget_value(settings.get("openrouter_budget_usd", default))
