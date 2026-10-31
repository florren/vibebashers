"""Живая проверка demo-каталога на отдельной синтетической базе cx_live20_*.

DATABASE_URL указывается явно; ENV_FILE содержит настройки GigaChat. Скрипт не сидирует,
не очищает БД и не запускает внешние интеграции. Каждый кейс создаёт отдельный scenario-run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import psycopg
from app.agent.runner import AgentService
from app.api.demo_execution import (
    DemoExecutionBody,
    delete_demo_execution,
    get_demo_execution,
    post_demo_execution,
)
from app.config import get_settings
from app.demo.execution import cycle
from app.llm.failover import build_chain, default_profile
from app.llm.roles import refresh
from app.main import create_app
from app.sim import scenarios
from app.sim.engine import Simulator
from psycopg.rows import dict_row
from starlette.requests import Request


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--matrix",
        action="store_true",
        help="Все 20 сценариев × 5 исходов (100 запусков)",
    )
    selection.add_argument(
        "--case",
        action="append",
        help="scenario_id:outcome; без флага — 20 входов и 5 дополнительных проверок",
    )
    return parser.parse_args()


ARGS = arguments()
OUT = ARGS.output


async def snapshot(rid, s):
    async with await psycopg.AsyncConnection.connect(
        s.database_url.replace("postgresql+psycopg://", "postgresql://"),
        row_factory=dict_row,
    ) as c:
        queries = {
            "signals": "select id,public_id,status,text,client_id,channel_code from signals where run_id=%s order by id",
            "incidents": "select id,public_id,status,sla_breached,outcome_class,resolution_summary,team_code from incidents where run_id=%s order by id",
            "artifacts": "select incident_id,kind,body_md,meta,published_sim,due_sim from incident_artifacts where run_id=%s order by id",
            "actions": "select incident_id,action,payload from team_actions where run_id=%s order by id",
            "employees": "select public_id,reason,decision,decided_by,comment,use_as_fewshot from human_decisions where sim_run_id=%s order by id",
            "notifications": "select public_id,signal_id,incident_id,recipient_type,template_code,body,status,channel_code from notifications where run_id=%s order by id",
            "runs": "select id,public_id,kind,outcome,error from agent_runs where sim_run_id=%s order by id",
            "steps": "select a.id as agent_run_id,s.node,s.status,s.output,s.model,s.tool_calls from agent_steps s join agent_runs a on a.id=s.run_id where a.sim_run_id=%s order by s.id",
            "tickets": "select ticket_id,status,incident_status,routing_status from v_tickets where run_id=%s order by incident_id",
            "tasks": "select public_id,kind,status,requires_hitl,payload from tasks where run_id=%s order by id",
            "alerts": "select a.id,a.decision,a.acknowledged_by,a.recommendation_ru from compliance_alerts a join audio_sessions s on s.id=a.session_id where s.run_id=%s order by a.id",
        }
        result = {}
        for k, q in queries.items():
            result[k] = await (await c.execute(q, (rid,))).fetchall()
        return result


async def main():
    s = get_settings()
    if not os.environ.get("DATABASE_URL") or not urlsplit(
        s.database_url
    ).path.removeprefix("/").startswith("cx_live20_"):
        raise SystemExit(
            "Требуется явный DATABASE_URL отдельной базы cx_live20_*. Рабочая база запрещена."
        )
    if s.llm_provider != "gigachat":
        raise SystemExit(
            "Требуется LLM_PROVIDER=gigachat. Результаты replay/mock будут помечены неуспешными."
        )
    OUT.mkdir(parents=True, exist_ok=True)
    guard = await psycopg.AsyncConnection.connect(
        s.database_url.replace("postgresql+psycopg://", "postgresql://"),
        autocommit=True,
    )
    locked = await (
        await guard.execute("select pg_try_advisory_lock(hashtext('live20-verifier'))")
    ).fetchone()
    if not locked[0]:
        raise RuntimeError("another verifier holds this database")
    app = create_app()
    chain = build_chain(
        s.model_copy(update={"llm_chain": "gigachat,replay,mock", "llm_record": False})
    )
    calls = []
    original = chain.complete_structured

    async def captured(messages, schema, profile, **kwargs):
        started = time.monotonic()
        try:
            result = await original(messages, schema, profile, **kwargs)
            calls.append(
                {
                    "role": profile.role,
                    "requested_model": profile.model,
                    "context": kwargs.get("context", "default"),
                    "schema": schema.get("$id") or schema.get("title"),
                    "obj": result.obj,
                    "source": result.usage.source,
                    "model": result.usage.model,
                    "usage": result.usage.as_dict(),
                    "attempts": [vars(a) for a in result.attempts],
                    "seconds": round(time.monotonic() - started, 3),
                }
            )
            return result
        except Exception as exc:
            calls.append(
                {
                    "role": profile.role,
                    "requested_model": profile.model,
                    "error": type(exc).__name__,
                    "seconds": round(time.monotonic() - started, 3),
                }
            )
            raise

    chain.complete_structured = captured
    app.state.llm_chain = chain
    app.state.llm_profile = default_profile(s)
    svc = app.state.agent = AgentService(chain, app.state.llm_profile)
    sim = app.state.sim = Simulator()
    await sim.load_state()
    await refresh(app, s, required=True)
    print(
        "PROFILES",
        [(role, p.provider, p.model) for role, p in chain.role_profiles.items()],
        flush=True,
    )
    for p in chain.providers:
        if p.name == "gigachat":
            print(
                "PREPARED",
                await p.prepare(list(chain.role_profiles.values())),
                flush=True,
            )
    request = Request({"type": "http", "app": app, "headers": []})
    await delete_demo_execution(request)
    cases = [
        (x["id"], "on_time")
        for x in scenarios.load_all()
        if x["id"].startswith("demo20_")
    ]
    cases += [
        ("demo20_11_mobile_crash", x)
        for x in ("late", "no_work", "failed", "recovered")
    ] + [("branch_misselling", "on_time")]
    if ARGS.matrix:
        cases = [
            (x["id"], outcome)
            for x in scenarios.load_all()
            if x["id"].startswith("demo20_")
            for outcome in ("on_time", "late", "no_work", "failed", "recovered")
        ]
    if ARGS.case:
        cases = [tuple(x.split(":")) for x in ARGS.case]
    failed_cases = 0
    try:
        for sid, outcome in cases:
            calls.clear()
            started = time.monotonic()
            state = {}
            error = None
            print("START", sid, outcome, flush=True)
            try:
                async with asyncio.timeout(300):
                    state = await post_demo_execution(
                        request,
                        DemoExecutionBody(
                            scenario_id=sid, team_outcome=outcome, emulate_humans=True
                        ),
                    )
                    for _ in range(240):
                        if svc._inflight:
                            await asyncio.gather(*list(svc._inflight))
                        await cycle(app)
                        state = await get_demo_execution(request)
                        if not state["configuration"].get("enabled"):
                            break
                        await asyncio.sleep(0.1)
            except Exception as exc:  # noqa: BLE001 — сохраняем ошибку кейса, остальные кейсы должны провериться
                error = type(exc).__name__ + ": " + str(exc)
                traceback.print_exc()
            rid = state.get("run_id") or sim.run_id
            try:
                data = await snapshot(rid, s)
            except Exception as exc:  # noqa: BLE001 — сохраняем ошибку кейса, остальные кейсы должны провериться
                data = {"snapshot_error": str(exc)}
                error = error or str(exc)
            success = outcome not in ("no_work", "failed")
            checks = {
                "finished": state.get("configuration", {}).get("status") == "finished",
                "incident_exists": bool(data.get("incidents")),
                "expected_incident_state": bool(data.get("incidents"))
                and all(
                    (i["status"] == "closed") == success for i in data["incidents"]
                ),
                "employees_decided": all(
                    x["decision"]
                    and x["decided_by"]
                    and (
                        not x["decided_by"].startswith("demo-agent")
                        or x["use_as_fewshot"] is False
                    )
                    for x in data.get("employees", [])
                ),
                "all_signals_final_reply": bool(data.get("signals"))
                and all(
                    any(
                        n["signal_id"] == x["id"]
                        and n["template_code"]
                        == ("resolved" if success else "demo_unresolved")
                        and n["status"] in ("sent", "delivered")
                        for n in data.get("notifications", [])
                    )
                    for x in data["signals"]
                ),
                "all_llm_live": bool(calls)
                and all(x.get("source") == "live" for x in calls),
                "tickets_match": bool(data.get("tickets"))
                and all((t["status"] == "closed") == success for t in data["tickets"]),
                "verified_before_closed": all(
                    any(
                        a["incident_id"] == i["id"]
                        and a["kind"] == "verification_report"
                        for a in data.get("artifacts", [])
                    )
                    for i in data.get("incidents", [])
                    if i["status"] == "closed"
                ),
                "canonical_result_used": all(
                    i["resolution_summary"]
                    and all(
                        i["resolution_summary"] in notice["body"]
                        for notice in data.get("notifications", [])
                        if notice["incident_id"] == i["id"]
                        and notice["template_code"] == "resolved"
                    )
                    for i in data.get("incidents", [])
                    if i["status"] == "closed"
                ),
                "expected_sla": all(
                    bool(i["sla_breached"]) == (outcome != "on_time")
                    for i in data.get("incidents", [])
                ),
                "all_role_outputs_live": all(
                    artifact["meta"].get("source") == "live"
                    and artifact["meta"].get("grounded")
                    for artifact in data.get("artifacts", [])
                    if artifact["meta"].get("content_source") != "verified_facts"
                )
                and all(
                    step["output"].get("source") == "live"
                    and step["output"].get("grounded")
                    for step in data.get("steps", [])
                    if "confirmed" in (step.get("output") or {})
                    and step["output"].get("content_source") != "verified_facts"
                ),
                "no_failed_agent_runs": not any(
                    x["outcome"] == "failed" for x in data.get("runs", [])
                ),
            }
            result = {
                "scenario_id": sid,
                "outcome": outcome,
                "run_id": rid,
                "seconds": round(time.monotonic() - started, 3),
                "error": error,
                "checks": checks,
                "calls": list(calls),
                **data,
            }
            (OUT / f"{sid}-{outcome}-run{rid}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2, default=str)
            )
            print(
                "RESULT",
                json.dumps(
                    {
                        k: result[k]
                        for k in (
                            "scenario_id",
                            "outcome",
                            "run_id",
                            "seconds",
                            "error",
                            "checks",
                        )
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            failed_cases += int(bool(error) or not all(checks.values()))
            await delete_demo_execution(request)
    finally:
        await svc.stop()
        await sim.shutdown()
        for provider in chain.providers:
            close = getattr(provider, "aclose", None)
            if close:
                await close()
        await guard.close()
    return int(failed_cases > 0)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
