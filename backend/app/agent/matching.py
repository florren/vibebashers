"""Матчинг клиента по косвенным данным (ТЗ 21.3, T-173).

Ник — 0,9; last4 — 0,5 / число совпадений; маскированный телефон — 0,6.
Город и продукт добавляют по 0,1, только если уже есть основной признак.
Итог — вероятностная комбинация основных признаков. identified — ровно один кандидат ≥ 0,8.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

THRESHOLD = 0.8
_PRIMARY = ("nickname", "card_last4", "masked_phone")
_ORDER = ("nickname", "card_last4", "masked_phone", "city", "product")
_LABELS = {
    "nickname": "ник",
    "card_last4": "карта",
    "masked_phone": "телефон",
    "city": "город",
    "product": "продукт",
}


@dataclass
class ClientView:
    client_id: int
    nicknames: set[str] = field(default_factory=set)
    last4: set[str] = field(default_factory=set)
    phone: str | None = None
    city: str | None = None
    products: set[str] = field(default_factory=set)


def norm_nick(value: str | None) -> str:
    return (value or "").strip().lstrip("@").lower()


def norm_phone(value: str | None) -> str:
    return "".join((value or "").split())


def nicknames_from_handles(raw: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(raw, dict):
        for item in raw.values():
            nick = norm_nick(item if isinstance(item, str) else None)
            if nick:
                found.add(nick)
    elif isinstance(raw, list):
        for item in raw:
            handle = item.get("handle") if isinstance(item, dict) else item
            nick = norm_nick(handle if isinstance(handle, str) else None)
            if nick:
                found.add(nick)
    return found


def _combine(parts: dict[str, float]) -> float:
    primary = [parts[k] for k in _PRIMARY if parts.get(k)]
    if not primary:
        return 0.0
    miss = 1.0
    for weight in primary:
        miss *= 1.0 - min(max(weight, 0.0), 0.99)
    score = 1.0 - miss
    if "city" in parts:
        score += 0.1
    if "product" in parts:
        score += 0.1
    return round(min(score, 0.99), 2)


def _score(client: ClientView, hint: dict[str, Any], n_last4: int) -> dict[str, Any] | None:
    parts: dict[str, float] = {}
    nick = norm_nick(hint.get("nickname"))
    if nick and nick in client.nicknames:
        parts["nickname"] = 0.9
    last4 = str(hint.get("masked_card_last4") or "")
    if last4 and last4 in client.last4 and n_last4 > 0:
        parts["card_last4"] = 0.5 / n_last4
    phone = norm_phone(hint.get("masked_phone"))
    if phone and phone == norm_phone(client.phone):
        parts["masked_phone"] = 0.6
    if not any(k in parts for k in _PRIMARY):
        return None
    city = (hint.get("city") or "").strip()
    if city and client.city and city.casefold() == client.city.casefold():
        parts["city"] = 0.1
    product = hint.get("product")
    if isinstance(product, str) and product in client.products:
        parts["product"] = 0.1
    return {
        "client_id": client.client_id,
        "confidence": _combine(parts),
        "matched_by": [k for k in _ORDER if k in parts],
    }


def match_clients(clients: list[ClientView], hint: dict[str, Any] | None) -> dict[str, Any]:
    """Чистая оценка. last4 делится на число клиентов с этими четырьмя цифрами во всём списке."""
    hint = hint or {}
    last4 = str(hint.get("masked_card_last4") or "")
    n_last4 = sum(1 for client in clients if last4 and last4 in client.last4)
    candidates = [scored for client in clients if (scored := _score(client, hint, n_last4))]
    candidates.sort(key=lambda item: (-float(item["confidence"]), int(item["client_id"])))
    candidates = candidates[:5]
    strong = [item for item in candidates if float(item["confidence"]) >= THRESHOLD]
    if len(strong) == 1:
        decision = "identified"
    elif candidates:
        decision = "ambiguous"
    else:
        decision = "not_found"
    return {"candidates": candidates, "decision": decision, "threshold": THRESHOLD}


def log_ru(result: dict[str, Any]) -> str:
    """Строка для панели Log: «Mock CRM: N кандидатов, лучший 0,93 (ник + карта)»."""
    candidates = result.get("candidates") or []
    if not candidates:
        return "Mock CRM: кандидатов нет"
    best = candidates[0]
    how = " + ".join(_LABELS[key] for key in best["matched_by"])
    conf = f"{float(best['confidence']):.2f}".replace(".", ",")
    return f"Mock CRM: {len(candidates)} кандидатов, лучший {conf} ({how})"
