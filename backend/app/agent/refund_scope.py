"""Сопоставление обращения с денежными правилами; metadata — data/rules.yaml.

ТЗ21.4 п1: CRM-операция не является причиной обращения только по client_id.
Selector не меняет money/HITL лимиты и не заменяет проверку правил/ledger.
"""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agent.state import AgentState
from app.contracts.enums import Intent, PaymentMethod, Product, System
from app.contracts.registry import deref


class OperationSelector(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product: list[Product] = Field(default_factory=list)
    method: list[PaymentMethod] = Field(default_factory=list)
    op_type: list[str] = Field(default_factory=list)
    system_path: list[System] = Field(default_factory=list)
    deny: bool = False


class Patterns(BaseModel):
    model_config = ConfigDict(extra="forbid")
    blocked_patterns: list[str] = Field(default_factory=list)

    @field_validator("blocked_patterns", check_fields=False)
    @classmethod
    def valid_patterns(cls, value: list[str]) -> list[str]:
        for pattern in value:
            if not pattern:
                raise ValueError("пустой pattern не является проверкой темы")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError("некорректный case pattern") from exc
        return value


class CaseScope(Patterns):
    allowed_intents: list[Intent] = Field(min_length=1)
    blocked_intents: list[Intent] = Field(default_factory=list)
    request_intents: list[Intent] = Field(default_factory=list)
    topic_patterns: list[str] = Field(min_length=1)
    evidence_patterns: list[str] = Field(default_factory=list)
    operation: OperationSelector

    @field_validator("topic_patterns", "evidence_patterns")
    @classmethod
    def valid_scope_patterns(cls, value: list[str]) -> list[str]:
        return cls.valid_patterns(value)


class CaseContext(Patterns):
    version: int = Field(ge=1, le=1)
    operation_hints: dict[str, OperationSelector]
    routing_operation_hints: dict[str, OperationSelector] = Field(default_factory=dict)


@lru_cache(maxsize=1)
def catalog() -> tuple[CaseContext, dict[str, CaseScope]]:
    path = Path(__file__).resolve().parents[3] / "data" / "rules.yaml"
    if not path.exists():
        path = Path("/data/rules.yaml")
    with path.open() as stream:
        data = yaml.safe_load(stream)
    context = CaseContext.model_validate(data["refund_case_context"])
    known_hints = deref("agent/normalization")["properties"]["entities"]["properties"]["operation_hint"]["enum"]
    if any(hint not in known_hints for hint in (*context.operation_hints, *context.routing_operation_hints)):
        raise ValueError("operation_hint вне normalization contract")
    scopes = {
        row["code"]: CaseScope.model_validate(row["case_scope"])
        for row in data["business_rules"]
        if row.get("action") == "refund_fee" and row.get("case_scope") is not None
    }
    return context, scopes


def catalog_fingerprint() -> str:
    context, scopes = catalog()
    payload = {
        "context": context.model_dump(mode="json"),
        "rules": {code: rule.model_dump(mode="json") for code, rule in scopes.items()},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _matches(op: dict[str, Any], selector: OperationSelector) -> bool:
    return (
        not selector.deny
        and (not selector.system_path or bool(set(selector.system_path).intersection(op.get("system_path") or [])))
        and all(
            not values or op.get(key) in values
            for key, values in selector.model_dump(exclude={"deny", "system_path"}).items()
        )
    )


def _select_operations(
    operations: list[dict[str, Any]], normalization: dict[str, Any], selectors: dict[str, OperationSelector]
) -> list[dict[str, Any]]:
    entities = normalization.get("entities") or {}
    product, hint = entities.get("product"), entities.get("operation_hint")
    selector = selectors.get(hint) if hint is not None else OperationSelector()
    if selector is None:
        return []
    return [op for op in operations if (not product or op.get("product") == product) and _matches(op, selector)]


def case_operations(operations: list[dict[str, Any]], normalization: dict[str, Any]) -> list[dict[str, Any]]:
    context, _ = catalog()
    return _select_operations(operations, normalization, context.operation_hints)


def routing_operations(operations: list[dict[str, Any]], normalization: dict[str, Any]) -> list[dict[str, Any]]:
    """Диагностика сохраняет notification/login факты, не разрешая ими refund."""
    context, _ = catalog()
    return _select_operations(operations, normalization, {**context.operation_hints, **context.routing_operation_hints})


def _amount(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        return None
    return result if result.is_finite() and result >= 0 else None


def _has(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def refund_candidates(
    operations: list[dict[str, Any]], normalization: dict[str, Any], text: str, rule_code: str
) -> tuple[list[dict[str, Any]], str]:
    context, scopes = catalog()
    scope = scopes.get(rule_code)
    if scope is None:
        return [], "нет metadata связи денежного правила с темой обращения"
    intents = set(normalization.get("intents") or [])
    if not intents.intersection(scope.allowed_intents) or intents.intersection(scope.blocked_intents):
        return [], "намерения не подтверждают текущую денежную претензию"
    if _has(text, [*context.blocked_patterns, *scope.blocked_patterns]):
        return [], "неоднозначная/отрицательная/несовместимая тема: требуется обычный граф"
    if not _has(text, scope.topic_patterns):
        return [], "тема денежного правила не соответствует обращению"
    if not intents.intersection(scope.request_intents) and not _has(text, scope.evidence_patterns):
        return [], "нет признаков спорной операции в текущем обращении"
    entities = normalization.get("entities") or {}
    if not any(entities.get(key) is not None for key in ("product", "operation_hint", "amount_rub")):
        return [], "нет привязки претензии к продукту/операции/сумме"
    selected = [op for op in case_operations(operations, normalization) if _matches(op, scope.operation)]
    raw_amount = entities.get("amount_rub")
    if raw_amount is not None:
        amount = _amount(raw_amount)
        if amount is None:
            return [], "сумма претензии некорректна"
        selected = [op for op in selected if amount in (_amount(op.get("amount_rub")), _amount(op.get("fee_amount")))]
    if len(selected) > 1:
        return [], "неоднозначно: несколько операций по теме/сумме обращения"
    return selected, "операция соответствует текущей претензии" if selected else "нет операции по теме/сумме обращения"


class StaleRefundDecision(ValueError):
    """Checkpoint не доказывает право решить текущий claim указанным возвратом."""


def validate_refund_decision(state: AgentState) -> None:
    context = state.get("context") or {}
    for rule in context.get("rules_matched") or []:
        if rule.get("action") != "refund_fee":
            continue
        candidates, why = refund_candidates(
            context.get("operations") or [],
            state.get("normalization") or {},
            (state.get("signal") or {}).get("text") or "",
            str(rule.get("rule_code") or ""),
        )
        expected_ids = [operation.get("operation_id") for operation in candidates]
        if not candidates or rule.get("operation_ids") != expected_ids:
            raise StaleRefundDecision(
                "stale_refund_scope: "
                + why
                + "; требуется актуальная обработка обращения, сохранённое решение человека не переинтерпретируется"
            )
