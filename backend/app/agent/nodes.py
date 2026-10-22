"""Узлы графа агента (T-056/T-059/T-060/T-061/T-076/T-210/T-212). Каждый узел: state → state, записывает agent_steps.

Принцип: LLM предлагает содержание (тексты, гипотезы), код — детерминированные поля (SLA, приоритет, маршрут по правилам,
политики HITL/эскалации) и пост-проверки согласованности. Любая ошибка LLM → fallback на правила, агент не падает."""

from __future__ import annotations

import datetime as dt
import re
import time
from dataclasses import dataclass, field
from typing import Any

import orjson

from app.agent import policies as pol
from app.agent import sla as slam
from app.agent.prompts import load as load_prompt
from app.agent.state import AgentState
from app.agent.tools import read as rt
from app.agent.tools import write as wt
from app.agent.tools.base import ToolContext, mask_name
from app.contracts.registry import deref, validate
from app.llm.base import LLMProfile, Message
from app.llm.failover import ProviderChain
from app.logging import get_logger
from app.rules.engine import check_rules
from app.sim.events import dumps

log = get_logger(__name__)

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
    tokens: dict[str, int] = field(default_factory=lambda: {"prompt": 0, "completion": 0, "latency_ms": 0})

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
        await self.ctx.conn.execute(
            "insert into agent_steps (run_id, seq, node, status, input, output, prompt, response_raw, reasoning, tool_calls, model, prompt_tokens, completion_tokens, latency_ms, started_at, finished_at) "
            "values (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, now() - make_interval(secs => %s / 1000.0), now())",
            (
                self.ctx.agent_run_id,
                seq,
                node,
                status,
                dumps(state_in),
                dumps(output),
                prompt,
                raw,
                reasoning,
                dumps(self.ctx.take_calls()),
                model,
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                latency_ms,
                latency_ms,
            ),
        )
        self.tokens["prompt"] += usage.get("prompt_tokens", 0)
        self.tokens["completion"] += usage.get("completion_tokens", 0)
        self.tokens["latency_ms"] += latency_ms
        self.steps.append({"seq": seq, "node": node, "status": status})
        await self.ctx.notify(
            "agent",
            "step",
            {
                "agent_run_id": self.ctx.agent_run_id,
                "seq": seq,
                "node": node,
                "status": status,
                "reasoning": (reasoning or "")[:300],
            },
        )


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


async def _llm(
    deps: Deps,
    task: str,
    schema_name: str,
    system_vars: dict[str, Any],
    user_text: str,
    *,
    profile: LLMProfile | None = None,
    context: str = "default",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Вызов цепочки: system = system.md + промпт задачи (с контекстом), user = текст сигнала. Возвращает (obj, meta)."""
    prompt = (
        load_prompt("system").body
        + "\n\n"
        + load_prompt(task).render(**{k: (v if isinstance(v, str) else dumps(v)) for k, v in system_vars.items()})
    )
    messages: list[Message] = [{"role": "system", "content": prompt}, {"role": "user", "content": user_text}]
    schema = deref(schema_name)
    t0 = time.perf_counter()
    res = await deps.chain.complete_structured(messages, schema, profile or deps.profile, context=context)
    obj = prune(res.obj, schema)
    meta = {
        "prompt": prompt,
        "raw": res.raw[:8000],
        "model": f"{res.provider}:{(profile or deps.profile).model}",
        "usage": res.usage.as_dict(),
        "latency_ms": int((time.perf_counter() - t0) * 1000),
        "provider": res.provider,
        "fallback_mock": res.fallback_mock,
        "error": res.error,
    }
    return obj, meta


# ---------------------------------------------------------------------------------------------------------------------
# узлы
# ---------------------------------------------------------------------------------------------------------------------
async def ingest(state: AgentState, deps: Deps) -> AgentState:
    sig = state["signal"]
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
            context="fast_path",
        )
        if meta.get("fallback_mock"):
            status = "fallback"
    except Exception as exc:  # noqa: BLE001
        status = "error"
        state["errors"].append(f"normalize: {exc}")
    # пост-проверки (T-210): согласованность sentiment/negativity, сарказм → negative, подсказки регулярок
    neg = int(obj.get("negativity") or 50)
    sentiment = obj.get("sentiment") or ("positive" if neg <= 33 else "neutral" if neg <= 66 else "negative")
    hidden = obj.get("hidden_negativity") or {}
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
    norm: dict[str, Any] = {
        "language": obj.get("language") or "ru",
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
        "confidence": float(obj.get("confidence") or 0.5),
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
        {"hints": hints},
        norm,
        prompt=meta.get("prompt"),
        raw=meta.get("raw"),
        reasoning=f"Тональность {sentiment} ({neg}/100); намерения: {', '.join(intents) or 'нет'}; сущности: {', '.join(f'{k}={v}' for k, v in ents.items()) or 'нет'}.",
        model=meta.get("model"),
        usage=meta.get("usage"),
        latency_ms=int(meta.get("latency_ms") or 0),
    )
    return state


async def identify_client(state: AgentState, deps: Deps) -> AgentState:
    sig = state["signal"]
    client = None
    how, conf = "none", 0.0
    if sig.get("client_id"):
        client = await rt.get_client_profile(deps.ctx, int(sig["client_id"]))
        how, conf = "authenticated_channel", 1.0
    else:
        ext = sig.get("external_contact") or {}
        hint = state["normalization"].get("contacts_hint") or {}
        nick = (ext.get("nick") or hint.get("nickname") or "").lstrip("@").lower()
        if nick:
            row = await deps.ctx.fetchone(
                "select id from clients where lower(coalesce(social_handles->>'vk', social_handles->>'telegram', social_handles->>'ok', '')) = %s or lower(coalesce(social_handles->>'telegram','')) = %s limit 1",
                (nick, "@" + nick),
            )
            if row:
                client = await rt.get_client_profile(deps.ctx, int(row[0]))
                how, conf = "social_handle", 0.9
        if client is None and hint.get("masked_card_last4"):
            region = (sig.get("geo") or {}).get("region_code") or ext.get("region_code")
            rows = await deps.ctx.fetchall(
                "select distinct c.id from clients c join client_products cp on cp.client_id = c.id where cp.card_last4 = %s and (%s::text is null or c.region_code = %s::text) limit 2",
                (hint["masked_card_last4"], region, region),
            )
            if len(rows) == 1:
                client = await rt.get_client_profile(deps.ctx, int(rows[0][0]))
                how, conf = "card_last4_region", 0.8
        if client is not None:
            await deps.ctx.conn.execute(
                "update signals set client_id = %s, updated_at = now() where id = %s and client_id is null",
                (client["client_id"], sig["id"]),
            )
            sig["client_id"] = client["client_id"]
    state["client"] = client
    state["context"]["identification"] = {"method": how, "confidence": conf}
    state["current_node"] = "gather_context"
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
        },
        reasoning=(
            f"Клиент #{client['client_id']} ({client['segment']}, {client['psychotype']}) идентифицирован: {how}."
            if client
            else "Клиент не идентифицирован — анонимное/публичное обращение."
        ),
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
    state["current_node"] = "classify"
    await deps.record_step(
        "check_rules",
        "ok",
        {"operations": len(ops)},
        {"matched": matched},
        reasoning=(
            f"Сработали правила: {', '.join(m['rule_code'] for m in matched)}."
            if matched
            else "Бизнес-правила не сработали."
        ),
    )
    return state


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
    elif hints.get("error_code") and (
        stype in ("tech_fault", "client_error")
        or (stype in ("tariff_terms", "info_request", "service_quality") and int(norm.get("negativity") or 0) >= 50)
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
    flags = [f for f in (c.get("flags") or []) if isinstance(f, str)]
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
    if "public_shaming" in (norm.get("intents") or []) and "public_shaming" not in flags:
        flags.append("public_shaming")
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
    if stype in ("legal_regulatory", "fraud_suspicion") and c["criticality"] != "high":
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
                    "public_shaming",
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
        {**c, "postcheck_notes": notes},
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


async def decide(state: AgentState, deps: Deps) -> AgentState:
    sig, c, norm, client, ctx = (
        state["signal"],
        state["classification"],
        state["normalization"],
        state.get("client") or {},
        state["context"],
    )
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
    sla_full = slam.sla_for(complexity, crit, deps.ctx.sim_time, deps.sla_matrix)
    # инцидент: создать / связать / не нужен
    related = ctx.get("related_incidents") or []
    link = next((i for i in related if i.get("same_error") and i.get("error_code")), None) or next(
        (i for i in related if i.get("is_clients") and i.get("incident_type") == incident_type), None
    )
    if stype in NO_INCIDENT_TYPES and "churn_intent" not in flags and not fee_rule:
        incident_action, link_id = "none", None
    elif link:
        incident_action, link_id = "link_existing", int(link["incident_id"])
    else:
        incident_action, link_id = "create", None
    # HITL / эскалация / уточнение
    gift = (
        slam.pick_gift(crit, segment, flags) if incident_action != "none" and stype not in NO_INCIDENT_TYPES else None
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
        human_reason is None
        and incident_action != "none"
        and pol.needs_clarification(c, norm, already_asked=already_asked, policies=deps.policies)
    )
    checks += [
        {
            "rule": "confidence>=threshold",
            "passed": float(c["confidence"]) >= p["confidence_threshold"],
            "note": f"{c['confidence']:.2f} vs {p['confidence_threshold']}",
        },
        {"rule": "ultra_vip_hitl", "passed": segment != "ultra_vip", "note": segment or "—"},
        {"rule": "legal_regulatory_hitl", "passed": stype != "legal_regulatory"},
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
        ok, why = pol.refund_allowed(
            float(fee_rule.get("amount_rub") or 0),
            segment,
            rule_confirmed=True,
            ident_conf=float((ctx.get("identification") or {}).get("confidence") or 0),
            class_conf=float(c["confidence"]),
            already_refunded=False,
            ctx=pctx,
            policies=deps.policies,
        )
        checks.append({"rule": "refund_autonomy", "passed": ok, "note": why})
        if not ok and human_reason is None:
            human_reason = "policy_other"
    router_action = (
        "escalate"
        if esc_reason
        else "request_clarification"
        if clarify
        else "none"
        if incident_action == "none" and not human_reason
        else "route"
    )
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
    text_ru = (ca.get("text_ru") or "").strip() or None
    bad = pol.forbidden_phrases(text_ru)
    if bad:
        checks.append({"rule": "forbidden_phrases", "passed": False, "note": ", ".join(bad)})
        text_ru = None
    else:
        checks.append({"rule": "forbidden_phrases", "passed": True})
    if text_ru:
        text_ru = wt.PII_RE.sub("****", text_ru)[:2000]
    question = (d.get("clarification_question_ru") or ca.get("question_ru") or "").strip() or None
    if clarify and not question:
        question = (
            "Уточните, пожалуйста, дату операции и сумму, о которой идёт речь, — так мы быстрее найдём её в системе."
        )
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
        "title_ru": (wt.PII_RE.sub("****", (d.get("title_ru") or c.get("summary_ru") or "Обращение клиента").strip()))[
            :160
        ],
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
        "gift": (
            {**gift, "when": "after_resolved", "requires_hitl": gift.get("privilege_code") in pol.PARTNER_PRIVILEGES}
            if gift
            else None
        ),
        "followup": (
            {"wake_in_sim_hours": 4.0, "reason": "awaiting_client"}
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
            if esc_reason
            else None
        ),
        "clarification_question_ru": question if clarify else None,
        "rationale_ru": (
            d.get("rationale_ru")
            or f"Тип {stype}, критичность {crit}, приоритет P{prio}; маршрут {team} по правилу {rule_id or 'по умолчанию'}; SLA {sla_full['fix_days']} раб. дн."
        ).strip()[:2000],
        "policy_checks": checks,
        "economics_preview": (
            {
                "affected_count": int(mass_impact),
                "rate_code": f"{stype}_{crit}",
                "potential_loss_rub": float(mass_impact) * 1500.0,
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
    res = await wt.request_human_decision(
        deps.ctx,
        sig["id"],
        None,
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


async def act(state: AgentState, deps: Deps) -> AgentState:
    """Исполнение решения через инструменты записи — идемпотентно (повторный вход не дублирует побочные эффекты)."""
    d, c, sig, client = state["decision"], state["classification"], state["signal"], state.get("client")
    done = {a["action"] for a in state["actions"]}
    actions = state["actions"]
    incident_id: int | None = next((a["incident_id"] for a in actions if a.get("incident_id")), None)
    human = (state.get("human") or {}).get("status")
    sla_full = state["context"].get("sla_full") or {}

    def mark(action: str, **kw: Any) -> None:
        actions.append({"action": action, **kw})

    if d["incident_action"] == "create" and "incident" not in done:
        spec = {
            **c,
            "incident_type": d["incident_type"],
            "title_ru": d["title_ru"],
            "complexity": d["complexity"],
            "criticality": d["criticality"],
            "priority": d["priority"],
            "team": d["route"]["team"],
            "co_teams": d["route"].get("co_teams") or [],
            "sla": {**d["sla"], **{k: sla_full.get(k) for k in ("take_due_sim", "report_due_sims")}},
            "mass_impact": (d.get("economics_preview") or {}).get("affected_count") or 1,
            "region_code": (client or {}).get("region_code") or (sig.get("geo") or {}).get("region_code"),
            "fault_id": (state["context"].get("hints") or {}).get("fault_id"),
            "problem_summary": c.get("problem_summary"),
        }
        inc = await wt.create_incident(deps.ctx, sig["id"], (client or {}).get("client_id"), spec)
        incident_id = int(inc["incident_id"])
        mark("incident", incident_id=incident_id, public_id=inc.get("public_id"))
    elif d["incident_action"] == "link_existing" and "incident" not in done and d.get("link_incident_id"):
        inc = await wt.link_signal_to_incident(deps.ctx, sig["id"], int(d["link_incident_id"]))
        incident_id = int(inc["incident_id"])
        mark("incident", incident_id=incident_id, linked=True)
    if incident_id and human in ("accept", "modify", "delegate"):
        await deps.ctx.conn.execute(
            "update human_decisions set incident_id = %s where agent_run_id = %s and incident_id is null",
            (incident_id, deps.ctx.agent_run_id),
        )
    if d.get("escalation") and d["router_action"] == "escalate" and "escalation" not in done:
        esc = await wt.escalate_to_manager(
            deps.ctx,
            sig["id"],
            incident_id,
            d["escalation"]["reason"],
            d["escalation"]["severity"],
            d["escalation"]["to_role"],
        )
        mark("escalation", escalation_id=esc.get("escalation_id"))
    ca = d["client_action"]
    if ca["kind"] != "none" and "notify_client" not in done:
        name = mask_name((client or {}).get("name"))
        summary = re.sub(r"[;,]?\s*тональность.*$", "", c.get("summary_ru") or "").strip().rstrip(".") or (
            c.get("problem_summary") or {}
        ).get("problem", "").rstrip(".")
        variables = {
            "name": name,
            "summary": summary,
            "sla_minutes": (client or {}).get("first_response_min") or 60,
            "manager": "вашим персональным менеджером",
            "question": ca.get("question_ru") or "",
            "resolution": summary,
        }
        consents = (client or {}).get("consents")
        if ca["kind"] == "public_reply_and_dm":
            pub = await wt.notify_client(
                deps.ctx,
                (client or {}).get("client_id"),
                sig["id"],
                incident_id,
                sig.get("channel") or "social",
                "public_reply",
                variables,
                text_override=ca.get("text_ru")
                or f"{name}, спасибо, что написали. Мы уже разбираемся и напишем вам в личные сообщения, чтобы уточнить детали.",
                segment=(client or {}).get("segment"),
                recipient_type="public",
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
                )
                mark("notify_client_dm", notification_id=dm.get("notification_id"))
        else:
            n = await wt.notify_client(
                deps.ctx,
                (client or {}).get("client_id"),
                sig["id"],
                incident_id,
                ca.get("channel") or sig.get("channel") or "chat",
                ca.get("template_code") or "ack_received",
                variables,
                text_override=ca.get("text_ru"),
                segment=(client or {}).get("segment"),
                consents=consents,
            )
            mark("notify_client", notification_id=n.get("notification_id"))
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
    if d.get("followup") and "followup" not in done:
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
    state["current_node"] = "close"
    await deps.record_step(
        "act",
        "ok",
        {"decision": {k: d.get(k) for k in ("incident_action", "router_action", "needs_human")}, "human": human},
        {"actions": actions, "signal_status": sig_status},
        reasoning="Выполнено: " + ", ".join(a["action"] for a in actions) + ".",
    )
    return state


async def close(state: AgentState, deps: Deps) -> AgentState:
    state["outcome"] = (
        "fallback_mock" if (state.get("llm_source") == "mock" and deps.profile.provider != "mock") else "completed"
    )
    state["current_node"] = "close"
    await deps.record_step(
        "close",
        "ok",
        {},
        {"outcome": state["outcome"], "errors": state["errors"]},
        reasoning="Проход завершён; follow-up/проверка фикса — по расписанию followups.",
    )
    return state


def _json(obj: Any) -> dict[str, Any]:
    return orjson.loads(dumps(obj))  # type: ignore[no-any-return]
