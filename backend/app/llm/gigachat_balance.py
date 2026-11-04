"""Provider package balance is independent from application session usage."""

from typing import Any

from app.llm.base import ProviderError

# Package names returned by /balance differ from inference model IDs.
PACKAGES = {
    "GigaChat": "GigaChat",
    "GigaChat-2": "GigaChat",
    "GigaChat-3-Lightning": "GigaChat",
    "GigaChat-Pro": "GigaChat-Pro",
    "GigaChat-2-Pro": "GigaChat-Pro",
    "GigaChat-3-Pro": "GigaChat-Pro",
    "GigaChat-Max": "GigaChat-Max",
    "GigaChat-2-Max": "GigaChat-Max",
    "GigaChat-3-Ultra": "GigaChat-Ultra",
}


def parse_balance(body: Any) -> dict[str, int]:
    rows = body.get("balance") if isinstance(body, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ProviderError("bad_output", "balance: отсутствуют остатки пакетов")
    result: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ProviderError("bad_output", "balance: некорректный пакет")
        name, value = row.get("usage"), row.get("value")
        if (
            not isinstance(name, str)
            or not name
            or len(name) > 100
            or type(value) is not int
            or not 0 <= value <= 2**63 - 1
            or name in result
        ):
            raise ProviderError("bad_output", "balance: некорректный или повторный остаток")
        result[name] = value
    return result


def require_balance(balances: dict[str, int], model: str) -> int:
    package = PACKAGES.get(model.split(":", 1)[0])
    if package is None or package not in balances:
        raise ProviderError("quota", "balance: пакет выбранной модели не подтверждён")
    remaining = balances[package]
    if remaining <= 0:
        raise ProviderError("quota", "balance: пакет выбранной модели исчерпан")
    return remaining
