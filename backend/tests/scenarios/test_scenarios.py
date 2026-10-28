"""Автотесты демо-сценариев ТЗ §18 на mock-модели (T-142).

Каждый сценарий с секцией `inject` в data/scenarios/*.yaml: отдельный запуск → инъекция сообщений → агент → `evaluate`.
Проверки с ok=None (нужны пакеты B05–B09, B14) не считаются провалом, но печатаются в отчёте.
"""

from __future__ import annotations

import psycopg
import pytest

from app.agent.graph import process_signal
from app.compliance.transcripts import analyze_transcript
from app.sim import scenarios as sc
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, sim_now

RUNNABLE = [s for s in sc.load_all() if sc.is_runnable(s)]


@pytest.mark.parametrize("scenario", RUNNABLE, ids=[f"{s['number']:02d}-{s['id']}" for s in RUNNABLE])
async def test_scenario(seeded: str, scenario: dict) -> None:
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run_id = await new_run(conn, f"test {scenario['id']}", scenario_id=scenario["id"])
        now = await sim_now(conn)
        if sc.is_transcript(scenario):
            tr = await sc.inject_transcript(conn, scenario, run_id, sim_time=now)
            await conn.commit()
            res_tr = await analyze_transcript(
                conn, tr["transcript_id"], chain=mock_chain(), profile=MOCK_PROFILE, sim_time=now
            )
            assert res_tr["status"] == "done", res_tr
            if res_tr.get("signal_id"):
                assert await process_signal(
                    conn, signal_id=res_tr["signal_id"], chain=mock_chain(), profile=MOCK_PROFILE
                )
            injected = []
        else:
            injected = await sc.inject(conn, scenario, run_id, sim_time=now)
        await conn.commit()
        for (
            item
        ) in injected:  # последовательно: в проде параллельно, гонку создания инцидента закрывает advisory lock в act
            state = await process_signal(conn, signal_id=item["signal_id"], chain=mock_chain(), profile=MOCK_PROFILE)
            assert state is not None, item
        res = await sc.evaluate(conn, scenario, run_id)
    report = "\n".join(
        f"  {'✓' if c['ok'] else ('·' if c['ok'] is None else '✗')} {c['code']}: {c['detail']}" for c in res["checks"]
    )
    print(f"\n[{scenario['number']}] {scenario['title_ru']}: {res['counts']}\n{report}")  # noqa: T201
    assert res["counts"]["errors"] == 0, report
    failed = [c for c in res["checks"] if c["ok"] is False]
    assert not failed, report


def test_all_scenarios_listed() -> None:
    """Все 13 сценариев ТЗ присутствуют; у незапускаемых указан пакет, который их включит."""
    items = sc.load_all()
    assert [s["number"] for s in items] == list(range(1, 14))
    for s in items:
        if not sc.is_runnable(s):
            assert s.get("requires"), s["id"]
        api = sc.to_api(s)
        assert set(api) == {
            "id",
            "title_ru",
            "title_en",
            "description_ru",
            "duration_sim_hours",
            "last_run_at",
            "last_result",
        }
