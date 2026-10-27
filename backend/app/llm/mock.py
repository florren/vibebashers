"""Mock-провайдер (AGENTS §6.3): детерминированные правила + шаблоны. Работает без сети, заполняет любой JSON-контракт.

Алгоритм: из сообщений извлекается текст сигнала → эвристики (тональность, сарказм, интенты, тип, критичность) →
обход схемы: известные поля заполняются эвристиками, остальные — детерминированно по типу/enum (seed = sha256 текста).
Результат всегда проходит jsonschema (валидируется перед возвратом)."""

from __future__ import annotations

import asyncio
import hashlib
import random
import re
import time
from collections.abc import AsyncIterator
from typing import Any

from app.contracts.registry import validate_schema
from app.i18n import communication_lang
from app.llm.base import LLMProfile, Message, Usage

NEG = (
    "ужас",
    "обман",
    "списал",
    "списали",
    "комисси",
    "не работает",
    "не прошла",
    "не проходит",
    "ошибк",
    "верните",
    "вернуть",
    "жалоб",
    "суд",
    "цб",
    "развод",
    "кошмар",
    "отстой",
    "издева",
    "обнагл",
    "позор",
    "украл",
    "мошенн",
    "зависл",
    "недоступ",
    "навязал",
    "обещал",
    "безобраз",
    "хамств",
    "грубо",
    "ждал",
    "ждут",
    "никто",
    "опять",
    "снова",
    "деньги пропали",
    "заблокир",
    "не могу",
    "невозможно",
    "бесит",
    "достал",
    "плохо",
    "отврат",
    "перестал",
    "сбой",
    "виснет",
    "вылетает",
    "обманули",
)
POS = (
    "спасибо",
    "отлично",
    "супер",
    "молодц",
    "быстро",
    "довол",
    "благодар",
    "класс",
    "рекоменд",
    "лучший",
    "удобно",
    "понрав",
)
SARCASM = (
    "ну конечно",
    "спасибо, что",
    "спасибо что",
    "отличный сервис",
    "прекрасно,",
    "браво",
    "гениально",
    "как всегда",
    "))",
    "ага,",
    "молодцы, ничего не скажешь",
)
CHURN = (
    "закрою",
    "закрываю",
    "уйду",
    "ухожу",
    "перейду",
    "другой банк",
    "расторг",
    "заберу деньги",
    "последний раз",
    "конкурент",
    "менять банк",
    "сменить банк",
    "сменю банк",
    "поменяю банк",
)
REGULATOR = ("цб", "центробанк", "роспотребнадзор", "прокуратур", "суд", "финансов", "омбудсмен", "жалобу в")
PUBLIC = ("все узнают", "расскажу всем", "отзыв", "соцсет", "репост", "подписчик", "сми", "журналист")
REFUND = ("верните", "вернуть", "возврат", "компенс", "отмените комиссию", "верните деньги")
QUESTION = ("как ", "почему", "когда", "где ", "что делать", "подскажите", "можно ли", "?")
FRAUD = ("мошенн", "украл", "не я", "не совершал", "взлом", "подозрительн", "чужой")
TARIFF = (
    "комисси",
    "тариф",
    "процент",
    "ставк",
    "условия",
    "мелким шрифтом",
    "обещали",
    "навязал",
    "страховк",
    "льготный период",
    "оказал",
    "нигде не написано",
    "отказали",
    "отказ в",
    "без объяснени",
)
TECH = (
    "не работает",
    "ошибк",
    "зависл",
    "вылетает",
    "сбой",
    "не приходит",
    "смс",
    "push",
    "код",
    "не грузит",
    "недоступ",
    "не открывается",
    "qr",
    "дважды",
    "два списания",
    "двойное",
    "не уменьшил",
    "не зачисл",
    "не пришёл",
    "не пришел",
    "не поступил",
    "не отобража",
    "не обновил",
)
CLIENT_ERROR = (
    "это я сам",
    "сам виноват",
    "сама виновата",
    "неверный пин",
    "неправильный пин",
    "забыл",
    "забыла",
    "перепутал",
    "ошибся",
    "ошиблась",
    "не туда",
    "как разблокировать",
    "как восстановить",
    "сам заблокировал",
    "не досмотрел",
    "не заметил",
    "не на тот",
    "сам ошиб",
)
SUGGEST = ("предлага", "было бы удобно", "добавьте", "хотелось бы", "сделайте", "хочу чтобы", "было бы здорово")
GRATITUDE = ("решила вопрос", "решил вопрос", "побольше бы таких", "всё решили", "все решили", "вернули", "выручили")
DOUBLE_DEBIT = (
    "двойное списание",
    "дважды списал",
    "два списания",
    "списали дважды",
    "списали два раза",
    "повторное списание",
)
TECH_STRONG = tuple(w for w in TECH if w not in ("смс", "push", "код", "qr", "не приходит"))
SERVICE = ("оператор", "отделен", "очеред", "хам", "груб", "ждал", "перезвон", "менеджер", "сотрудник", "консультант")
PRODUCT_WORDS = {
    "deposit": ("вклад", "депозит", "накопит"),
    "credit_card": ("кредитк", "кредитная карта"),
    "credit": ("кредит", "ипотек", "займ", "платёж по"),
    "debit_card": ("карт", "дебет", "qr", "оплат", "перевод"),
}
SYSTEM_WORDS = {
    "mobile_app": ("приложени", "апп", "мобильн"),
    "web_bank": ("сайт", "интернет-банк", "веб"),
    "contact_center": ("оператор", "горячая линия", "колл", "звон"),
    "processing": ("qr", "оплат", "терминал", "списал", "комисси"),
    "notification_gw": ("смс", "push", "уведомлен", "код"),
    "antifraud": ("заблокир", "мошенн", "подозрит"),
    "promo_engine": ("промокод", "акци", "кешбэк", "бонус"),
    "sub_deposits": ("вклад", "депозит"),
    "sub_lending": ("кредит", "ипотек"),
    "sub_debit": ("дебет",),
}
TEAM_BY_TYPE = {
    "tech_fault": "team_processing",
    "client_error": "team_contact_center",
    "tariff_terms": "team_debit",
    "service_quality": "team_cx",
    "fraud_suspicion": "team_antifraud",
    "legal_regulatory": "team_compliance",
    "info_request": "team_contact_center",
    "gratitude": "team_cx",
    "suggestion": "team_cx",
    "churn": "team_cx",
}


def _has(text: str, words: tuple[str, ...]) -> bool:
    return any(w in text for w in words)


def analyze(text: str) -> dict[str, Any]:
    """Эвристический разбор текста сигнала — общий для всех контрактов."""
    t = text.lower()
    neg = sum(1 for w in NEG if w in t)
    pos = sum(1 for w in POS if w in t)
    sarcasm = _has(t, SARCASM) and (neg > 0 or "спасибо" in t and _has(t, TARIFF + TECH))
    exclam = t.count("!")
    caps = sum(1 for w in re.findall(r"[А-ЯA-Z]{4,}", text))
    negativity = min(
        100, neg * 22 + exclam * 5 + caps * 8 + (35 if sarcasm else 0) + (20 if _has(t, CHURN) else 0) - pos * 15
    )
    negativity = max(0, negativity)
    if pos > 0 and neg == 0 and not sarcasm:
        negativity = min(negativity, 15)
    sentiment = (
        "negative"
        if negativity >= 67 or (negativity >= 34 and neg >= 2)
        else "positive"
        if negativity <= 33 and pos > 0 and neg == 0
        else "neutral"
    )
    if negativity >= 67:
        sentiment = "negative"
    hidden = sarcasm or (sentiment != "negative" and neg > 0 and pos > 0)
    grateful = (pos > 0 or _has(t, GRATITUDE)) and not _has(t, ("не вернули", "не решили", "так и не"))
    if _has(t, FRAUD):
        stype = "fraud_suspicion"
    elif _has(t, CLIENT_ERROR):
        stype = "client_error"
    elif _has(t, SUGGEST):
        stype = "suggestion"
    elif (
        _has(t, ("есть ли", "можно ли", "подскажите", "какие документы", "сколько стоит", "как оформить"))
        and neg <= 1
        and not _has(t, REFUND + ("оказал", "нигде не написано", "обещал"))
        and not sarcasm
    ):
        stype = "info_request"
    elif grateful and neg <= 1 and not sarcasm and not _has(t, CHURN + REGULATOR):
        stype = "gratitude"
    elif _has(t, REGULATOR) and neg > 0:
        stype = "legal_regulatory"
    elif _has(t, DOUBLE_DEBIT):
        stype = "tech_fault"  # «двойное списание» — сбой процессинга, даже если речь о комиссии
    elif _has(t, TARIFF) and (neg > 0 or sarcasm or _has(t, ("оказал", "нигде не", "обещал"))):
        stype = "tariff_terms"
    elif _has(t, TECH_STRONG) or (_has(t, TECH) and (neg > 0 or sarcasm)):
        stype = "tech_fault"
    elif _has(t, SERVICE) and neg > 0:
        stype = "service_quality"
    elif _has(t, QUESTION) and neg == 0:
        stype = "info_request"
    elif _has(t, CHURN):
        stype = "churn"
    else:
        stype = "service_quality" if neg > 0 else "info_request"
    if stype == "gratitude" and neg == 0:
        sentiment, negativity = "positive", min(negativity, 15)
    elif (
        stype in ("tech_fault", "tariff_terms", "service_quality", "fraud_suspicion", "legal_regulatory")
        and pos == 0
        and not sarcasm
    ):
        sentiment, negativity = "negative", max(negativity, 60)
    intents = []
    if _has(t, CHURN):
        intents.append("churn_threat")
    if _has(t, REFUND):
        intents.append("refund_request")
    if _has(t, REGULATOR) and neg > 0:
        intents.append("regulator_threat")
    if _has(t, PUBLIC) and neg > 0:
        intents.append("public_shaming")
    if stype == "gratitude":
        intents.append("gratitude")
    elif _has(t, QUESTION) and neg == 0:
        intents.append("question")
    elif neg > 0 or sarcasm:
        intents.append("complaint")
    flags = []
    if _has(t, CHURN):
        flags.append("churn_intent")
    if sarcasm:
        flags.append("sarcasm")
    if exclam >= 3 or caps >= 2 or _has(t, ("хам", "идиот", "твар", "сволоч")):
        flags.append("aggression")
    if _has(t, REGULATOR) and neg > 0:
        flags.append("regulator_threat")
    if hidden and not sarcasm:
        flags.append("passive_aggression")
    if _has(t, ("опять", "снова", "в третий раз", "второй раз", "уже писал")):
        flags.append("repeat")
    amount = re.search(r"(\d[\d\s]{1,9})\s*(?:₽|руб|р\.)", t)
    product = next((p for p, ws in PRODUCT_WORDS.items() if _has(t, ws)), None)
    system = next((s for s, ws in SYSTEM_WORDS.items() if _has(t, ws)), None)
    criticality = (
        "high"
        if negativity >= 67 or "churn_threat" in intents or "regulator_threat" in intents or stype == "fraud_suspicion"
        else "medium"
        if negativity >= 34
        else "low"
    )
    tone = (
        "sarcastic"
        if sarcasm
        else "angry"
        if negativity >= 75 or "aggression" in flags
        else "irritated"
        if negativity >= 40
        else "positive"
        if sentiment == "positive"
        else "formal"
        if _has(t, ("прошу", "уважаем", "в соответствии", "заявлени"))
        else "neutral"
    )
    groups = {
        "fraud_suspicion": FRAUD,
        "client_error": CLIENT_ERROR,
        "gratitude": POS + GRATITUDE,
        "legal_regulatory": REGULATOR,
        "tariff_terms": TARIFF,
        "tech_fault": TECH,
        "service_quality": SERVICE,
        "suggestion": SUGGEST,
        "info_request": QUESTION,
        "churn": CHURN,
    }
    hits = sum(1 for w in groups.get(stype, ()) if w in t)
    confidence = 0.55 if hits == 0 else 0.78 if hits == 1 else 0.9
    if sarcasm or hidden:
        confidence = min(confidence, 0.8)
    return {
        "confidence": confidence,
        "negativity": negativity,
        "sentiment": sentiment,
        "hidden_negativity": hidden,
        "sarcasm": sarcasm,
        "intents": intents,
        "flags": flags,
        "signal_type": stype,
        "criticality": criticality,
        "tone": tone,
        "product": product,
        "system": system,
        "amount_rub": float(amount.group(1).replace(" ", "")) if amount else None,
        "churn": "churn_threat" in intents,
        "team": TEAM_BY_TYPE[stype]
        if stype != "tariff_terms"
        else (
            "team_debit"
            if product in (None, "debit_card")
            else "team_deposits"
            if product == "deposit"
            else "team_lending"
        ),
        "text": text,
    }


def _summary(a: dict[str, Any]) -> str:
    kind = {
        "tech_fault": "техническая проблема",
        "client_error": "ошибка клиента",
        "tariff_terms": "спор о тарифах/комиссии",
        "service_quality": "качество обслуживания",
        "fraud_suspicion": "подозрение на мошенничество",
        "legal_regulatory": "угроза регулятору/суд",
        "info_request": "вопрос клиента",
        "gratitude": "благодарность",
        "suggestion": "предложение",
        "churn": "риск оттока",
    }[a["signal_type"]]
    amt = f", сумма {a['amount_rub']:.0f} ₽" if a.get("amount_rub") else ""
    return (
        f"{kind.capitalize()}{amt}; тональность {a['sentiment']}, негатив {a['negativity']}/100"
        + (" (скрытый негатив/сарказм)" if a["hidden_negativity"] else "")
        + "."
    )


def _rationale(a: dict[str, Any]) -> str:
    bits = [f"Текст классифицирован как «{a['signal_type']}» по ключевым словам."]
    if a["sarcasm"]:
        bits.append("Обнаружены маркеры сарказма — реальная тональность негативная при внешне нейтральной форме.")
    if a["intents"]:
        bits.append("Намерения: " + ", ".join(a["intents"]) + ".")
    bits.append(f"Критичность {a['criticality']}, рекомендуемая команда {a['team']}.")
    return " ".join(bits)


def _text_for(field: str, a: dict[str, Any]) -> str:
    f = field.lower()
    if "public_reply" in f:
        return (
            "Здравствуйте! Нам очень жаль, что так вышло. Мы уже разбираемся в ситуации и напишем вам в личные сообщения, чтобы уточнить детали и помочь."
            if a["sentiment"] != "positive"
            else "Спасибо за тёплые слова! Нам очень приятно, передадим команде."
        )
    if "client_notice" in f or "notice" in f:
        return (
            "Мы получили ваше обращение и уже разбираемся. Если спишется комиссия или платёж не пройдёт — вернём средства автоматически и сообщим вам."
            if a["sentiment"] != "positive"
            else "Спасибо за обращение! Рады, что всё понравилось."
        )
    if "team_notice" in f:
        return f"Сигнал: {a['signal_type']}, негатив {a['negativity']}/100. Проверьте систему {a.get('system') or 'не определена'} и свяжитесь с клиентом."
    if "clarification" in f:
        return "Уточните, пожалуйста, дату операции и последние 4 цифры карты, чтобы мы быстрее нашли платёж."
    if "title" in f:
        return _summary(a).split(";")[0]
    if "problem" in f:
        return _summary(a).split(";")[0] + ". Требуется проверка и ответ клиенту."
    if "summary" in f:
        return _summary(a)
    if "rationale" in f or "reason" in f:
        return _rationale(a)
    if "hypothesis" in f:
        return str(a["signal_type"])
    if "human_reason" in f:
        return "Высокая критичность: угроза оттока или регулятора — нужна проверка человеком перед ответом."
    if "human_recommendation" in f:
        return "Рекомендуем: подтвердить возврат комиссии и персональный звонок в течение 30 минут."
    if "human_option" in f or f in ("option", "label_ru", "label"):
        return "Подтвердить возврат и позвонить клиенту"
    if f == "code":
        return "confirm_refund_and_call"
    if f == "language":
        return communication_lang(str(a.get("text") or ""))
    if f == "text_ru" or f.endswith("_ru"):
        return "Спасибо, жду решения." if a["sentiment"] != "positive" else "Отлично, спасибо!"
    return "—"


MOCK_HINT_START, MOCK_HINT_END = "<<mock_verdict>>", "<</mock_verdict>>"


def _mock_hint(messages: list[Message]) -> dict[str, Any] | None:
    """Детекторы комплаенса передают предварительный вердикт правил; mock возвращает его как ответ модели (mock = правила)."""
    import json

    for m in reversed(messages):
        c = m.get("content") or ""
        i, j = c.find(MOCK_HINT_START), c.find(MOCK_HINT_END)
        if i >= 0 and j > i:
            try:
                out = json.loads(c[i + len(MOCK_HINT_START) : j])
            except ValueError:
                return None
            return out if isinstance(out, dict) else None
    return None


class MockProvider:
    name = "mock"

    def __init__(self, latency_ms: int = 0) -> None:
        self.latency_ms = latency_ms

    @staticmethod
    def _signal_text(messages: list[Message]) -> str:
        users = [m["content"] for m in messages if m["role"] == "user"]
        return users[-1] if users else " ".join(m["content"] for m in messages)

    def fill(
        self,
        schema: dict[str, Any],
        a: dict[str, Any],
        rnd: random.Random,
        name: str = "",
        depth: int = 0,
        *,
        required: bool = True,
    ) -> Any:  # noqa: C901, PLR0911, PLR0912
        """Детерминированное заполнение (разыменованной) схемы с учётом эвристик по имени поля."""
        if "const" in schema:
            return schema["const"]
        if "anyOf" in schema or "oneOf" in schema:
            variants: list[dict[str, Any]] = schema.get("anyOf") or schema.get("oneOf") or []
            non_null = [v for v in variants if v.get("type") != "null"]
            has_null = len(non_null) < len(variants)
            if name in ("product", "system"):
                return a.get(name) if a.get(name) in (non_null[0].get("enum") or [a.get(name)]) else None
            if has_null and (not required or name in ("error_code", "next_channel")):
                return None
            return (
                self.fill(non_null[0] if non_null else variants[0], a, rnd, name, depth, required=required)
                if non_null
                else None
            )
        if "allOf" in schema:
            base = {k: v for k, v in schema.items() if k != "allOf"}
            plain = [p for p in schema["allOf"] if "if" not in p]
            for part in plain:  # обычные части allOf — объединяем
                base = {
                    **base,
                    **part,
                    "properties": {**base.get("properties", {}), **part.get("properties", {})},
                    "required": [*base.get("required", []), *part.get("required", [])],
                }
            obj = self.fill(base, a, rnd, name, depth)
            if isinstance(obj, dict):
                for _ in range(2):  # условные части if/then: дозаполняем обязательные поля ветки
                    for part in schema["allOf"]:
                        if "if" in part and not validate_schema(obj, part["if"]):
                            then = part.get("then", {})
                            for key in then.get("required", []):
                                sub = {
                                    **base.get("properties", {}).get(key, {}),
                                    **then.get("properties", {}).get(key, {}),
                                }
                                if key not in obj or obj[key] is None or validate_schema(obj[key], sub):
                                    obj[key] = self.fill(sub, a, rnd, key, depth + 1, required=True)
                            for key, extra in then.get("properties", {}).items():
                                if key in obj and key not in then.get("required", []):
                                    sub = {**base.get("properties", {}).get(key, {}), **extra}
                                    if validate_schema(obj[key], sub):
                                        obj[key] = self.fill(sub, a, rnd, key, depth + 1, required=True)
            return obj
        typ = schema.get("type")
        if isinstance(typ, list):
            if "null" in typ and not required and name not in ("title_ru", "human_recommendation"):
                return None
            typ = next((t for t in typ if t != "null"), "null")
        enum = schema.get("enum")
        n = name.lower()
        if enum:
            for key in ("sentiment", "tone", "criticality", "signal_type"):
                if n == key and a[key] in enum:
                    return a[key]
            if n == "severity":
                return (
                    {"low": "low", "medium": "medium", "high": "high"}[a["criticality"]]
                    if not a["churn"]
                    else "critical"
                )
            if n in ("suggested_team", "team", "route", "team_code") and a["team"] in enum:
                return a["team"]
            if n == "incident_type":
                return a["signal_type"] if a["signal_type"] in enum else enum[0]
            if n == "code" and "—" not in enum:
                return enum[0]
            if n == "cause_hypothesis":
                return a["signal_type"] if a["signal_type"] in enum else "unknown"
            if n == "complexity":
                return "instant" if a["criticality"] == "low" else "easy" if a["criticality"] == "medium" else "medium"
            if n == "incident_action":
                return (
                    "create"
                    if "create" in enum and a["sentiment"] == "negative"
                    else "none"
                    if "none" in enum
                    else enum[0]
                )
            if n == "router_action":
                return (
                    "escalate"
                    if a["criticality"] == "high" and "escalate" in enum
                    else "route"
                    if "route" in enum
                    else enum[0]
                )
            if n == "client_action":
                return (
                    next((e for e in enum if "notice" in e or "reply" in e), enum[0])
                    if a["sentiment"] == "negative"
                    else enum[-1]
                )
            if n == "language":
                return "ru" if "ru" in enum else enum[0]
            if n == "reaction":
                return next((e for e in enum if e != "silent"), enum[0])
            if n == "decision":
                return enum[0]
            if n == "llm_source":
                return "mock"
            return enum[0]
        if typ == "object" or "properties" in schema:
            props = schema.get("properties", {})
            req = set(schema.get("required", []))
            out: dict[str, Any] = {}
            for key, sub in props.items():
                if key in req or key in (
                    "flags",
                    "intents",
                    "entities",
                    "secondary_types",
                    "negativity",
                    "language",
                    "product",
                    "system",
                    "fast_path",
                    "rule_codes",
                ):
                    out[key] = self.fill(sub, a, rnd, key, depth + 1, required=key in req)
            if not props and schema.get("additionalProperties") not in (False, None) and depth < 2:
                return {}
            if "present" in out:  # блоки hidden_negativity.{sarcasm, passive_aggression, churn_threat}
                present = {
                    "sarcasm": a["sarcasm"],
                    "passive_aggression": "passive_aggression" in a["flags"],
                    "churn_threat": a["churn"],
                }.get(n, False)
                out["present"] = present
                if "confidence" in out:
                    out["confidence"] = 0.85 if present else 0.1
                if "evidence_ru" in props:
                    out["evidence_ru"] = a["text"][:300] if present and a["text"] else None
            return out
        if typ == "array":
            items = schema.get("items", {})
            if n == "flags":
                vals = [f for f in a["flags"] if not items.get("enum") or f in items["enum"]]
            elif n == "intents":
                vals = [i for i in a["intents"] if not items.get("enum") or i in items["enum"]]
            elif n in (
                "secondary_types",
                "related_incident_ids",
                "candidates",
                "violations",
                "steps",
                "rule_codes",
                "mentions",
                "wants",
                "evaluated",
            ):
                vals = []
                if n == "rule_codes" and a["signal_type"] == "tariff_terms" and "qr" in a["text"].lower():
                    vals = ["RULE-QR-FEE-001"]
                if n == "actions" or n == "evaluated":
                    vals = []
            else:
                vals = [self.fill(items, a, rnd, n[:-1], depth + 1)] if schema.get("minItems", 0) > 0 else []
            mn = schema.get("minItems", 0)
            while len(vals) < mn and items:
                vals.append(self.fill(items, a, rnd, n[:-1], depth + 1))
            mx = schema.get("maxItems")
            if mx is not None:
                vals = vals[:mx]
            if schema.get("uniqueItems"):
                uniq: list[Any] = []
                for v in vals:
                    if v not in uniq:
                        uniq.append(v)
                vals = uniq
            return vals
        if typ == "string":
            if n == "masked_card":
                return None
            s = _text_for(name, a)
            if "format" in schema and schema["format"] == "date-time":
                return "2026-11-09T10:00:00+03:00"
            if "pattern" in schema:
                return s
            mn, mx = schema.get("minLength", 0), schema.get("maxLength")
            if len(s) < mn:
                s = (s + " Подробности уточняются.") * ((mn // max(len(s), 1)) + 1)
            return s[:mx] if mx else s
        if typ == "integer":
            lo, hi = schema.get("minimum", 0), schema.get("maximum", 100)
            if n == "churn_risk":
                return int(max(lo, min(hi, a["negativity"] * 0.7 + (30 if a["churn"] else 0))))
            if n in ("negativity",):
                return int(max(lo, min(hi, a["negativity"])))
            if n in ("priority",):
                return {"high": lo + 0, "medium": (lo + hi) // 2, "low": hi}[a["criticality"]] if hi <= 10 else 1
            if n in ("satisfaction", "perceived_care"):
                return int(max(lo, min(hi, 100 - a["negativity"])))
            if n in ("ms", "at_ms", "latency_ms"):
                return 120
            return int(max(lo, min(hi, 1)))
        if typ == "number":
            lo, hi = float(schema.get("minimum", 0)), float(schema.get("maximum", 1))
            if n == "confidence":
                return round(max(lo, min(hi, float(a.get("confidence", 0.7)))), 2)
            if n in ("negativity", "churn_intent", "threshold"):
                return round(max(lo, min(hi, a["negativity"] / (100 if hi <= 1 else 1))), 2)
            if n == "amount_rub":
                return a.get("amount_rub")
            return lo
        if typ == "boolean":
            if n == "needs_human":
                return a["criticality"] == "high" and (a["churn"] or "regulator_threat" in a["intents"])
            if n == "hidden_negativity":
                return a["hidden_negativity"]
            if n in ("ok", "escalate_to_dm"):
                return n == "ok"
            return False
        if typ == "null":
            return None
        return None

    async def complete_structured(
        self, messages: list[Message], schema: dict[str, Any], profile: LLMProfile, *, timeout_s: float
    ) -> tuple[dict[str, Any], Usage, str]:
        import json

        t0 = time.perf_counter()
        text = self._signal_text(messages)
        a = analyze(text)
        rnd = random.Random(int(hashlib.sha256(text.encode()).hexdigest()[:12], 16))
        hinted = _mock_hint(messages)
        obj = hinted if hinted is not None else self.fill(schema, a, rnd)
        errors = validate_schema(obj, schema)
        if errors:  # mock обязан соответствовать контракту — иначе это ошибка mock, а не модели
            raise AssertionError("mock не прошёл схему: " + "; ".join(errors[:3]))
        if self.latency_ms:
            await asyncio.sleep(self.latency_ms / 1000)
        raw = json.dumps(obj, ensure_ascii=False)
        usage = Usage(
            prompt_tokens=sum(len(m["content"]) // 4 for m in messages),
            completion_tokens=len(raw) // 4,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            provider=self.name,
            model="mock-rules-v1",
            source="mock",
        )
        return obj, usage, raw

    async def stream(self, messages: list[Message], profile: LLMProfile, *, timeout_s: float) -> AsyncIterator[str]:
        a = analyze(self._signal_text(messages))
        for word in _text_for("public_reply_ru", a).split(" "):
            yield word + " "
            await asyncio.sleep(0.01)
