"""T-063: узлы verify, followup_monitor, close, gift и verify_service_delivered."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.agent import graph, nodes
from app.agent.state import new_state
from app.agent.tools import read as rt
from app.agent.tools import write as wt
from app.agent.tools.base import ToolContext

SIM = dt.datetime(2025, 6, 1, 12, 0, tzinfo=dt.UTC)


class _Conn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...] | None]] = []
        self.fetch_result: Any = None
        self.fetchall_result: list[Any] = []

    async def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> Any:
        self.calls.append((sql, params))
        return self

    async def fetchone(self) -> Any:
        return self.fetch_result

    async def fetchall(self) -> list[Any]:
        return self.fetchall_result

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class _Ctx(ToolContext):
    def __init__(self) -> None:
        super().__init__(_Conn(), run_id=1, agent_run_id=10, sim_time=SIM)  # type: ignore[arg-type]
        self.rows: dict[str, Any] = {}

    async def fetchone(self, sql: str, params: tuple[Any, ...] | None = None) -> Any:
        if "from followups" in sql and "scheduled" in sql:
            return self.rows.get("followup")
        if "from incidents where id" in sql and "status" in sql:
            return self.rows.get("incident_status")
        if "incident_id from agent_runs" in sql:
            return self.rows.get("agent_incident")
        if "from escalations where agent_run_id" in sql:
            return self.rows.get("escalation_dup")
        if "from tasks where incident_id" in sql:
            return self.rows.get("task_dup")
        return self.rows.get("fetchone")

    async def notify(self, *args: Any, **kwargs: Any) -> None:
        return None


def _deps(ctx: _Ctx, policies: dict[str, Any] | None = None) -> nodes.Deps:
    profile = SimpleNamespace(provider="mock")
    return nodes.Deps(ctx=ctx, chain=AsyncMock(), profile=profile, policies=policies or {})  # type: ignore[arg-type]


def _state(**extra: Any) -> dict[str, Any]:
    sig = {"id": 5, "channel": "chat", "text": "тест", "run_id": 1}
    st = new_state(1, sig, 10, "v1-test")
    st.update(extra)
    return st


@pytest.mark.asyncio
async def test_verify_service_delivered_fee_refund(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fetch(sql: str, params: tuple[Any, ...] | None = None) -> Any:
        if "from incidents" in sql:
            return ("resolved", "fee_refund", None, None, 42)
        if "ledger_entries" in sql:
            return (99, 138.0)
        return None

    ctx = _Ctx()
    monkeypatch.setattr(ctx, "fetchone", _fetch)
    monkeypatch.setattr(
        "app.agent.tools.read.abs_tools.get_account_balance",
        AsyncMock(return_value={"balance": 1000.0}),
    )
    res = await rt.verify_service_delivered(ctx, 7)
    assert res["delivered"] is True
    assert any("refund" in e for e in res["evidence"])


@pytest.mark.asyncio
async def test_verify_delivered_sets_verified_resolved_goes_gift(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _Ctx()
    ctx.rows["incident_status"] = ("fix_deployed",)
    deps = _deps(ctx)
    deps.record_step = AsyncMock()
    update_inc = AsyncMock()
    monkeypatch.setattr("app.agent.nodes.wt.update_incident", update_inc)
    monkeypatch.setattr(
        "app.agent.nodes.rt.verify_service_delivered",
        AsyncMock(return_value={"delivered": True, "evidence": ["фикс в проде"]}),
    )
    state = _state(client={"client_id": 1}, actions=[{"incident_id": 3}])
    out = await nodes.verify(state, deps)
    assert out["verified"] is True
    assert out["current_node"] == "gift"
    update_inc.assert_awaited()
    assert any(c.args[2] == "resolved" for c in update_inc.await_args_list)


@pytest.mark.asyncio
async def test_verify_without_client_still_calls_delivered_check(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _Ctx()
    ctx.rows["agent_incident"] = (3,)
    ctx.rows["incident_status"] = ("in_progress",)
    deps = _deps(ctx)
    deps.record_step = AsyncMock()
    delivered = AsyncMock(return_value={"delivered": False, "evidence": []})
    monkeypatch.setattr("app.agent.nodes.rt.verify_service_delivered", delivered)
    monkeypatch.setattr("app.agent.nodes.wt.update_incident", AsyncMock())
    monkeypatch.setattr("app.agent.nodes.wt.notify_team", AsyncMock())
    monkeypatch.setattr("app.agent.nodes.wt.schedule_followup", AsyncMock(return_value={"followup_id": 1}))
    state = _state(client=None, actions=[])
    out = await nodes.verify(state, deps)
    delivered.assert_awaited_once_with(deps.ctx, 3)
    assert out["current_node"] == "followup_monitor"
    assert out.get("reopen_count") == 1


@pytest.mark.asyncio
async def test_verify_reopen_cap_escalates_stays_followup(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _Ctx()
    ctx.rows["agent_incident"] = (3,)
    ctx.rows["incident_status"] = ("in_progress",)
    deps = _deps(ctx, policies={"verify_reopen_cap": 1})
    deps.record_step = AsyncMock()
    monkeypatch.setattr(
        "app.agent.nodes.rt.verify_service_delivered",
        AsyncMock(return_value={"delivered": False, "evidence": []}),
    )
    monkeypatch.setattr("app.agent.nodes.wt.update_incident", AsyncMock())
    monkeypatch.setattr("app.agent.nodes.wt.notify_team", AsyncMock())
    monkeypatch.setattr("app.agent.nodes.wt.schedule_followup", AsyncMock(return_value={"followup_id": 1}))
    esc = AsyncMock()
    monkeypatch.setattr("app.agent.nodes.wt.escalate_to_manager", esc)
    state = _state(client={"client_id": 1}, actions=[{"incident_id": 3}], reopen_count=0)
    out = await nodes.verify(state, deps)
    assert out["current_node"] == "followup_monitor"
    assert out.get("reopen_count") == 1
    esc.assert_awaited_once()
    assert out["current_node"] != "gift"
    assert out["current_node"] != "close"


@pytest.mark.asyncio
async def test_followup_monitor_parks_deferred(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _Ctx()
    ctx.rows["followup"] = (1, "awaiting_team", SIM + dt.timedelta(hours=4))
    deps = _deps(ctx)
    deps.record_step = AsyncMock()
    state = _state()
    out = await nodes.followup_monitor(state, deps)
    assert out["outcome"] == "deferred"
    assert any("deferred" in c[0] for c in ctx.conn.calls)


@pytest.mark.parametrize(
    "reason",
    ["promo_end", "verify_fix", "report_due"],
)
@pytest.mark.asyncio
async def test_followup_monitor_deferred_reasons_set_signal(reason: str) -> None:
    ctx = _Ctx()
    ctx.rows["followup"] = (1, reason, SIM + dt.timedelta(hours=4))
    deps = _deps(ctx)
    deps.record_step = AsyncMock()
    state = _state()
    out = await nodes.followup_monitor(state, deps)
    assert out["outcome"] == "deferred"
    assert any("deferred" in c[0] for c in ctx.conn.calls)


@pytest.mark.asyncio
async def test_followup_monitor_awaiting_client_no_signal_deferred() -> None:
    ctx = _Ctx()
    ctx.rows["followup"] = (1, "awaiting_client", SIM + dt.timedelta(hours=4))
    deps = _deps(ctx)
    deps.record_step = AsyncMock()
    state = _state()
    out = await nodes.followup_monitor(state, deps)
    assert out["outcome"] == "deferred"
    assert not any("update signals set status = 'deferred'" in c[0] for c in ctx.conn.calls)


@pytest.mark.asyncio
async def test_followup_monitor_no_row_goes_close(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _Ctx()
    ctx.rows["followup"] = None
    deps = _deps(ctx)
    deps.record_step = AsyncMock()
    state = _state()
    out = await nodes.followup_monitor(state, deps)
    assert out["current_node"] == "close"


@pytest.mark.asyncio
async def test_create_task_gift_idempotent() -> None:
    ctx = _Ctx()
    ctx.rows["task_dup"] = (99,)
    first = await wt.create_task(ctx, "gift", 3, 1, {"gift": {"gift_code": "pts"}})
    second = await wt.create_task(ctx, "gift", 3, 1, {"gift": {"gift_code": "pts"}})
    assert first["task_id"] == 99
    assert second["deduplicated"] is True
    assert second["task_id"] == 99


@pytest.mark.asyncio
async def test_gift_auto_issue_only_when_verified_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _Ctx()
    ctx.rows["incident_status"] = ("resolved",)
    deps = _deps(ctx)
    deps.record_step = AsyncMock()
    issue = AsyncMock(return_value=1)
    monkeypatch.setattr("app.agent.nodes.wt.create_task", AsyncMock(return_value={"task_id": 1}))
    monkeypatch.setattr("app.agent.nodes.giftmod.issue_automatic", issue)
    state = _state(
        client={"client_id": 1, "segment": "retail"},
        classification={"criticality": "medium", "flags": [], "signal_type": "tech_fault"},
        decision={"gift": {"gift_code": "pts", "points": 100}},
        actions=[{"incident_id": 3}],
        verified=True,
    )
    await nodes.gift(state, deps)
    issue.assert_awaited_once()

    issue.reset_mock()
    ctx.rows["incident_status"] = ("in_progress",)
    state2 = _state(
        client={"client_id": 1, "segment": "retail"},
        classification={"criticality": "medium", "flags": [], "signal_type": "tech_fault"},
        decision={"gift": {"gift_code": "pts", "points": 100}},
        actions=[{"incident_id": 3}],
        verified=True,
    )
    await nodes.gift(state2, deps)
    issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_close_blocks_without_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _Ctx()
    ctx.rows["agent_incident"] = (3,)
    deps = _deps(ctx)
    deps.record_step = AsyncMock()
    state = _state(actions=[{"action": "incident", "incident_id": 3}], verified=False)
    out = await nodes.close(state, deps)
    assert out["outcome"] == "fallback"
    deps.record_step.assert_awaited()
    assert deps.record_step.await_args.args[1] == "fallback"


@pytest.mark.asyncio
async def test_close_verified_sends_resolved_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _Ctx()
    deps = _deps(ctx)
    deps.record_step = AsyncMock()
    notify = AsyncMock()
    close_inc = AsyncMock()
    render = AsyncMock(return_value=("Спасибо за обращение", "resolved"))
    monkeypatch.setattr("app.agent.nodes.wt.notify_client", notify)
    monkeypatch.setattr("app.agent.nodes.wt.close_incident", close_inc)
    monkeypatch.setattr("app.agent.nodes.wt.render_template", render)
    state = _state(
        client={"client_id": 1, "name": "Тест Т.", "segment": "retail"},
        actions=[{"incident_id": 3}],
        verified=True,
        decision={"title_ru": "готово", "client_action": {"channel": "chat"}},
    )
    out = await nodes.close(state, deps)
    assert out["outcome"] == "completed"
    notify.assert_awaited_once()
    assert notify.await_args.args[5] == "resolved"
    close_inc.assert_awaited_once()
    assert any("signals set status = 'closed'" in c[0] for c in ctx.conn.calls)


@pytest.mark.asyncio
async def test_verify_reopen_schedules_followup(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _Ctx()
    ctx.rows["agent_incident"] = (3,)
    ctx.rows["incident_status"] = ("in_progress",)
    deps = _deps(ctx)
    deps.record_step = AsyncMock()
    monkeypatch.setattr(
        "app.agent.nodes.rt.verify_service_delivered",
        AsyncMock(return_value={"delivered": False, "evidence": ["нет фикса"]}),
    )
    monkeypatch.setattr("app.agent.nodes.wt.update_incident", AsyncMock())
    monkeypatch.setattr("app.agent.nodes.wt.notify_team", AsyncMock())
    monkeypatch.setattr("app.agent.nodes.wt.schedule_followup", AsyncMock(return_value={"followup_id": 1}))
    monkeypatch.setattr("app.agent.nodes.wt.escalate_to_manager", AsyncMock())
    state = _state(client={"client_id": 1}, actions=[{"incident_id": 3}])
    out = await nodes.verify(state, deps)
    assert out["current_node"] == "followup_monitor"
    assert out.get("reopen_count") == 1


@pytest.mark.asyncio
async def test_escalate_to_manager_dedup_updates_reason() -> None:
    ctx = _Ctx()
    ctx.rows["escalation_dup"] = (7, "ESC-1")
    out = await wt.escalate_to_manager(ctx, 5, 3, "Повторная неудачная проверка устранения", "high", "cx_lead")
    assert out["deduplicated"] is True
    assert out.get("reason_updated") is True
    assert any("update escalations set reason" in c[0] for c in ctx.conn.calls)


@pytest.mark.asyncio
async def test_wake_followups_for_incident_skips_awaiting_client() -> None:
    conn = _Conn()
    monkey_wake = AsyncMock(return_value=0)
    import app.agent.graph as gmod

    orig = gmod.wake_due_followups
    gmod.wake_due_followups = monkey_wake
    try:
        await graph.wake_followups_for_incident(
            conn,  # type: ignore[arg-type]
            incident_id=9,
            sim_time=SIM,
            chain=AsyncMock(),
            profile=AsyncMock(),
        )
    finally:
        gmod.wake_due_followups = orig
    sql, _params = conn.calls[0]
    assert "awaiting_client" in sql
    assert "distinct from" in sql.lower() or "!=" in sql or "<>" in sql
