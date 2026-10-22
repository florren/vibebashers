"""Атрибуция спикера в режиме auto (ТЗ 22.3): быстрая эвристика по маркерам речи менеджера/клиента + контекст предыдущей реплики.

Результат соответствует `events/compliance/speaker_attribution.schema.json` (speaker, confidence, reason_ru)."""

from __future__ import annotations

import re
from typing import Any

EMPLOYEE_MARKERS = (
    "предлага",
    "оформ",
    "подпиш",
    "у нас есть",
    "ставк",
    "страхов",
    "рекоменд",
    "давайте",
    "могу предложить",
    "услови",
    "договор",
    "вам подойд",
    "программ",
    "доходност",
    "формальност",
    "гарантир",
    "вклад",
    "продукт",
    "тариф",
    "комисси",
    "подключ",
    "оставьте",
    "паспорт",
)
CLIENT_MARKERS = (
    "у меня",
    "мне ",
    "мне,",
    "хочу",
    "не хочу",
    "почему",
    "сколько",
    "а если",
    "не понимаю",
    "спасибо",
    "скажите",
    "можно ли",
    "я думал",
    "мне не нужн",
    "а это",
    "правда",
    "точно",
    "а что",
    "подожд",
)
_Q = re.compile(r"\?|^(а|почему|сколько|когда|зачем|можно|что|как)\b", re.IGNORECASE)


def attribute(text: str, previous: str | None, history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    low = " " + text.lower().strip() + " "
    e = sum(1 for m in EMPLOYEE_MARKERS if m in low)
    c = sum(1 for m in CLIENT_MARKERS if m in low) + (1 if _Q.search(text.strip()) else 0)
    if e > c:
        return {
            "speaker": "employee",
            "confidence": min(0.95, 0.7 + 0.08 * (e - c)),
            "reason_ru": "Предлагает продукт и описывает условия — типичная речь менеджера",
        }
    if c > e:
        return {
            "speaker": "client",
            "confidence": min(0.95, 0.7 + 0.08 * (c - e)),
            "reason_ru": "Вопросы и речь от первого лица о своей ситуации — типичная речь клиента",
        }
    if previous in ("employee", "client"):
        # диалог чередуется: длинная реплика без маркеров после клиента — скорее менеджер, короткая после менеджера — клиент
        guess = "employee" if (previous == "client" or len(text) > 120) else "client"
        return {
            "speaker": guess,
            "confidence": 0.7,
            "reason_ru": f"Маркеров нет; по чередованию после реплики «{previous}»",
        }
    return {
        "speaker": "employee",
        "confidence": 0.7,
        "reason_ru": "Первая реплика встречи без маркеров — по умолчанию сотрудник",
    }
