"""T-037: SLA-движок симулятора."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from app.agent.tools.base import ToolContext
from app.agent.tools.write import STATUS_TRANSITIONS
from app.contracts.registry import validate
from app.sim.clock import MSK, add_working_days
from app.sim.events import EventBus
from app.sim.sla import SlaEngine, fix_deadline, remaining_pct, sla_tick_times


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


class SlaStore:
    def __init__(self) -> None:
        self.incidents: dict[int, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.notifications: list[dict[str, Any]] = []
        self.escalations: list[dict[str, Any]] = []
        self.followups: list[dict[str, Any]] = []
        self.artifacts: list[dict[str, Any]] = []
        self.signals: dict[int, dict[str, Any]] = {}
        self.incident_signals: list[tuple[int, int]] = []
        self.history: list[tuple[Any, ...]] = []
        self.segments = {
            "mass": 60,
            "social": 30,
            "premium": 20,
            "vip": 10,
            "ultra_vip": 5,
        }
        self._next = 1

    def add_incident(self, **fields: Any) -> int:
        iid = int(fields.pop("id", len(self.incidents) + 1))
        base = {
            "id": iid,
            "status": "in_progress",
            "team_code": "team_deposits",
            "created_sim": dt.datetime(2026, 11, 9, 9, 0, tzinfo=MSK),
            "take_due_sim": dt.datetime(2026, 11, 9, 12, 0, tzinfo=MSK),
            "sla_due_sim": dt.datetime(2026, 11, 9, 17, 0, tzinfo=MSK),
            "report_due_sims": [],
            "complexity": "medium",
            "sla_breached": False,
            "outcome_class": None,
            "agent_run_id": 0,
            "run_id": 1,
            "taken_sim": dt.datetime(2026, 11, 9, 9, 30, tzinfo=MSK),
            "closed_sim": None,
            "resolved_sim": None,
        }
        base.update(fields)
        self.incidents[iid] = base
        return iid


class SlaConn:
    def __init__(self, store: SlaStore) -> None:
        self.store = store

    async def execute(self, sql: str, args: tuple[Any, ...] = ()) -> _Cursor:
        s = " ".join(sql.lower().split())
        st = self.store
        if "max(sim_time) from sim_events" in s:
            ticks = [e["sim_time"] for e in st.events if e["event_type"] == "sla.tick"]
            return _Cursor((max(ticks),) if ticks else None)
        if "from segments" in s:
            return _Cursor([(c, m) for c, m in st.segments.items()])
        if "from incidents where run_id" in s and "status <> all" in s:
            terminal = set(args[1])
            rows = []
            for inc in st.incidents.values():
                if inc["run_id"] != args[0] or inc["status"] in terminal:
                    continue
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
                        inc["sla_breached"],
                        inc["outcome_class"],
                        inc["agent_run_id"],
                    )
                )
            return _Cursor(rows)
        if "select status from incidents where id" in s:
            return _Cursor((st.incidents[int(args[0])]["status"],))
        if "select taken_sim from incidents" in s:
            return _Cursor((st.incidents[int(args[0])].get("taken_sim"),))
        if s.startswith("update incidents set sla_breached"):
            st.incidents[int(args[0])]["sla_breached"] = True
            return _Cursor(None)
        if s.startswith("update incidents set status"):
            iid = int(args[-1])
            st.incidents[iid]["status"] = str(args[0])
            return _Cursor(None)
        if "insert into incident_status_history" in s:
            st.history.append(args)
            return _Cursor(None)
        if "count(distinct payload" in s and "report_missing" in s:
            dues = {
                e["payload"].get("due_sim")
                for e in st.events
                if e["event_type"] == "sla.report_missing" and str(e["payload"].get("incident_id")) == str(args[1])
            }
            return _Cursor((len(dues),))
        if "from sim_events where run_id" in s and "event_type" in s:
            et = args[1]
            iid = args[2] if len(args) > 2 else ""
            due = args[3] if len(args) > 3 else ""
            for e in st.events:
                if e["run_id"] != args[0] or e["event_type"] != et:
                    continue
                p = e["payload"]
                if et == "sla.warning" and str(p.get("incident_id")) == str(iid):
                    return _Cursor((1,))
                if et == "sla.first_response_overdue" and str(p.get("signal_id")) == str(iid):
                    return _Cursor((1,))
                if str(p.get("incident_id")) == str(iid) and str(p.get("due_sim", "")) == str(due or ""):
                    return _Cursor((1,))
            return _Cursor(None)
        if "from incident_artifacts where incident_id" in s:
            iid, due, pub = args
            for a in st.artifacts:
                if (
                    a["incident_id"] == iid
                    and a["kind"] == "progress_report"
                    and a["due_sim"] == due
                    and a.get("published_sim") is not None
                    and a["published_sim"] <= pub
                ):
                    return _Cursor((1,))
            return _Cursor(None)
        if "from signals s" in s and "link_type = 'primary'" in s:
            rows = []
            for sig in st.signals.values():
                if sig["run_id"] != args[0]:
                    continue
                inc_id = next((i for i, s_id in st.incident_signals if s_id == sig["id"]), None)
                if inc_id is None:
                    continue
                inc = st.incidents[inc_id]
                if inc["status"] in set(args[1]):
                    continue
                if any(
                    n["signal_id"] == sig["id"] and n["recipient_type"] == "client" and n["status"] == "sent"
                    for n in st.notifications
                ):
                    continue
                rows.append((sig["id"], sig["received_sim"], sig["segment_code"], inc_id))
            return _Cursor(rows)
        if "select id from notifications where run_id" in s:
            for n in st.notifications:
                if (
                    n.get("run_id") == args[0]
                    and n.get("incident_id") == args[1]
                    and n.get("template_code") == args[2]
                    and n.get("recipient_type") == args[3]
                ):
                    return _Cursor((n["id"],))
            return _Cursor(None)
        if "insert into notifications" in s:
            st.notifications.append(
                {
                    "run_id": args[0],
                    "recipient_type": args[1],
                    "team_code": args[2],
                    "incident_id": args[3],
                    "template_code": args[5],
                    "status": "sent",
                    "signal_id": None,
                }
            )
            return _Cursor((len(st.notifications),))
        if "select id from escalations where run_id" in s:
            for e in st.escalations:
                if e["run_id"] == args[0] and e["incident_id"] == args[1] and e["reason"] == args[2]:
                    return _Cursor((e["id"],))
            return _Cursor(None)
        if "insert into escalations" in s:
            st.escalations.append(
                {
                    "run_id": args[0],
                    "incident_id": args[1],
                    "reason": args[2],
                    "to_role": "cx_lead",
                }
            )
            return _Cursor((1,))
        if "select id from followups where sim_run_id" in s:
            for f in st.followups:
                if f["sim_run_id"] == args[0] and f["incident_id"] == args[1] and f["reason"] == args[2]:
                    return _Cursor((f["id"],))
            return _Cursor(None)
        if "insert into followups" in s:
            st.followups.append(
                {"sim_run_id": args[0], "incident_id": args[3], "reason": args[5], "status": "fired"}
            )
            return _Cursor((1,))
        if "select subject, body from notification_templates" in s:
            return _Cursor(None)
        if "select pg_notify" in s:
            return _Cursor(None)
        if "insert into sim_events" in s:
            import orjson

            payload = orjson.loads(args[2]) if isinstance(args[2], str) else args[2]
            st.events.append(
                {
                    "run_id": args[0],
                    "event_type": args[1],
                    "payload": payload,
                    "sim_time": args[3],
                }
            )
            return _Cursor((len(st.events),))
        raise AssertionError(f"unexpected sql: {sql[:160]}")


class RecordingBus:
    strict = True

    def __init__(self, store: SlaStore) -> None:
        self.store = store

    async def emit(self, run_id: int, event_type: str, payload: dict[str, Any], sim_time: dt.datetime, **kw: Any) -> Any:
        payload = {**payload, "event_type": event_type}
        if event_type.startswith("sla."):
            assert validate(payload, "sim/sla") == []
        self.store.events.append(
            {"run_id": run_id, "event_type": event_type, "payload": payload, "sim_time": sim_time}
        )
        return __import__("uuid").uuid4()


async def _engine(store: SlaStore) -> SlaEngine:
    eng = SlaEngine(SlaConn(store), RecordingBus(store), 1)  # type: ignore[arg-type]
    await eng.load()
    return eng


async def _noop_compute(*_a: Any, **_k: Any) -> None:
    return None


async def _noop_update(*_a: Any, **_k: Any) -> dict[str, Any]:
    return {}


@pytest.mark.asyncio
async def test_fix_deadline_friday_to_monday() -> None:
    fri = dt.datetime(2026, 11, 6, 17, 0, tzinfo=MSK)
    assert fix_deadline(fri, 1) == dt.datetime(2026, 11, 9, 17, 0, tzinfo=MSK)


def test_sla_tick_times_sixty_minutes_and_short_step() -> None:
    t0 = dt.datetime(2026, 11, 9, 9, 0, tzinfo=MSK)
    assert sla_tick_times(t0, t0 + dt.timedelta(minutes=60)) == [
        t0 + dt.timedelta(minutes=15),
        t0 + dt.timedelta(minutes=30),
        t0 + dt.timedelta(minutes=45),
        t0 + dt.timedelta(minutes=60),
    ]
    assert sla_tick_times(t0, t0 + dt.timedelta(minutes=10)) == []


@pytest.mark.asyncio
async def test_warning_once(monkeypatch: pytest.MonkeyPatch) -> None:
    store = SlaStore()
    created = dt.datetime(2026, 11, 9, 9, 0, tzinfo=MSK)
    due = dt.datetime(2026, 11, 9, 17, 0, tzinfo=MSK)
    store.add_incident(created_sim=created, sla_due_sim=due, complexity="medium")
    at = dt.datetime(2026, 11, 9, 15, 30, tzinfo=MSK)
    assert remaining_pct(created, due, at, complexity="medium") < 25.0
    monkeypatch.setattr("app.sim.sla.dcltv.compute_incident", _noop_compute)
    eng = await _engine(store)

    async def track(ctx: ToolContext, incident_id: int, status: str, reason: str | None = None, fields=None):
        store.incidents[incident_id]["status"] = status
        return {"incident_id": incident_id}

    monkeypatch.setattr("app.sim.sla.update_incident", track)
    await eng.tick(created, at)
    await eng.tick(at, at + dt.timedelta(minutes=15))
    warnings = [e for e in store.events if e["event_type"] == "sla.warning"]
    assert len(warnings) == 1


@pytest.mark.asyncio
async def test_breach_from_fix_proposed_escalates_via_in_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    store = SlaStore()
    created = dt.datetime(2026, 11, 9, 9, 0, tzinfo=MSK)
    due = dt.datetime(2026, 11, 9, 17, 0, tzinfo=MSK)
    store.add_incident(created_sim=created, sla_due_sim=due, status="fix_proposed")
    monkeypatch.setattr("app.sim.sla.dcltv.compute_incident", _noop_compute)
    eng = await _engine(store)
    transitions: list[str] = []

    async def track(ctx: ToolContext, incident_id: int, status: str, reason: str | None = None, fields=None):
        store.incidents[incident_id]["status"] = status
        transitions.append(status)
        return {"incident_id": incident_id}

    monkeypatch.setattr("app.sim.sla.update_incident", track)
    await eng.tick(created, due)
    inc = store.incidents[1]
    assert transitions == ["in_progress", "escalated"]
    assert inc["sla_breached"] is True
    assert inc["status"] == "escalated"
    assert len(store.escalations) == 1
    assert any(e["event_type"] == "sla.breached" for e in store.events)
    assert any(e["event_type"] == "sla.escalated" for e in store.events)


@pytest.mark.asyncio
async def test_breach_without_fsm_path_leaves_incident_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    store = SlaStore()
    created = dt.datetime(2026, 11, 9, 9, 0, tzinfo=MSK)
    due = dt.datetime(2026, 11, 9, 17, 0, tzinfo=MSK)
    store.add_incident(created_sim=created, sla_due_sim=due, status="fix_proposed")
    monkeypatch.setitem(STATUS_TRANSITIONS, "fix_proposed", {"fix_deployed"})
    monkeypatch.setattr("app.sim.sla.dcltv.compute_incident", _noop_compute)
    eng = await _engine(store)

    async def track(ctx: ToolContext, incident_id: int, status: str, reason: str | None = None, fields=None):
        store.incidents[incident_id]["status"] = status
        return {"incident_id": incident_id}

    monkeypatch.setattr("app.sim.sla.update_incident", track)
    await eng.tick(created, due)
    inc = store.incidents[1]
    assert inc["status"] == "fix_proposed"
    assert inc["sla_breached"] is False
    assert not store.escalations
    assert not any(e["event_type"] == "sla.breached" for e in store.events)


@pytest.mark.asyncio
async def test_outcome_class_recomputed_after_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    store = SlaStore()
    created = dt.datetime(2026, 11, 9, 9, 0, tzinfo=MSK)
    due = dt.datetime(2026, 11, 9, 17, 0, tzinfo=MSK)
    closed = dt.datetime(2026, 11, 9, 16, 0, tzinfo=MSK)
    store.add_incident(
        status="closed",
        created_sim=created,
        sla_due_sim=due,
        closed_sim=closed,
        outcome_class="open",
    )
    compute_calls: list[int] = []

    async def record_compute(conn: Any, incident_id: int, *, sim_time: dt.datetime | None = None) -> dict[str, Any]:
        compute_calls.append(incident_id)
        store.incidents[incident_id]["outcome_class"] = "closed_in_sla"
        return {"outcome_class": "closed_in_sla"}

    monkeypatch.setattr("app.sim.sla.dcltv.compute_incident", record_compute)
    eng = await _engine(store)
    await eng.tick(closed, closed + dt.timedelta(minutes=15))
    assert compute_calls == [1]
    assert store.incidents[1]["outcome_class"] == "closed_in_sla"


@pytest.mark.asyncio
async def test_breach_escalates(monkeypatch: pytest.MonkeyPatch) -> None:
    store = SlaStore()
    created = dt.datetime(2026, 11, 9, 9, 0, tzinfo=MSK)
    due = dt.datetime(2026, 11, 9, 17, 0, tzinfo=MSK)
    store.add_incident(created_sim=created, sla_due_sim=due, status="in_progress")
    monkeypatch.setattr("app.sim.sla.dcltv.compute_incident", _noop_compute)
    eng = await _engine(store)

    async def track(ctx: ToolContext, incident_id: int, status: str, reason: str | None = None, fields=None):
        store.incidents[incident_id]["status"] = status
        store.history.append((incident_id, status, reason))
        return {"incident_id": incident_id}

    monkeypatch.setattr("app.sim.sla.update_incident", track)
    await eng.tick(created, due)
    inc = store.incidents[1]
    assert inc["sla_breached"] is True
    assert inc["status"] == "escalated"
    assert any(e["event_type"] == "sla.breached" for e in store.events)
    assert any(e["event_type"] == "sla.escalated" for e in store.events)
    assert store.history


@pytest.mark.asyncio
async def test_report_missing_second_escalates(monkeypatch: pytest.MonkeyPatch) -> None:
    store = SlaStore()
    created = dt.datetime(2026, 11, 9, 9, 0, tzinfo=MSK)
    d1 = add_working_days(created, 3)
    d2 = add_working_days(created, 6)
    store.add_incident(created_sim=created, report_due_sims=[d1, d2], sla_due_sim=add_working_days(created, 10))
    monkeypatch.setattr("app.sim.sla.dcltv.compute_incident", _noop_compute)
    eng = await _engine(store)
    async def set_status(ctx: ToolContext, iid: int, st: str, reason: str | None = None, fields=None):
        store.incidents[iid]["status"] = st
        return {"incident_id": iid}

    monkeypatch.setattr("app.sim.sla.update_incident", set_status)
    await eng.tick(created, d2)
    missing = [e for e in store.events if e["event_type"] == "sla.report_missing"]
    assert len(missing) == 2
    assert len([e for e in store.escalations if e["to_role"] == "cx_lead"]) >= 1


@pytest.mark.asyncio
async def test_repeat_tick_no_duplicate_events(monkeypatch: pytest.MonkeyPatch) -> None:
    store = SlaStore()
    created = dt.datetime(2026, 11, 9, 9, 0, tzinfo=MSK)
    due = dt.datetime(2026, 11, 9, 17, 0, tzinfo=MSK)
    store.add_incident(created_sim=created, sla_due_sim=due)
    monkeypatch.setattr("app.sim.sla.dcltv.compute_incident", _noop_compute)
    eng = await _engine(store)
    monkeypatch.setattr("app.sim.sla.update_incident", _noop_update)
    await eng.tick(created, due)
    n1 = len([e for e in store.events if e["event_type"] != "sla.tick"])
    await eng.tick(due, due + dt.timedelta(minutes=15))
    n2 = len([e for e in store.events if e["event_type"] != "sla.tick"])
    assert n2 == n1


@pytest.mark.asyncio
async def test_progress_report_blocks_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    store = SlaStore()
    created = dt.datetime(2026, 11, 9, 9, 0, tzinfo=MSK)
    due_report = add_working_days(created, 3)
    store.add_incident(created_sim=created, report_due_sims=[due_report], sla_due_sim=add_working_days(created, 10))
    store.artifacts.append(
        {
            "incident_id": 1,
            "kind": "progress_report",
            "due_sim": due_report,
            "published_sim": due_report,
        }
    )
    monkeypatch.setattr("app.sim.sla.dcltv.compute_incident", _noop_compute)
    eng = await _engine(store)
    monkeypatch.setattr("app.sim.sla.update_incident", _noop_update)
    await eng.tick(created, due_report)
    assert not [e for e in store.events if e["event_type"] == "sla.report_missing"]


@pytest.mark.asyncio
async def test_take_overdue(monkeypatch: pytest.MonkeyPatch) -> None:
    store = SlaStore()
    created = dt.datetime(2026, 11, 9, 9, 0, tzinfo=MSK)
    take_due = dt.datetime(2026, 11, 9, 10, 0, tzinfo=MSK)
    store.add_incident(created_sim=created, take_due_sim=take_due, taken_sim=None, status="routed")
    monkeypatch.setattr("app.sim.sla.dcltv.compute_incident", _noop_compute)
    eng = await _engine(store)
    monkeypatch.setattr("app.sim.sla.update_incident", _noop_update)
    await eng.tick(created, take_due + dt.timedelta(minutes=1))
    assert any(e["event_type"] == "sla.take_overdue" for e in store.events)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("segment", "minutes"),
    [
        ("mass", 60),
        ("social", 30),
        ("premium", 20),
        ("vip", 10),
        ("ultra_vip", 5),
    ],
)
async def test_first_response_overdue_by_segment(
    monkeypatch: pytest.MonkeyPatch, segment: str, minutes: int
) -> None:
    store = SlaStore()
    received = dt.datetime(2026, 11, 9, 9, 0, tzinfo=MSK)
    store.add_incident(status="in_progress")
    store.signals[1] = {"id": 1, "run_id": 1, "received_sim": received, "segment_code": segment}
    store.incident_signals.append((1, 1))
    monkeypatch.setattr("app.sim.sla.dcltv.compute_incident", _noop_compute)
    eng = await _engine(store)
    monkeypatch.setattr("app.sim.sla.update_incident", _noop_update)
    await eng.tick(received, received + dt.timedelta(minutes=minutes + 30))
    overdue = [e for e in store.events if e["event_type"] == "sla.first_response_overdue"]
    assert len(overdue) == 1


@pytest.mark.asyncio
async def test_emit_sla_validation() -> None:
    store = SlaStore()
    sim_time = dt.datetime(2026, 11, 9, 12, 0, tzinfo=MSK)
    payload = {
        "incident_id": 1,
        "team": "team_deposits",
        "remaining_pct": 10.0,
        "due_sim": sim_time.isoformat(),
        "sim_time": sim_time.isoformat(),
    }
    bus = EventBus(SlaConn(store), strict=True)  # type: ignore[arg-type]
    await bus.emit(1, "sla.warning", payload, sim_time)
    assert store.events
