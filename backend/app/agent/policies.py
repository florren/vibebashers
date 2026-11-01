"""Политики HITL и эскалации (ТЗ 9.3, T-076): чистые функции, пороги — из settings.policies (без рестарта)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_POLICIES: dict[str, Any] = {
    "confidence_threshold": 0.75,
    "clarification_threshold": 0.6,
    "fraud_amount_rub": 50_000,
    "repeat_hitl_count": 3,
    "escalation_negativity": 80,
    "escalation_signals_7d": 3,
    "refund_autonomy_limit_rub": 5_000,
    "refund_autonomy_limit_premium_rub": 15_000,
    "mass_refund_threshold": 50,
    "dedup_window_sim_hours": 4,
}
PARTNER_PRIVILEGES = {"lounge_pass", "restaurant_special", "business_class_discount"}
FORBIDDEN_PHRASES = (
    "вы сами виноваты",
    "ваша ошибка",
    "вы неправильно",
    "гарантируем",
    "в течение часа",
    "сегодня же",
    "немедленно вернём",
    "компенсируем все",
    "100%",
    "your fault",
    "your mistake",
    "you incorrectly",
    "guarantee",
    "within the hour",
    "this very day",
    "refund immediately",
    "immediate refund",
    "compensate everything",
)
HUMAN_OPTIONS: dict[str, list[dict[str, str]]] = {
    "_default": [
        {"code": "accept", "label_ru": "Принять предложение агента", "label_en": "Accept"},
        {"code": "modify", "label_ru": "Изменить и выполнить", "label_en": "Modify"},
        {"code": "reject", "label_ru": "Отклонить, закрыть без действий", "label_en": "Reject"},
    ],
    "legal_regulatory": [
        {"code": "accept", "label_ru": "Передать в комплаенс (предложение агента)", "label_en": "Accept"},
        {"code": "modify", "label_ru": "Изменить маршрут/текст", "label_en": "Modify"},
        {"code": "delegate", "label_ru": "Делегировать юристу", "label_en": "Delegate"},
    ],
    "fraud_amount": [
        {"code": "accept", "label_ru": "Блокировать операции и передать в антифрод", "label_en": "Accept"},
        {"code": "modify", "label_ru": "Изменить меры", "label_en": "Modify"},
        {"code": "reject", "label_ru": "Мошенничество не подтверждено", "label_en": "Reject"},
    ],
}
HUMAN_RECOMMENDATION: dict[str, str] = {
    "low_confidence": "Уверенность классификации ниже порога: проверьте тип сигнала и маршрут, затем примите или скорректируйте.",
    "ultra_vip": "Клиент Ultra VIP: подтвердите текст ответа и подарок, при необходимости подключите персонального менеджера.",
    "legal_regulatory": "Регуляторный/судебный сигнал: согласуйте позицию с комплаенсом, клиенту — только подтверждение приёма.",
    "fraud_amount": "Сумма выше порога мошенничества: подтвердите блокировку и передачу в антифрод.",
    "partner_privilege": "Предложена привилегия партнёра: подтвердите или замените на бонусные баллы.",
    "repeat_3plus": "Третье и более обращение по той же причине: нужен персональный контакт и контроль руководителя.",
    "classifier_conflict": "Модель и правила разошлись: выберите тип сигнала и маршрут вручную.",
    "policy_other": "Требуется решение человека по политике банка.",
}


@dataclass
class PolicyContext:
    segment: str | None = None
    repeat_count: int = 0  # сигналов по той же причине за 14 дней (включая текущий)
    signals_7d: int = 0  # любых обращений клиента за 7 дней (включая текущий)
    amount_rub: float | None = None
    gift_code: str | None = None
    rule_based_type: str | None = None  # тип по эвристике/правилам для проверки конфликта
    refunds_30d: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def merged(policies: dict[str, Any] | None) -> dict[str, Any]:
    return {**DEFAULT_POLICIES, **(policies or {})}


def red_words_require_hitl(classification: dict[str, Any]) -> bool:
    """Юридическая категория правил требует HITL независимо от мнения LLM."""
    from app.ingest.red_words import detect

    return any(detect(word)["legal"] for word in classification.get("red_words") or [])


def needs_human(
    classification: dict[str, Any], ctx: PolicyContext, policies: dict[str, Any] | None = None
) -> str | None:
    """HumanReason из contracts/events/agent/decision.schema.json или None (ТЗ 9.3). Порядок — по убыванию строгости."""
    p = merged(policies)
    stype = classification.get("signal_type")
    amount = ctx.amount_rub or (classification.get("entities") or {}).get("amount_rub") or 0
    if stype == "legal_regulatory" or red_words_require_hitl(classification):
        return "legal_regulatory"
    if stype == "fraud_suspicion" and float(amount) > p["fraud_amount_rub"]:
        return "fraud_amount"
    if ctx.segment == "ultra_vip":
        return "ultra_vip"
    if ctx.gift_code in PARTNER_PRIVILEGES:
        return "partner_privilege"
    if ctx.repeat_count >= p["repeat_hitl_count"]:
        return "repeat_3plus"
    if ctx.rule_based_type and stype and ctx.rule_based_type != stype and classification.get("confidence", 1.0) < 0.9:
        return "classifier_conflict"
    if (classification.get("problem_summary") or {}).get("severity") == "critical":
        return "policy_other"
    if float(classification.get("confidence", 0.0)) < p["confidence_threshold"]:
        return "low_confidence"
    return None


def needs_escalation(
    normalization: dict[str, Any],
    classification: dict[str, Any],
    ctx: PolicyContext,
    policies: dict[str, Any] | None = None,
) -> str | None:
    """Обязательная эскалация руководителю (ТЗ 9.3 [ДТЗ]); возвращает причину или None."""
    p = merged(policies)
    neg = int(normalization.get("negativity") or classification.get("negativity") or 0)
    hidden = normalization.get("hidden_negativity") or {}
    churn = (hidden.get("churn_threat") or {}).get("present") or "churn_threat" in (normalization.get("intents") or [])
    if churn and neg >= p["escalation_negativity"]:
        return "churn_threat_high_negativity"
    if "repeat" in (classification.get("flags") or []) and classification.get("sentiment") == "negative":
        return "repeat_negative"
    if (classification.get("problem_summary") or {}).get("severity") == "critical":
        return "critical_severity"
    if ctx.signals_7d >= p["escalation_signals_7d"]:
        return "three_signals_7d"
    return None


def needs_clarification(
    classification: dict[str, Any],
    normalization: dict[str, Any],
    *,
    already_asked: bool,
    policies: dict[str, Any] | None = None,
) -> bool:
    """Один уточняющий вопрос при низкой уверенности или отсутствии обязательных сущностей; второй подряд запрещён."""
    if already_asked:
        return False
    p = merged(policies)
    if float(classification.get("confidence", 1.0)) < p["clarification_threshold"]:
        return True
    ents = {**(normalization.get("entities") or {}), **(classification.get("entities") or {})}
    if (
        classification.get("signal_type") in ("tariff_terms", "tech_fault")
        and not ents.get("amount_rub")
        and not ents.get("product")
        and not classification.get("product")
    ):
        return True
    return False


def human_options(reason: str) -> list[dict[str, str]]:
    return HUMAN_OPTIONS.get(reason, HUMAN_OPTIONS["_default"])


def human_recommendation(reason: str, classification: dict[str, Any] | None = None) -> str:
    base = HUMAN_RECOMMENDATION.get(reason, HUMAN_RECOMMENDATION["policy_other"])
    if classification and classification.get("summary_ru"):
        return f"{base} Суть: {classification['summary_ru']}"
    return base


def forbidden_phrases(text: str | None) -> list[str]:
    t = (text or "").lower()
    return [ph for ph in FORBIDDEN_PHRASES if ph in t]


def mass_refund_threshold(policies: dict[str, Any] | None = None) -> int:
    return int(merged(policies).get("mass_refund_threshold") or DEFAULT_POLICIES["mass_refund_threshold"])


def mass_refund_requires_human(pending_count: int, policies: dict[str, Any] | None = None) -> bool:
    return pending_count >= mass_refund_threshold(policies)


def fast_path_allowed(
    *,
    fee_rule: dict[str, Any] | None,
    identification: dict[str, Any],
    normalization: dict[str, Any],
    client: dict[str, Any] | None,
    abs_state: dict[str, Any],
    mass_pending: int,
    policies: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Быстрый путь (ТЗ 21.4): подтверждённое правило refund_fee + политики 9.3, не массовый случай."""
    if not fee_rule or fee_rule.get("action") != "refund_fee":
        return False, "нет подтверждённого правила возврата"
    if not fee_rule.get("within_limit", True):
        return False, "сумма выше лимита правила"
    threshold = mass_refund_threshold(policies)
    if mass_pending >= threshold:
        return False, f"массовый случай ({mass_pending} ≥ {threshold}) → HITL"
    segment = (client or {}).get("segment")
    class_conf = float(normalization.get("confidence") or 0.85)
    ok, why = refund_allowed(
        float(fee_rule.get("amount_rub") or 0),
        segment,
        rule_confirmed=True,
        ident_conf=float(identification.get("confidence") or 0),
        class_conf=class_conf,
        already_refunded=abs_state["already_refunded"],
        ctx=PolicyContext(refunds_30d=abs_state["refunds_30d"]),
        policies=policies,
    )
    return (True, "ok") if ok else (False, why)


def refund_allowed(
    amount_rub: float,
    segment: str | None,
    *,
    rule_confirmed: bool,
    ident_conf: float,
    class_conf: float,
    already_refunded: bool,
    ctx: PolicyContext,
    policies: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Автономный возврат комиссии (ТЗ 9.3 [BRD]) — пять условий одновременно."""
    p = merged(policies)
    if segment == "ultra_vip":
        return False, "ultra_vip → всегда HITL"
    limit = p["refund_autonomy_limit_premium_rub"] if segment in ("vip", "premium") else p["refund_autonomy_limit_rub"]
    if not rule_confirmed:
        return False, "правило не подтвердило нарушение"
    if amount_rub > limit:
        return False, f"сумма {amount_rub:.0f} ₽ выше лимита автономии {limit} ₽"
    if ident_conf < 0.8 or class_conf < 0.75:
        return False, "недостаточная уверенность идентификации/классификации"
    if already_refunded:
        return False, "по операции уже был возврат"
    if ctx.refunds_30d >= 3:
        return False, "≥ 3 возвратов за 30 дней — подозрение на злоупотребление"
    return True, "ok"
