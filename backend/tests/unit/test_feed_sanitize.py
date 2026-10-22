"""Публичный ответ: маскирование ПДн и снятие обещаний (ТЗ 21.5) — чистые функции."""

from __future__ import annotations

from app.feed.service import PLATFORM_BY_CHANNEL, sanitize_public_text


def test_sanitize_masks_cards_and_phones() -> None:
    out = sanitize_public_text("Карта 1234567890123456, 1234 5678 9012 3456, тел. +7 (912) 345-67-89 и 89123456789.")
    assert "1234" not in out and "+7" not in out and "8912" not in out and "••••" in out


def test_sanitize_removes_promises() -> None:
    out = sanitize_public_text("Гарантируем возврат, обязательно вернём в течение 10 минут, 100% решим.")
    low = out.lower()
    assert "гарантиру" not in low and "в течение 10 минут" not in low and "100" not in low
    assert "постараемся" in low


def test_platform_mapping() -> None:
    assert PLATFORM_BY_CHANNEL == {"review_portal": "review_portal", "social": "telegram_channel"}
