"""Узлы графа агента (T-056/T-059/T-060/T-061/T-076/T-210/T-212). Каждый узел: state → state, записывает agent_steps.

Принцип: LLM предлагает содержание (тексты, гипотезы), код — детерминированные поля (SLA, приоритет, маршрут по правилам,
политики HITL/эскалации) и пост-проверки согласованности. Любая ошибка LLM → fallback на правила, агент не падает."""

from __future__ import annotations

import dataclasses
import datetime as dt
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import orjson

from app.agent import gifts as giftmod
from app.agent import policies as pol
from app.agent import sla as slam
from app.agent.matching import log_ru
from app.agent.prompts import load as load_prompt
from app.agent.state import AgentState
from app.agent.tools import abs as abs_tools
from app.agent.tools import read as rt
from app.agent.tools import router_tools
from app.agent.tools import write as wt
from app.agent.tools.base import ActFrame, ToolContext, mask_name
from app.contracts.registry import deref, validate
from app.economics.calibration import PIPELINE as SCORE_PIPELINE
from app.i18n import communication_lang
from app.llm.base import LLMProfile, Message
from app.llm.failover import ProviderChain
from app.logging import get_logger
from app.rules.engine import check_rules
from app.sim.events import dumps

log = get_logger(__name__)

RUN_STEP_TEXT_BUDGET = 200 * 1024
PG_NOTIFY_PAYLOAD_LIMIT = 8000
TOKEN_DELTA_CHUNK = 512


def _utf8_len(value: str | None) -> int:
    if not value:
        return 0
    return len(value.encode("utf-8"))


def _truncate_utf8(value: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    raw = value.encode("utf-8")
    if len(raw) <= max_bytes:
        return value
    cut = raw[:max_bytes]
    while cut:
        try:
            return cut.decode("utf-8")
        except UnicodeDecodeError:
            cut = cut[:-1]
    return ""


def _chunk_utf8(text: str, chunk_bytes: int) -> list[str]:
    if not text:
        return []
    out: list[str] = []
    pos = 0
    encoded = text.encode("utf-8")
    while pos < len(encoded):
        piece = encoded[pos : pos + chunk_bytes]
        while piece:
            try:
                out.append(piece.decode("utf-8"))
                pos += len(piece)
                break
            except UnicodeDecodeError:
                piece = piece[:-1]
        else:
            break
    return out


def _trim_text_fields(
    remaining: int,
    prompt: str | None,
    response_raw: str | None,
    reasoning: str | None,
    *,
    fixed_bytes: int,
) -> tuple[str | None, str | None, str | None]:
    """Ужимает только prompt/response_raw/reasoning; fixed_bytes — уже учтённые output+tool_calls."""
    fields: dict[str, str | None] = {"prompt": prompt, "response_raw": response_raw, "reasoning": reasoning}
    total = fixed_bytes + sum(_utf8_len(v) for v in fields.values())
    if total <= remaining:
        return prompt, response_raw, reasoning
    keys = [k for k in fields if _utf8_len(fields[k])]
    while total > remaining and keys:
        key = max(keys, key=lambda k: _utf8_len(fields[k]))
        current = fields[key] or ""
        over = total - remaining
        new_len = max(0, _utf8_len(current) - over)
        trimmed = _truncate_utf8(current, new_len)
        total -= _utf8_len(current) - _utf8_len(trimmed)
        fields[key] = trimmed or None
        if not fields[key]:
            keys.remove(key)
    return fields["prompt"], fields["response_raw"], fields["reasoning"]


def _fit_step_texts(
    remaining: int,
    *,
    prompt: str | None,
    response_raw: str | None,
    reasoning: str | None,
    output_json: str,
    tool_calls_json: str,
) -> tuple[str | None, str | None, str | None, str, str]:
    empty_out, empty_tools = "{}", "[]"
    out, tools = output_json, tool_calls_json
    p, r, reason = _trim_text_fields(
        remaining, prompt, response_raw, reasoning, fixed_bytes=_utf8_len(out) + _utf8_len(tools)
    )
    if _utf8_len(p) + _utf8_len(r) + _utf8_len(reason) + _utf8_len(out) + _utf8_len(tools) <= remaining:
        return p, r, reason, out, tools
    out, tools = empty_out, empty_tools
    p, r, reason = _trim_text_fields(remaining, p, r, reason, fixed_bytes=_utf8_len(out) + _utf8_len(tools))
    return p, r, reason, out, tools


PRODUCT_SYSTEMS = {
    "deposit": ["sub_deposits", "promo_engine", "mobile_app", "core_abs"],
    "debit_card": ["processing", "sub_debit", "mobile_app", "notification_gw"],
    "credit": ["sub_lending", "mobile_app", "core_abs"],
    "credit_card": ["sub_lending", "processing", "mobile_app"],
}
TYPE_BASE_CRIT = {
    "tech_fault": "high",
    "client_error": "low",
    "tariff_terms": "medium",
    "service_quality": "medium",
    "fraud_suspicion": "high",
    "legal_regulatory": "high",
    "info_request": "low",
    "gratitude": "low",
    "suggestion": "low",
}
NO_INCIDENT_TYPES = {"gratitude", "suggestion", "info_request"}
PUBLIC_CHANNELS = {"social", "review_portal"}
RE_AMOUNT = re.compile(r"(\d[\d\s]{1,8})\s*(?:₽|руб|р\.|рублей|рубля)", re.I)
RE_CARD4 = re.compile(r"\*{2,4}\s?(\d{4})")
RE_PROMO = re.compile(r"\b(PROMO-[A-Z0-9-]+)\b", re.I)
RE_SENT = re.compile(r"[^.!?…]+[.!?…]*")


@dataclass
class Deps:
    ctx: ToolContext
    chain: ProviderChain
    profile: LLMProfile
    fast_profile: LLMProfile | None = None
    policies: dict[str, Any] = field(default_factory=dict)
    teams: list[str] = field(default_factory=list)
    routing_rules: list[tuple[int, dict[str, Any], list[str]]] = field(default_factory=list)
    sla_matrix: dict[tuple[str, str], dict[str, Any]] | None = None
    fewshot: list[dict[str, Any]] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)  # накопленные agent_steps (seq, node, …)
    tokens: dict[str, float | int] = field(
        default_factory=lambda: {"prompt": 0, "completion": 0, "latency_ms": 0, "cost": 0.0}
    )
    text_bytes_used: int = 0

    async def begin_step(self, node: str) -> None:
        seq = len(self.steps) + 1
        await self.ctx.notify(
            "agent",
            "step_started",
            {
                "run_id": self.ctx.agent_run_id,
                "seq": seq,
                "node": node,
                "status": "started",
            },
        )

    async def _emit_token_deltas(self, node: str, seq: int, raw: str) -> None:
        chunks = _chunk_utf8(raw, TOKEN_DELTA_CHUNK)
        for idx, chunk in enumerate(chunks):
            await self.ctx.notify(
                "agent_tokens",
                "delta",
                {
                    "run_id": self.ctx.agent_run_id,
                    "step_seq": seq,
                    "node": node,
                    "delta": chunk,
                    "kind": "content",
                    "done": idx == len(chunks) - 1,
                },
            )

    async def record_step(
        self,
        node: str,
        status: str,
        state_in: dict[str, Any],
        output: dict[str, Any],
        *,
        prompt: str | None = None,
        raw: str | None = None,
        reasoning: str | None = None,
        model: str | None = None,
        usage: dict[str, int] | None = None,
        latency_ms: int = 0,
    ) -> None:
        seq = len(self.steps) + 1
        usage = usage or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        step_cost = float(usage.get("cost_rub") or 0)
        if step_cost == 0.0 and (prompt_tokens or completion_tokens):
            step_cost = self.profile.cost(prompt_tokens, completion_tokens)
        self.tokens["cost"] = float(self.tokens.get("cost", 0)) + step_cost

        tool_calls = self.ctx.take_calls()
        tool_calls_json = dumps(tool_calls)
        output_json = dumps(output)
        remaining = RUN_STEP_TEXT_BUDGET - self.text_bytes_used
        prompt, raw, reasoning, output_json, tool_calls_json = _fit_step_texts(
            remaining,
            prompt=prompt,
            response_raw=raw,
            reasoning=reasoning,
            output_json=output_json,
            tool_calls_json=tool_calls_json,
        )
        if raw:
            await self._emit_token_deltas(node, seq, raw)

        finished: dict[str, Any] = {
            "run_id": self.ctx.agent_run_id,
            "seq": seq,
            "node": node,
            "status": status,
            "latency_ms": latency_ms,
            "tokens": prompt_tokens + completion_tokens,
        }
        finished_with_tools = {**finished, "tool_calls": tool_calls}
        notify_body = dumps({"type": "step_finished", "run_id": self.ctx.run_id, "data": finished_with_tools})
        finished_payload = finished_with_tools if _utf8_len(notify_body) <= PG_NOTIFY_PAYLOAD_LIMIT else finished
        await self.ctx.notify("agent", "step_finished", finished_payload)

        await self.ctx.conn.execute(
            "insert into agent_steps (run_id, seq, node, status, input, output, prompt, response_raw, reasoning, tool_calls, model, prompt_tokens, completion_tokens, latency_ms, started_at, finished_at) "
            "values (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, now() - make_interval(secs => %s / 1000.0), now())",
            (
                self.ctx.agent_run_id,
                seq,
                node,
                status,
                dumps(state_in),
                output_json,
                prompt,
                raw,
                reasoning,
                tool_calls_json,
                model,
                prompt_tokens,
                completion_tokens,
                latency_ms,
                latency_ms,
            ),
        )
        self.text_bytes_used += (
            _utf8_len(prompt)
            + _utf8_len(raw)
            + _utf8_len(reasoning)
            + _utf8_len(output_json)
            + _utf8_len(tool_calls_json)
        )
        self.tokens["prompt"] += prompt_tokens
        self.tokens["completion"] += completion_tokens
        self.tokens["latency_ms"] += latency_ms
        self.steps.append({"seq": seq, "node": node, "status": status})


# ---------------------------------------------------------------------------------------------------------------------
# помощники
# ---------------------------------------------------------------------------------------------------------------------
def prune(obj: Any, schema: dict[str, Any]) -> Any:
    """Убирает ключи, не описанные схемой (additionalProperties=false), и приводит очевидные типы — чтобы ответ модели прошёл валидацию."""
    if isinstance(obj, dict) and schema.get("type") in ("object", ["object", "null"]) and "properties" in schema:
        out: dict[str, Any] = {}
        for k, sub in schema["properties"].items():
            if k in obj:
                out[k] = prune(obj[k], sub)
        return out
    if isinstance(obj, list) and isinstance(schema.get("items"), dict):
        return [prune(x, schema["items"]) for x in obj]
    if isinstance(obj, str) and "enum" in schema and obj not in schema["enum"]:
        if None in schema["enum"] or "null" in (schema.get("type") or []):
            return None
    return obj


def _state_brief(state: AgentState) -> dict[str, Any]:
    return {
        "signal_id": state["signal"].get("id"),
        "client_id": (state.get("client") or {}).get("client_id"),
        "node": state.get("current_node"),
        "classification": {k: state["classification"].get(k) for k in ("signal_type", "confidence", "criticality")},
        "decision": {k: state["decision"].get(k) for k in ("incident_action", "router_action", "needs_human")},
    }


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in RE_SENT.findall(text or "") if s.strip()]


def _dt(value: Any) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value
    return dt.datetime.fromisoformat(str(value))


def clamp_hidden_evidence(text: str, hidden: dict[str, Any]) -> dict[str, Any]:
    """evidence_ru обязан быть подстрокой текста; иначе null и confidence × 0,7 (T-211)."""
    out: dict[str, Any] = {}
    for key in ("sarcasm", "passive_aggression", "churn_threat"):
        block = dict(hidden.get(key) or {})
        evidence = block.get("evidence_ru")
        if evidence and str(evidence) not in text:
            block["evidence_ru"] = None
            block["confidence"] = round(float(block.get("confidence") or 0) * 0.7, 3)
        if "present" not in block:
            block["present"] = False
        out[key] = block
    return out


async def _llm(
    deps: Deps,
    task: str,
    schema_name: str,
    system_vars: dict[str, Any],
    user_text: str,
    *,
    profile: LLMProfile | None = None,
    context: str = "default",
    fallback_profile: LLMProfile | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Вызов цепочки: system = system.md + промпт задачи (с контекстом), user = текст сигнала. Возвращает (obj, meta)."""
    prompt = (
        load_prompt("system").body
        + "\n\n"
        + load_prompt(task, "v2" if task in ("classify", "normalize") else "v1").render(
            **{k: (v if isinstance(v, str) else dumps(v)) for k, v in system_vars.items()}
        )
    )
    messages: list[Message] = [{"role": "system", "content": prompt}, {"role": "user", "content": user_text}]
    schema = deref(schema_name)
    t0 = time.perf_counter()
    options: dict[str, Any] = {"fallback_profile": fallback_profile} if fallback_profile is not None else {}
    res = await deps.chain.complete_structured(messages, schema, profile or deps.profile, context=context, **options)
    obj = prune(res.obj, schema)
    meta = {
        "prompt": prompt,
        "raw": res.raw[:8000],
        "model": f"{res.provider}:{res.usage.model or (profile or deps.profile).model}",
        "usage": res.usage.as_dict(),
        "latency_ms": int((time.perf_counter() - t0) * 1000),
        "provider": res.provider,
        "fallback_mock": res.fallback_mock,
        "error": res.error,
        "attempts": [
            {"provider": a.provider, "model": a.model, "ok": a.ok, "ms": a.ms, "error": a.error} for a in res.attempts
        ],
    }
    return obj, meta


# ---------------------------------------------------------------------------------------------------------------------
# узлы
# ---------------------------------------------------------------------------------------------------------------------
async def ingest(state: AgentState, deps: Deps) -> AgentState:
    sig = state["signal"]
    # Старые baseline/симуляторные записи могли появиться до T-239: предобработка до первого LLM.
    if "red_words" not in (sig.get("meta") or {}):
        from app.ingest.red_words import detect

        red = detect(sig.get("text") or "")
        sig["red_words"] = red["words"]
        sig["flags"] = list(dict.fromkeys([*(sig.get("flags") or []), *(["red_word"] if red["words"] else [])]))
        sig["meta"] = {**(sig.get("meta") or {}), "red_words": red}
        await deps.ctx.conn.execute(
            "update signals set red_words = %s, flags = %s, meta = meta || %s::jsonb where id = %s",
            (red["words"], sig["flags"], dumps({"red_words": red}), sig["id"]),
        )
    await deps.ctx.conn.execute(
        "update signals set status = 'processing', updated_at = now() where id = %s and status in ('new','deferred')",
        (sig["id"],),
    )
    await deps.ctx.notify(
        "signals", "status", {"id": sig["id"], "status": "processing", "agent_run_id": deps.ctx.agent_run_id}
    )
    state["current_node"] = "normalize"
    await deps.record_step(
        "ingest",
        "ok",
        {"signal_id": sig["id"], "channel": sig.get("channel"), "origin": sig.get("origin")},
        {"text_len": len(sig.get("text") or ""), "client_id": sig.get("client_id")},
        reasoning="Сигнал принят в обработку, статус processing.",
    )
    return state


def regex_hints(text: str) -> dict[str, Any]:
    hints: dict[str, Any] = {}
    if m := RE_AMOUNT.search(text):
        try:
            hints["amount_rub"] = float(m.group(1).replace(" ", "").replace("\u00a0", ""))
        except ValueError:
            pass
    if m := RE_CARD4.search(text):
        hints["masked_card_last4"] = m.group(1)
    if m := RE_PROMO.search(text):
        hints["promo_code"] = m.group(1).upper()
    low = text.lower()
    if "qr" in low or "кьюар" in low or "сбп" in low:
        hints["operation_hint"] = "qr_payment"
    elif "перевод" in low:
        hints["operation_hint"] = "transfer"
    elif "вклад" in low:
        hints["operation_hint"] = "deposit"
    return hints


def _client_lang(raw: str | None, text: str) -> str:
    """ru и en сохраняются; иное значение, включая пустое, берётся из текста сигнала."""
    if raw in ("ru", "en"):
        return raw
    return communication_lang(text)


def _message_for_lang(message: str, lang: str, template_body: str | None) -> str:
    """Если язык текста не совпал с lang сигнала, клиенту уходит тело шаблона на этом lang."""
    text = message.strip()
    if lang in ("ru", "en") and communication_lang(text) != lang and template_body:
        return template_body
    return text


async def _render_client_text(
    deps: Deps,
    message: str,
    lang: str,
    template_code: str,
    channel: str,
    segment: str | None,
    variables: dict[str, Any],
) -> str:
    text = message.strip()
    if communication_lang(text) == lang:
        return text
    _subject, body = await wt.render_template(deps.ctx, template_code, channel, segment, variables, lang)
    return _message_for_lang(text, lang, body)


def _fixed_question(kind: str, lang: str) -> str:
    if lang == "en":
        if kind == "identify":
            return (
                "To help you, we need to find your profile. Please send the phone number from the application "
                "or the last 4 digits of the card. The data is handled confidentially."
            )
        if kind == "fraud_data":
            return (
                "Please send a screenshot of the transaction (date, amount, merchant name) and confirm that the card is with you. "
                "We will pass the details to the fraud team. You can block the card in the app if you need to."
            )
        return "Please share the date and the amount of the transaction so we can find it."
    if kind == "identify":
        return (
            "Чтобы помочь, нам нужно вас найти: напишите, пожалуйста, номер телефона, указанный в заявке, "
            "или последние 4 цифры карты. Данные обрабатываются конфиденциально."
        )
    if kind == "fraud_data":
        return (
            "Пришлите, пожалуйста, скриншот операции (дата, сумма, название магазина) и подтвердите, что карта у вас. "
            "Мы сразу передадим данные в антифрод; при необходимости карту можно заблокировать в приложении."
        )
    return "Уточните, пожалуйста, дату операции и сумму, о которой идёт речь, — так мы быстрее найдём её в системе."


def _short_ack(lang: str) -> str:
    if lang == "en":
        return "We have received your request and are already looking into it."
    return "Мы приняли ваше обращение и уже разбираемся."


def _anonymous_ack(lang: str) -> str:
    if lang == "en":
        return "Your request has been received and will be reviewed by the responsible team. We will share the decision in this channel separately."
    return "Ваше обращение принято и будет рассмотрено ответственной командой. О решении сообщим дополнительно в этом канале."


async def normalize(state: AgentState, deps: Deps) -> AgentState:
    sig = state["signal"]
    text = sig.get("text") or ""
    hints = regex_hints(text)
    status = "ok"
    obj: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    try:
        obj, meta = await _llm(
            deps,
            "normalize",
            "agent/normalization",
            {"hints": hints, "channel": sig.get("channel"), "text": text},
            text,
            profile=deps.fast_profile or deps.profile,
            context="normalization",
            fallback_profile=deps.profile
            if deps.fast_profile and deps.profile.provider not in ("mock", "replay")
            else None,
        )
        if meta.get("fallback_mock"):
            status = "fallback"
    except Exception as exc:  # noqa: BLE001
        status = "error"
        state["errors"].append(f"normalize: {exc}")
    # пост-проверки (T-210): согласованность sentiment/negativity, сарказм → negative, подсказки регулярок
    neg = int(obj["negativity"]) if obj.get("negativity") is not None else 50
    sentiment = obj.get("sentiment") or ("positive" if neg <= 33 else "neutral" if neg <= 66 else "negative")
    hidden = clamp_hidden_evidence(text, obj.get("hidden_negativity") or {})
    if (hidden.get("sarcasm") or {}).get("present") or (hidden.get("churn_threat") or {}).get("present"):
        sentiment = "negative"
        neg = max(neg, 67)
    if sentiment == "negative" and neg < 67:
        neg = 67
    if sentiment == "positive" and neg > 33:
        neg = 33
    ents = {
        **{k: v for k, v in hints.items() if k in ("amount_rub", "operation_hint", "promo_code")},
        **{k: v for k, v in (obj.get("entities") or {}).items() if v is not None},
    }
    contacts = {
        **({"masked_card_last4": hints["masked_card_last4"]} if "masked_card_last4" in hints else {}),
        **{k: v for k, v in (obj.get("contacts_hint") or {}).items() if v},
    }
    intents: list[str] = list(dict.fromkeys(obj.get("intents") or []))
    raw_lang = obj.get("language")
    language = _client_lang(raw_lang if isinstance(raw_lang, str) else None, text)
    norm: dict[str, Any] = {
        "language": language,
        "summary_ru": (obj.get("summary_ru") or text[:200]).strip()[:200],
        "negativity": neg,
        "sentiment": sentiment,
        "hidden_negativity": {
            k: hidden.get(k) or {"present": False, "confidence": 0.0}
            for k in ("sarcasm", "passive_aggression", "churn_threat")
        },
        "intents": intents,
        "entities": ents,
        "contacts_hint": contacts,
        "confidence": float(obj["confidence"]) if obj.get("confidence") is not None else 0.5,
    }
    errors = validate(norm, "agent/normalization")
    if errors:
        log.warning("normalization_invalid", errors=errors[:3])
        norm["hidden_negativity"] = {
            k: {"present": False, "confidence": 0.0} for k in ("sarcasm", "passive_aggression", "churn_threat")
        }
        norm["entities"] = {
            k: v for k, v in ents.items() if k in ("amount_rub", "product", "operation_hint", "promo_code")
        }
        norm["contacts_hint"] = {k: v for k, v in contacts.items() if k in ("masked_card_last4", "city", "nickname")}
        intents = [
            i
            for i in intents
            if i in ("churn_threat", "refund_request", "complaint", "question", "public_shaming", "regulator_threat")
        ]
        norm["intents"] = intents
    state["normalization"] = norm
    sig["lang"] = language
    state["llm_source"] = (
        "mock" if meta.get("provider", "mock") == "mock" else ("replay" if meta.get("provider") == "replay" else "live")
    )
    deps.ctx.llm_source = state["llm_source"]
    await deps.ctx.conn.execute(
        "update signals set sentiment = %s, lang = %s, updated_at = now() where id = %s",
        (sentiment, norm["language"], sig["id"]),
    )
    state["current_node"] = "identify_client"
    await deps.record_step(
        "normalize",
        status,
        {"hints": hints, "llm_attempts": meta.get("attempts", []), "fallback_reason": meta.get("error")},
        norm,
        prompt=meta.get("prompt"),
        raw=meta.get("raw"),
        reasoning=f"Тональность {sentiment} ({neg}/100); намерения: {', '.join(intents) or 'нет'}; сущности: {', '.join(f'{k}={v}' for k, v in ents.items()) or 'нет'}."
        + (f" Причина резервирования: {meta['error']}" if meta.get("error") else ""),
        model=meta.get("model"),
        usage=meta.get("usage"),
        latency_ms=int(meta.get("latency_ms") or 0),
    )
    return state


def _contacts_hint_for_match(state: AgentState, sig: dict[str, Any]) -> dict[str, Any]:
    """contacts_hint из нормализации + ник из external_contact и продукт из entities (ТЗ 21.3)."""
    hint = {k: v for k, v in (state["normalization"].get("contacts_hint") or {}).items() if v}
    ext = sig.get("external_contact") or {}
    nick = (ext.get("nick") or hint.get("nickname") or "").strip()
    if nick:
        hint["nickname"] = nick
    product = state["normalization"].get("entities", {}).get("product")
    if product and not hint.get("product"):
        hint["product"] = product
    return hint


async def identify_client(state: AgentState, deps: Deps) -> AgentState:
    sig = state["signal"]
    client = None
    how, conf = "none", 0.0
    match_result: dict[str, Any] | None = None
    crm_line = ""
    if sig.get("client_id"):
        client = await rt.get_client_profile(deps.ctx, int(sig["client_id"]))
        how, conf = "authenticated_channel", 1.0
    else:
        hint = _contacts_hint_for_match(state, sig)
        match_result = await rt.match_client_by_hints(deps.ctx, hint)
        crm_line = log_ru(match_result)
        decision = match_result["decision"]
        if decision == "identified":
            winner = match_result["candidates"][0]
            profile = await rt.get_client_profile(deps.ctx, int(winner["client_id"]))
            if profile:
                client = profile
                how = "mock_crm"
                conf = float(winner["confidence"])
                await deps.ctx.conn.execute(
                    "update signals set client_id = %s, updated_at = now() where id = %s and client_id is null",
                    (client["client_id"], sig["id"]),
                )
                sig["client_id"] = client["client_id"]
            else:
                how = "not_found"
                conf = 0.0
        else:
            how = decision
            conf = 0.0
    state["client"] = client
    state["context"]["identification"] = {"method": how, "confidence": conf}
    if match_result is not None:
        state["context"]["client_match"] = match_result
    state["current_node"] = "gather_context"
    if crm_line:
        reasoning = (
            f"{crm_line} Клиент #{client['client_id']} ({client['segment']}, {client['psychotype']}) идентифицирован."
            if client
            else f"{crm_line} Клиент не идентифицирован — анонимное/публичное обращение."
        )
    elif client:
        reasoning = (
            f"Клиент #{client['client_id']} ({client['segment']}, {client['psychotype']}) идентифицирован: {how}."
        )
    else:
        reasoning = "Клиент не идентифицирован — анонимное/публичное обращение."
    await deps.record_step(
        "identify_client",
        "ok",
        {"client_id": sig.get("client_id"), "external_contact": sig.get("external_contact")},
        {
            "client": {k: client.get(k) for k in ("client_id", "segment", "psychotype", "region_code", "city", "state")}
            if client
            else None,
            "method": how,
            "confidence": conf,
            "match_decision": match_result["decision"] if match_result else None,
        },
        reasoning=reasoning,
    )
    return state


async def gather_context(state: AgentState, deps: Deps) -> AgentState:
    sig, client = state["signal"], state.get("client")
    ctx: dict[str, Any] = {}
    systems: list[str] = []
    if client:
        ctx["products"] = await rt.get_client_products(deps.ctx, client["client_id"])
        ctx["operations"] = await rt.get_recent_operations(deps.ctx, client["client_id"])
        for p in ctx["products"]:
            systems += PRODUCT_SYSTEMS.get(p["product"], [])
        for op in ctx["operations"]:
            if op["status"] == "failed" or op.get("error_code"):
                systems += op["system_path"]
    else:
        ctx["products"], ctx["operations"] = [], []
    hint_product = state["normalization"].get("entities", {}).get("product")
    if sig.get("channel_subtype") == "ui_pers_demo":
        form_product = (sig.get("meta") or {}).get("product_code")
        ctx["form_context"] = {
            "product_code": form_product,
            "visitor_name": (sig.get("meta") or {}).get("visitor_name") or None,
            "region_code": (sig.get("geo") or {}).get("region_code"),
            "city_id": (sig.get("geo") or {}).get("city_id"),
        }
        hint_product = hint_product or form_product
    if hint_product:
        systems += PRODUCT_SYSTEMS.get(hint_product, [])
    systems = list(dict.fromkeys(systems)) or ["processing", "mobile_app"]
    ctx["system_logs"] = await rt.get_system_logs(deps.ctx, systems)
    failed = [op for op in ctx["operations"] if op["status"] == "failed" or op.get("error_code")]
    active = ctx["system_logs"]["active_faults"]
    # error_code/система — только по фактам клиента (его неуспешные операции); активные сбои без операции — лишь подсказка
    error_code = failed[0]["error_code"] if failed else None
    system = failed[0]["system_path"][0] if failed and failed[0]["system_path"] else None
    if not error_code and sig.get("source_fault_id"):
        src = next((f for f in active if f["fault_id"] == sig["source_fault_id"]), None)
        if src:
            error_code, system = src["error_code"], src["system"]
    nearby = [f for f in active if f["error_code"] != error_code]
    region = (client or {}).get("region_code") or (sig.get("geo") or {}).get("region_code")
    ctx["related_incidents"] = await rt.find_related_incidents(
        deps.ctx,
        (client or {}).get("client_id"),
        error_code,
        system,
        hint_product or (ctx["products"][0]["product"] if ctx["products"] else None),
        region,
        hours=int(pol.merged(deps.policies)["dedup_window_sim_hours"]),
    )
    sim = await rt.search_similar_signals(
        deps.ctx, sig.get("text") or "", (client or {}).get("client_id"), exclude_signal_id=sig["id"]
    )
    ctx["similar_signals"], ctx["client_history"] = sim["similar"], sim["client_history"]
    ctx["hints"] = {
        "error_code": error_code,
        "system": system,
        "failed_operation_id": failed[0]["operation_id"] if failed else None,
        "fault_id": (failed[0].get("fault_id") if failed else None) or sig.get("source_fault_id"),
        "nearby_faults": [f["error_code"] for f in nearby][:3],
    }
    ctx["source"] = {"operation_id": sig.get("source_operation_id"), "fault_id": sig.get("source_fault_id")}
    from app.agent.operator_feedback import feedback_context

    feedback = await feedback_context(deps.ctx.conn, sig["id"], deps.ctx.run_id)
    if feedback:
        ctx["operator_feedback"] = feedback
    if sig.get("channel_subtype") == "ui_pers_demo":
        rows = await deps.ctx.fetchall(
            "select s.text,(select jsonb_agg(n.body order by n.id) from notifications n where n.signal_id=s.id and n.recipient_type='client') from personal_chat_messages m join signals s on s.id=m.signal_id where m.session_id=(select session_id from personal_chat_messages where signal_id=%s) and m.signal_id<%s order by m.id desc limit 20",
            (sig["id"], sig["id"]),
        )
        ctx["conversation"] = [{"user": r[0], "agent": r[1] or []} for r in reversed(rows)]
    state["context"].update(ctx)
    state["current_node"] = "check_rules"
    await deps.record_step(
        "gather_context",
        "ok",
        {"systems": systems},
        {
            "products": len(ctx["products"]),
            "operations": len(ctx["operations"]),
            "failed_ops": len(failed),
            "active_faults": len(ctx["system_logs"]["active_faults"]),
            "related_incidents": len(ctx["related_incidents"]),
            "similar_signals": len(ctx["similar_signals"]),
            "client_history": ctx["client_history"],
            "hints": ctx["hints"],
        },
        reasoning=f"Собрано: {len(ctx['operations'])} операций (из них с ошибкой {len(failed)}), активных сбоев {len(ctx['system_logs']['active_faults'])}, связанных инцидентов {len(ctx['related_incidents'])}, похожих сигналов {len(ctx['similar_signals'])}.",
    )
    return state


async def check_rules_node(state: AgentState, deps: Deps) -> AgentState:
    ops = state["context"].get("operations") or []
    matched = await check_rules(
        deps.ctx.conn,
        run_id=deps.ctx.run_id,
        signal_id=state["signal"]["id"],
        agent_run_id=deps.ctx.agent_run_id,
        operations=ops,
    )
    state["context"]["rules_matched"] = matched
    fee_rule = next((r for r in matched if r.get("action") == "refund_fee"), None)
    mass_pending = 0
    if fee_rule and fee_rule.get("error_code"):
        aff = await abs_tools.find_affected_clients(deps.ctx, str(fee_rule["error_code"]), 72)
        mass_pending = int(aff.get("pending_count") or 0)
    ident = state["context"].get("identification") or {}
    abs_state = await _abs_refund_state(
        deps, (state.get("client") or {}).get("client_id"), (fee_rule or {}).get("operation_ids") or []
    )
    fp_ok, fp_why = pol.fast_path_allowed(
        fee_rule=fee_rule,
        identification=ident,
        normalization=state.get("normalization") or {},
        client=state.get("client"),
        abs_state=abs_state,
        mass_pending=mass_pending,
        policies=deps.policies,
    )
    if state["signal"].get("red_words"):
        fp_ok, fp_why = False, "красные слова требуют полного прохода политик"
    state["context"]["fast_path"] = {"allowed": fp_ok, "reason": fp_why}
    state["current_node"] = "instant_decide" if fp_ok else "classify"
    await deps.record_step(
        "check_rules",
        "ok",
        {"operations": len(ops)},
        {"matched": matched, "fast_path": state["context"]["fast_path"]},
        reasoning=(
            f"Сработали правила: {', '.join(m['rule_code'] for m in matched)}. "
            + (f"Быстрый путь: {fp_why}." if fp_ok else f"Обычный граф: {fp_why}.")
            if matched
            else "Бизнес-правила не сработали."
        ),
    )
    return state


def _ensure_instant_decision(state: AgentState, obj: dict[str, Any]) -> dict[str, Any]:
    """Дополняет instant_decision детерминированным планом по fee_rule (mock часто не заполняет actions)."""
    fee_rule = next((r for r in (state["context"].get("rules_matched") or []) if r.get("action") == "refund_fee"), None)
    out = dict(obj)
    if fee_rule:
        codes = out.get("rule_codes") or [fee_rule["rule_code"]]
        out["rule_codes"] = list(dict.fromkeys([*codes, fee_rule["rule_code"]]))
        op_id = next((o for o in fee_rule.get("operation_ids") or [] if o is not None), None)
        amount = float(fee_rule.get("amount_rub") or 0)
        actions = list(out.get("actions") or [])
        if not actions and op_id is not None:
            actions = [
                {
                    "tool": "refund_fee",
                    "args": {
                        "operation_id": int(op_id),
                        "amount_rub": amount,
                        "rule_id": fee_rule["rule_code"],
                    },
                },
                {"tool": "create_incident", "args": {"incident_type": "fee_refund", "status": "resolved"}},
                {"tool": "publish_public_reply", "args": {"post_id": state["signal"].get("external_post_id")}},
                {"tool": "notify_client", "args": {"channel": "chat"}},
            ]
        out["actions"] = actions
    cls = dict(out.get("classification") or {})
    cls.setdefault("signal_type", "tariff_terms")
    cls.setdefault("error_code", (fee_rule or {}).get("error_code"))
    cls.setdefault("product", "debit_card")
    cls.setdefault("system", "processing")
    flags = list(dict.fromkeys([*(cls.get("flags") or []), "rule_confirmed", "public"]))
    if int(state["normalization"].get("negativity") or 0) >= 67:
        flags.append("churn_intent")
    cls["flags"] = flags
    cls.setdefault("confidence", float(out.get("confidence") or 0.9))
    out["classification"] = cls
    name = mask_name((state.get("client") or {}).get("name"))
    amount = float(
        (fee_rule or {}).get("amount_rub") or state["normalization"].get("entities", {}).get("amount_rub") or 0
    )
    out.setdefault(
        "public_reply_ru",
        f"{name}, приносим извинения за ошибочную комиссию"
        + (f" {amount:.0f} ₽" if amount else "")
        + ". Средства уже возвращены на карту. Напишите нам в чат приложения — проверим, что всё в порядке.",
    )
    out.setdefault(
        "client_notice_ru",
        "Мы вернули комиссию"
        + (f" {amount:.0f} ₽" if amount else "")
        + " за оплату по QR. Приносим извинения за неудобства.",
    )
    out.setdefault("confidence", cls["confidence"])
    out.setdefault(
        "rationale_ru", "Правило подтвердило ошибочную комиссию; сумма в лимите автономии, клиент идентифицирован."
    )
    return out


async def instant_decide(state: AgentState, deps: Deps) -> AgentState:
    """Один вызов основной модели со схемой instant_decision (ТЗ 21.4)."""
    sig = state["signal"]
    text = sig.get("text") or ""
    status = "ok"
    obj: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    try:
        obj, meta = await _llm(
            deps,
            "instant_decision",
            "agent/instant_decision",
            {
                "rules_matched": state["context"].get("rules_matched") or [],
                "identification": state["context"].get("identification") or {},
                "context": _context_for_prompt(state),
                "channel": sig.get("channel"),
                "text": text,
            },
            text,
            context="fast_path",
        )
        if meta.get("fallback_mock"):
            status = "fallback"
    except Exception as exc:  # noqa: BLE001
        status = "error"
        state["errors"].append(f"instant_decide: {exc}")
        obj = {}
    inst = _ensure_instant_decision(state, obj)
    cls, notes = _postcheck_classification(inst.get("classification") or {}, state, deps)
    if notes:
        cls["summary_ru"] = (cls.get("summary_ru") or "") + ("; " + "; ".join(notes) if cls.get("summary_ru") else "")
    inst["classification"] = cls
    state["instant"] = inst
    state["classification"] = cls
    fee_rule = next((r for r in (state["context"].get("rules_matched") or []) if r.get("action") == "refund_fee"), None)
    team = (fee_rule or {}).get("team") or "team_debit"
    state["decision"] = {
        "fast_path": True,
        "incident_action": "create",
        "router_action": "route",
        "rule_codes": inst.get("rule_codes") or [],
        "confidence": float(inst.get("confidence") or cls.get("confidence") or 0.9),
        "route": {"team": team, "co_teams": []},
        "incident_type": "fee_refund",
        "complexity": "instant",
    }
    if meta.get("provider"):
        state["llm_source"] = (
            "mock"
            if meta.get("fallback_mock") or meta["provider"] == "mock"
            else "replay"
            if meta["provider"] == "replay"
            else "live"
        )
    deps.ctx.llm_source = state["llm_source"]
    await deps.ctx.conn.execute(
        "update signals set classification = %s::jsonb, decision = %s::jsonb, updated_at = now() where id = %s",
        (dumps(cls), dumps(state["decision"]), sig["id"]),
    )
    state["current_node"] = "act_instant"
    await deps.record_step(
        "instant_decide",
        status,
        {"fast_path": True},
        {
            "instant": {k: inst.get(k) for k in ("rule_codes", "confidence", "actions")},
            "classification_type": cls.get("signal_type"),
            "churn_risk": cls.get("churn_risk"),
            "score_pipeline": SCORE_PIPELINE,
            "churn_predicted_sim": deps.ctx.sim_time.isoformat(),
        },
        prompt=meta.get("prompt"),
        raw=meta.get("raw"),
        reasoning=(inst.get("rationale_ru") or "Быстрое решение по подтверждённому правилу.")[:800],
        model=meta.get("model"),
        usage=meta.get("usage"),
        latency_ms=int(meta.get("latency_ms") or 0),
    )
    return state


async def act_instant(state: AgentState, deps: Deps) -> AgentState:
    """Исполнение быстрого пути: деньги → инцидент → публичный ответ → личное уведомление (ТЗ 21.4)."""
    inst, sig, client = state["instant"], state["signal"], state.get("client")
    c = state["classification"]
    fee_rule = next((r for r in (state["context"].get("rules_matched") or []) if r.get("action") == "refund_fee"), None)
    actions = state["actions"]
    done = {a["action"] for a in actions}
    incident_id: int | None = next((a["incident_id"] for a in actions if a.get("incident_id")), None)

    def mark(action: str, **kw: Any) -> None:
        actions.append({"action": action, **kw})

    refund_total = 0.0
    if fee_rule and "refund" not in done:
        for op_id in fee_rule.get("operation_ids") or []:
            if op_id is None:
                continue
            try:
                rf = await abs_tools.refund_fee(
                    deps.ctx,
                    int(op_id),
                    float(fee_rule.get("amount_rub") or 0) or None,
                    fee_rule.get("rule_code"),
                    (inst.get("rationale_ru") or "ошибочная комиссия")[:160],
                )
            except Exception as exc:
                mark("refund_failed", operation_id=op_id, error=str(exc)[:200])
                continue
            if not rf.get("duplicate"):
                refund_total += float(rf.get("amount_rub") or 0)
            mark(
                "refund",
                operation_id=op_id,
                entry_id=rf.get("entry_id"),
                amount_rub=rf.get("amount_rub"),
                duplicate=rf.get("duplicate"),
            )

    if "incident" not in done and fee_rule:
        crit = slam.effective_criticality(
            c.get("criticality", "medium"),
            c.get("flags") or [],
            (client or {}).get("segment"),
            c.get("signal_type", "tariff_terms"),
            1,
        )
        prio = slam.priority(crit, int(c.get("churn_risk") or 0), (client or {}).get("segment"), c.get("flags") or [])
        sla_full = slam.sla_for("instant", crit, deps.ctx.sim_time, deps.sla_matrix)
        spec = {
            **c,
            "incident_type": "fee_refund",
            "title_ru": _title(c.get("summary_ru") or "Ошибочная комиссия за QR"),
            "complexity": "instant",
            "criticality": crit,
            "priority": prio,
            "team": (fee_rule.get("team") or "team_debit"),
            "co_teams": [],
            "sla": sla_full,
            "mass_impact": 1,
            "region_code": (client or {}).get("region_code") or (sig.get("geo") or {}).get("region_code"),
            "problem_summary": c.get("problem_summary"),
        }
        inc = await wt.create_incident(deps.ctx, sig["id"], (client or {}).get("client_id"), spec)
        incident_id = int(inc["incident_id"])
        mark("incident", incident_id=incident_id, public_id=inc.get("public_id"))
        if refund_total:
            await wt.update_incident(
                deps.ctx,
                incident_id,
                "resolved",
                "Комиссия возвращена (быстрый путь)",
                {"resolution_summary": f"Комиссия {refund_total:.2f} ₽ возвращена на счёт клиента"},
            )

    post_id = sig.get("external_post_id")
    pub_text = str(inst.get("public_reply_ru") or _public_fallback(client))
    if post_id and "feed_reply" not in done:
        try:
            fr = await abs_tools.publish_public_reply(
                deps.ctx, int(post_id), pub_text, incident_id, True, bool(inst.get("escalate_to_dm"))
            )
            mark("feed_reply", post_id=post_id, reply_id=fr.get("reply_id"), latency_ms=fr.get("latency_ms"))
        except Exception as exc:
            mark("feed_reply_failed", post_id=post_id, error=str(exc)[:160])

    if client and "notify_client" not in done:
        notice = str(inst.get("client_notice_ru") or pub_text)
        n = await wt.notify_client(
            deps.ctx,
            client["client_id"],
            sig["id"],
            incident_id,
            "chat",
            "fee_refund_done",
            {"name": mask_name(client.get("name")), "resolution": notice},
            text_override=notice,
            segment=client.get("segment"),
            consents=client.get("consents"),
        )
        mark("notify_client", notification_id=n.get("notification_id"))

    await deps.ctx.conn.execute(
        "update signals set status = 'answered', updated_at = now() where id = %s", (sig["id"],)
    )
    if incident_id:
        await deps.ctx.conn.execute(
            "update agent_runs set incident_id = %s where id = %s", (incident_id, deps.ctx.agent_run_id)
        )
    state["actions"] = actions
    state["current_node"] = "verify"
    await deps.record_step(
        "act_instant",
        "ok",
        {"rule_codes": inst.get("rule_codes")},
        {"actions": actions, "refund_total_rub": refund_total},
        reasoning="Быстрый путь: " + ", ".join(a["action"] for a in actions) + ".",
    )
    return state


async def verify(state: AgentState, deps: Deps) -> AgentState:
    """Проверка устранения: verify_service_delivered; быстрый путь — refund и баланс (ТЗ 21.4)."""
    client = state.get("client") or {}
    sig = state["signal"]
    incident_id = next((a["incident_id"] for a in state.get("actions") or [] if a.get("incident_id")), None)
    if incident_id is None:
        row = await deps.ctx.fetchone("select incident_id from agent_runs where id = %s", (deps.ctx.agent_run_id,))
        incident_id = int(row[0]) if row and row[0] else None
    evidence: list[str] = []
    ok = False
    reopened = False
    if client.get("client_id"):
        refunded = any(a.get("action") == "refund" and not a.get("duplicate") for a in state.get("actions") or [])
        if refunded:
            bal = await abs_tools.get_account_balance(deps.ctx, int(client["client_id"]))
            ok = bal.get("balance") is not None
            if ok:
                evidence.append(f"баланс {bal.get('balance')} ₽ после возврата")
        elif incident_id:
            check = await rt.verify_service_delivered(deps.ctx, int(incident_id))
            ok = bool(check.get("delivered"))
            evidence.extend(list(check.get("evidence") or []))
    elif incident_id:
        check = await rt.verify_service_delivered(deps.ctx, int(incident_id))
        ok = bool(check.get("delivered"))
        evidence.extend(list(check.get("evidence") or []))
    if ok and incident_id:
        state["verified"] = True
        inc_row = await deps.ctx.fetchone("select status from incidents where id = %s", (incident_id,))
        inc_status = str(inc_row[0]) if inc_row else ""
        if inc_status == "fix_deployed":
            await wt.update_incident(deps.ctx, int(incident_id), "verifying", "проверка устранения агентом")
        if inc_status in ("fix_deployed", "verifying", "in_progress", "routed"):
            await wt.update_incident(deps.ctx, int(incident_id), "resolved", "услуга подтверждена")
        state["current_node"] = "gift"
        step_status = "ok"
        reasoning = "; ".join(evidence) if evidence else "услуга подтверждена"
    elif incident_id:
        state["verified"] = False
        reopened = True
        reopen_count = int(state.get("reopen_count") or 0) + 1
        state["reopen_count"] = reopen_count
        cap = int(pol.merged(deps.policies).get("verify_reopen_cap") or 2)
        await wt.update_incident(deps.ctx, int(incident_id), "in_progress", "reopen: услуга не подтверждена")
        team = (state.get("decision") or {}).get("route", {}).get("team") or "team_cx"
        await wt.notify_team(
            deps.ctx,
            str(team),
            int(incident_id),
            int(sig["id"]),
            "Услуга не подтверждена после проверки — требуется доработка команды",
            {"incident_id": incident_id},
        )
        wake_h = float((state.get("decision") or {}).get("followup", {}).get("wake_in_sim_hours") or 4.0)
        wake_at = deps.ctx.sim_time + dt.timedelta(hours=wake_h)
        dup_f = await deps.ctx.fetchone(
            "select id from followups where agent_run_id = %s and status = 'scheduled'",
            (deps.ctx.agent_run_id,),
        )
        if dup_f:
            await deps.ctx.conn.execute(
                "update followups set reason = 'verify_fix', wake_sim = %s, payload = %s::jsonb where id = %s",
                (wake_at, dumps({"incident_id": incident_id}), int(dup_f[0])),
            )
        else:
            await wt.schedule_followup(
                deps.ctx, int(sig["id"]), int(incident_id), wake_h, "verify_fix", {"incident_id": incident_id}
            )
        if reopen_count >= cap:
            await wt.escalate_to_manager(
                deps.ctx,
                int(sig["id"]),
                int(incident_id),
                "Повторная неудачная проверка устранения",
                "high",
                "cx_lead",
            )
        state["current_node"] = "followup_monitor"
        step_status = "fallback"
        reasoning = "услуга не подтверждена: " + ("; ".join(evidence) if evidence else "нет доказательств")
    else:
        state["verified"] = ok
        state["current_node"] = "gift"
        step_status = "ok" if ok else "fallback"
        reasoning = "; ".join(evidence) if evidence else "инцидент не найден"
    await deps.record_step(
        "verify",
        step_status,
        {"client_id": client.get("client_id"), "incident_id": incident_id},
        {"ok": ok, "evidence": evidence, "reopened": reopened},
        reasoning=reasoning,
    )
    return state


async def gift(state: AgentState, deps: Deps) -> AgentState:
    """Подарок: задача (идемпотентно), автовыдача только при verified и resolved|closed."""
    client = state.get("client") or {}
    c = state.get("classification") or {}
    d = state.get("decision") or {}
    incident_id = next((a["incident_id"] for a in state.get("actions") or [] if a.get("incident_id")), None)
    created = None
    auto_issued = 0
    gift_spec = d.get("gift") if d.get("gift") else None
    verified = bool(state.get("verified"))
    if incident_id and client.get("client_id"):
        segment = client.get("segment")
        flags = c.get("flags") or []
        crit = slam.effective_criticality(
            c.get("criticality", "medium"),
            flags,
            segment,
            c.get("signal_type", "tech_fault"),
            1,
        )
        if not gift_spec:
            gift_spec = giftmod.choose(segment, crit, flags, client.get("psychotype"))
        if gift_spec:
            gift_body = {k: gift_spec[k] for k in ("gift_code", "points", "privilege_code") if k in gift_spec}
            t = await wt.create_task(
                deps.ctx,
                "gift",
                incident_id,
                client["client_id"],
                {"gift": gift_body, "when": gift_spec.get("when") or "after_resolved"},
                requires_hitl=bool(gift_spec.get("requires_hitl")),
            )
            created = t.get("task_id")
            inc_row = await deps.ctx.fetchone("select status from incidents where id = %s", (incident_id,))
            inc_status = str(inc_row[0]) if inc_row else ""
            if verified and inc_status in ("resolved", "closed") and not gift_spec.get("requires_hitl"):
                auto_issued = await giftmod.issue_automatic(deps.ctx, incident_id)
    state["current_node"] = "close"
    await deps.record_step(
        "gift",
        "ok",
        {"gift": gift_spec, "verified": verified},
        {"task_id": created, "auto_issued": auto_issued},
        reasoning="Подарок начислен." if created else "Подарок не требуется.",
    )
    return state


async def followup_monitor(state: AgentState, deps: Deps) -> AgentState:
    """Парковка отложенного обращения по scheduled followup (чекпоинт = вход шага)."""
    sig = state["signal"]
    row = await deps.ctx.fetchone(
        "select id, reason, wake_sim from followups where agent_run_id = %s and status = 'scheduled' "
        "order by id desc limit 1",
        (deps.ctx.agent_run_id,),
    )
    if not row:
        state["current_node"] = "close"
        await deps.record_step(
            "followup_monitor",
            "ok",
            dict(state),
            {"parked": False},
            reasoning="Нет запланированного follow-up — переход к закрытию.",
        )
        return state
    fid, reason, wake_sim = int(row[0]), str(row[1]), row[2]
    if reason in ("awaiting_team", "promo_end", "verify_fix", "report_due"):
        await deps.ctx.conn.execute(
            "update signals set status = 'deferred', updated_at = now() where id = %s", (sig["id"],)
        )
        await deps.ctx.notify(
            "signals",
            "status",
            {"signal_id": sig["id"], "status": "deferred", "reason": reason, "wake_sim": wake_sim},
        )
    state["outcome"] = "deferred"
    state["current_node"] = "followup_monitor"
    await deps.record_step(
        "followup_monitor",
        "ok",
        dict(state),
        {
            "reason": reason,
            "wake_sim": wake_sim.isoformat() if wake_sim else None,
            "followup_id": fid,
        },
        reasoning=f"Отложено до {wake_sim}: {reason}.",
    )
    return state


# слова в тексте, при которых сбой из контекста операций считаем причиной обращения (иначе клиент пишет о другом)
ERROR_CODE_WORDS: dict[str, tuple[str, ...]] = {
    "NOTIF-DELAY": ("смс", "sms", "push", "пуш", "код", "уведомлен", "оповещ"),
    "PROC-QR-FEE-CHARGED": ("qr", "кьюар", "куар", "сбп", "комисси", "по коду"),
    "PROC-DOUBLE-DEBIT": ("двойн", "дважды", "два раза", "повторн", "списал", "списан", "комисси"),
    "DEP-TIMEOUT-503": ("вклад", "депозит", "накопител", "ставк"),
    "PROMO-RATE-MISMATCH": ("ставк", "промо", "акци", "процент"),
    "APP-LOGIN-FAIL": ("войти", "вход", "логин", "пароль", "авториз", "приложен"),
    "APP-CRASH-PAY": ("приложен", "вылета", "падает", "закрыва", "завис", "оплат"),
    "WEB-SESSION-DROP": ("сайт", "браузер", "веб", "интернет-банк", "сесси", "выкидыва", "разлогин"),
    "AF-FALSE-BLOCK": ("заблок", "блокир", "блок"),
    "LEND-PAYMENT-NOT-POSTED": ("платёж", "платеж", "кредит", "зачисл", "задолж", "долг"),
    "CC-GRACE-MISCALC": ("льготн", "грейс", "grace", "процент", "кредитн"),
    "DEBIT-CASHBACK-MISS": ("кешбэк", "кэшбэк", "cashback", "бонус"),
    "PROMO-CODE-REJECTED": ("промокод", "код акции", "промо"),
}


def _text_matches_error(text: str, error_code: str) -> bool:
    words = ERROR_CODE_WORDS.get(error_code)
    if not words:
        return True  # неизвестный код — доверяем контексту
    t = text.lower()
    return any(w in t for w in words)


def _postcheck_classification(obj: dict[str, Any], state: AgentState, deps: Deps) -> tuple[dict[str, Any], list[str]]:
    """Пост-проверки классификации (T-059 п. 3, T-212): согласованность, факты из контекста важнее мнения модели."""
    notes: list[str] = []
    ctx, norm, client = state["context"], state["normalization"], state.get("client")
    hints = ctx.get("hints") or {}
    rules = ctx.get("rules_matched") or []
    c = dict(obj)
    stype = c.get("signal_type") or "info_request"
    if any(r["action"] == "refund_fee" and r.get("error_code") == "PROC-QR-FEE-CHARGED" for r in rules):
        if stype not in ("legal_regulatory", "fraud_suspicion"):
            if stype != "tariff_terms":
                notes.append(f"правило RULE-QR-FEE подтвердило ошибочную комиссию → tariff_terms (модель: {stype})")
            stype, c["product"], c["system"], c["error_code"] = (
                "tariff_terms",
                "debit_card",
                "processing",
                "PROC-QR-FEE-CHARGED",
            )
    elif (
        hints.get("error_code")
        and (
            stype in ("tech_fault", "client_error")
            or (stype in ("tariff_terms", "info_request", "service_quality") and int(norm.get("negativity") or 0) >= 50)
        )
        and _text_matches_error(state["signal"].get("text") or "", hints["error_code"])
    ):
        if stype != "tech_fault":
            notes.append(f"активный сбой {hints['error_code']} на пути операции клиента → tech_fault (модель: {stype})")
        stype, c["system"], c["error_code"] = "tech_fault", hints.get("system") or c.get("system"), hints["error_code"]
    c["signal_type"] = stype
    # продукт ↔ система
    product = (
        c.get("product")
        or norm.get("entities", {}).get("product")
        or (ctx["products"][0]["product"] if ctx.get("products") else None)
    )
    system = c.get("system")
    if product and system and system not in PRODUCT_SYSTEMS.get(product, [system]):
        if stype == "service_quality" and system in ("contact_center", "mobile_app", "web_bank"):
            pass
        else:
            notes.append(f"система {system} не согласуется с продуктом {product} → {PRODUCT_SYSTEMS[product][0]}")
            system = PRODUCT_SYSTEMS[product][0]
    if stype == "service_quality" and not system:
        system = "contact_center" if state["signal"].get("channel") in ("call", "chat") else None
    c["product"], c["system"] = product, system
    # флаги
    flags = list(
        dict.fromkeys(f for f in [*(c.get("flags") or []), *(state["signal"].get("flags") or [])] if isinstance(f, str))
    )
    c["red_words"] = list(state["signal"].get("red_words") or [])
    hist = ctx.get("client_history") or {}
    if stype in (hist.get("last_types") or []) and "repeat" not in flags:
        flags.append("repeat")
        notes.append("повтор: клиент уже обращался с тем же типом за 14 дней")
    hidden = norm.get("hidden_negativity") or {}
    if (hidden.get("churn_threat") or {}).get("present") or "churn_threat" in (norm.get("intents") or []):
        if "churn_intent" not in flags:
            flags.append("churn_intent")
    if (hidden.get("sarcasm") or {}).get("present") and "sarcasm" not in flags:
        flags.append("sarcasm")
    if (hidden.get("passive_aggression") or {}).get("present") and "passive_aggression" not in flags:
        flags.append("passive_aggression")
    if "regulator_threat" in (norm.get("intents") or []) and "regulator_threat" not in flags:
        flags.append("regulator_threat")
    if "public_shaming" in (norm.get("intents") or []) and "public" not in flags:
        flags.append("public")  # флаг по схеме common.flag; намерение остаётся public_shaming
    mass = max(
        [i.get("mass_impact") or 0 for i in ctx.get("related_incidents") or [] if i.get("same_error")]
        + [
            f.get("affected_clients") or 0
            for f in (ctx.get("system_logs") or {}).get("active_faults") or []
            if hints.get("error_code")
            and (f.get("error_code") == hints.get("error_code") or f.get("fault_id") == hints.get("fault_id"))
        ]
        + [0]
    )
    if mass >= 3 and "mass_impact" not in flags:
        flags.append("mass_impact")
        notes.append(f"массовость: затронуто {mass} клиентов")
    c["flags"] = list(dict.fromkeys(flags))
    # тональность ↔ нормализация
    c["sentiment"] = norm.get("sentiment") or c.get("sentiment") or "neutral"
    if c["sentiment"] == "negative" and c.get("tone") in (None, "neutral", "positive"):
        c["tone"] = "sarcastic" if "sarcasm" in flags else "irritated"
    if c["sentiment"] == "positive" and c.get("tone") in ("angry", "irritated", "sarcastic"):
        c["tone"] = "positive"
    c["negativity"] = norm.get("negativity")
    c["criticality"] = (
        c.get("criticality")
        if c.get("criticality") in ("low", "medium", "high")
        else TYPE_BASE_CRIT.get(stype, "medium")
    )
    if (c.get("red_words") or stype in ("legal_regulatory", "fraud_suspicion")) and c["criticality"] != "high":
        c["criticality"] = "high"
    c["cause_hypothesis"] = (
        c.get("cause_hypothesis") if c.get("cause_hypothesis") else (stype if stype in TYPE_BASE_CRIT else "unknown")
    )
    churn = int(c.get("churn_risk") or 0)
    base = int((client or {}).get("churn_risk") or 20)
    if "churn_intent" in flags:
        churn = max(churn, 75)
    if "repeat" in flags:
        churn = max(churn, base + 20)
    c["churn_risk"] = max(0, min(100, churn or base))
    c["confidence"] = max(0.0, min(1.0, float(c.get("confidence") or 0.5)))
    if notes and c["confidence"] > 0.85 and any("модель:" in n for n in notes):
        c["confidence"] = 0.85  # модель ошиблась в типе — уверенность не может быть максимальной
    text = state["signal"].get("text") or ""
    if not c.get("summary_ru") or c["summary_ru"].strip() == text.strip():
        c["summary_ru"] = norm.get("summary_ru") or text[:200]
    # служебный хвост «; тональность …» (mock) — тональность уже есть в полях sentiment/negativity
    c["summary_ru"] = re.sub(r"[;,]?\s*тональность.*$", "", c["summary_ru"]).strip().rstrip(".").strip() or text[:200]
    if not c.get("rationale_ru"):
        c["rationale_ru"] = "Тип определён по правилам и контексту операций; подробности в шагах графа."
    # problem_summary (T-212)
    ps = dict(c.get("problem_summary") or {})
    problem = (ps.get("problem") or c["summary_ru"] or "").strip()
    sents = _sentences(problem)
    if len(sents) > 2:
        problem = " ".join(sents[:2])
        notes.append("problem_summary: обрезано до 2 предложений")
    problem = wt.PII_RE.sub("****", problem)[:300]
    if len(problem) < 10:
        problem = (c["summary_ru"] + ".")[:300]
    severity = ps.get("severity") if ps.get("severity") in ("low", "medium", "high", "critical") else c["criticality"]
    critical_ok = c["criticality"] == "high" and (
        "regulator_threat" in flags
        or stype == "legal_regulatory"
        or "mass_impact" in flags
        or (
            stype == "fraud_suspicion"
            and float(norm.get("entities", {}).get("amount_rub") or 0) > pol.merged(deps.policies)["fraud_amount_rub"]
        )
        or ("churn_intent" in flags and (client or {}).get("segment") in ("vip", "ultra_vip"))
    )
    if severity == "critical" and not critical_ok:
        severity = "high"
        notes.append("problem_summary.severity: critical без оснований → high")
    if severity != "critical" and critical_ok:
        severity = "critical"
    team = ps.get("suggested_team") if ps.get("suggested_team") in deps.teams else None
    if team is None:
        team = route_team(c, state, deps)[0]
    c["problem_summary"] = {"problem": problem, "severity": severity, "suggested_team": team}
    c.pop("error_code_hint", None)
    return c, notes


def _fewshot_for_decide(deps: Deps, classification: dict[str, Any]) -> list[dict[str, Any]] | str:
    base = deps.fewshot[:5]
    if not base:
        return "нет"
    stype = classification.get("signal_type")
    prod = classification.get("product")
    sys = classification.get("system")
    filtered: list[dict[str, Any]] = []
    for ex in base:
        if ex.get("signal_type") != stype:
            continue
        if prod and ex.get("product") and ex.get("product") != prod:
            continue
        if sys and ex.get("system") and ex.get("system") != sys:
            continue
        filtered.append(ex)
    return filtered if filtered else base


async def _hitl_incident_id(deps: Deps, decision: dict[str, Any]) -> int | None:
    if decision.get("incident_action") != "link_existing" or not decision.get("link_incident_id"):
        return None
    iid = int(decision["link_incident_id"])
    row = await deps.ctx.fetchone("select status from incidents where id = %s", (iid,))
    if not row:
        return None
    if "awaiting_human" in wt.STATUS_TRANSITIONS.get(str(row[0]), set()):
        return iid
    return None


def route_team(c: dict[str, Any], state: AgentState, deps: Deps) -> tuple[str, list[str], int | None]:
    """Маршрутизация по routing_rules (первое совпадение по priority); fallback team_cx."""
    facts = {
        "signal_type": c.get("signal_type"),
        "error_code": c.get("error_code"),
        "system": c.get("system"),
        "product": c.get("product"),
        "channel": state["signal"].get("channel"),
        "incident_type": c.get("incident_type"),
    }
    if "churn_intent" in (c.get("flags") or []) and c.get("signal_type") in ("info_request", "suggestion"):
        facts["signal_type"] = "churn"
    for rule_id, match, teams in deps.routing_rules:
        if all(facts.get(k) == v for k, v in match.items()):
            teams = [t for t in teams if t in deps.teams] or ["team_cx"]
            return teams[0], teams[1:], rule_id
    return "team_cx", [], None


async def classify(state: AgentState, deps: Deps) -> AgentState:
    sig = state["signal"]
    text = sig.get("text") or ""
    status = "ok"
    obj: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    try:
        obj, meta = await _llm(
            deps,
            "classify",
            "agent/classification",
            {
                "teams": ", ".join(deps.teams),
                "fewshot": deps.fewshot[:5] or "нет",
                "context": _context_for_prompt(state),
                "normalization": state["normalization"],
                "channel": sig.get("channel"),
                "text": text,
            },
            text,
        )
        if meta.get("fallback_mock"):
            status = "fallback"
    except Exception as exc:  # noqa: BLE001
        status = "error"
        state["errors"].append(f"classify: {exc}")
    c, notes = _postcheck_classification(obj, state, deps)
    if c.get("error_code") and not await deps.ctx.fetchone(
        "select code from error_codes where code=%s", (c["error_code"],)
    ):
        # Гипотеза модели не создаёт новый код справочника и не должна ломать FK инцидента.
        notes.append(f"неизвестный код ошибки {c['error_code']} исключён: в справочнике отсутствует")
        c["error_code"] = None
    c.setdefault("tone", "neutral")
    c.setdefault("churn_risk", 0)
    c = prune(c, deref("agent/classification"))
    errors = validate(c, "agent/classification")
    if errors:
        log.warning("classification_invalid", errors=errors[:3])
        state["errors"].append(f"classification schema: {errors[:2]}")
        c = {
            **c,
            "entities": {},
            "flags": [
                f
                for f in c.get("flags", [])
                if f
                in (
                    "churn_intent",
                    "repeat",
                    "sarcasm",
                    "aggression",
                    "mass_impact",
                    "passive_aggression",
                    "hidden_negativity",
                    "regulator_threat",
                    "public",
                    "rule_confirmed",
                    "repeat_contact_7d",
                )
            ],
        }
        c["tone"] = (
            c.get("tone")
            if c.get("tone") in ("neutral", "positive", "irritated", "angry", "sarcastic", "formal")
            else "neutral"
        )
    state["classification"] = c
    await deps.ctx.conn.execute(
        "update signals set classification = %s::jsonb, status = 'classified', updated_at = now() where id = %s",
        (dumps(c), sig["id"]),
    )
    await deps.ctx.notify(
        "signals",
        "classified",
        {
            "id": sig["id"],
            "signal_type": c["signal_type"],
            "criticality": c["criticality"],
            "confidence": c["confidence"],
            "flags": c["flags"],
        },
    )
    state["current_node"] = "decide"
    await deps.record_step(
        "classify",
        status,
        {"normalization": state["normalization"], "hints": state["context"].get("hints")},
        {
            **c,
            "postcheck_notes": notes,
            "score_pipeline": SCORE_PIPELINE,
            "churn_predicted_sim": deps.ctx.sim_time.isoformat(),
        },
        prompt=meta.get("prompt"),
        raw=meta.get("raw"),
        reasoning=(c.get("rationale_ru") or "") + ((" Пост-проверки: " + "; ".join(notes) + ".") if notes else ""),
        model=meta.get("model"),
        usage=meta.get("usage"),
        latency_ms=int(meta.get("latency_ms") or 0),
    )
    return state


def _context_for_prompt(state: AgentState) -> dict[str, Any]:
    ctx, client = state["context"], state.get("client")
    return {
        "client": {k: client.get(k) for k in ("segment", "psychotype", "city", "region_code", "state", "churn_risk")}
        if client
        else None,
        **({"operator_feedback": ctx["operator_feedback"]} if ctx.get("operator_feedback") else {}),
        **({"conversation": ctx["conversation"]} if ctx.get("conversation") else {}),
        **({"form_context": ctx["form_context"]} if ctx.get("form_context") else {}),
        "identification": ctx.get("identification"),
        "products": [{k: p.get(k) for k in ("product", "status", "card_last4")} for p in ctx.get("products") or []],
        "operations": [
            {
                k: o.get(k)
                for k in (
                    "op_type",
                    "method",
                    "amount_rub",
                    "fee_amount",
                    "status",
                    "error_code",
                    "started_sim",
                    "merchant",
                )
            }
            for o in (ctx.get("operations") or [])[:8]
        ],
        "active_faults": (ctx.get("system_logs") or {}).get("active_faults"),
        "related_incidents": [
            {
                k: i.get(k)
                for k in ("incident_id", "title", "error_code", "status", "mass_impact", "is_clients", "same_error")
            }
            for i in ctx.get("related_incidents") or []
        ],
        "client_history": ctx.get("client_history"),
        "similar_signals": [
            {k: s.get(k) for k in ("text", "signal_type", "same_client")}
            for s in (ctx.get("similar_signals") or [])[:4]
        ],
        "rules_matched": [
            {k: r.get(k) for k in ("rule_code", "action", "amount_rub", "within_limit")}
            for r in ctx.get("rules_matched") or []
        ],
    }


async def _abs_refund_state(deps: Deps, client_id: int | None, operation_ids: list[Any]) -> dict[str, Any]:
    """Факты из Mock-АБС для политики автономного возврата: уже был возврат по операции; возвратов клиенту за 30 сим-дней."""
    ops = [int(o) for o in operation_ids if o is not None]
    already = False
    if ops:
        row = await deps.ctx.fetchone(
            "select 1 from ledger_entries r join ledger_entries f on r.refund_of_entry_id = f.id "
            "where r.kind = 'refund' and f.operation_id = any(%s) limit 1",
            (ops,),
        )
        already = row is not None
    refunds_30d = 0
    if client_id:
        row = await deps.ctx.fetchone(
            "select count(*) from ledger_entries l join accounts a on a.id = l.account_id "
            "where a.client_id = %s and l.kind = 'refund' and l.posted_sim >= %s",
            (client_id, deps.ctx.sim_time - dt.timedelta(days=30)),
        )
        refunds_30d = int(row[0]) if row else 0
    return {"already_refunded": already, "refunds_30d": refunds_30d}


def _policy_context(state: AgentState, deps: Deps) -> pol.PolicyContext:
    client, ctx, c = state.get("client") or {}, state["context"], state["classification"]
    hist = ctx.get("client_history") or {}
    repeat = 1 + sum(1 for t in hist.get("last_types") or [] if t == c.get("signal_type"))
    amount = (state["normalization"].get("entities") or {}).get("amount_rub")
    return pol.PolicyContext(
        segment=client.get("segment"),
        repeat_count=repeat,
        signals_7d=int(hist.get("signals_7d") or 0) + 1,
        amount_rub=float(amount) if amount else None,
        refunds_30d=0,
    )


def _decision_rationale(llm: str | None, cls: str | None, own: str) -> str:
    """Обоснование решения: если модель вернула то же, что в классификации (mock), берём своё резюме маршрута/SLA."""
    llm = (llm or "").strip()
    if not llm or llm == (cls or "").strip():
        return own[:2000]
    return f"{llm} {own}"[:2000]


def _title(raw: str) -> str:
    """Заголовок инцидента: без служебного хвоста «; тональность…», без PII, до 160 символов."""
    t = re.sub(r"[;,]?\s*тональность.*$", "", raw).strip().rstrip(".").strip() or "Обращение клиента"
    return wt.PII_RE.sub("****", t)[:160]


async def decide(state: AgentState, deps: Deps) -> AgentState:
    sig, c, norm, client, ctx = (
        state["signal"],
        state["classification"],
        state["normalization"],
        state.get("client") or {},
        state["context"],
    )
    from app.agent.operator_feedback import feedback_context

    feedback = await feedback_context(deps.ctx.conn, sig["id"], deps.ctx.run_id)
    if feedback:
        ctx["operator_feedback"] = feedback
    text = sig.get("text") or ""
    stype = c["signal_type"]
    flags = list(c.get("flags") or [])
    segment = client.get("segment")
    pctx = _policy_context(state, deps)
    p = pol.merged(deps.policies)
    team, co_teams, rule_id = route_team(c, state, deps)
    status = "ok"
    obj: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    try:
        obj, meta = await _llm(
            deps,
            "decide",
            "agent/decision",
            {
                "routing_hint": f"{team} (+{', '.join(co_teams)})" if co_teams else team,
                "segment": segment or "mass",
                "first_response_min": client.get("first_response_min") or 60,
                "fewshot": _fewshot_for_decide(deps, c),
                "classification": c,
                "normalization": norm,
                "context": _context_for_prompt(state),
                "channel": sig.get("channel"),
                "text": text,
            },
            text,
        )
        if meta.get("fallback_mock"):
            status = "fallback"
    except Exception as exc:  # noqa: BLE001
        status = "error"
        state["errors"].append(f"decide: {exc}")
    d: dict[str, Any] = dict(obj)
    checks: list[dict[str, Any]] = []
    # --- детерминированные поля ---
    rules = ctx.get("rules_matched") or []
    fee_rule = next((r for r in rules if r["action"] == "refund_fee"), None)
    mass_impact = max(
        [i.get("mass_impact") or 0 for i in ctx.get("related_incidents") or [] if i.get("same_error")] + [1]
    )
    crit = slam.effective_criticality(c["criticality"], flags, segment, stype, mass_impact)
    complexity = slam.complexity_for(stype, None, flags)
    incident_type = stype
    if fee_rule and stype == "tariff_terms":
        incident_type, complexity = "fee_refund", "easy"
    if incident_type not in (
        "tech_fault",
        "client_error",
        "tariff_terms",
        "service_quality",
        "fraud_suspicion",
        "legal_regulatory",
        "info_request",
        "suggestion",
        "account_closure",
        "proactive",
        "fee_refund",
        "misselling",
    ):
        incident_type = "tech_fault"
    prio = slam.priority(crit, int(c.get("churn_risk") or 0), segment, flags)
    from app.agent.operator_feedback import planned_priority

    prio = planned_priority(ctx, prio)
    sla_full = slam.sla_for(complexity, crit, deps.ctx.sim_time, deps.sla_matrix)
    # инцидент: создать / связать / не нужен
    related = ctx.get("related_incidents") or []
    link = next((i for i in related if i.get("same_error") and i.get("error_code")), None) or next(
        (i for i in related if i.get("is_clients") and i.get("incident_type") == incident_type), None
    )
    unidentified = not state.get("client")
    anonymous_request = unidentified and stype != "gratitude"
    demo_team_task = False
    if stype == "info_request" and sig.get("origin") == "scenario":
        # В явно запущенной эмуляции даже запрос объяснения должен пройти команду и получить итог.
        demo_team_task = bool(
            await deps.ctx.fetchone(
                "select id from sim_runs where id=%s and kind='scenario' "
                "and settings_snapshot->'demo_execution'->>'enabled'='true'",
                (deps.ctx.run_id,),
            )
        )
        if demo_team_task:
            checks.append(
                {
                    "rule": "demo_team_task",
                    "passed": True,
                    "note": "Запрос передаётся demo-команде для итогового ответа",
                }
            )
    if (
        stype in NO_INCIDENT_TYPES
        and "churn_intent" not in flags
        and not fee_rule
        and not anonymous_request
        and not demo_team_task
    ):
        incident_action, link_id = "none", None
    elif link:
        incident_action, link_id = "link_existing", int(link["incident_id"])
    else:
        incident_action, link_id = "create", None
    # HITL / эскалация / уточнение
    gift = (
        giftmod.choose(segment, crit, flags, (client or {}).get("psychotype"))
        if incident_action != "none" and stype not in NO_INCIDENT_TYPES and not unidentified
        else None
    )
    pctx.gift_code = (gift or {}).get("privilege_code")
    pctx.rule_based_type = "tariff_terms" if fee_rule else None
    human_reason = pol.needs_human(c, pctx, deps.policies)
    if human_reason is None and client.get("hitl_required"):
        human_reason = "ultra_vip" if segment == "ultra_vip" else "policy_other"
    if human_reason is None and gift and gift.get("privilege_code") in pol.PARTNER_PRIVILEGES:
        human_reason = "partner_privilege"
    esc_reason = pol.needs_escalation(norm, c, pctx, deps.policies) if incident_action != "none" else None
    already_asked = (
        any(s.get("signal_type") == stype and s.get("same_client") for s in ctx.get("similar_signals") or [])
        or sig.get("parent_signal_id") is not None
    )
    clarify = (
        human_reason in (None, "low_confidence")
        and incident_action != "none"
        and pol.needs_clarification(c, norm, already_asked=already_asked, policies=deps.policies)
    )
    clarify_kind: str | None = "generic" if clarify else None
    sarcasm_clarify_path = False
    if not unidentified and human_reason is None and not already_asked:
        if stype == "fraud_suspicion" and not str(ctx.get("hints", {}).get("error_code") or "").startswith("AF-"):
            # подозрение на мошенничество без подтверждения антифрода (сценарий 5): просим данные операции и ждём
            clarify, clarify_kind = True, "fraud_data"
        elif (
            "sarcasm" in (c.get("flags") or [])
            and not (norm.get("entities") or {}).get("amount_rub")
            and incident_action != "none"
        ):
            # сарказм без конкретики (сценарий 11): один уточняющий вопрос
            clarify, clarify_kind = True, "generic"
            sarcasm_clarify_path = True
    if anonymous_request:
        clarify, clarify_kind = False, None
        checks.append(
            {
                "rule": "anonymous_handoff",
                "passed": True,
                "note": "Приём и маршрут без обязательной идентификации; деньги и HITL — по прежним политикам",
            }
        )
    checks += [
        {
            "rule": "confidence>=threshold",
            "passed": float(c["confidence"]) >= p["confidence_threshold"],
            "note": f"{c['confidence']:.2f} vs {p['confidence_threshold']}",
        },
        {"rule": "ultra_vip_hitl", "passed": segment != "ultra_vip", "note": segment or "—"},
        {"rule": "legal_regulatory_hitl", "passed": stype != "legal_regulatory" and not pol.red_words_require_hitl(c)},
        {
            "rule": "fraud_amount",
            "passed": not (stype == "fraud_suspicion" and (pctx.amount_rub or 0) > p["fraud_amount_rub"]),
            "note": f"{pctx.amount_rub or 0:.0f} ₽",
        },
        {
            "rule": "repeat_3plus",
            "passed": pctx.repeat_count < p["repeat_hitl_count"],
            "note": f"повторов: {pctx.repeat_count}",
        },
        {"rule": "partner_privilege_hitl", "passed": pctx.gift_code not in pol.PARTNER_PRIVILEGES},
        {"rule": "escalation", "passed": esc_reason is None, "note": esc_reason or "—"},
        {
            "rule": "dedup_window",
            "passed": incident_action != "link_existing",
            "note": f"инцидент #{link_id}" if link_id else "—",
        },
    ]
    if fee_rule:
        abs_state = await _abs_refund_state(deps, (client or {}).get("client_id"), fee_rule.get("operation_ids") or [])
        pctx = dataclasses.replace(pctx, refunds_30d=abs_state["refunds_30d"])
        ok, why = pol.refund_allowed(
            float(fee_rule.get("amount_rub") or 0),
            segment,
            rule_confirmed=True,
            ident_conf=float((ctx.get("identification") or {}).get("confidence") or 0),
            class_conf=float(c["confidence"]),
            already_refunded=abs_state["already_refunded"],
            ctx=pctx,
            policies=deps.policies,
        )
        checks.append({"rule": "refund_autonomy", "passed": ok, "note": why})
        if not ok:
            # Несработавший возврат закрывает человек: уточнение не подменяет HITL и не снимает причину.
            clarify = False
            if human_reason in (None, "low_confidence"):
                human_reason = "policy_other"
    if clarify and human_reason == "low_confidence":
        # Иначе граф остаётся на wait_human и фасад уточнения не вызывается. Другие причины HITL не снимаем.
        human_reason = None
    if clarify:
        # Уточнение важнее эскалации на этом проходе: второй вопрос подряд уже запрещён, эскалация — на следующем.
        router_action = "request_clarification"
    elif incident_action == "none":
        # human_reason сам по себе не маршрут: HITL остаётся в needs_human / wait_human.
        router_action = "none"
    elif esc_reason:
        router_action = "escalate"
    else:
        router_action = "route"
    # --- тексты от модели с проверками ---
    ca = dict(d.get("client_action") or {})
    public = sig.get("channel") in PUBLIC_CHANNELS
    kind = ca.get("kind")
    if clarify:
        kind = "request_data"
    elif public:
        kind = "public_reply_and_dm"
    elif kind not in ("reply", "acknowledge", "proactive_notice", "request_data", "public_reply_and_dm", "none"):
        kind = "acknowledge" if incident_action != "none" else "reply"
    if kind == "request_data" and not clarify:
        kind = "acknowledge"
    channel = (
        ca.get("channel")
        if ca.get("channel")
        in (
            "social",
            "call",
            "chat",
            "email",
            "branch",
            "landing",
            "telegram_bot",
            "proactive",
            "review_portal",
            "voice_input",
            "branch_audio",
        )
        else sig.get("channel") or "chat"
    )
    signal_lang = _client_lang(norm.get("language") if isinstance(norm.get("language"), str) else None, text)
    text_ru = (ca.get("text_ru") or "").strip() or None
    bad = pol.forbidden_phrases(text_ru)
    if bad:
        checks.append({"rule": "forbidden_phrases", "passed": False, "note": ", ".join(bad)})
        text_ru = None
    else:
        checks.append({"rule": "forbidden_phrases", "passed": True})
    if text_ru:
        text_ru = wt.PII_RE.sub("****", text_ru)[:2000]
    if anonymous_request:
        kind = "public_reply_and_dm" if public else "acknowledge"
        text_ru = _anonymous_ack(signal_lang)
    question = (d.get("clarification_question_ru") or ca.get("question_ru") or "").strip() or None
    if clarify and clarify_kind == "identify":
        question = _fixed_question("identify", signal_lang)
    elif clarify and clarify_kind == "fraud_data":
        question = _fixed_question("fraud_data", signal_lang)
    if clarify and not question:
        question = _fixed_question("generic", signal_lang)
    template = (
        "clarify_request"
        if kind == "request_data"
        else "public_reply"
        if public
        else "resolved"
        if stype == "gratitude"
        else "ack_received"
    )
    client_action = {
        "kind": kind,
        "channel": channel,
        "template_code": template,
        "text_ru": text_ru,
        "question_ru": question if kind == "request_data" else None,
        "promise_check": True,
    }
    decision: dict[str, Any] = {
        "incident_action": incident_action,
        "link_incident_id": link_id,
        "incident_type": incident_type if incident_action != "none" else None,
        "title_ru": _title(d.get("title_ru") or c.get("summary_ru") or "Обращение клиента"),
        "complexity": complexity,
        "criticality": crit,
        "priority": prio,
        "sla": {k: sla_full[k] for k in ("fix_days", "report_days", "take_hours", "due_sim")},
        "route": {"team": team, "co_teams": co_teams, "rule_id": rule_id},
        "client_action": client_action,
        "team_notice_ru": (
            d.get("team_notice_ru")
            or f"Инцидент: {c.get('summary_ru')}. Код ошибки: {c.get('error_code') or '—'}, система: {c.get('system') or '—'}. Проверьте журналы и подтвердите масштаб."
        )[:1500],
        "gift": gift,
        "followup": (
            {"wake_in_sim_hours": 24.0 if clarify_kind == "fraud_data" else 4.0, "reason": "awaiting_client"}
            if clarify
            else {"wake_in_sim_hours": max(0.25, float(sla_full["take_hours"] or 2)), "reason": "awaiting_team"}
            if incident_action != "none"
            else None
        ),
        "needs_human": human_reason is not None,
        "human_reason": human_reason,
        "human_options": pol.human_options(human_reason) if human_reason else [],
        "human_recommendation": pol.human_recommendation(human_reason, c) if human_reason else None,
        "router_action": router_action,
        "escalation": (
            {
                "reason": esc_reason,
                "severity": "critical" if c["problem_summary"]["severity"] == "critical" else "high",
                "to_role": "branch_manager" if sig.get("channel") == "branch" else "cx_lead",
            }
            if esc_reason and (router_action == "escalate" or (clarify and sarcasm_clarify_path))
            else None
        ),
        "clarification_question_ru": question if clarify else None,
        "rationale_ru": _decision_rationale(
            d.get("rationale_ru"),
            c.get("rationale_ru"),
            f"Тип {stype}, критичность {crit}, приоритет P{prio}; маршрут {team} по правилу {rule_id or 'по умолчанию'}; "
            f"SLA {sla_full['fix_days']} раб. дн.{' Нужен человек: ' + str(human_reason) + '.' if human_reason else ''}",
        ),
        "policy_checks": checks,
        "economics_preview": (
            {
                "affected_count": int(mass_impact),
                # При неизвестном продукте оценку даст сервер экономики после приёма, без фиктивной ставки.
                **(
                    {"rate_code": f"{stype}_{crit}", "potential_loss_rub": float(mass_impact) * 1500.0}
                    if c.get("product") not in (None, "unknown", "other")
                    else {}
                ),
            }
            if incident_action != "none"
            else None
        ),
    }
    decision = prune(decision, deref("agent/decision"))
    errors = validate(decision, "agent/decision")
    if errors:
        log.warning("decision_invalid", errors=errors[:3])
        state["errors"].append(f"decision schema: {errors[:2]}")
    state["decision"] = decision
    state["context"]["sla_full"] = sla_full
    await deps.ctx.conn.execute(
        "update signals set decision = %s::jsonb, updated_at = now() where id = %s", (dumps(decision), sig["id"])
    )
    state["current_node"] = "wait_human" if decision["needs_human"] else "act"
    await deps.record_step(
        "decide",
        status,
        {"classification": {k: c.get(k) for k in ("signal_type", "criticality", "confidence", "flags")}, "policies": p},
        decision,
        prompt=meta.get("prompt"),
        raw=meta.get("raw"),
        reasoning=decision["rationale_ru"]
        + (f" Требуется человек: {human_reason}." if human_reason else "")
        + (f" Эскалация: {esc_reason}." if esc_reason else ""),
        model=meta.get("model"),
        usage=meta.get("usage"),
        latency_ms=int(meta.get("latency_ms") or 0),
    )
    return state


async def wait_human(state: AgentState, deps: Deps) -> AgentState:
    """Создаёт запрос HITL и прерывает граф (outcome awaiting_human); чекпоинт — вход этого шага."""
    d, sig = state["decision"], state["signal"]
    incident_id = await _hitl_incident_id(deps, d)
    if not state.get("client") and not sig.get("client_id") and d.get("incident_action") in ("create", "link_existing"):
        incident_id = await _accept_anonymous_before_hitl(state, deps)

    res = await wt.request_human_decision(
        deps.ctx,
        sig["id"],
        incident_id,
        d["human_reason"] or "policy_other",
        d,
        d.get("human_options") or pol.human_options("_default"),
        d.get("human_recommendation") or "",
    )
    await deps.ctx.conn.execute(
        "update signals set status = 'awaiting_human', updated_at = now() where id = %s", (sig["id"],)
    )
    state["human"] = {"human_decision_id": res.get("human_decision_id"), "status": "requested"}
    state["outcome"] = "awaiting_human"
    await deps.record_step(
        "wait_human",
        "ok",
        dict(state),
        {"human_decision_id": res.get("human_decision_id"), "reason": d["human_reason"]},
        reasoning=f"Ожидание решения человека: {d.get('human_recommendation')}",
    )
    return state


def apply_human_decision(state: AgentState, decision: str, modified: dict[str, Any] | None) -> AgentState:
    """Вход после решения оператора: accept/modify/reject/delegate (resume графа)."""
    state["human"] = {**(state.get("human") or {}), "status": decision, "modified": modified or {}}
    if decision == "modify" and modified:
        d = dict(state["decision"])
        for k, v in modified.items():
            if k in ("client_action", "route", "gift", "sla") and isinstance(v, dict) and isinstance(d.get(k), dict):
                d[k] = {**d[k], **v}
            else:
                d[k] = v
        state["decision"] = d
    if decision == "reject":
        state["decision"] = {
            **state["decision"],
            "incident_action": "none",
            "router_action": "none",
            "client_action": {**state["decision"]["client_action"], "kind": "none"},
            "gift": None,
            "escalation": None,
        }
    state["current_node"] = "act"
    state["outcome"] = None
    return state


def _refund_text(base: str, amount: float, already: float = 0.0, lang: str = "ru") -> str:
    """Текст клиенту после фактического возврата: не обещание «вернём», а факт «возвращено» (или «была возвращена ранее»)."""
    if lang == "en":
        low = base.lower()
        if "returned" in low or "refunded" in low:
            return base
        if amount:
            fact = f"The fee of {amount:.0f} RUB was charged by mistake and has already been returned to your account."
        else:
            fact = (
                f"The fee of {already:.0f} RUB was charged by mistake and had already been returned to your account. "
                "Please check your statement."
            )
        apology = "We are sorry for the inconvenience."
        if communication_lang(base) == "en":
            first = base.split(". ")[0].strip().rstrip(".")
            return f"{first}. {fact} {apology}" if first else f"{fact} {apology}"
        return f"{fact} {apology}"
    if "возвращ" in base.lower():
        return base
    if amount:
        fact = f"Комиссия {amount:.0f} ₽ списана ошибочно и уже возвращена на ваш счёт."
    else:
        fact = f"Комиссия {already:.0f} ₽ была списана ошибочно и уже возвращена на ваш счёт ранее — проверьте, пожалуйста, выписку."
    first = base.split(". ")[0].strip().rstrip(".")
    return (
        f"{first}. {fact} Приносим извинения за неудобства." if first else f"{fact} Приносим извинения за неудобства."
    )


def _public_fallback(client: dict[str, Any] | None, lang: str = "ru") -> str:
    name = mask_name((client or {}).get("name"))
    if lang == "en":
        return (
            f"{name}, thank you for writing. We are already looking into this and will message you privately "
            "to clarify the details."
        )
    return f"{name}, спасибо, что написали. Мы уже разбираемся и напишем вам в личные сообщения, чтобы уточнить детали."


_ROUTER_FACADES = ("route_to_product_team", "route_to_department", "escalate_to_manager", "request_clarification")


def _route_summary(d: dict[str, Any], c: dict[str, Any]) -> str:
    raw = wt.PII_RE.sub("****", (d.get("title_ru") or c.get("summary_ru") or "Обращение клиента в банк").strip())
    if len(raw) < 10:
        raw = f"{raw} — обращение клиента".strip()
    return raw[:300]


def _act_spec(
    d: dict[str, Any],
    c: dict[str, Any],
    sig: dict[str, Any],
    client: dict[str, Any] | None,
    sla_full: dict[str, Any],
    state: AgentState,
) -> dict[str, Any]:
    follow = d.get("followup") or {}
    route = d.get("route") or {}
    raw_lang = (state.get("normalization") or {}).get("language") or sig.get("lang")
    lang = _client_lang(raw_lang if isinstance(raw_lang, str) else None, str(sig.get("text") or ""))
    return {
        **c,
        "incident_action": d.get("incident_action"),
        "incident_type": d.get("incident_type") or c.get("signal_type") or "tech_fault",
        "title_ru": d.get("title_ru") or c.get("summary_ru") or "Обращение клиента",
        "complexity": d.get("complexity") or "medium",
        "criticality": d.get("criticality") or "medium",
        "priority": int(d.get("priority") or 3),
        "team": route.get("team") or "team_cx",
        "co_teams": route.get("co_teams") or [],
        "sla": {**(d.get("sla") or {}), **{k: sla_full.get(k) for k in ("take_due_sim", "report_due_sims")}},
        "mass_impact": (d.get("economics_preview") or {}).get("affected_count") or 1,
        "region_code": (client or {}).get("region_code") or (sig.get("geo") or {}).get("region_code"),
        "fault_id": (state["context"].get("hints") or {}).get("fault_id"),
        "problem_summary": c.get("problem_summary"),
        "followup_hours": float(follow.get("wake_in_sim_hours") or 4.0),
        "lang": lang,
    }


def _facade_names(calls: list[dict[str, Any]]) -> list[str]:
    return [str(c["name"]) for c in calls if c.get("ok") is not False and c.get("name") in _ROUTER_FACADES]


def _router_matches(action: str, names: list[str]) -> bool:
    """route — маршрут без эскалации; escalate — оба фасада; уточнение — без маршрута; none — ни одного.

    Для route и escalate отсутствие фасада не считается успехом.
    """
    has_route = bool({"route_to_department", "route_to_product_team"}.intersection(names))
    has_esc = "escalate_to_manager" in names
    has_clar = "request_clarification" in names
    if action == "route":
        return has_route and not has_esc
    if action == "escalate":
        return has_route and has_esc
    if action == "request_clarification":
        return has_clar and not has_route
    if action == "none":
        return not has_route and not has_esc and not has_clar
    return False


async def _act_route(deps: Deps, d: dict[str, Any], c: dict[str, Any], mark: Callable[..., None]) -> int:
    summary = _route_summary(d, c)
    product_line = c.get("product_line")
    if product_line and product_line != "other":
        routed = await router_tools.route_to_product_team(deps.ctx, str(product_line), deps.ctx.act_frame.signal_id)  # type: ignore[union-attr]
    else:
        routed = await router_tools.route_to_department(deps.ctx, str(d["route"]["team"]), int(d["priority"]), summary)
    d["route"]["team"] = routed["department"]
    new_id = int(routed["incident_id"])
    if deps.ctx.act_frame is not None:
        deps.ctx.act_frame.incident_id = new_id
    mark("incident", incident_id=new_id, public_id=routed.get("ticket_id"), linked=bool(routed.get("linked")))
    return new_id


async def _act_escalate(deps: Deps, d: dict[str, Any], mark: Callable[..., None]) -> None:
    esc_spec = d.get("escalation") or {}
    reason = str(esc_spec.get("reason") or "эскалация по политике банка")
    if len(reason) < 5:
        reason = "эскалация по политике банка"
    esc = await router_tools.escalate_to_manager(
        deps.ctx,
        reason,
        str(esc_spec.get("severity") or "high"),
        str(esc_spec.get("to_role") or "cx_lead"),
    )
    mark("escalation", escalation_id=esc.get("escalation_id"), public_id=esc.get("public_id"))


async def _accept_anonymous_before_hitl(state: AgentState, deps: Deps) -> int:
    """До HITL разрешён только приём: маршрут, уведомления и обязательная эскалация. Деньги/подарки не исполняются."""
    d, c, sig = state["decision"], state["classification"], state["signal"]
    done = {a["action"] for a in state["actions"]}
    incident_id = next((a["incident_id"] for a in state["actions"] if a.get("incident_id")), None)
    deps.ctx.act_frame = ActFrame(
        signal_id=int(sig["id"]),
        client_id=None,
        incident_id=incident_id,
        link_incident_id=d.get("link_incident_id"),
        spec=_act_spec(d, c, sig, None, state["context"].get("sla_full") or {}, state),
    )

    def mark(action: str, **kw: Any) -> None:
        state["actions"].append({"action": action, **kw})

    if incident_id is None:
        incident_id = await _act_route(deps, d, c, mark)
    if d.get("router_action") == "escalate" and "escalation" not in done:
        await _act_escalate(deps, d, mark)
    if "notify_team" not in done:
        notice = await wt.notify_team(
            deps.ctx, d["route"]["team"], incident_id, sig["id"], d.get("team_notice_ru") or ""
        )
        mark("notify_team", notification_id=notice.get("notification_id"))
    lang = deps.ctx.act_frame.spec["lang"]
    message = _anonymous_ack(lang)
    if "notify_client" not in done:
        notice = await router_tools.notify_customer(deps.ctx, str(sig.get("channel") or "chat"), message)
        mark("notify_client", notification_id=notice.get("notification_id"))
    if sig.get("external_post_id") and "feed_reply" not in done:
        reply = await abs_tools.publish_public_reply(
            deps.ctx, int(sig["external_post_id"]), message, incident_id, True, False
        )
        mark("feed_reply", post_id=sig["external_post_id"], reply_id=reply.get("reply_id"))
    return int(incident_id)


async def _act_clarify(deps: Deps, d: dict[str, Any], sig: dict[str, Any], mark: Callable[..., None]) -> int | None:
    ca = d.get("client_action") or {}
    lang = "ru"
    if deps.ctx.act_frame is not None:
        raw = (deps.ctx.act_frame.spec or {}).get("lang")
        lang = raw if raw in ("ru", "en") else "ru"
    question = (d.get("clarification_question_ru") or ca.get("question_ru") or "").strip()
    if len(question) < 5:
        question = (
            "Please share the date and amount of the transaction."
            if lang == "en"
            else "Уточните, пожалуйста, дату и сумму операции."
        )
    channel = str(ca.get("channel") or sig.get("channel") or "chat")
    if communication_lang(question) != lang:
        question = await _render_client_text(
            deps,
            question,
            lang,
            "clarify_request",
            channel,
            None,
            {"name": mask_name(None), "question": _fixed_question("generic", lang)},
        )
        if len(question) < 5:
            question = _fixed_question("generic", lang)
    clar = await router_tools.request_clarification(deps.ctx, question[:400], channel)
    new_id = deps.ctx.act_frame.incident_id if deps.ctx.act_frame else None
    mark("clarification", notification_id=clar.get("notification_id"))
    return int(new_id) if new_id is not None else None


async def act(state: AgentState, deps: Deps) -> AgentState:
    """Исполнение решения через инструменты записи — идемпотентно (повторный вход не дублирует побочные эффекты)."""
    d, c, sig, client = state["decision"], state["classification"], state["signal"], state.get("client")
    done = {a["action"] for a in state["actions"]}
    actions = state["actions"]
    step_status = "ok"
    incident_id: int | None = next((a["incident_id"] for a in actions if a.get("incident_id")), None)
    human = (state.get("human") or {}).get("status")
    sla_full = state["context"].get("sla_full") or {}

    def mark(action: str, **kw: Any) -> None:
        actions.append({"action": action, **kw})

    if d["incident_action"] == "create" and "incident" not in done and c.get("error_code"):
        # гонка параллельных прогонов (массовый сбой): сериализуем создание по коду ошибки и ещё раз ищем открытый инцидент
        await deps.ctx.conn.execute(
            "select pg_advisory_xact_lock(hashtext(%s))", (f"incident:{deps.ctx.run_id}:{c['error_code']}",)
        )
        dup = await deps.ctx.fetchone(
            "select id from incidents where run_id = %s and error_code = %s and status not in ('closed','rejected','duplicate') "
            "and created_sim >= %s - interval '4 hours' and agent_run_id <> %s order by id limit 1",
            (deps.ctx.run_id, c["error_code"], deps.ctx.sim_time, deps.ctx.agent_run_id),
        )
        if dup:
            d["incident_action"], d["link_incident_id"] = "link_existing", int(dup[0])
            flags_now = list(dict.fromkeys([*(c.get("flags") or []), "mass_impact"]))
            c["flags"] = flags_now
            state["decision"] = d
    spec = _act_spec(d, c, sig, client, sla_full, state)
    link_id = (
        int(d["link_incident_id"])
        if d.get("incident_action") == "link_existing" and d.get("link_incident_id")
        else None
    )
    deps.ctx.act_frame = ActFrame(
        signal_id=int(sig["id"]),
        client_id=(client or {}).get("client_id"),
        incident_id=incident_id,
        link_incident_id=link_id,
        spec=spec,
    )
    router_action = str(d.get("router_action") or "none")
    can_ticket = (
        d.get("incident_action") in ("create", "link_existing") or incident_id is not None or link_id is not None
    )

    async def run_router() -> None:
        nonlocal incident_id
        if router_action in ("route", "escalate") and can_ticket:
            incident_id = await _act_route(deps, d, c, mark)
            if router_action == "escalate":
                await _act_escalate(deps, d, mark)
        elif router_action == "request_clarification":
            clarified = await _act_clarify(deps, d, sig, mark)
            if clarified is not None:
                incident_id = clarified

    if router_action in ("route", "escalate", "request_clarification"):
        await run_router()
    elif d["incident_action"] == "create" and "incident" not in done:
        inc = await wt.create_incident(deps.ctx, sig["id"], (client or {}).get("client_id"), spec)
        incident_id = int(inc["incident_id"])
        mark("incident", incident_id=incident_id, public_id=inc.get("public_id"))
    elif d["incident_action"] == "link_existing" and "incident" not in done and d.get("link_incident_id"):
        inc = await wt.link_signal_to_incident(deps.ctx, sig["id"], int(d["link_incident_id"]))
        incident_id = int(inc["incident_id"])
        mark("incident", incident_id=incident_id, linked=True)
    names = _facade_names(deps.ctx.calls)
    matched = _router_matches(router_action, names)
    if not matched and router_action != "none":
        await run_router()
        names = _facade_names(deps.ctx.calls)
        matched = _router_matches(router_action, names)
    if not matched:
        step_status = "error"
        await wt.request_human_decision(
            deps.ctx,
            int(sig["id"]),
            None,
            "policy_other",
            {"router_action": router_action, "tools": names},
            pol.human_options("policy_other"),
            pol.human_recommendation("policy_other"),
        )
    checks = list(d.get("policy_checks") or [])
    checks.append({"rule": "router_action_tools", "passed": matched, "note": ",".join(names) or "—"})
    d["policy_checks"] = checks
    state["decision"] = d
    await deps.ctx.conn.execute(
        "update signals set decision = %s::jsonb, updated_at = now() where id = %s", (dumps(d), sig["id"])
    )
    if incident_id and human in ("accept", "modify", "delegate"):
        await deps.ctx.conn.execute(
            "update human_decisions set incident_id = %s where agent_run_id = %s and incident_id is null",
            (incident_id, deps.ctx.agent_run_id),
        )
    # --- Mock-АБС: возврат ошибочной комиссии (ТЗ 9.2–9.3, 21.4): автономно в лимите или после решения человека
    fee_rule = next((r for r in (state["context"].get("rules_matched") or []) if r.get("action") == "refund_fee"), None)
    refund_check = next((pc for pc in (d.get("policy_checks") or []) if pc.get("rule") == "refund_autonomy"), None)
    refund_ok = bool(fee_rule) and (
        human in ("accept", "modify") or (human is None and bool(refund_check and refund_check.get("passed")))
    )
    refund_total = refund_dup = 0.0
    if fee_rule and refund_ok and "refund" not in done:
        for op_id in fee_rule.get("operation_ids") or []:
            if op_id is None:
                continue
            try:
                rf = await abs_tools.refund_fee(
                    deps.ctx,
                    int(op_id),
                    None,
                    fee_rule.get("rule_code"),
                    f"{fee_rule.get('error_code') or 'правило'}: {d['title_ru']}"[:160],
                )
            except Exception as exc:  # AbsError / ToolError — без побочных эффектов, фиксируем причину
                mark("refund_failed", operation_id=op_id, error=str(exc)[:200])
                continue
            if rf.get("duplicate"):
                refund_dup += float(rf.get("amount_rub") or 0)
            else:
                refund_total += float(rf.get("amount_rub") or 0)
            mark(
                "refund",
                operation_id=op_id,
                entry_id=rf.get("entry_id"),
                amount_rub=rf.get("amount_rub"),
                duplicate=rf.get("duplicate"),
            )
        if refund_total and incident_id:
            try:
                await wt.update_incident(
                    deps.ctx,
                    incident_id,
                    "resolved",
                    "Комиссия возвращена (Mock-АБС)",
                    {"resolution_summary": f"Комиссия {refund_total:.2f} ₽ возвращена на счёт клиента"},
                )
            except Exception as exc:  # статусный переход может быть запрещён — не ломаем проход
                mark("incident_update_failed", error=str(exc)[:160])
        if fee_rule.get("error_code") and "affected_scan" not in done:
            aff = await abs_tools.find_affected_clients(deps.ctx, str(fee_rule["error_code"]), 72)
            mark("affected_scan", **{k: v for k, v in aff.items() if k != "operations"})
            threshold = int(pol.merged(deps.policies).get("mass_refund_threshold") or 50)
            if aff.get("pending_count", 0) >= threshold and "mass_refund_task" not in done:
                task = await wt.create_task(
                    deps.ctx,
                    "manual_review",
                    incident_id,
                    None,
                    {
                        "kind": "mass_refund",
                        "error_code": fee_rule["error_code"],
                        "pending_count": aff["pending_count"],
                        "pending_fee_rub": aff["pending_fee_rub"],
                        "operations": aff.get("operations") or [],
                        "title": f"Массовый возврат комиссии {fee_rule['error_code']}: {aff['pending_count']} операций на {aff['pending_fee_rub']:.2f} ₽",
                    },
                    requires_hitl=True,
                )
                mark("mass_refund_task", task=task, pending_count=aff["pending_count"])

    ca = d["client_action"]
    lang = str(spec.get("lang") or "ru")
    if lang not in ("ru", "en"):
        lang = "ru"
    if (refund_total or refund_dup) and ca["kind"] != "none":
        ca = {**ca, "text_ru": _refund_text(ca.get("text_ru") or "", refund_total, refund_dup, lang)}
    human_mod = (state.get("human") or {}).get("modified") or {}
    if human == "modify" and isinstance(human_mod.get("gift"), dict) and d.get("gift"):
        gift = d["gift"]
        parts: list[str] = []
        if lang == "en":
            if gift.get("points"):
                parts.append(f"{int(gift['points'])} bonus points")
            if gift.get("gift_code"):
                parts.append(f"gift {gift['gift_code']}")
            suffix = " We will also add " + " and ".join(parts) + " after the issue is resolved."
        else:
            if gift.get("points"):
                parts.append(f"{int(gift['points'])} баллов")
            if gift.get("gift_code"):
                parts.append(f"подарок {gift['gift_code']}")
            suffix = " Также начислим " + " и ".join(parts) + " после решения проблемы."
        if parts and ca["kind"] != "none":
            ca = {**ca, "text_ru": ((ca.get("text_ru") or "").rstrip(".") + suffix)[:2000]}
    if ca["kind"] != "none" and "notify_client" not in done and d.get("router_action") != "request_clarification":
        name = mask_name((client or {}).get("name"))
        summary = re.sub(r"[;,]?\s*тональность.*$", "", c.get("summary_ru") or "").strip().rstrip(".") or (
            c.get("problem_summary") or {}
        ).get("problem", "").rstrip(".")
        variables = {
            "name": name,
            "summary": summary,
            "sla_minutes": (client or {}).get("first_response_min") or 60,
            "manager": "your personal manager" if lang == "en" else "вашим персональным менеджером",
            "question": ca.get("question_ru") or "",
            "resolution": summary,
        }
        consents = (client or {}).get("consents")
        segment = (client or {}).get("segment")
        if ca["kind"] == "public_reply_and_dm":
            public_channel = str(sig.get("channel") or "social")
            public_text = await _render_client_text(
                deps,
                (ca.get("text_ru") or "").strip() or _public_fallback(client, lang),
                lang,
                "public_reply",
                public_channel,
                segment,
                variables,
            )
            pub = await wt.notify_client(
                deps.ctx,
                (client or {}).get("client_id"),
                sig["id"],
                incident_id,
                public_channel,
                "public_reply",
                variables,
                text_override=public_text,
                segment=segment,
                recipient_type="public",
                lang=lang,
            )
            mark("notify_client", notification_id=pub.get("notification_id"), public=True)
            if client:
                dm = await wt.notify_client(
                    deps.ctx,
                    client["client_id"],
                    sig["id"],
                    incident_id,
                    "chat",
                    "ack_received",
                    variables,
                    segment=client.get("segment"),
                    consents=consents,
                    lang=lang,
                )
                mark("notify_client_dm", notification_id=dm.get("notification_id"))
        else:
            message = (ca.get("text_ru") or summary or "").strip()
            if len(message) < 10:
                message = _short_ack(lang)
            message = await _render_client_text(
                deps,
                message,
                lang,
                str(ca.get("template_code") or "ack_received"),
                str(ca.get("channel") or sig.get("channel") or "chat"),
                segment,
                variables,
            )
            if len(message) < 10:
                message = _short_ack(lang)
            n = await router_tools.notify_customer(
                deps.ctx,
                str(ca.get("channel") or sig.get("channel") or "chat"),
                message[:1000],
            )
            mark("notify_client", notification_id=n.get("notification_id"))
    # --- публичная лента (ТЗ 21.2, 21.5): ответ под постом, без ПДн и обещаний, с приглашением в личный канал
    post_id = sig.get("external_post_id")
    if post_id and "feed_reply" not in done and ca["kind"] != "none":
        escalate = client is None and ca["kind"] != "public_reply_and_dm"
        feed_text = str(ca.get("text_ru") or _public_fallback(client, lang))
        if communication_lang(feed_text) != lang:
            feed_text = await _render_client_text(
                deps,
                feed_text,
                lang,
                "public_reply",
                str(sig.get("channel") or "social"),
                (client or {}).get("segment"),
                {
                    "name": mask_name((client or {}).get("name")),
                    "manager": "your personal manager" if lang == "en" else "вашим персональным менеджером",
                },
            )
        try:
            fr = await abs_tools.publish_public_reply(deps.ctx, int(post_id), feed_text, incident_id, True, escalate)
            mark(
                "feed_reply",
                post_id=post_id,
                reply_id=fr.get("reply_id"),
                latency_ms=fr.get("latency_ms"),
                status=fr.get("status"),
            )
        except Exception as exc:
            mark("feed_reply_failed", post_id=post_id, error=str(exc)[:160])
    if incident_id and d["incident_action"] == "create" and "notify_team" not in done:
        tn = await wt.notify_team(
            deps.ctx,
            d["route"]["team"],
            incident_id,
            sig["id"],
            d.get("team_notice_ru") or "",
            {
                "incident_id": incident_id,
                "title": d["title_ru"],
                "criticality": d["criticality"],
                "due": d["sla"].get("due_sim"),
                "system": c.get("system") or "—",
                "affected": (d.get("economics_preview") or {}).get("affected_count") or 1,
            },
        )
        mark("notify_team", notification_id=tn.get("notification_id"))
        for co in d["route"].get("co_teams") or []:
            await wt.notify_team(
                deps.ctx, co, incident_id, sig["id"], f"Соисполнитель: {d.get('team_notice_ru') or d['title_ru']}"
            )
    if d.get("gift") and incident_id and "gift_task" not in done:
        skip_gift_task = False
        if human == "modify" and isinstance(human_mod.get("gift"), dict):
            dup_task = await deps.ctx.fetchone(
                "select id from tasks where run_id = %s and incident_id = %s and kind = 'gift' limit 1",
                (deps.ctx.run_id, incident_id),
            )
            if dup_task:
                mark("gift_task", task_id=int(dup_task[0]), deduplicated=True)
                skip_gift_task = True
        if not skip_gift_task:
            t = await wt.create_task(
                deps.ctx,
                "gift",
                incident_id,
                (client or {}).get("client_id"),
                {"gift": d["gift"], "when": "after_resolved"},
                requires_hitl=bool(d["gift"].get("requires_hitl")),
            )
            mark("gift_task", task_id=t.get("task_id"))
    if human == "delegate" and "delegate_task" not in done:
        t = await wt.create_task(
            deps.ctx,
            "manual_review",
            incident_id,
            (client or {}).get("client_id"),
            {"reason": d.get("human_reason"), "decision": d},
            assignee="legal",
            requires_hitl=True,
        )
        mark("delegate_task", task_id=t.get("task_id"))
    if d.get("followup") and "followup" not in done and d.get("router_action") != "request_clarification":
        f = await wt.schedule_followup(
            deps.ctx,
            sig["id"],
            incident_id,
            float(d["followup"]["wake_in_sim_hours"]),
            d["followup"]["reason"],
            {"incident_id": incident_id},
        )
        mark("followup", followup_id=f.get("followup_id"))
    if client and "client_state" not in done:
        new_state = (
            "churn_intent"
            if "churn_intent" in (c.get("flags") or [])
            else "escalates"
            if d.get("escalation")
            else "complaining"
            if incident_id
            else "satisfied"
            if c["signal_type"] == "gratitude"
            else "waiting"
            if d["router_action"] == "request_clarification"
            else "calm"
        )
        if new_state != (client.get("state") or "calm"):
            await wt.set_client_state(
                deps.ctx, client["client_id"], new_state, f"agent:{c['signal_type']}", sig["id"], incident_id
            )
            mark("client_state", state=new_state)
    sig_status = (
        "awaiting_client"
        if d["router_action"] == "request_clarification"
        else "linked"
        if d["incident_action"] == "link_existing"
        else "answered"
        if ca["kind"] != "none"
        else "noise"
        if d["incident_action"] == "none" and c["signal_type"] in NO_INCIDENT_TYPES
        else "classified"
    )
    if human == "reject":
        sig_status = "closed"
    await deps.ctx.conn.execute(
        "update signals set status = %s, updated_at = now() where id = %s", (sig_status, sig["id"])
    )
    if incident_id:
        await deps.ctx.conn.execute(
            "update agent_runs set incident_id = %s where id = %s", (incident_id, deps.ctx.agent_run_id)
        )
    state["actions"] = actions
    fup = await deps.ctx.fetchone(
        "select id from followups where agent_run_id = %s and status = 'scheduled' limit 1",
        (deps.ctx.agent_run_id,),
    )
    state["current_node"] = "followup_monitor" if fup else "close"
    await deps.record_step(
        "act",
        step_status,
        {"decision": {k: d.get(k) for k in ("incident_action", "router_action", "needs_human")}, "human": human},
        {"actions": actions, "signal_status": sig_status},
        reasoning="Выполнено: " + ", ".join(a["action"] for a in actions) + ".",
    )
    return state


async def close(state: AgentState, deps: Deps) -> AgentState:
    sig, client = state["signal"], state.get("client") or {}
    d = state.get("decision") or {}
    incident_id = next((a["incident_id"] for a in state.get("actions") or [] if a.get("incident_id")), None)
    if incident_id is None:
        row = await deps.ctx.fetchone("select incident_id from agent_runs where id = %s", (deps.ctx.agent_run_id,))
        incident_id = int(row[0]) if row and row[0] else None
    verified = bool(state.get("verified"))
    step_status = "ok"
    if incident_id and not verified:
        state["outcome"] = "failed"
        state["errors"].append("close: услуга не подтверждена")
        state["current_node"] = "close"
        await deps.record_step(
            "close",
            "fallback",
            {},
            {"outcome": state["outcome"], "errors": state["errors"], "verified": False},
            reasoning="Закрытие без подтверждённой услуги запрещено.",
        )
        return state
    lang = communication_lang(sig.get("text") or "")
    if incident_id:
        ca = d.get("client_action") or {}
        channel = str(ca.get("channel") or sig.get("channel") or "chat")
        resolution_row = await deps.ctx.fetchone(
            "select resolution_summary,sla_breached from incidents where id=%s and run_id=%s",
            (incident_id, deps.ctx.run_id),
        )
        resolution = str((resolution_row[0] if resolution_row else None) or d.get("title_ru") or "")
        variables = {"name": mask_name(client.get("name")), "resolution": resolution}
        _subject, body = await wt.render_template(deps.ctx, "resolved", channel, client.get("segment"), variables, lang)
        if body and pol.forbidden_phrases(body):
            body = _short_ack(lang)
        if body:
            await wt.notify_client(
                deps.ctx,
                client.get("client_id"),
                int(sig["id"]),
                incident_id,
                channel,
                "resolved",
                variables,
                text_override=body,
                segment=client.get("segment"),
                consents=client.get("consents"),
                lang=lang,
            )
        await wt.close_incident(
            deps.ctx,
            int(incident_id),
            resolution[:2000] or "обращение закрыто",
            "closed_late" if resolution_row and resolution_row[1] else "closed_in_sla",
        )
        await deps.ctx.conn.execute(
            "update signals set status = 'closed', updated_at = now() where id = %s", (sig["id"],)
        )
    elif not incident_id:
        await deps.ctx.conn.execute(
            "update signals set status = 'closed', updated_at = now() where id = %s", (sig["id"],)
        )
    state["outcome"] = (
        "fallback_mock" if (state.get("llm_source") == "mock" and deps.profile.provider != "mock") else "completed"
    )
    state["current_node"] = "close"
    await deps.record_step(
        "close",
        step_status,
        {},
        {"outcome": state["outcome"], "errors": state["errors"], "verified": verified},
        reasoning="Проход завершён.",
    )
    return state


def _json(obj: Any) -> dict[str, Any]:
    return orjson.loads(dumps(obj))  # type: ignore[no-any-return]
