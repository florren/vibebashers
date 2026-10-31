"""Язык коммуникации с клиентом (ТЗ 12.4, AGENTS §5 п.9): по умолчанию ru."""

from __future__ import annotations

import re

_CYRILLIC = re.compile(r"[А-Яа-яЁё]")
_LATIN = re.compile(r"[A-Za-z]")


def communication_lang(text: str) -> str:
    """Кириллица → ru, латиница без кириллицы → en, иначе ru."""
    sample = text or ""
    if _CYRILLIC.search(sample):
        return "ru"
    if _LATIN.search(sample):
        return "en"
    return "ru"


def declined_action_text(lang: str) -> str:
    """Итог отказа от автоматических действий без заявления об устранении проблемы."""
    if lang == "en":
        return "We have reviewed your request. Unfortunately, we could not approve the requested action based on the information available. We are sorry. Please reply with any additional details so we can continue reviewing your case."
    return "Мы рассмотрели ваше обращение. К сожалению, по результатам проверки согласовать запрошенное действие не удалось. Приносим извинения. Если у вас есть дополнительные сведения, ответьте на это сообщение — продолжим разбор."
