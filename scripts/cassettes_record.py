"""Запись replay-кассет для демо-сценария (T-198): live LLM → data/cassettes/*.jsonl и demo_assets.

  make cassettes-record SCENARIO=qr_fee_public_review

Без ключей live — сообщение и код 0 (файлы не создаются). Без DATABASE_URL при наличии ключей — код 2.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.graph import process_signal  # noqa: E402
from app.agent.prompts import prompt_version  # noqa: E402
from app.compliance.transcripts import analyze_transcript  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.llm.failover import build_chain, default_profile, live_recording_possible  # noqa: E402
from app.replay.store import CassetteStore, upsert_demo_asset  # noqa: E402
from app.sim import runs as run_svc  # noqa: E402
from app.sim import scenarios as sc  # noqa: E402


def _dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


async def _sim_now(conn: psycopg.AsyncConnection) -> object:
    row = await (await conn.execute("select sim_time from sim_state where id = 1")).fetchone()
    if not row:
        raise RuntimeError("sim_state не инициализирован — нужен сид/стенд")
    return row[0]


async def _run_scenario(dsn: str, scenario_id: str) -> None:
    settings = get_settings()
    scenario = sc.get(scenario_id)
    assert scenario is not None
    store = CassetteStore(settings.cassettes_dir)
    chain = build_chain(settings)
    chain.record_store = store
    chain.scenario_id = scenario_id
    chain.prompt_version = prompt_version()
    profile = default_profile(settings)

    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        run_id = await run_svc.create_run(
            conn,
            kind="scenario",
            label=f"кассеты {scenario_id}",
            seed=settings.sim_seed,
            sim_time=await _sim_now(conn),
            scenario_id=scenario_id,
        )
        now = await _sim_now(conn)
        if sc.is_transcript(scenario):
            tr = await sc.inject_transcript(conn, scenario, run_id, sim_time=now)
            await analyze_transcript(
                conn,
                tr["transcript_id"],
                chain=chain,
                profile=profile,
                sim_time=now,  # type: ignore[arg-type]
            )
        else:
            injected = await sc.inject(conn, scenario, run_id, sim_time=now)
            for item in injected:
                await process_signal(conn, signal_id=item["signal_id"], chain=chain, profile=profile, sim_time=now)
        await conn.commit()

        asset = store.cassette_asset(scenario_id)
        if asset is not None:
            with psycopg.connect(dsn, autocommit=True) as sync_conn:
                upsert_demo_asset(sync_conn, asset)


async def main() -> int:
    ap = argparse.ArgumentParser(description="Запись кассет replay для демо-сценария")
    ap.add_argument("scenario", nargs="?", default=os.environ.get("SCENARIO"), help="id сценария из data/scenarios")
    args = ap.parse_args()
    if not args.scenario:
        print("укажите SCENARIO=id сценария", file=sys.stderr)  # noqa: T201
        return 1
    if sc.get(args.scenario) is None:
        print(f"неизвестный сценарий: {args.scenario}", file=sys.stderr)  # noqa: T201
        return 2

    settings = get_settings()
    if not live_recording_possible(settings):
        print("live-запись пропущена: нет ключей GigaChat / OpenAI-совместимого провайдера")  # noqa: T201
        return 0

    db_url = os.environ.get("DATABASE_URL") or settings.database_url
    if not db_url:
        print("нет DATABASE_URL", file=sys.stderr)  # noqa: T201
        return 2

    await _run_scenario(_dsn(db_url), args.scenario)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
