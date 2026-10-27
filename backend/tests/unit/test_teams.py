"""T-036: эмулятор команд, SLA, регрессии, валидация fault.regression."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from app.agent.tools.base import ToolContext
from app.contracts.registry import validate
from app.sim.clock import MSK, add_working_days, add_working_hours
from app.sim.events import EventBus
from app.sim.rng import SimRng
from app.sim.teams import PII_RE, TeamEmulator, _plan_blob


class _World:
    def __init__(self) -> None:
        self.active_faults: list[dict[str, Any]] = []


class _Cursor:
    def __init__(self, rows: list[tuple[Any, ...]] | tuple[Any, ...] | None) -> None:
        if rows is None:
            self._rows: list[tuple[Any, ...]] = []
        elif isinstance(rows, tuple):
            self._rows = [rows]
        else:
            self._rows = rows

    async def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class MemStore:
    def __init__(self) -> None:
        self.incidents: dict[int, dict[str, Any]] = {}
        self.team_actions: list[dict[str, Any]] = []
        self.artifacts: list[dict[str, Any]] = []
        self.faults: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.history: list[tuple[Any, ...]] = []
        self._next_id = {"team_actions": 1, "artifacts": 1, "faults": 1}
        self.teams = {
            "team_deposits": {
                "take_hours": [1, 4],
                "fix_days_factor": 0.8,
                "p_clarify": 0.0,
                "p_sla_breach": 0.0,
                "p_regression": 0.12,
            }
        }
        self.error_codes = {
            "DEP-TIMEOUT-503": {"system": "sub_deposits", "product": "deposit"},
            "PROMO-RATE-MISMATCH": {"system": "promo_engine", "product": "deposit"},
            "PROC-QR-FEE-CHARGED": {"system": "processing", "product": "debit_card"},
        }

    def add_incident(self, **fields: Any) -> int:
        iid = int(fields.pop("id", len(self.incidents) + 1))
        base = {
            "id": iid,
            "status": "routed",
            "team_code": "team_deposits",
            "created_sim": dt.datetime(2026, 11, 9, 9, 0, tzinfo=MSK),
            "take_due_sim": add_working_hours(dt.datetime(2026, 11, 9, 9, 0, tzinfo=MSK), 8),
            "sla_due_sim": add_working_days(dt.datetime(2026, 11, 9, 9, 0, tzinfo=MSK), 10),
            "report_due_sims": [
                add_working_days(dt.datetime(2026, 11, 9, 9, 0, tzinfo=MSK), 3),
                add_working_days(dt.datetime(2026, 11, 9, 9, 0, tzinfo=MSK), 6),
                add_working_days(dt.datetime(2026, 11, 9, 9, 0, tzinfo=MSK), 9),
            ],
            "complexity": "hard",
            "criticality": "low",
            "title": "Сбой открытия вклада по промо",
            "system_code": "sub_deposits",
            "product_code": "deposit",
            "error_code": "DEP-TIMEOUT-503",
            "agent_run_id": 0,
            "run_id": 1,
        }
        base.update(fields)
        self.incidents[iid] = base
        return iid


class MemConn:
    def __init__(self, store: MemStore) -> None:
        self.store = store

    async def execute(self, sql: str, args: tuple[Any, ...] = ()) -> _Cursor:
        s = " ".join(sql.lower().split())
        st = self.store
        if "from error_codes" in s:
            return _Cursor([(c, m["system"], m["product"]) for c, m in st.error_codes.items()])
        if "from teams" in s and "speed_profile" in s:
            return _Cursor([(c, p) for c, p in st.teams.items()])
        if "from team_actions where run_id" in s:
            rows = sorted(
                (
                    a["id"],
                    a["incident_id"],
                    a["action"],
                    a.get("payload", {}),
                    a["action_sim"],
                )
                for a in st.team_actions
                if a.get("run_id") == args[0]
            )
            return _Cursor(rows)
        if "from faults where run_id" in s and "caused_by_incident_id is not null" in s:
            return _Cursor([(f["id"], f["caused_by_incident_id"]) for f in st.faults if f.get("caused_by_incident_id")])
        if "from incidents where run_id" in s and "status = any" in s:
            allowed = set(args[1])
            rows = []
            for inc in st.incidents.values():
                if inc["run_id"] == args[0] and inc["status"] in allowed:
                    rows.append(
                        (
                            inc["id"],
                            inc["status"],
                            inc["team_code"],
                            inc["created_sim"],
                            inc["take_due_sim"],
                            inc["sla_due_sim"],
                            inc["report_due_sims"],
                            inc["complexity"],
                            inc["criticality"],
                            inc["title"],
                            inc["system_code"],
                            inc["product_code"],
                            inc["error_code"],
                            inc["agent_run_id"],
                        )
                    )
            return _Cursor(rows)
        if "select status from incidents where id" in s:
            inc = st.incidents[int(args[0])]
            return _Cursor((inc["status"],))
        if s.startswith("update incidents set status"):
            iid = int(args[-1])
            inc = st.incidents[iid]
            new_status = str(args[0])
            inc["status"] = new_status
            if "taken_sim" in s:
                inc["taken_sim"] = args[1] if len(args) > 2 else inc.get("taken_sim")
            if new_status == "closed":
                inc["closed_sim"] = args[1] if "closed_sim" in s else inc.get("closed_sim")
            if new_status == "resolved":
                inc["resolved_sim"] = args[1]
            return _Cursor(None)
        if "insert into incident_status_history" in s:
            st.history.append(args)
            return _Cursor(None)
        if "insert into incident_artifacts" in s:
            aid = st._next_id["artifacts"]
            st._next_id["artifacts"] += 1
            st.artifacts.append({"id": aid, "kind": args[2], "body_md": args[4], "meta": args[5]})
            return _Cursor((aid,))
        if "insert into team_actions" in s:
            tid = st._next_id["team_actions"]
            st._next_id["team_actions"] += 1
            st.team_actions.append(
                {
                    "id": tid,
                    "run_id": args[0],
                    "incident_id": args[1],
                    "action": args[3],
                    "payload": __import__("orjson").loads(args[4]) if isinstance(args[4], str) else args[4],
                    "action_sim": args[5],
                }
            )
            return _Cursor((tid,))
        if "insert into faults" in s:
            fid = st._next_id["faults"]
            st._next_id["faults"] += 1
            st.faults.append(
                {
                    "id": fid,
                    "run_id": args[0],
                    "system_code": args[1],
                    "error_code": args[2],
                    "started_sim": args[3],
                    "caused_by_incident_id": args[4],
                }
            )
            return _Cursor((fid,))
        if "select 1 from faults where run_id" in s:
            for f in st.faults:
                if f["run_id"] == args[0] and f.get("caused_by_incident_id") == args[1]:
                    return _Cursor((1,))
            return _Cursor(None)
        if "select subject, body from notification_templates" in s:
            return _Cursor(None)
        if "select pg_notify" in s:
            return _Cursor(None)
        if "insert into sim_events" in s:
            return _Cursor((len(st.events) + 1,))
        raise AssertionError(f"unexpected sql: {sql[:120]}")


class RecordingBus:
    strict = True

    def __init__(self, store: MemStore) -> None:
        self.store = store

    async def emit(
        self, run_id: int, event_type: str, payload: dict[str, Any], sim_time: dt.datetime, **kw: Any
    ) -> Any:
        payload = {**payload, "event_type": event_type}
        if event_type == "fault.regression":
            assert validate(payload, "sim/fault_regression") == []
        elif event_type.startswith("team."):
            assert validate(payload, "sim/team_action") == []
        self.store.events.append({"event_type": event_type, "payload": payload, "sim_time": sim_time})
        return __import__("uuid").uuid4()


def _emu(store: MemStore, seed: int = 42) -> tuple[TeamEmulator, MemConn, RecordingBus]:
    conn = MemConn(store)
    bus = RecordingBus(store)
    emu = TeamEmulator(SimRng(seed), conn, bus, 1)  # type: ignore[arg-type]
    emu.error_codes = store.error_codes
    emu._team_profiles = store.teams
    return emu, conn, bus


async def _run_until_closed(emu: TeamEmulator, store: MemStore, end: dt.datetime) -> None:
    world = _World()
    t = dt.datetime(2026, 11, 9, 8, 0, tzinfo=MSK)
    for _ in range(400):
        await emu.tick(t, world)
        if store.incidents[1]["status"] == "closed":
            break
        t += dt.timedelta(hours=6)
        if t > end + dt.timedelta(days=5):
            break


@pytest.mark.asyncio
async def test_hard_low_full_path_no_clarify_no_breach(monkeypatch: pytest.MonkeyPatch) -> None:
    store = MemStore()
    iid = store.add_incident()
    updates: list[str] = []

    async def track(ctx: ToolContext, incident_id: int, status: str, reason: str | None = None, fields=None):
        updates.append(status)
        inc = store.incidents[incident_id]
        inc["status"] = status
        if status == "in_progress":
            inc["taken_sim"] = ctx.sim_time
        if status == "closed":
            inc["closed_sim"] = ctx.sim_time
        if status == "resolved":
            inc["resolved_sim"] = ctx.sim_time
        return {"incident_id": incident_id, "status": status}

    monkeypatch.setattr("app.sim.teams.update_incident", track)
    monkeypatch.setattr(SimRng, "random", lambda self: 0.5)

    emu, _, _ = _emu(store)
    await _run_until_closed(emu, store, add_working_days(store.incidents[iid]["created_sim"], 12))
    inc = store.incidents[iid]
    assert updates == [
        "in_progress",
        "fix_proposed",
        "fix_deployed",
        "verifying",
        "resolved",
        "closed",
    ]
    assert inc["closed_sim"] <= inc["sla_due_sim"]
    assert inc["closed_sim"] <= add_working_days(inc["created_sim"], 10)
    reports = [a for a in store.artifacts if a["kind"] == "progress_report"]
    assert len(reports) == 3
    days = sorted(
        (__import__("orjson").loads(r["meta"]) if isinstance(r["meta"], str) else r["meta"]).get("report_day")
        for r in reports
    )
    assert days == [3, 6, 9]
    for a in store.artifacts:
        assert PII_RE.search(a["body_md"]) is None
        assert any(ch in a["body_md"] for ch in "аеио")


@pytest.mark.asyncio
async def test_clarify_blocks_fix_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    store = MemStore()
    store.teams["team_deposits"]["p_clarify"] = 1.0
    store.add_incident()
    statuses: list[str] = []

    async def track(ctx: ToolContext, incident_id: int, status: str, reason: str | None = None, fields=None):
        statuses.append(status)
        inc = store.incidents[incident_id]
        inc["status"] = status
        return {"incident_id": incident_id, "status": status}

    monkeypatch.setattr("app.sim.teams.update_incident", track)
    monkeypatch.setattr(SimRng, "random", lambda self: 0.5)

    emu, _, _ = _emu(store)
    t = add_working_hours(store.incidents[1]["created_sim"], 10)
    await emu.tick(t, _World())
    assert "awaiting_client" in statuses
    assert "fix_proposed" not in statuses
    assert store.incidents[1]["status"] == "awaiting_client"


@pytest.mark.asyncio
async def test_sla_breach_late_take_and_close(monkeypatch: pytest.MonkeyPatch) -> None:
    store = MemStore()
    store.teams["team_deposits"]["p_sla_breach"] = 1.0
    iid = store.add_incident()
    inc = store.incidents[iid]

    async def track(ctx: ToolContext, incident_id: int, status: str, reason: str | None = None, fields=None):
        inc = store.incidents[incident_id]
        inc["status"] = status
        if status == "in_progress":
            inc["taken_sim"] = ctx.sim_time
        if status == "closed":
            inc["closed_sim"] = ctx.sim_time
        return {"incident_id": incident_id, "status": status}

    monkeypatch.setattr("app.sim.teams.update_incident", track)
    monkeypatch.setattr(SimRng, "random", lambda self: 0.5)

    emu, _, _ = _emu(store)
    await _run_until_closed(emu, store, add_working_days(inc["created_sim"], 15))
    assert inc["taken_sim"] > inc["take_due_sim"]
    assert inc["closed_sim"] > inc["sla_due_sim"]


@pytest.mark.asyncio
async def test_regression_rate_on_seed_2026(monkeypatch: pytest.MonkeyPatch) -> None:
    store = MemStore()
    store.teams["team_deposits"]["p_regression"] = 0.12
    for n in range(1, 101):
        store.add_incident(id=n, title=f"Сбой вклада #{n}")

    async def track(ctx: ToolContext, incident_id: int, status: str, reason: str | None = None, fields=None):
        store.incidents[incident_id]["status"] = status
        return {"incident_id": incident_id, "status": status}

    monkeypatch.setattr("app.sim.teams.update_incident", track)

    emu, _, _ = _emu(store, seed=2026)
    world = _World()
    base = store.incidents[1]["created_sim"]
    end = add_working_days(base, 12)
    t = base
    while t <= end:
        await emu.tick(t, world)
        if all((iid, "release", None) in emu.done or (iid, "close", None) in emu.done for iid in range(1, 101)):
            break
        t += dt.timedelta(hours=4)
    t = end + dt.timedelta(minutes=250)
    await emu.tick(t, world)
    reg_events = [e for e in store.events if e["event_type"] == "fault.regression"]
    assert 10 <= len(reg_events) <= 15


@pytest.mark.asyncio
async def test_regression_flow_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    store = MemStore()
    store.teams["team_deposits"]["p_regression"] = 1.0
    iid = store.add_incident()
    inc = store.incidents[iid]
    incidents_before = len(store.incidents)

    async def track(ctx: ToolContext, incident_id: int, status: str, reason: str | None = None, fields=None):
        store.incidents[incident_id]["status"] = status
        return {"incident_id": incident_id, "status": status}

    monkeypatch.setattr("app.sim.teams.update_incident", track)
    monkeypatch.setattr(SimRng, "random", lambda self: 0.5)

    emu, _, _ = _emu(store)
    world = _World()
    end = add_working_days(inc["created_sim"], 12)
    t = inc["created_sim"]
    while t <= end + dt.timedelta(days=1):
        await emu.tick(t, world)
        if store.faults:
            break
        t += dt.timedelta(hours=2)

    reg_events = [e for e in store.events if e["event_type"] == "fault.regression"]
    assert reg_events
    p = reg_events[0]["payload"]
    assert 60 <= p["delay_min"] <= 240
    assert p["system"] != inc["system_code"]
    assert p["caused_by_incident_id"] == iid
    assert p["release_action_id"] > 0
    assert len(store.incidents) == incidents_before
    assert len([f for f in store.faults if f.get("caused_by_incident_id")]) == 1


@pytest.mark.asyncio
async def test_progress_report_skip_and_no_duplicate_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    store = MemStore()
    store.add_incident()
    seq = iter([0.5, 0.5, 0.5, 0.05, 0.5, 0.5, 0.5, 0.5])

    monkeypatch.setattr(SimRng, "random", lambda self: next(seq))

    async def track(ctx: ToolContext, incident_id: int, status: str, reason: str | None = None, fields=None):
        store.incidents[incident_id]["status"] = status
        return {"incident_id": incident_id, "status": status}

    monkeypatch.setattr("app.sim.teams.update_incident", track)
    emu, _, _ = _emu(store)
    t = add_working_days(store.incidents[1]["created_sim"], 10)
    await emu.tick(t, _World())
    await emu.tick(t, _World())
    reports = [a for a in store.team_actions if a["action"] == "progress_report"]
    assert len(reports) == 2
    assert len(store.team_actions) == len(
        {(a["incident_id"], a["action"], a["payload"].get("report_day")) for a in store.team_actions}
    )


@pytest.mark.asyncio
async def test_emit_fault_regression_validation() -> None:
    store = MemStore()
    sim_time = dt.datetime(2026, 11, 9, 12, 0, tzinfo=MSK)
    payload = {
        "fault_id": 1,
        "caused_by_incident_id": 2,
        "release_action_id": 3,
        "origin_system": "sub_deposits",
        "system": "promo_engine",
        "error_code": "PROMO-RATE-MISMATCH",
        "product": "deposit",
        "delay_min": 120,
        "impact_count": 0,
        "started_sim": sim_time.isoformat(),
    }
    bus = EventBus(MemConn(store), strict=True)  # type: ignore[arg-type]
    await bus.emit(1, "fault.regression", payload, sim_time)
    assert bus.emitted == 1


@pytest.mark.asyncio
async def test_load_restores_pending_regressions(monkeypatch: pytest.MonkeyPatch) -> None:
    store = MemStore()
    iid = store.add_incident()
    inc = store.incidents[iid]
    emu, conn, bus = _emu(store, seed=7)
    plan = emu._build_plan(
        iid,
        "team_deposits",
        store.teams["team_deposits"],
        inc["created_sim"],
        inc["take_due_sim"],
        inc["sla_due_sim"],
        inc["report_due_sims"],
        inc["system_code"],
        inc["product_code"],
    )
    release_step = next(s for s in plan.steps if s.action == "release")
    release_step.regression = {
        "error_code": "PROMO-RATE-MISMATCH",
        "system": "promo_engine",
        "product": "deposit",
        "delay_min": 90,
        "origin_system": "sub_deposits",
    }
    release_sim = release_step.at
    store.team_actions.append(
        {
            "id": 10,
            "run_id": 1,
            "incident_id": iid,
            "action": "take",
            "payload": {"plan": _plan_blob(plan)},
            "action_sim": inc["created_sim"],
        }
    )
    store.team_actions.append(
        {
            "id": 11,
            "run_id": 1,
            "incident_id": iid,
            "action": "release",
            "payload": {},
            "action_sim": release_sim,
        }
    )
    store.incidents[iid]["status"] = "fix_deployed"

    async def track(ctx: ToolContext, incident_id: int, status: str, reason: str | None = None, fields=None):
        store.incidents[incident_id]["status"] = status
        return {"incident_id": incident_id, "status": status}

    monkeypatch.setattr("app.sim.teams.update_incident", track)

    emu2 = TeamEmulator(SimRng(99), conn, bus, 1)  # type: ignore[arg-type]
    await emu2.load()
    assert len(emu2.pending_regressions) == 1
    pr = emu2.pending_regressions[0]
    assert pr.release_action_id == 11
    assert pr.delay_min == 90
    world = _World()
    await emu2.tick(release_sim + dt.timedelta(minutes=100), world)
    assert [e for e in store.events if e["event_type"] == "fault.regression"]
