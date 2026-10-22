"""Чистые функции B07: TXT-парсер, факт-чек, нечёткое совпадение фраз, отрицание маркеров скрипта."""

from __future__ import annotations

import pytest

from app.compliance.fact_check import check_claims, extract_claims, numbers_in
from app.compliance.rules_detector import _marker_present, phrase_matches
from app.compliance.txt_parser import TranscriptParseError, parse_txt

PRODUCTS = {
    "deposit": {"name_ru": "Вклады", "tariffs": {"base_rate_pct": 9.5, "promo_rate_pct": 14.0}},
    "debit_card": {
        "name_ru": "Дебетовые карты",
        "tariffs": {"cashback_pct": 1.0, "qr_sbp_fee_pct": 0.0, "service_fee_rub": 0, "transfer_fee_pct": 0.5},
    },
    "credit": {"name_ru": "Кредиты", "tariffs": {"rate_pct": 19.9}},
    "credit_card": {
        "name_ru": "Кредитные карты",
        "tariffs": {
            "rate_pct": 29.9,
            "grace_days": 120,
            "service_fee_rub": 0,
            "cash_withdraw_fee_pct": 3.9,
            "cash_withdraw_fee_min_rub": 390,
        },
    },
}


def test_parse_txt_one_line_meta_and_timestamps() -> None:
    d = parse_txt(
        "# kind: branch_retail; branch: VSP-0042; desk: 5; product: deposit\n[00:00:00] Сотрудник: Добрый день!\n[00:00:04] Клиент: Ставка?\nпродолжение реплики\n"
    )
    assert (
        d["kind"] == "branch_retail"
        and d["branch_code"] == "VSP-0042"
        and d["desk_no"] == 5
        and d["deal_product"] == "deposit"
    )
    assert [t["speaker"] for t in d["turns"]] == ["employee", "client"]
    assert d["turns"][0]["t1_ms"] == 4000 and d["turns"][1]["text"] == "Ставка? продолжение реплики"


def test_parse_txt_roles_without_timestamps_and_error() -> None:
    d = parse_txt("Оператор: Банк, слушаю.\nКлиент 2: Хочу карту.")
    assert [t["speaker"] for t in d["turns"]] == ["employee", "client"]
    with pytest.raises(TranscriptParseError):
        parse_txt("просто текст без ролей")


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("четырнадцать процентов", 14.0),
        ("девять с половиной процентов", 9.5),
        ("девятнадцать и девять десятых процента", 19.9),
        ("сто двадцать дней", 120.0),
        ("3,9 %", 3.9),
    ],
)
def test_numbers_in_words(text: str, value: float) -> None:
    assert any(abs(v - value) < 0.01 for v, _, _ in numbers_in(text)), numbers_in(text)


def _false(text: str, deal: str) -> list[tuple[str, str]]:
    return [(f.claim, f.truth) for f in check_claims(extract_claims(text, deal), PRODUCTS) if f.is_false]


def test_fact_check_catches_misinformation() -> None:
    assert _false("По вкладу ставка четырнадцать процентов.", "deposit")[0][1].startswith("9,5 %")
    assert _false("Комиссия за оплату по QR один процент.", "debit_card")
    assert _false("Снятие наличных с кредитки бесплатно.", "credit_card")[0][1] == "3,9 % + 390 ₽"
    assert _false("Льготный период двести дней.", "credit_card")


def test_fact_check_accepts_truth_and_promo_with_mention() -> None:
    assert not _false("Ставка по кредиту девятнадцать и девять десятых процента.", "credit")
    assert not _false("Обслуживание карты бесплатное, оплата по QR без комиссии, кешбэк один процент.", "debit_card")
    assert not _false("По акции промо-ставка 14 % на полгода.", "deposit")
    assert _false("Ставка 14 % на полгода.", "deposit")
    assert not _false("Досрочное закрытие — по ставке до востребования, комиссий нет.", "deposit")


def test_phrase_matches_fuzzy() -> None:
    assert phrase_matches("Карту выдадим, только если оформите подписку.", "карту выдадим, если оформите подписку")
    assert phrase_matches("Без страховки кредит вам не одобрят, это условие.", "без страховки вам не одобрят")
    assert not phrase_matches("Страховка добровольная, решение за вами.", "кредит только со страховкой")


def test_marker_negation() -> None:
    assert not _marker_present("давайте сразу к делу, паспорт не нужен — я вас помню", "паспорт")
    assert _marker_present("паспорт, пожалуйста, для идентификации", "паспорт")
