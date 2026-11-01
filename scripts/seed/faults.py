"""T-018: детерминированная предыстория сбоев без изменения ошибок/статусов операций."""

from __future__ import annotations

import argparse
import datetime as dt
import random
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
for candidate in (ROOT / "backend", Path("/app")):
    if (candidate / "app").is_dir():
        sys.path.insert(0, str(candidate))

from app.contracts.registry import validate  # noqa: E402

from scripts.seed.common import PROFILES, J, get_setting, load_yaml, log, set_setting  # noqa: E402


@dataclass(frozen=True)
class FaultWindow:
    system: str
    error_code: str
    started: dt.datetime
    resolved: dt.datetime
    regions: tuple[str, ...]


def plan_faults(
    rnd: random.Random,
    sim_now: dt.datetime,
    errors: Sequence[tuple[str, str]],
    anchors: Sequence[tuple[dt.datetime, str, str, str]],
) -> list[FaultWindow]:
    """14 последовательных 24-часовых окон; 2–4 сбоя в каждом, 10–240 минут."""
    if sim_now.tzinfo is None or sim_now.utcoffset() is None:
        raise ValueError("sim_now должен иметь timezone")
    if not errors or len(set(errors)) != len(errors):
        raise ValueError("нужен непустой уникальный справочник ошибок")
    for code, system in errors:
        if validate(
            {
                "event_type": "fault.started",
                "fault_id": 1,
                "system": system,
                "error_code": code,
                "started_sim": sim_now.isoformat(),
            },
            "sim/fault",
        ):
            raise ValueError("пара error/system нарушает event contract")
    known = set(errors)
    if any((code, system) not in known for _, code, system, _ in anchors):
        raise ValueError("операция ссылается на неизвестную пару error/system")
    plan = []
    history_start = sim_now - dt.timedelta(days=14)
    for day in range(14):
        day_start = history_start + dt.timedelta(days=day)
        count = rnd.randint(2, 4)
        for slot in range(count):
            left = day_start + dt.timedelta(days=slot / count)
            right = day_start + dt.timedelta(days=(slot + 1) / count)
            eligible = [row for row in anchors if left <= row[0] < right]
            duration = dt.timedelta(minutes=rnd.randint(10, 240))
            if eligible:
                when, code, system, region = rnd.choice(eligible)
                started = max(left, min(when - duration / 2, right - duration))
                regions = (region,) if (day + slot) % 2 else ()
            else:
                code, system = rnd.choice(errors)
                started = left + (right - left - duration) * rnd.random()
                regions = ()
            plan.append(FaultWindow(system, code, started, started + duration, regions))
    return plan


def _event(cur: Any, run_id: int, kind: str, payload: dict[str, Any], when: dt.datetime) -> None:
    payload = {**payload, "event_type": kind}
    errors = validate(payload, "sim/fault_regression" if kind == "fault.regression" else "sim/fault")
    if errors:
        raise ValueError(f"невалидное событие {kind}: {errors[:2]}")
    cur.execute(
        "insert into sim_events(run_id,event_type,payload,sim_time) values(%s,%s,%s,%s)",
        (run_id, kind, J(payload), when),
    )


def seed_faults(
    cur: Any, rnd: random.Random, run_id: int, sim_now: dt.datetime, *, profile: str = "lite"
) -> dict[str, Any]:
    if profile not in PROFILES:
        raise ValueError("неизвестный профиль")
    with cur.connection.transaction():
        cur.execute("select pg_advisory_xact_lock(hashtextextended(%s,0))", (f"seed-fault-history:{run_id}",))
        key = f"seed_fault_history:{run_id}"
        previous = get_setting(cur, key)
        if previous is not None:
            actual = cur.execute("select id from faults where run_id=%s order by id", (run_id,)).fetchall()
            if [row[0] for row in actual] != previous.get("fault_ids"):
                raise ValueError("fault marker расходится с БД; данные сохранены, нужен review")
            return previous
        if cur.execute("select exists(select 1 from faults where run_id=%s)", (run_id,)).fetchone()[0]:
            raise ValueError("существующие faults без marker сохранены; нужен отдельный review")
        if not cur.execute("select 1 from sim_runs where id=%s and kind='baseline'", (run_id,)).fetchone():
            raise ValueError("предыстория требует существующий baseline run")
        configured = load_yaml("op_paths.yaml")["failure_codes"]
        errors = cur.execute(
            "select code,system_code from error_codes where code=any(%s) order by code", (configured,)
        ).fetchall()
        if {row[0] for row in errors} != set(configured):
            raise ValueError("справочник БД не покрывает настроенные failure_codes T-017")
        anchors = cur.execute(
            "select o.started_sim,o.error_code,ec.system_code,c.region_code from operations o "
            "join error_codes ec on ec.code=o.error_code join clients c on c.id=o.client_id "
            "where o.run_id=%s and o.status='failed' and ec.system_code=any(o.system_path) "
            "and o.started_sim >= %s and o.started_sim < %s order by o.started_sim,o.id",
            (run_id, sim_now - dt.timedelta(days=14), sim_now),
        ).fetchall()
        windows = plan_faults(rnd, sim_now, errors, anchors)
        ids = []
        for fault in windows:
            fid = cur.execute(
                "insert into faults(run_id,system_code,error_code,started_sim,resolved_sim,region_codes) "
                "values(%s,%s,%s,%s,%s,%s) returning id",
                (run_id, fault.system, fault.error_code, fault.started, fault.resolved, list(fault.regions)),
            ).fetchone()[0]
            ids.append(fid)
            affected = cur.execute(
                "update operations o set fault_id=%s from clients c where o.client_id=c.id "
                "and o.run_id=%s and o.status='failed' and o.error_code=%s and %s=any(o.system_path) "
                "and o.started_sim >= %s and o.started_sim < %s and o.fault_id is null "
                "and (cardinality(%s::text[])=0 or c.region_code=any(%s::text[])) "
                "returning o.id,o.client_id,o.started_sim",
                (
                    fid,
                    run_id,
                    fault.error_code,
                    fault.system,
                    fault.started,
                    fault.resolved,
                    list(fault.regions),
                    list(fault.regions),
                ),
            ).fetchall()
            affected.sort(key=lambda row: (row[2], row[0]))
            impact, clients = len(affected), len({row[1] for row in affected})
            cur.execute("update faults set impact_count=%s,affected_clients=%s where id=%s", (impact, clients, fid))
            payload = {
                "fault_id": fid,
                "system": fault.system,
                "error_code": fault.error_code,
                "started_sim": fault.started.isoformat(),
                "resolved_sim": fault.resolved.isoformat(),
                "region_codes": list(fault.regions),
                "impact_count": impact,
                "affected_clients": clients,
            }
            _event(
                cur,
                run_id,
                "fault.started",
                {**payload, "resolved_sim": None, "impact_count": 0, "affected_clients": 0},
                fault.started,
            )
            _event(cur, run_id, "fault.resolved", payload, fault.resolved)
            logs = [
                ("WARN", "health_probe degraded; retry_budget=3", fault.started, None),
                *[
                    ("ERROR", f"request failed; code={fault.error_code}; retry_exhausted=true", when, oid)
                    for oid, _, when in affected
                ],
                *[
                    (
                        "ERROR",
                        f"health_probe failed; code={fault.error_code}; attempt={i + 1}",
                        fault.started + (fault.resolved - fault.started) * (i + 1) / 4,
                        None,
                    )
                    for i in range(3)
                ],
                (
                    "FATAL",
                    "circuit_breaker open; upstream_unavailable=true",
                    fault.started + (fault.resolved - fault.started) / 2,
                    None,
                ),
                ("INFO", "health_probe recovered; circuit_breaker=closed", fault.resolved, None),
            ]
            cur.executemany(
                "insert into system_logs(run_id,system_code,level,error_code,component,message,affected_operation_id,fault_id,logged_sim) values(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [
                    (
                        run_id,
                        fault.system,
                        level,
                        fault.error_code,
                        f"{fault.system}.request_handler",
                        message,
                        oid,
                        fid,
                        when,
                    )
                    for level, message, when, oid in logs
                ],
            )
        systems = [row[0] for row in cur.execute("select code from systems order by code").fetchall()]
        cur.executemany(
            "insert into system_logs(run_id,system_code,level,component,message,logged_sim) values(%s,%s,'INFO',%s,%s,%s)",
            [
                (
                    run_id,
                    system,
                    f"{system}.scheduler",
                    "heartbeat ok; queue_depth=0",
                    sim_now - dt.timedelta(days=day, hours=1),
                )
                for day in range(14)
                for system in systems
            ],
        )
        candidates = sorted(rnd.sample(ids[1:], round(len(ids) * 0.125)))
        result = {
            "version": 1,
            "run_id": run_id,
            "fault_ids": ids,
            "regression_candidate_ids": candidates,
            "regressions_finalized": [],
        }
        set_setting(cur, key, result)
        log.info("fault_history_done", faults=len(ids), regression_candidates=len(candidates))
        return result


def finalize_regressions(cur: Any, run_id: int, bindings: Sequence[dict[str, int]]) -> None:
    """T-020 передаёт реальные incident/release; до этого candidates не являются регрессиями."""
    with cur.connection.transaction():
        cur.execute("select pg_advisory_xact_lock(hashtextextended(%s,0))", (f"seed-fault-history:{run_id}",))
        key = f"seed_fault_history:{run_id}"
        state = get_setting(cur, key)
        if not state:
            raise ValueError("сначала seed_faults")
        if len({row["fault_id"] for row in bindings}) != len(bindings):
            raise ValueError("повторяющийся regression binding")
        for binding in bindings:
            fid, incident_id, release_id = (
                binding[k] for k in ("fault_id", "caused_by_incident_id", "release_action_id")
            )
            if fid not in state["regression_candidate_ids"]:
                raise ValueError("fault не является regression candidate")
            row = cur.execute(
                "select f.system_code,f.error_code,f.started_sim,f.impact_count,f.caused_by_incident_id,"
                "i.system_code,a.action_sim,a.action from faults f join incidents i on i.id=%s and i.run_id=f.run_id "
                "join team_actions a on a.id=%s and a.incident_id=i.id and a.run_id=f.run_id where f.id=%s and f.run_id=%s for update of f",
                (incident_id, release_id, fid, run_id),
            ).fetchone()
            if not row:
                raise ValueError("binding не принадлежит данному run/incident")
            system, code, when, impact, previous, origin, released, action = row
            delay = (when - released).total_seconds() / 60
            if action != "release" or system == origin or origin is None or not 60 <= delay <= 240:
                raise ValueError("регрессия требует release другой системы за1–4 часа до сбоя")
            existing = cur.execute(
                "select payload from sim_events where run_id=%s and event_type='fault.regression' and payload->>'fault_id'=%s",
                (run_id, str(fid)),
            ).fetchall()
            if existing:
                if previous != incident_id or len(existing) != 1 or existing[0][0]["release_action_id"] != release_id:
                    raise ValueError("существующая regression имеет другой binding")
                continue
            if previous is not None:
                raise ValueError("fault уже связан с другим incident")
            cur.execute("update faults set caused_by_incident_id=%s where id=%s", (incident_id, fid))
            _event(
                cur,
                run_id,
                "fault.regression",
                {
                    "fault_id": fid,
                    "caused_by_incident_id": incident_id,
                    "release_action_id": release_id,
                    "origin_system": origin,
                    "system": system,
                    "error_code": code,
                    "started_sim": when.isoformat(),
                    "delay_min": int(delay),
                    "impact_count": impact,
                },
                when,
            )
            state["regressions_finalized"].append(fid)
        state["regressions_finalized"].sort()
        set_setting(cur, key, state)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=sorted(PROFILES), default="lite")
    parser.add_argument("--check", action="store_true", required=True)
    args = parser.parse_args()
    configured = load_yaml("op_paths.yaml")["failure_codes"]
    errors = [
        (row["code"], row["system"])
        for row in load_yaml("error_codes.yaml")["error_codes"]
        if row["code"] in configured
    ]
    if {row[0] for row in errors} != set(configured):
        raise ValueError("каталог не покрывает failure_codes T-017")
    plan = plan_faults(random.Random(42), dt.datetime(2026, 11, 9, 9, tzinfo=dt.UTC), errors, [])
    log.info(
        "fault_history_config_ok",
        profile=args.profile,
        faults=len(plan),
        regression_candidates=round(len(plan) * 0.125),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
