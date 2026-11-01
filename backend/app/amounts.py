"""Точные рублёвые суммы из текста для подсказок normalization (T-059).

Выбирается первое полное упоминание с маркером валюты. Это подсказка, не
основание возврата: комиссии и проводки по-прежнему подтверждаются данными БД.
"""

from __future__ import annotations

import math
import re
from decimal import Decimal

# Горизонтальные разделители тысяч: пробел, NBSP, narrow NBSP, thin space.
GROUP_SPACES = " \u00a0\u202f\u2009"
_RUBLE_AMOUNT = re.compile(
    r"(?<![0-9−-])"
    r"(?P<amount>(?:[0-9]{1,3}(?:[ \u00a0\u202f\u2009][0-9]{3})+|[0-9]+)(?:[.,][0-9]{1,2})?)"
    r"[ \t\u00a0\u202f\u2009]*"
    r"(?:₽|руб(?:лей|ля|ль)?(?![а-яёa-z])\.?|р\.)",
    re.IGNORECASE,
)


def first_ruble_amount(text: str) -> Decimal | None:
    """Без округления: decimal comma/dot, ≤2 знаков копеек, строгие группы тысяч.

    Проверка слева не позволяет взять хвост неправильной группы или дроби,
    включая случаи `12 34 руб`, `123.456 руб` и `- 450 руб`.
    """
    for match in _RUBLE_AMOUNT.finditer(text):
        prefix = text[: match.start()].rstrip()
        before_punctuation = prefix.rstrip(".,")
        if prefix and (
            prefix[-1].isdigit()
            or prefix[-1] in "−-"
            or (
                prefix[-1] in ".,"
                and (not before_punctuation or before_punctuation[-1].isdigit() or before_punctuation[-1].isspace())
            )
        ):
            continue
        number = match["amount"].translate(str.maketrans("", "", GROUP_SPACES)).replace(",", ".")
        return Decimal(number)
    return None


def ruble_amount_hint(text: str) -> float | None:
    """JSON normalization contract требует number; денежной арифметики здесь нет."""
    amount = first_ruble_amount(text)
    if amount is None:
        return None
    value = float(amount)
    return value if math.isfinite(value) else None
