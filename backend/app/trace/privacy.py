"""Output boundary: only projected business fields, with contact masking."""

from __future__ import annotations

import re


def mask(value: object, limit: int = 500) -> str:
    text = str(value or "")
    # Необходимые условия совпадения: не меняют Unicode/boundary правила regex.
    # Большой отчёт обрабатывает тысячи обычных строк без контактов.
    if re.search(r"\d", text):
        text = re.sub(
            r"(?<!\w)(?:\+?[78][\s()-]*)?(?:\d[\s()-]*){10,19}(?!\w)",
            lambda m: "**** " + re.sub(r"\D", "", m[0])[-4:],
            text,
        )
    if "@" in text:
        text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email скрыт]", text)
        text = re.sub(r"@[\w.-]+", "@***", text)
    return text[:limit]
