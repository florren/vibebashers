"""T-213: фасады роутера, свёртка tool_call, согласованность router_action."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from app.agent import nodes
from app.agent.nodes import Deps, decide
from app.agent.prompts import load
from app.agent.tools import router_tools
from app.agent.tools.base import ActFrame, ToolContext, ToolError
from app.api.agent import build_decision_chain
from app.llm.base import LLMProfile, Usage
from app.llm.failover import ChainResult
from app.sim.clock import MSK

TEAMS = {
    "team_cx",
    "team_deposits",
    "team_lending",
    "team_debit",
    "team_front",
    "team_processing",
    "team_notifications",
    "team_contact_center",
    "team_promo",
    "team_antifraud",
    "team_compliance",
    "team_branch_network",
}
SIM = dt.datetime(2026, 10, 24, 12, 0, tzinfo=MSK)
SUMMARY = "Повторное списание комиссии за обслуживание карты"


class _Cursor:
    def __init__(self, row: Any = None) -> None:
        self.row = row

    async def fetchone(self) -> Any:
        return self.row

    async def fetchall(self) -> list[Any]:
        return []


class _Conn:
    def __init__(self) -> None:
        self.sql: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, sql: str, args: tuple[Any, ...] = ()) -> _Cursor:
        self.sql.append((sql, args))
        if "from teams" in sql:
            code = args[0] if args else None
            return _Cursor((code,) if code in TEAMS else None)
        return _Cursor(None)


def _ctx() -> tuple[ToolContext, _Conn]:
    conn = _Conn()
    return ToolContext(conn, run_id=1, agent_run_id=7, sim_time=SIM), conn  # type: ignore[arg-type]


def _frame(**kw: Any) -> ActFrame:
    base: dict[str, Any] = {
        "signal_id": 10,
        "client_id": 3,
        "incident_id": None,
        "link_incident_id": None,
        "spec": {
            "incident_action": "create",
            "incident_type": "tariff_terms",
            "title_ru": SUMMARY,
            "team": "team_debit",
            "priority": 2,
            "problem_summary": {"problem": SUMMARY, "severity": "high", "suggested_team": "team_debit"},
            "followup_hours": 4.0,
        },
    }
    base.update(kw)
    return ActFrame(**base)


def _install_inners(monkeypatch: pytest.MonkeyPatch, seen: dict[str, Any]) -> None:
    async def create(ctx: ToolContext, signal_id: int, client_id: int | None, spec: dict[str, Any]) -> dict[str, Any]:
        seen["create"] = spec
        ctx.calls.append({"name": "create_incident", "args": {}, "ok": True, "ms": 1, "side_effect": True})
        return {"incident_id": 12, "public_id": "INC-000012", "status": "routed", "title": spec.get("title_ru")}

    async def link(ctx: ToolContext, signal_id: int, incident_id: int, link_type: str = "linked") -> dict[str, Any]:
        seen["link"] = incident_id
        ctx.calls.append({"name": "link_signal_to_incident", "args": {}, "ok": True, "ms": 1, "side_effect": True})
        return {"incident_id": incident_id, "public_id": f"INC-{incident_id:06d}", "status": "routed"}

    async def update(
        ctx: ToolContext,
        incident_id: int,
        status: str,
        reason: str | None = None,
        fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        seen.setdefault("updates", []).append({"status": status, "fields": fields or {}})
        if status == "awaiting_human":
            seen["awaiting_human"] = True
        ctx.calls.append({"name": "update_incident", "args": {}, "ok": True, "ms": 1, "side_effect": True})
        return {"incident_id": incident_id, "status": status, "public_id": f"INC-{incident_id:06d}"}

    async def notify_client(ctx: ToolContext, *args: Any, **kwargs: Any) -> dict[str, Any]:
        seen["notify_client"] = kwargs.get("text_override")
        ctx.calls.append({"name": "notify_client", "args": {}, "ok": True, "ms": 1, "side_effect": True})
        return {"notification_id": 4, "status": "sent"}

    async def notify_team(ctx: ToolContext, team_code: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        seen.setdefault("teams", []).append(team_code)
        ctx.calls.append({"name": "notify_team", "args": {}, "ok": True, "ms": 1, "side_effect": True})
        return {"notification_id": 5}

    async def hitl(
        ctx: ToolContext,
        signal_id: int,
        incident_id: int | None,
        reason: str,
        proposal: dict[str, Any],
        options: list[dict[str, str]],
        recommendation: str,
    ) -> dict[str, Any]:
        seen["hitl"] = {"incident_id": incident_id, "reason": reason}
        ctx.calls.append({"name": "request_human_decision", "args": {}, "ok": True, "ms": 1, "side_effect": True})
        return {"human_decision_id": 91}

    async def follow(
        ctx: ToolContext,
        signal_id: int,
        incident_id: int | None,
        wake_in_sim_hours: float,
        reason: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        seen["follow_reason"] = reason
        ctx.calls.append({"name": "schedule_followup", "args": {}, "ok": True, "ms": 1, "side_effect": True})
        return {"followup_id": 8, "wake_sim": SIM + dt.timedelta(hours=wake_in_sim_hours), "reason": reason}

    async def write_esc(
        ctx: ToolContext,
        signal_id: int,
        incident_id: int | None,
        reason: str,
        severity: str,
        to_role: str = "cx_lead",
    ) -> dict[str, Any]:
        seen["write_esc"] = {"incident_id": incident_id, "severity": severity, "to_role": to_role}
        ctx.calls.append({"name": "escalate_to_manager", "args": {}, "ok": True, "ms": 1, "side_effect": True})
        return {"escalation_id": 7, "public_id": "ESC-000007"}

    monkeypatch.setattr(router_tools, "write_create_incident", create)
    monkeypatch.setattr(router_tools, "write_link_signal", link)
    monkeypatch.setattr(router_tools, "write_update_incident", update)
    monkeypatch.setattr(router_tools, "write_notify_client", notify_client)
    monkeypatch.setattr(router_tools, "write_notify_team", notify_team)
    monkeypatch.setattr(router_tools, "write_request_human", hitl)
    monkeypatch.setattr(router_tools, "write_schedule_followup", follow)
    monkeypatch.setattr(router_tools, "write_escalate_to_manager", write_esc)


async def test_facade_collapses_inner_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    _install_inners(monkeypatch, seen)
    ctx, _conn = _ctx()
    ctx.act_frame = _frame()
    result = await router_tools.route_to_department(ctx, "team_debit", 2, SUMMARY)
    assert result["ticket_id"] == "INC-000012" and result["linked"] is False
    assert len(ctx.calls) == 1
    call = ctx.calls[0]
    assert call["name"] == "route_to_department"
    assert set(call["args"]) == {"department", "priority", "summary"}
    assert "create_incident" in call["wraps"]
    assert "create_incident" not in {c["name"] for c in ctx.calls}


async def test_route_links_open_incident_and_dedup(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    _install_inners(monkeypatch, seen)
    ctx, _conn = _ctx()
    ctx.act_frame = _frame(incident_id=9)
    opened = await router_tools.route_to_department(ctx, "team_debit", 2, SUMMARY)
    assert opened["linked"] is True and opened["ticket_id"] == "INC-000009"
    assert "link_signal_to_incident" in ctx.calls[0]["wraps"]
    assert "create" not in seen

    ctx.calls.clear()
    ctx.pending_wraps.clear()
    seen.clear()
    ctx.act_frame = _frame(link_incident_id=15)
    linked = await router_tools.route_to_department(ctx, "team_debit", 2, SUMMARY)
    assert linked["linked"] is True
    assert seen["link"] == 15
    assert "link_signal_to_incident" in ctx.calls[0]["wraps"]


async def test_unknown_department_is_tool_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_inners(monkeypatch, {})
    ctx, _conn = _ctx()
    ctx.act_frame = _frame()
    with pytest.raises(ToolError):
        await router_tools.route_to_department(ctx, "not_a_team", 2, SUMMARY)


async def test_escalation_hitl_does_not_await_human(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    _install_inners(monkeypatch, seen)
    ctx, conn = _ctx()
    ctx.act_frame = _frame(incident_id=12)
    result = await router_tools.escalate_to_manager(ctx, "повторная жалоба с угрозой ухода", "critical", "cx_lead")
    assert result["public_id"] == "ESC-000007" and result["hitl_item_id"] == 91
    assert seen["hitl"]["incident_id"] is None
    assert "team_cx" in seen["teams"]
    assert "request_human_decision" in ctx.calls[0]["wraps"]
    assert "notify_team" in ctx.calls[0]["wraps"]
    assert not seen.get("awaiting_human")
    assert any("human_decision_id" in sql for sql, _args in conn.sql)
    assert any("human_decisions" in sql and args[0] == 12 for sql, args in conn.sql)


async def test_clarification_skips_route_and_sets_status(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    _install_inners(monkeypatch, seen)
    routed: list[str] = []

    async def boom(*_a: Any, **_k: Any) -> dict[str, Any]:
        routed.append("route_to_department")
        return {}

    monkeypatch.setattr(router_tools, "route_to_department", boom)
    ctx, _conn = _ctx()
    ctx.act_frame = _frame()
    result = await router_tools.request_clarification(ctx, "Уточните, пожалуйста, дату и сумму операции.", "chat")
    assert routed == []
    assert result["notification_id"] == 4
    assert seen["updates"][-1]["fields"]["routing_status"] == "clarification"
    assert seen["follow_reason"] == "awaiting_client"
    assert "create_incident" in ctx.calls[0]["wraps"]
    assert ctx.calls[0]["name"] == "request_clarification"


async def test_notify_customer_forbidden_phrase(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_inners(monkeypatch, {})
    ctx, _conn = _ctx()
    ctx.act_frame = _frame()
    with pytest.raises(ToolError):
        await router_tools.notify_customer(ctx, "chat", "Гарантируем возврат средств клиенту сегодня")


def _decision(action: str, **over: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "incident_action": "none" if action == "none" else "create",
        "link_incident_id": None,
        "incident_type": None if action == "none" else "tariff_terms",
        "title_ru": SUMMARY,
        "complexity": "medium",
        "criticality": "high",
        "priority": 2,
        "sla": {"fix_days": 3, "due_sim": "2026-10-27T18:00:00+03:00", "take_hours": 4},
        "route": {"team": "team_debit", "co_teams": [], "rule_id": None},
        "client_action": {
            "kind": "none" if action == "none" else "acknowledge",
            "channel": "chat",
            "template_code": "ack_received",
            "text_ru": "Мы уже разбираемся с вашим обращением и вернёмся с ответом.",
            "question_ru": "Уточните, пожалуйста, дату и сумму операции.",
            "promise_check": True,
        },
        "team_notice_ru": "Проверьте списание комиссии по карте клиента.",
        "gift": None,
        "followup": None
        if action == "none"
        else {
            "wake_in_sim_hours": 4.0 if action == "request_clarification" else 2.0,
            "reason": "awaiting_client" if action == "request_clarification" else "awaiting_team",
        },
        "needs_human": False,
        "human_reason": None,
        "router_action": action,
        "escalation": {"reason": "critical_severity", "severity": "critical", "to_role": "cx_lead"}
        if action == "escalate"
        else None,
        "clarification_question_ru": "Уточните, пожалуйста, дату и сумму операции."
        if action == "request_clarification"
        else None,
        "policy_checks": [],
        "rationale_ru": "Маршрут выбран по типу обращения и политике эскалации.",
    }
    d.update(over)
    return d


def _state(action: str, **over: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "signal": {"id": 10, "channel": "chat", "text": "Списали комиссию", "geo": {}},
        "client": {
            "client_id": 3,
            "name": "Анна Тестова",
            "segment": "mass",
            "state": "calm",
            "region_code": "77",
        },
        "context": {},
        "classification": {
            "signal_type": "tariff_terms",
            "flags": [],
            "summary_ru": "Списали комиссию за оплату картой",
            "problem_summary": {"problem": SUMMARY, "severity": "high", "suggested_team": "team_debit"},
            "error_code": None,
        },
        "decision": _decision(action),
        "actions": [],
        "errors": [],
        "human": None,
    }
    state.update(over)
    return state


def _deps(ctx: ToolContext) -> Deps:
    profile = LLMProfile(code="mock", provider="mock", model="mock")
    return Deps(ctx=ctx, chain=object(), profile=profile, policies={})  # type: ignore[arg-type]


def _patch_node_side_effects(monkeypatch: pytest.MonkeyPatch, seen: dict[str, Any]) -> None:
    async def notify_team(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {"notification_id": 5}

    async def schedule(*_a: Any, **_k: Any) -> dict[str, Any]:
        seen["node_followup"] = True
        return {"followup_id": 1, "wake_sim": SIM}

    async def hitl(
        _ctx: ToolContext,
        signal_id: int,
        incident_id: int | None,
        reason: str,
        *_a: Any,
    ) -> dict[str, Any]:
        seen.setdefault("node_hitl", []).append({"incident_id": incident_id, "reason": reason})
        return {"human_decision_id": 3}

    async def task(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {"task_id": 1}

    monkeypatch.setattr(nodes.wt, "notify_team", notify_team)
    monkeypatch.setattr(nodes.wt, "schedule_followup", schedule)
    monkeypatch.setattr(nodes.wt, "request_human_decision", hitl)
    monkeypatch.setattr(nodes.wt, "create_task", task)
    monkeypatch.setattr(nodes.wt, "notify_client", notify_team)


async def _run_act(monkeypatch: pytest.MonkeyPatch, action: str, **state_over: Any) -> tuple[dict[str, Any], list[str]]:
    seen: dict[str, Any] = state_over.pop("_seen", {})
    _install_inners(monkeypatch, seen)
    _patch_node_side_effects(monkeypatch, seen)
    ctx, _conn = _ctx()
    deps = _deps(ctx)

    async def _record(node: str, status: str, *_a: Any, **_k: Any) -> None:
        deps.steps.append({"node": node, "status": status})

    deps.record_step = _record  # type: ignore[method-assign]
    state = _state(action, **state_over)
    out = await nodes.act(state, deps)  # type: ignore[arg-type]
    names = [c["name"] for c in ctx.calls if c.get("ok") is not False]
    out["_seen"] = seen
    out["_status"] = deps.steps[-1]["status"]
    out["_names"] = names
    return out, names


@pytest.mark.parametrize(
    ("action", "present", "absent"),
    [
        ("route", ["route_to_department"], ["escalate_to_manager", "request_clarification"]),
        ("escalate", ["route_to_department", "escalate_to_manager"], ["request_clarification"]),
        ("request_clarification", ["request_clarification"], ["route_to_department", "escalate_to_manager"]),
        ("none", [], ["route_to_department", "escalate_to_manager", "request_clarification"]),
    ],
)
async def test_router_action_matches_facades(
    monkeypatch: pytest.MonkeyPatch, action: str, present: list[str], absent: list[str]
) -> None:
    out, names = await _run_act(monkeypatch, action)
    for tool in present:
        assert tool in names
    for tool in absent:
        assert tool not in names
    if action == "escalate":
        assert names.index("route_to_department") < names.index("escalate_to_manager")
    assert out["_status"] == "ok"
    assert any(c["rule"] == "router_action_tools" and c["passed"] for c in out["decision"]["policy_checks"])


async def test_scenario_11_clarification_then_route_and_escalate(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    first, names1 = await _run_act(monkeypatch, "request_clarification", _seen=seen)
    assert "request_clarification" in names1 and "route_to_department" not in names1
    assert seen["updates"][-1]["fields"]["routing_status"] == "clarification"
    assert not seen.get("node_followup")
    assert first["_status"] == "ok"

    seen2: dict[str, Any] = {}
    _second, names2 = await _run_act(
        monkeypatch,
        "escalate",
        _seen=seen2,
        decision=_decision("escalate"),
    )
    assert names2.index("route_to_department") < names2.index("escalate_to_manager")
    assert not seen2.get("awaiting_human")
    hitl = seen2.get("hitl") or {}
    assert hitl.get("incident_id") is None


async def test_router_mismatch_retries_once_then_policy_other(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    calls = {"n": 0}

    async def silent(ctx: ToolContext, department: str, priority: int, summary: str) -> dict[str, Any]:
        calls["n"] += 1
        return {"ticket_id": "INC-000001", "incident_id": 1, "linked": False, "department": department}

    _install_inners(monkeypatch, seen)
    _patch_node_side_effects(monkeypatch, seen)
    monkeypatch.setattr(nodes.router_tools, "route_to_department", silent)
    ctx, _conn = _ctx()
    deps = _deps(ctx)

    async def _record(node: str, status: str, *_a: Any, **_k: Any) -> None:
        deps.steps.append({"node": node, "status": status})

    deps.record_step = _record  # type: ignore[method-assign]
    out = await nodes.act(_state("route"), deps)  # type: ignore[arg-type]
    assert calls["n"] == 2
    assert deps.steps[-1]["status"] == "error"
    assert seen["node_hitl"][-1]["reason"] == "policy_other"
    assert seen["node_hitl"][-1]["incident_id"] is None
    assert any(c["rule"] == "router_action_tools" and c["passed"] is False for c in out["decision"]["policy_checks"])


class _Chain:
    async def complete_structured(self, *_a: Any, **_k: Any) -> ChainResult:
        return ChainResult(obj={}, usage=Usage(source="mock"), raw="{}", provider="mock")


def _decide_deps() -> Deps:
    ctx, _conn = _ctx()
    return Deps(
        ctx=ctx,
        chain=_Chain(),  # type: ignore[arg-type]
        profile=LLMProfile(code="mock", provider="mock", model="mock"),
        policies={},
        teams=["team_cx", "team_debit"],
    )


def _decide_state(*, already: bool, signals_7d: int = 2) -> dict[str, Any]:
    return {
        "signal": {
            "id": 10,
            "channel": "chat",
            "text": "Ничего не работает, разберитесь уже",
            "parent_signal_id": 4 if already else None,
            "geo": {},
        },
        "client": {"client_id": 3, "segment": "mass", "name": "Анна Тестова", "region_code": "77"},
        "context": {
            "client_history": {"signals_7d": signals_7d, "last_types": []},
            "similar_signals": [],
            "related_incidents": [],
            "rules_matched": [],
        },
        "normalization": {"negativity": 10, "entities": {}, "intents": [], "hidden_negativity": {}},
        "classification": {
            "signal_type": "tech_fault",
            "confidence": 0.9,
            "criticality": "medium",
            "flags": [],
            "sentiment": "neutral",
            "summary_ru": "Сбой без суммы и продукта в обращении",
            "problem_summary": {
                "problem": "Сбой без суммы и продукта в обращении",
                "severity": "high",
                "suggested_team": "team_cx",
            },
            "entities": {},
        },
        "errors": [],
        "decision": {},
    }


async def test_decide_clarification_precedes_escalation() -> None:
    deps = _decide_deps()
    first = await decide(_decide_state(already=False), deps)  # type: ignore[arg-type]
    assert first["decision"]["router_action"] == "request_clarification"
    assert first["decision"]["escalation"] is None

    second = await decide(_decide_state(already=True), deps)  # type: ignore[arg-type]
    assert second["decision"]["router_action"] == "escalate"
    assert second["decision"]["escalation"]["reason"]


async def test_decide_sarcasm_clarify_keeps_escalation_for_cx_lead() -> None:
    state = _decide_state(already=False, signals_7d=2)
    state["signal"]["channel"] = "social"
    state["classification"]["flags"] = ["sarcasm", "repeat"]
    state["classification"]["sentiment"] = "negative"
    state["normalization"]["entities"] = {}
    state["classification"]["entities"] = {}
    out = await decide(state, _decide_deps())  # type: ignore[arg-type]
    assert out["decision"]["router_action"] == "request_clarification"
    esc = out["decision"]["escalation"]
    assert esc is not None
    assert esc["to_role"] == "cx_lead"
    assert esc["reason"]


def _blocked_refund_state(*, confidence: float) -> dict[str, Any]:
    """tariff_terms без сущностей: тип совпадает с правилом, уверенность не становится конфликтом."""
    state = _decide_state(already=False, signals_7d=0)
    state["classification"]["signal_type"] = "tariff_terms"
    state["classification"]["confidence"] = confidence
    state["classification"]["entities"] = {}
    state["normalization"]["entities"] = {}
    state["context"]["identification"] = {"confidence": 0.5}
    state["context"]["rules_matched"] = [
        {"rule_code": "RULE-QR-FEE-001", "action": "refund_fee", "amount_rub": 49.0, "operation_ids": []}
    ]
    return state


def _known_fault_state(*, confidence: float, segment: str = "mass", already: bool = False) -> dict[str, Any]:
    state = _decide_state(already=already, signals_7d=0)
    state["classification"]["confidence"] = confidence
    state["classification"]["product"] = "debit_card"
    state["normalization"]["entities"] = {"product": "debit_card"}
    state["client"]["segment"] = segment
    return state


async def test_gratitude_ultra_vip_router_action_stays_none(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _known_fault_state(confidence=0.9, segment="ultra_vip")
    state["classification"]["signal_type"] = "gratitude"
    state["signal"]["text"] = "Спасибо, что разобрались с картой"
    decided = await decide(state, _decide_deps())  # type: ignore[arg-type]
    assert decided["decision"]["incident_action"] == "none"
    assert decided["decision"]["router_action"] == "none"
    assert decided["decision"]["needs_human"] is True
    assert decided["decision"]["human_reason"] == "ultra_vip"
    assert decided["current_node"] == "wait_human"

    _out, names = await _run_act(
        monkeypatch,
        "none",
        decision=decided["decision"],
        classification=decided["classification"],
        signal=decided["signal"],
        client=decided["client"],
    )
    assert "route_to_department" not in names


async def test_route_without_incident_is_not_a_match(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    out, names = await _run_act(
        monkeypatch,
        "route",
        _seen=seen,
        decision=_decision("route", incident_action="none", incident_type=None),
    )
    assert "route_to_department" not in names
    assert out["_status"] == "error"
    assert seen["node_hitl"][-1]["reason"] == "policy_other"
    assert any(c["rule"] == "router_action_tools" and c["passed"] is False for c in out["decision"]["policy_checks"])


async def test_low_confidence_alone_requests_clarification() -> None:
    deps = _decide_deps()
    first = await decide(_known_fault_state(confidence=0.59), deps)  # type: ignore[arg-type]
    assert first["decision"]["router_action"] == "request_clarification"
    assert first["decision"]["escalation"] is None
    assert first["decision"]["needs_human"] is False
    assert first["current_node"] == "act"

    vip = await decide(_known_fault_state(confidence=0.59, segment="ultra_vip"), deps)  # type: ignore[arg-type]
    assert vip["decision"]["router_action"] != "request_clarification"
    assert vip["decision"]["human_reason"] == "ultra_vip"
    assert vip["decision"]["needs_human"] is True
    assert vip["current_node"] == "wait_human"

    again = await decide(_known_fault_state(confidence=0.59, already=True), deps)  # type: ignore[arg-type]
    assert again["decision"]["router_action"] != "request_clarification"
    assert again["decision"]["needs_human"] is True
    assert again["current_node"] == "wait_human"


async def test_blocked_refund_stays_hitl_instead_of_clarification() -> None:
    deps = _decide_deps()
    high = await decide(_blocked_refund_state(confidence=0.9), deps)  # type: ignore[arg-type]
    assert high["decision"]["router_action"] != "request_clarification"
    assert high["decision"]["human_reason"] == "policy_other"
    assert high["decision"]["needs_human"] is True
    assert high["current_node"] == "wait_human"

    low = await decide(_blocked_refund_state(confidence=0.59), deps)  # type: ignore[arg-type]
    assert low["decision"]["router_action"] != "request_clarification"
    assert low["decision"]["human_reason"] == "policy_other"
    assert low["decision"]["needs_human"] is True
    assert low["current_node"] == "wait_human"
    assert low["current_node"] != "act"

    control = await decide(_known_fault_state(confidence=0.59), deps)  # type: ignore[arg-type]
    assert control["context"]["rules_matched"] == []
    assert control["decision"]["router_action"] == "request_clarification"
    assert control["decision"]["needs_human"] is False
    assert control["current_node"] == "act"


async def test_second_pass_critical_escalates_after_accept(monkeypatch: pytest.MonkeyPatch) -> None:
    deps = _decide_deps()
    # Нехватка сущностей, severity не critical: первый проход — уточнение, без другого HITL.
    first = await decide(_decide_state(already=False, signals_7d=0), deps)  # type: ignore[arg-type]
    assert first["decision"]["router_action"] == "request_clarification"
    assert first["decision"]["needs_human"] is False
    assert first["current_node"] == "act"

    # decide прибавляет текущий сигнал: 1 + 1 = 2 < порога 3, причина эскалации — critical.
    second_in = _decide_state(already=True, signals_7d=1)
    second_in["classification"]["problem_summary"]["severity"] = "critical"
    second = await decide(second_in, deps)  # type: ignore[arg-type]
    assert second["decision"]["router_action"] == "escalate"
    assert second["decision"]["escalation"]["severity"] == "critical"
    assert second["decision"]["escalation"]["reason"] == "critical_severity"
    assert second["decision"]["needs_human"] is True
    assert second["decision"]["human_reason"] == "policy_other"
    assert second["current_node"] == "wait_human"

    seen: dict[str, Any] = {}
    _out, names = await _run_act(
        monkeypatch,
        "escalate",
        _seen=seen,
        decision=second["decision"],
        classification=second["classification"],
        human={"status": "accept"},
    )
    assert names.index("route_to_department") < names.index("escalate_to_manager")
    assert seen["write_esc"]["severity"] == "critical"
    assert not seen.get("awaiting_human")
    assert all(item["status"] != "awaiting_human" for item in seen.get("updates") or [])


def test_decide_prompt_lists_facades() -> None:
    prompt = load("decide")
    assert prompt.version == "v1.3"
    for name in (
        "route_to_product_team",
        "route_to_department",
        "notify_customer",
        "escalate_to_manager",
        "request_clarification",
    ):
        assert name in prompt.body


class _DictCursor:
    def __init__(self, row: dict[str, Any] | None = None, rows: list[dict[str, Any]] | None = None) -> None:
        self.row = row
        self.rows = rows or []

    async def fetchone(self) -> dict[str, Any] | None:
        return self.row

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _DictConn:
    async def execute(self, sql: str, args: tuple[Any, ...] = ()) -> _DictCursor:
        if "agent_steps" in sql:
            return _DictCursor(
                rows=[
                    {
                        "seq": 1,
                        "node": "act",
                        "status": "ok",
                        "reasoning": "маршрут в команду",
                        "tool_calls": [
                            {
                                "name": "route_to_department",
                                "args": {"department": "team_debit", "summary": SUMMARY},
                                "ok": True,
                                "ms": 5,
                                "side_effect": True,
                                "wraps": ["create_incident"],
                                "result": {"ticket_id": "INC-000012"},
                            },
                            {
                                "name": "notify_team",
                                "args": {"team_code": "team_debit"},
                                "ok": True,
                                "ms": 2,
                                "side_effect": True,
                                "result": {"notification_id": 1},
                            },
                        ],
                        "output": {},
                        "latency_ms": 5,
                    }
                ]
            )
        return _DictCursor(
            row={
                "id": 7,
                "signal_id": 10,
                "incident_id": 12,
                "outcome": "completed",
                "ticket_id": "INC-000012",
                "router_action": "route",
                "provider": "mock",
            }
        )


async def test_decision_chain_keeps_facade_wraps() -> None:
    chain = await build_decision_chain(_DictConn(), 7)  # type: ignore[arg-type]
    assert chain is not None
    facade, plain = chain["steps"]
    assert facade["tool"] == "route_to_department"
    assert facade["wraps"] == ["create_incident"]
    assert plain["wraps"] == ["side_effect"]


async def test_en_spec_keeps_ack_received_and_passes_lang(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def notify_client(ctx: ToolContext, *args: Any, **kwargs: Any) -> dict[str, Any]:
        seen["template"] = args[4]
        seen["lang"] = kwargs.get("lang", "ru")
        return {"notification_id": 4, "status": "sent"}

    monkeypatch.setattr(router_tools, "write_notify_client", notify_client)
    ctx, _conn = _ctx()
    ctx.act_frame = _frame()
    await router_tools.notify_customer(ctx, "chat", "Мы уже разбираемся с вашим обращением.")
    assert seen["template"] == "ack_received"
    assert seen["lang"] == "ru"

    spec = dict(_frame().spec)
    spec["lang"] = "en"
    ctx.act_frame = _frame(spec=spec)
    await router_tools.notify_customer(ctx, "chat", "We are already looking into the card fee.")
    assert seen["template"] == "ack_received"
    assert seen["lang"] == "en"


@pytest.mark.parametrize("kind", ["tech_fault", "info_request", "tariff_terms", "fraud_suspicion"])
async def test_anonymous_is_classified_and_routed_without_identity_gate(kind: str) -> None:
    state = _decide_state(already=False, signals_7d=0)
    state["client"] = None
    state["classification"]["signal_type"] = kind
    result = await decide(state, _decide_deps())  # type: ignore[arg-type]
    decision = result["decision"]
    assert decision["incident_action"] == "create"
    assert decision["router_action"] == "route"
    assert decision["clarification_question_ru"] is None
    assert decision["client_action"]["kind"] == "acknowledge"
    assert "О решении сообщим дополнительно" in decision["client_action"]["text_ru"]
    assert decision["followup"]["reason"] == "awaiting_team"
    assert decision["gift"] is None
    assert "potential_loss_rub" not in decision["economics_preview"]


async def test_anonymous_low_confidence_keeps_hitl_but_accepts_and_routes_before_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _decide_state(already=False, signals_7d=0)
    state["client"] = None
    state["classification"]["confidence"] = 0.4
    state["actions"] = []
    state = await decide(state, _decide_deps())  # type: ignore[arg-type]
    assert state["decision"]["needs_human"] and state["decision"]["human_reason"] == "low_confidence"
    seen: dict[str, Any] = {}
    _install_inners(monkeypatch, seen)
    _patch_node_side_effects(monkeypatch, seen)
    deps = _decide_deps()

    async def record(*_args: Any, **_kwargs: Any) -> None:
        return None

    deps.record_step = record  # type: ignore[method-assign]
    result = await nodes.wait_human(state, deps)  # type: ignore[arg-type]
    assert result["outcome"] == "awaiting_human"
    assert seen["create"]["team"] == "team_cx"
    assert seen["node_hitl"][-1]["incident_id"] == 12
    assert "О решении сообщим дополнительно" in seen["notify_client"]
    assert not any(c["name"] in {"refund_fee", "create_task", "request_clarification"} for c in deps.ctx.calls)


@pytest.mark.parametrize(
    ("kind", "reason"), [("legal_regulatory", "legal_regulatory"), ("fraud_suspicion", "fraud_amount")]
)
async def test_anonymous_handoff_does_not_remove_protected_human_reasons(kind: str, reason: str) -> None:
    state = _decide_state(already=False, signals_7d=0)
    state["client"] = None
    state["classification"]["signal_type"] = kind
    state["classification"]["entities"] = {"amount_rub": 100000}
    state["normalization"]["entities"] = {"amount_rub": 100000}
    result = await decide(state, _decide_deps())  # type: ignore[arg-type]
    assert result["decision"]["needs_human"]
    assert result["decision"]["human_reason"] == reason
    assert result["decision"]["client_action"]["kind"] == "acknowledge"


async def test_anonymous_known_product_uses_the_existing_product_route() -> None:
    state = _decide_state(already=False, signals_7d=0)
    state["client"] = None
    state["classification"]["product"] = "deposit"
    deps = _decide_deps()
    deps.teams.append("team_deposits")
    deps.routing_rules = [(1, {"product": "deposit"}, ["team_deposits"])]
    result = await decide(state, deps)  # type: ignore[arg-type]
    assert result["decision"]["route"]["team"] == "team_deposits"
    assert result["decision"]["router_action"] == "route"
