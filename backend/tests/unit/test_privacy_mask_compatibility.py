"""Оптимизация masking сохраняет прежние Unicode/boundary/truncation правила."""

from __future__ import annotations

import random
import re

import pytest

from app.trace.privacy import mask


def legacy_mask(value: object, limit: int) -> str:
    """Зафиксированная до оптимизации output boundary для differential regression."""
    text = str(value or "")
    text = re.sub(
        r"(?<!\w)(?:\+?[78][\s()-]*)?(?:\d[\s()-]*){10,19}(?!\w)",
        lambda m: "**** " + re.sub(r"\D", "", m[0])[-4:],
        text,
    )
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email скрыт]", text)
    text = re.sub(r"@[\w.-]+", "@***", text)
    return text[:limit]


@pytest.mark.parametrize("limit", [-1, 0, 1, 12, 500, 2000])
def test_mask_retains_legacy_unicode_contacts_and_truncation(limit):
    examples: list[object] = [
        None,
        0,
        1234567890,
        "Обычный текст без контактов. Второе предложение.",
        "ДлинноеСловоБезАдреса" * 100,
        "карта 4111 1111 1111 4512 телефон +7 900 123-45-67 @realuser me@example.org",
        "email a.b+tag@example.org @ник.имя @ @-name а@пример.рф",
        "числа 1234 123456789 1234567890 1234567890123456789 12345678901234567890",
        "Unicode ١٢٣٤٥٦٧٨٩٠ १२३४५६७८९० １２３４５６７８９０",
        "boundaries x1234567890y _1234567890 1234567890_ !1234567890!",
        "mixed 1234567890@example.org @1234567890 +7 (900) 123-45-67@name",
        "prefix " * 80 + "me@example.org +7 900 123-45-67",
    ]
    rng = random.Random(244)
    alphabet = "abcАБВ0123456789١٢٣٤٥٦٧٨٩٠@.+-_ ()\n"
    examples.extend("".join(rng.choices(alphabet, k=rng.randrange(200))) for _ in range(250))
    for value in examples:
        assert mask(value, limit) == legacy_mask(value, limit)


def test_known_contacts_remain_hidden():
    assert mask("me@example.org @handle +7 900 123-45-67") == "[email скрыт] @*** **** 4567"
