"""Проверка фактов в речи сотрудника (ДТЗ FR-4.2, T-215): утверждения о ставках/комиссиях/сроках ↔ products.tariffs.

Чистые функции: extract_claims(text, deal_product) → check_claims(claims, products). verified=true только при определённом продукте.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# ------------------------------------------------------------------ числа словами
_UNITS = {
    "ноль": 0, "один": 1, "одна": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "восемь": 8,
    "девять": 9, "десять": 10, "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14, "пятнадцать": 15,
    "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18, "девятнадцать": 19,
}  # fmt: skip
_TENS = {
    "двадцать": 20,
    "тридцать": 30,
    "сорок": 40,
    "пятьдесят": 50,
    "шестьдесят": 60,
    "семьдесят": 70,
    "восемьдесят": 80,
    "девяносто": 90,
}
_HUNDREDS = {
    "сто": 100,
    "двести": 200,
    "триста": 300,
    "четыреста": 400,
    "пятьсот": 500,
    "шестьсот": 600,
    "семьсот": 700,
    "восемьсот": 800,
    "девятьсот": 900,
}
_WORDS = {**_UNITS, **_TENS, **_HUNDREDS}
_NUM_WORD = "|".join(sorted(_WORDS, key=len, reverse=True))
# «девятнадцать и девять десятых», «девять с половиной», «сто двадцать», «три и девять десятых»
_WORD_NUM_RE = re.compile(
    rf"\b((?:{_NUM_WORD})(?:\s+(?:{_NUM_WORD})){{0,2}})(?:\s+(?:и\s+((?:{_NUM_WORD})(?:\s+(?:{_NUM_WORD}))?)\s+десят\w+|с\s+половиной))?\b",
    re.IGNORECASE,
)
_DIGIT_RE = re.compile(r"\d{1,3}(?:[.,]\d{1,2})?")


def _words_to_int(chunk: str) -> int:
    return sum(_WORDS.get(w.lower(), 0) for w in chunk.split())


def numbers_in(text: str) -> list[tuple[float, int, int]]:
    """Все числа (цифрами и словами) → [(value, start, end)]."""
    out: list[tuple[float, int, int]] = []
    for m in _DIGIT_RE.finditer(text):
        out.append((float(m.group(0).replace(",", ".")), m.start(), m.end()))
    for m in _WORD_NUM_RE.finditer(text):
        whole = _words_to_int(m.group(1))
        frac = 0.0
        tail = m.group(0).lower()
        if m.group(2):
            frac = _words_to_int(m.group(2)) / 10
        elif "с половиной" in tail:
            frac = 0.5
        out.append((whole + frac, m.start(), m.end()))
    return sorted(out, key=lambda x: x[1])


# ------------------------------------------------------------------ темы утверждений
PRODUCT_WORDS: dict[str, tuple[str, ...]] = {
    "deposit": ("вклад", "депозит", "накопител", "сбережен"),
    "credit_card": ("кредитн", "кредитк", "льготн", "грейс"),
    "credit": ("кредит", "потребительск", "заём", "займ"),
    "debit_card": ("дебетов", "карта", "карту", "карты", "qr", "сбп", "кешбэк", "кэшбэк", "обслуживан", "перевод"),
}
DEAL_WORDS: dict[str, tuple[str, ...]] = {
    "deposit": ("вклад", "депозит", "накопит", "deposit"),
    "credit_card": ("кредитн", "кредитка", "credit_card"),
    "credit": ("кредит", "credit"),
    "debit_card": ("карт", "debit"),
}


@dataclass
class Claim:
    topic: str  # rate | qr_fee | cash_withdraw_fee | grace_days | service_fee | cashback | transfer_fee
    product: str | None
    value: float  # число из речи; «бесплатно/без комиссии» → 0
    quote: str


@dataclass
class FactResult:
    claim: str
    truth: str
    source_table: str
    source_key: str | None
    verified: bool
    is_false: bool
    product: str | None


def product_of(text: str, deal_product: str | None) -> str | None:
    t = text.lower()
    for code, words in PRODUCT_WORDS.items():
        if any(w in t for w in words):
            return code
    dp = (deal_product or "").lower()
    for code, words in DEAL_WORDS.items():
        if any(w in dp for w in words):
            return code
    return None


def _sentences(text: str) -> list[str]:
    """Предложения и клаузы (по , ; . ! ?) — одно утверждение на клаузу."""
    return [s.strip() for s in re.split(r"(?<=[.!?;,])\s+", text) if s.strip()]


def _pct_values(sent: str) -> list[float]:
    """Числа, за которыми идёт «%»/«процент»."""
    vals = []
    low = sent.lower()
    for v, _, end in numbers_in(sent):
        tail = low[end : end + 14]
        if re.match(r"\s*(%|процент)", tail):
            vals.append(v)
    return vals


def _free(sent: str) -> bool:
    low = sent.lower()
    return bool(
        re.search(
            r"бесплатн|без комисси|комисси\w*\s+нет|комисси\w*\s+не\s+(берём|взимается)|0\s*%|ноль процентов", low
        )
    )


def extract_claims(text: str, deal_product: str | None = None) -> list[Claim]:
    """Утверждения о числах по предложениям: ставка, комиссия QR/СБП, снятие наличных, льготный период, обслуживание, кешбэк, переводы."""
    claims: list[Claim] = []
    for sent in _sentences(text):
        low = sent.lower()
        product = product_of(sent, deal_product)
        pcts = _pct_values(sent)
        free = _free(sent)
        if "qr" in low or "сбп" in low:
            if pcts:
                claims.append(Claim("qr_fee", "debit_card", pcts[0], sent))
            elif free:
                claims.append(Claim("qr_fee", "debit_card", 0.0, sent))
            continue
        if re.search(r"снят\w*\s+налич|налични?\w*\s+(в|из)\s+банкомат|снять\s+деньги\s+в\s+банкомат", low):
            if pcts:
                claims.append(Claim("cash_withdraw_fee", product or "credit_card", pcts[0], sent))
            elif free:
                claims.append(Claim("cash_withdraw_fee", product or "credit_card", 0.0, sent))
            continue
        if "льготн" in low or "грейс" in low:
            days = [v for v, _, e in numbers_in(sent) if re.match(r"\s*(дн|сут)", low[e : e + 6])]
            if days:
                claims.append(Claim("grace_days", "credit_card", days[0], sent))
            continue
        if "обслуживан" in low and ("карт" in low or product in ("debit_card", "credit_card")):
            rub = [v for v, _, e in numbers_in(sent) if re.match(r"\s*(₽|руб|р\.)", low[e : e + 6])]
            if rub:
                claims.append(Claim("service_fee", product or "debit_card", rub[0], sent))
            elif free:
                claims.append(Claim("service_fee", product or "debit_card", 0.0, sent))
            # не continue: в том же предложении может быть кешбэк
        if ("кешбэк" in low or "кэшбэк" in low) and pcts:
            claims.append(Claim("cashback", "debit_card", pcts[0], sent))
            continue
        if "перевод" in low and pcts:
            claims.append(Claim("transfer_fee", "debit_card", pcts[0], sent))
            continue
        if pcts and re.search(r"ставк|годовых|доходност", low):
            claims.append(Claim("rate", product, pcts[0], sent))
    return claims


def _fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _eq(a: float, b: float) -> bool:
    return abs(a - b) < 0.051


def check_claims(claims: list[Claim], products: dict[str, dict[str, Any]]) -> list[FactResult]:
    """Сверка с products.tariffs. Промо-ставка вклада засчитывается только при упоминании акции."""
    out: list[FactResult] = []
    for c in claims:
        prod = products.get(c.product or "")
        if not prod:
            out.append(
                FactResult(
                    f"{c.topic}: {_fmt(c.value)}", "продукт не определён", "products", None, False, False, c.product
                )
            )
            continue
        t = prod.get("tariffs") or {}
        name = prod.get("name_ru") or c.product
        if c.topic == "rate":
            if c.product == "deposit":
                base = float(t.get("base_rate_pct", 0))
                promo = t.get("promo_rate_pct")
                mentions_promo = any(w in c.quote.lower() for w in ("промо", "акци", "спецпредлож"))
                ok = _eq(c.value, base) or (promo is not None and mentions_promo and _eq(c.value, float(promo)))
                truth = f"{_fmt(base)} % годовых" + (
                    f" (промо {_fmt(float(promo))} % только по акции)" if promo is not None else ""
                )
                key = "deposit.tariffs.base_rate_pct"
            elif c.product in ("credit", "credit_card"):
                base = float(t.get("rate_pct", 0))
                ok, truth, key = _eq(c.value, base), f"{_fmt(base)} % годовых", f"{c.product}.tariffs.rate_pct"
            else:
                out.append(
                    FactResult(
                        f"ставка {name}: {_fmt(c.value)} %",
                        "у продукта нет ставки",
                        "products",
                        c.product,
                        False,
                        False,
                        c.product,
                    )
                )
                continue
            out.append(FactResult(f"ставка {name}: {_fmt(c.value)} %", truth, "products", key, True, not ok, c.product))
        elif c.topic == "qr_fee":
            fee = float((products.get("debit_card") or {}).get("tariffs", {}).get("qr_sbp_fee_pct", 0))
            out.append(
                FactResult(
                    f"комиссия за оплату по QR/СБП: {_fmt(c.value)} %",
                    f"{_fmt(fee)} % (без комиссии)",
                    "products",
                    "debit_card.tariffs.qr_sbp_fee_pct",
                    True,
                    not _eq(c.value, fee),
                    "debit_card",
                )
            )
        elif c.topic == "cash_withdraw_fee":
            if c.product == "credit_card":
                fee, fixed = float(t.get("cash_withdraw_fee_pct", 0)), float(t.get("cash_withdraw_fee_min_rub", 0))
                truth = f"{_fmt(fee)} % + {_fmt(fixed)} ₽" if fixed else f"{_fmt(fee)} %"
                out.append(
                    FactResult(
                        f"снятие наличных с кредитной карты: {'бесплатно' if c.value == 0 else _fmt(c.value) + ' %'}",
                        truth,
                        "products",
                        "credit_card.tariffs.cash_withdraw_fee_pct",
                        True,
                        not _eq(c.value, fee),
                        c.product,
                    )
                )
            else:
                limit = t.get("atm_withdraw_free_limit_rub")
                truth = f"бесплатно до {_fmt(float(limit))} ₽ в месяц" if limit else "по тарифу"
                out.append(
                    FactResult(
                        f"снятие наличных: {'бесплатно' if c.value == 0 else _fmt(c.value) + ' %'}",
                        truth,
                        "products",
                        "debit_card.tariffs.atm_withdraw_free_limit_rub",
                        True,
                        c.value != 0 and not _eq(c.value, 1.0),
                        c.product,
                    )
                )
        elif c.topic == "grace_days":
            days = float((products.get("credit_card") or {}).get("tariffs", {}).get("grace_days", 0))
            out.append(
                FactResult(
                    f"льготный период: {int(c.value)} дней",
                    f"{int(days)} дней",
                    "products",
                    "credit_card.tariffs.grace_days",
                    True,
                    not _eq(c.value, days),
                    "credit_card",
                )
            )
        elif c.topic == "service_fee":
            fee = float(t.get("service_fee_rub", 0))
            out.append(
                FactResult(
                    f"обслуживание {name}: {'бесплатно' if c.value == 0 else _fmt(c.value) + ' ₽'}",
                    "бесплатно" if fee == 0 else f"{_fmt(fee)} ₽",
                    "products",
                    f"{c.product}.tariffs.service_fee_rub",
                    True,
                    not _eq(c.value, fee),
                    c.product,
                )
            )
        elif c.topic == "cashback":
            cb = float((products.get("debit_card") or {}).get("tariffs", {}).get("cashback_pct", 0))
            out.append(
                FactResult(
                    f"кешбэк: {_fmt(c.value)} %",
                    f"{_fmt(cb)} %",
                    "products",
                    "debit_card.tariffs.cashback_pct",
                    True,
                    not _eq(c.value, cb),
                    "debit_card",
                )
            )
        elif c.topic == "transfer_fee":
            fee = float((products.get("debit_card") or {}).get("tariffs", {}).get("transfer_fee_pct", 0))
            out.append(
                FactResult(
                    f"комиссия за переводы: {_fmt(c.value)} %",
                    f"{_fmt(fee)} % сверх бесплатного лимита",
                    "products",
                    "debit_card.tariffs.transfer_fee_pct",
                    True,
                    not _eq(c.value, fee),
                    "debit_card",
                )
            )
    return out
