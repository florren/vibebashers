"""Прогон демо-сценария на работающем стенде и сверка ожиданий (L5, T-142 — ручной/вечерний прогон).

Использование:
  python scripts/scenario_check.py 2                 # сценарий № 2 на http://localhost:8000
  python scripts/scenario_check.py all --base http://localhost:8011 --wait 20
Нужен DATABASE_URL (для проверки ожиданий читаем БД напрямую). Коды возврата: 0 — все проверяемые ожидания выполнены, 1 — есть провалы.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

import httpx
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.sim import scenarios as sc  # noqa: E402


def _dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


async def _wait_runs(dsn: str, run_id: int, expected: int, timeout: float) -> None:
    t0 = time.time()
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        while time.time() - t0 < timeout:
            row = await (
                await conn.execute(
                    "select count(*) from agent_runs where sim_run_id = %s and outcome in ('completed','awaiting_human','deferred','error','failed')",
                    (run_id,),
                )
            ).fetchone()
            if row and int(row[0]) >= expected:
                return
            await asyncio.sleep(0.5)


async def _wait_transcript(dsn: str, run_id: int, timeout: float) -> None:
    t0 = time.time()
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        while time.time() - t0 < timeout:
            row = await (
                await conn.execute(
                    "select count(*) from transcripts where run_id = %s and source = 'scenario' and status in ('done','failed')",
                    (run_id,),
                )
            ).fetchone()
            if row and int(row[0]) >= 1:
                return
            await asyncio.sleep(0.5)


async def _wait_scripted(dsn: str, run_id: int, timeout: float) -> None:
    # Existing --wait bound, no HTTP/provider retries. Missing/failed phase
    # evaluator ниже оставит FAIL, в том числе после timeout.
    deadline = time.monotonic() + timeout
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        while time.monotonic() < deadline:
            row = await (
                await conn.execute(
                    "select 1 from sim_events where run_id=%s and event_type in "
                    "('scenario.proactive_completed','scenario.proactive_failed') limit 1",
                    (run_id,),
                )
            ).fetchone()
            if row:
                return
            await asyncio.sleep(0.5)


async def run_one(base: str, dsn: str, scenario: dict, wait: float) -> bool:
    if scenario.get("kind") == "read_model" and scenario["id"] == "customer_journey":
        from scripts.journey_check import run_journeys

        return await run_journeys(base, dsn, scenario)
    if scenario.get("kind") == "read_model" and scenario["id"] == "search_and_trace":
        from scripts.read_model_check import run_search_trace

        return await run_search_trace(base, dsn, scenario)
    async with httpx.AsyncClient(base_url=base, timeout=60) as http:
        r = await http.post(f"/api/scenarios/{scenario['id']}/run", json={})
        if r.status_code == 501:
            why = r.json().get("detail") or r.text[:80]
            print(  # noqa: T201
                f"  [{scenario['number']:>2}] FAIL {scenario['title_ru']}: сценарий не выполнен — {why}"
            )
            return False
        r.raise_for_status()
        run_id = int(r.json()["run"]["id"])
    if "script" in scenario:
        await _wait_scripted(dsn, run_id, wait)
    elif sc.is_transcript(scenario):
        await _wait_transcript(dsn, run_id, wait)
    else:
        await _wait_runs(dsn, run_id, len(scenario.get("inject") or []), wait)
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        res = await sc.evaluate(conn, scenario, run_id)
        if scenario.get("kind") == "acceptance":
            from scripts.acceptance_check import verify_reads

            header = await (
                await conn.execute("select settings_snapshot->'t262_inputs' from sim_runs where id=%s", (run_id,))
            ).fetchone()
            refs = await (
                await conn.execute("select public_id from signals where run_id=%s order by id", (run_id,))
            ).fetchall()
            async with httpx.AsyncClient(base_url=base, timeout=60) as http:
                res["checks"].extend(
                    await verify_reads(
                        http, scenario["id"], run_id, header[0] if header else None, [r[0] for r in refs]
                    )
                )
            res["passed"] = res["passed"] and all(c["ok"] is True for c in res["checks"])
            print("        T262: только Mock foundation; UI/replay not_verified")  # noqa: T201
        await sc.save_result(conn, scenario["id"], res)
        await conn.commit()
    mark = "OK " if res["passed"] else "FAIL"
    print(  # noqa: T201
        f"  [{scenario['number']:>2}] {mark} {scenario['title_ru']} (run {run_id}; {res['counts']})"
    )
    for c in res["checks"]:
        sym = "✓" if c["ok"] else ("·" if c["ok"] is None else "✗")
        print(f"        {sym} {c['code']}: {c['detail']}")  # noqa: T201
    return bool(res["passed"])


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("which", help="номер сценария, id или all")
    ap.add_argument("--base", default=os.environ.get("CX_BASE_URL", "http://localhost:8000"))
    ap.add_argument(
        "--recording-source",
        choices=("replay", "live"),
        default="replay",
        help="источник записанных путей сценария12; не запускает LLM",
    )
    ap.add_argument(
        "--wait",
        type=float,
        default=30,
        help="сколько секунд ждать агента на один сценарий",
    )
    a = ap.parse_args()
    dsn = _dsn(os.environ.get("DATABASE_URL") or "postgresql://cx:cx@localhost:5432/cx_pulse")
    items = sc.load_all()
    if a.which != "all":
        items = [
            s for s in items if str(s.get("number")) == a.which or s["id"] == a.which or a.which in s.get("aliases", [])
        ]
        if not items:
            print(f"сценарий {a.which} не найден")  # noqa: T201
            return 2
    ok = True
    for s in items:
        ok = await run_one(a.base, dsn, {**s, "_recording_source": a.recording_source}, a.wait) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
