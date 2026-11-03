"""Проверенный native catalog важнее общего эвристического product path."""

from types import SimpleNamespace

import pytest

from app.agent.nodes import PRODUCT_SYSTEMS, _postcheck_classification
from app.agent.state import new_state


@pytest.mark.parametrize(
    "product,system,error",
    [
        ("debit_card", "promo_engine", "PROMO-ELIGIBILITY-FAIL"),
        ("credit", "notification_gw", "NOTIF-OTP-MISSING"),
        ("debit_card", "core_abs", "ABS-BALANCE-MISMATCH"),
    ],
)
@pytest.mark.parametrize("native", [True, False])
def test_only_verified_native_scope_preserves_shared_system(product, system, error, native):
    state = new_state(1, {"id": 1, "text": f"Служебный мониторинг. Ошибка {error}.", "channel": "proactive"}, 1, "v1.1")
    state["context"] = {"hints": {}, "products": []}
    if native:
        state["context"]["proactive_fault"] = {
            "product_code": product,
            "system_code": system,
            "error_code": error,
            "default_criticality": "high",
            "co_team_codes": [],
        }
    result, _ = _postcheck_classification(
        {"signal_type": "tech_fault", "product": product, "system": system, "error_code": error},
        state,
        SimpleNamespace(teams=["team_cx"], policies={}, routing_rules=[(1, {}, ["team_cx"])]),
    )
    assert result["system"] == (system if native else PRODUCT_SYSTEMS[product][0])
    assert result["product"] == product and result["error_code"] == error
