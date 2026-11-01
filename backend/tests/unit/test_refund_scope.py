"""ТЗ21.4: операция/сумма/тема, а не client_id, определяют денежный case."""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.agent import refund_scope as scope
from app.rules.engine import check_rules

RULE = "RULE-QR-FEE-001"
OP = {
    "operation_id": 10,
    "product": "debit_card",
    "op_type": "card_payment",
    "method": "qr_sbp",
    "amount_rub": Decimal("5472.45"),
    "fee_amount": Decimal("54.72"),
    "status": "failed",
    "error_code": "PROC-QR-FEE-CHARGED",
}
NORM = {
    "intents": ["complaint", "refund_request"],
    "entities": {"product": "debit_card", "operation_hint": "qr_payment", "amount_rub": 5472.45},
}
TEXT = "Оплатил по QR5472.45руб, ошибочно списали комиссию54.72руб. Верните комиссию"


@pytest.mark.parametrize("amount", [5472.45, 54.72, None])
def test_current_qr_fee_claim_matches_payment_or_fee(amount):
    norm = {**NORM, "entities": {**NORM["entities"], "amount_rub": amount}}
    candidates, _ = scope.refund_candidates([OP], norm, TEXT, RULE)
    assert candidates == [OP]


@pytest.mark.parametrize(
    "change",
    [
        {"product": "deposit"},
        {"operation_hint": "deposit"},
        {"operation_hint": "login"},
        {"amount_rub": 450},
        {"amount_rub": float("nan")},
        {"amount_rub": -1},
    ],
)
def test_other_topic_or_amount_is_not_a_refund_basis(change):
    norm = {**NORM, "entities": {**NORM["entities"], **change}}
    assert scope.refund_candidates([OP], norm, TEXT, RULE)[0] == []


@pytest.mark.parametrize("intents", [[], ["question"], ["gratitude"], ["refund_request", "gratitude"]])
def test_gratitude_or_unknown_intent_cannot_auto_settle_fee(intents):
    assert scope.refund_candidates([OP], {**NORM, "intents": intents}, TEXT, RULE)[0] == []


@pytest.mark.parametrize(
    "text",
    [
        "Не открывается вклад в приложении, ошибка503",
        "Не узнаю списание5472.45по дебетовой карте, верните деньги",
        "Не я совершал QR оплату5472.45, списали комиссию54.72, верните деньги",
        "Комиссию не списывали; верните54.72руб",
        "Верните QR комиссию54.72 и не открывается вклад",
        "Подскажите, какая комиссия у QR?",
    ],
)
def test_fraud_negated_mixed_or_unknown_topic_not_claim_resolution(text):
    intents = ["complaint"] if "Подскажите" in text else NORM["intents"]
    assert scope.refund_candidates([OP], {**NORM, "intents": intents}, text, RULE)[0] == []


def test_same_amount_is_ambiguous_not_two_refunds():
    other = {**OP, "operation_id": 11}
    candidates, why = scope.refund_candidates([OP, other], NORM, TEXT, RULE)
    assert candidates == [] and "неоднозначно" in why


def test_unknown_financial_rule_has_no_implicit_scope():
    assert scope.refund_candidates([OP], NORM, TEXT, "CUSTOM-UNKNOWN")[0] == []


def test_catalog_is_validated_and_does_not_embed_rule_id_in_selector(monkeypatch):
    original_hash = scope.catalog_fingerprint()
    context, rules = scope.catalog()
    custom = rules[RULE].model_copy(deep=True)
    custom.topic_patterns = ["CUSTOMTOPIC"]
    monkeypatch.setattr(scope, "catalog", lambda: (context, {"CUSTOM-RULE": custom}))
    assert scope.refund_candidates([OP], NORM, "CUSTOMTOPIC верните деньги", "CUSTOM-RULE")[0] == [OP]
    assert scope.catalog_fingerprint() != original_hash
    assert scope.catalog_fingerprint() == scope.catalog_fingerprint()
    assert scope.refund_candidates([OP], NORM, TEXT, "CUSTOM-RULE")[0] == []
    with pytest.raises(ValidationError):
        scope.CaseScope.model_validate({**custom.model_dump(), "allowed_intents": ["invented_intent"]})
    with pytest.raises(ValidationError):
        scope.OperationSelector.model_validate({"method": ["invented_method"]})


async def test_only_refund_rule_uses_scoped_candidates_other_rules_still_read_all_operations():
    conn = AsyncMock()
    conn.execute.return_value.fetchall.return_value = [
        (
            RULE,
            {"field": "operation.fee_amount", "gt": 0},
            "refund_fee",
            {},
            "team_processing",
            "PROC-QR-FEE-CHARGED",
            1,
        ),
        ("TEST-NOTIFY", {"field": "operation.product", "eq": "deposit"}, "notify_only", {}, "team_deposits", None, 1),
    ]
    operations = [OP, {**OP, "operation_id": 12, "product": "deposit", "method": "online"}]
    matched = await check_rules(
        conn, run_id=1, signal_id=2, agent_run_id=3, operations=operations, refund_operations={RULE: []}
    )
    assert [m["rule_code"] for m in matched] == ["TEST-NOTIFY"]
    assert matched[0]["operation_ids"] == [12]
    assert conn.execute.await_args_list[1].args[1][5] == "not_matched"


def test_invalid_metadata_is_rejected_instead_of_becoming_allow_all():
    _context, rules = scope.catalog()
    data = rules[RULE].model_dump()
    with pytest.raises(ValidationError):
        scope.CaseScope.model_validate({**data, "topic_patterns": ["["]})
    with pytest.raises(ValidationError):
        scope.CaseScope.model_validate({**data, "operation": {"method": ["qr_sbp"], "invented": True}})


@pytest.mark.parametrize("node_name", ["act", "act_instant", "verify", "gift", "close"])
async def test_legacy_unrelated_refund_scope_fails_before_business_effects(node_name):
    from types import SimpleNamespace

    from app.agent import nodes

    conn = AsyncMock()
    deps = SimpleNamespace(ctx=SimpleNamespace(conn=conn))
    state = {
        "signal": {"text": "Не открывается вклад, ошибка503"},
        "normalization": {"intents": ["complaint"], "entities": {"product": "deposit", "operation_hint": "deposit"}},
        "context": {
            "operations": [OP],
            "rules_matched": [{"action": "refund_fee", "rule_code": RULE, "operation_ids": [10]}],
        },
    }
    with pytest.raises(scope.StaleRefundDecision, match="stale_refund_scope"):
        await getattr(nodes, node_name)(state, deps)
    conn.execute.assert_not_awaited()


def test_current_single_operation_refund_scope_remains_valid():
    scope.validate_refund_decision(
        {
            "signal": {"text": TEXT},
            "normalization": NORM,
            "context": {
                "operations": [OP],
                "rules_matched": [{"action": "refund_fee", "rule_code": RULE, "operation_ids": [10]}],
            },
        }
    )
