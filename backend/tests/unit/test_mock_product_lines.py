"""T262: canonical однозначная mock классификация, без подмены output или provider."""

import pytest

from app.contracts.registry import deref, validate
from app.llm.mock import MockProvider, _unique_product_lines
from tests.helpers import MOCK_PROFILE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,product,line",
    [
        ("Не могу открыть вклад, ошибка приложения.", "deposit", "deposits"),
        ("Не могу погасить кредит, произошла ошибка.", "credit", None),
        ("С дебетовой карты списали комиссию за оплату по QR.", "debit_card", None),
        ("Не работает кредитная карта, ошибка приложения.", "credit_card", "credit_cards"),
        ("Не работает обслуживание, прошу разобраться.", None, None),
    ],
)
async def test_native_mock_only_assigns_unambiguous_catalog_line(text, product, line):
    obj, usage, _ = await MockProvider().complete_structured(
        [{"role": "user", "content": text}], deref("agent/classification"), MOCK_PROFILE, timeout_s=1
    )
    assert not validate(obj, "agent/classification")
    assert obj["product"] == product and obj.get("product_line") == line
    if line is None:
        assert "product_line" not in obj  # Optional enum не допускает JSON null.
    assert usage.provider == "mock" and usage.source == "mock" and usage.model == "mock-rules-v1"


def test_shared_cached_product_mapping_is_immutable_and_credit_stays_ambiguous():
    mapping = _unique_product_lines()
    assert mapping is _unique_product_lines() and mapping["credit"] is None
    with pytest.raises(TypeError):
        mapping["deposit"] = "other"
