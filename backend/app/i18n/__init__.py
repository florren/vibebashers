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
        return "The review is complete. Automated actions were not approved; no refund or gift was issued. You can provide additional information to continue the review."
    return "Проверка обращения завершена. Автоматические действия по нему не согласованы; возврат средств и выдача подарка не выполнялись. Для продолжения разбора можно направить дополнительную информацию."
