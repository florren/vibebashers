"""Клиент получает понятный исход, без служебного отчёта и неподтверждённых обещаний."""

import pytest

from app.agent.customer_messages import outcome_text
from app.i18n import declined_action_text


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_rejection_is_customer_facing(lang):
    text = declined_action_text(lang)
    assert not any(s in text.lower() for s in ("автоматическ", "automated", "gift", "подарок", "начислили"))
    assert "Приносим извинения" in text if lang == "ru" else "We are sorry" in text


@pytest.mark.parametrize("lang", ["ru", "en"])
@pytest.mark.parametrize("resolved,late", [(True, False), (True, True), (False, True)])
def test_outcome_copy(lang, resolved, late):
    body = outcome_text(lang, resolved=resolved, late=late)
    assert not any(
        s in body.lower()
        for s in ("демонстрац", "стенд", "маршрут", "эскалац", "mock", "demonstration", "external financial")
    )
    assert ("устранена" in body if lang == "ru" else "has been resolved" in body) == resolved
    assert ("остаётся открытым" in body if lang == "ru" else "remains open" in body) == (not resolved)
    assert not any(s in body.lower() for s in ("баллов", "подарок", "bonus points", "refund"))
    if late and resolved:
        assert "больше времени" in body if lang == "ru" else "longer than promised" in body


@pytest.mark.parametrize("lang,label", [("ru", "600 бонусных баллов"), ("en", "600 bonus points")])
def test_issued_gift_is_in_customer_copy(lang, label):
    assert label in outcome_text(lang, resolved=True, late=True, gift=label)
