"""T-240: настоящий normalizer/PG, отделённый gold и атомарный повтор импорта."""

from __future__ import annotations

import asyncio
import datetime as dt
from pathlib import Path

import psycopg
import pytest

from app.contracts.enums import Channel, Criticality
from app.corpus.importer import import_reviews
from app.corpus.reviews import CorpusError, parse_reviews
from app.corpus.seed_plan import apply_seed_projection
from tests.helpers import dsn, new_run

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "data/corpus/reviews/product_lines_v1/reviews.json"


@pytest.mark.asyncio
async def test_actual_reviews_date_idempotence_and_run_isolation(seeded: str) -> None:
    rows = parse_reviews(CORPUS)
    async with await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True) as conn:
        run_id = await new_run(conn, "T240 imports", kind="free")
        assert await import_reviews(conn, rows, run_id=run_id, source_code="test_reviews") == {
            "accepted": 162,
            "duplicates": 0,
        }
        assert await import_reviews(conn, rows, run_id=run_id, source_code="test_reviews") == {
            "accepted": 0,
            "duplicates": 162,
        }
        stored = await (
            await conn.execute(
                "select s.received_sim,s.meta,s.product_line_code,s.classification from signals s "
                "join ingest_messages m on m.signal_id=s.id where m.source_code='test_reviews' and m.external_id=%s",
                (f"run:{run_id}:{rows[0].external_id}",),
            )
        ).fetchone()
        assert stored is not None
        assert stored[0] == dt.datetime.fromisoformat(rows[0].date)
        assert stored[1]["source_url"] == rows[0].source_url and stored[1]["source_date"] == rows[0].date
        assert stored[1]["source_platform"] == rows[0].source_platform and "gold" not in stored[1]
        assert stored[2] is None and not (stored[3] or {}).get("product_line")
        second = await new_run(conn, "T240 separate run", kind="free")
        assert await import_reviews(conn, rows[:1], run_id=second, source_code="test_reviews") == {
            "accepted": 1,
            "duplicates": 0,
        }
        assert (
            await (
                await conn.execute(
                    "select count(*) from ingest_messages where source_code='test_reviews' and run_id=%s", (run_id,)
                )
            ).fetchone()
        )[0] == 162


@pytest.mark.asyncio
async def test_invalid_csi_context_rolls_back_entire_file(seeded: str) -> None:
    row = parse_reviews(CORPUS)[0]
    bad = row.model_copy(update={"external_id": "BAD-CSI", "channel": Channel.CSI_SURVEY})
    async with await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True) as conn:
        run_id = await new_run(conn, "T240 rollback", kind="free")
        before = (await (await conn.execute("select count(*) from signals where run_id=%s", (run_id,))).fetchone())[0]
        with pytest.raises(CorpusError, match="весь импорт отменён"):
            await import_reviews(conn, [row, bad], run_id=run_id, source_code="rollback_reviews")
        assert (await (await conn.execute("select count(*) from signals where run_id=%s", (run_id,))).fetchone())[
            0
        ] == before
        assert (
            await (await conn.execute("select 1 from ingest_sources where code='rollback_reviews'")).fetchone() is None
        )
        with pytest.raises(CorpusError, match="run_id отсутствует"):
            await import_reviews(conn, [row], run_id=2_000_000_000, source_code="missing_run")


@pytest.mark.asyncio
async def test_seed_projection_baseline_only_red_word_priority(seeded: str) -> None:
    original = parse_reviews(CORPUS)[0]
    assert original.gold is not None
    row = original.model_copy(
        update={"external_id": "RED-WORD", "text": "Подам заявление в суд, если банк не объяснит условия вклада."}
    )
    low_gold = original.gold.model_copy(update={"criticality": Criticality.LOW})
    async with await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True) as conn:
        baseline = (
            await (await conn.execute("select id from sim_runs where kind='baseline' order by id limit 1")).fetchone()
        )[0]
        await import_reviews(conn, [row], run_id=baseline, source_code="seed_reviews")
        signal = (
            await (
                await conn.execute("select signal_id from ingest_messages where source_code='seed_reviews'")
            ).fetchone()
        )[0]
        with pytest.raises(CorpusError, match="внешнюю транзакцию"):
            await apply_seed_projection(conn, run_id=baseline, signal_id=signal, gold=low_gold)
        async with conn.transaction():
            await apply_seed_projection(conn, run_id=baseline, signal_id=signal, gold=low_gold)
        stored = await (
            await conn.execute("select product_line_code,classification,red_words from signals where id=%s", (signal,))
        ).fetchone()
        assert stored[0] == original.gold.product_line.value
        assert stored[1]["criticality"] == stored[1]["signal_level"] == "high" and stored[2]
        free = await new_run(conn, "T240 runtime not seed", kind="free")
        await import_reviews(conn, [row], run_id=free, source_code="runtime_reviews")
        other = (
            await (
                await conn.execute("select signal_id from ingest_messages where source_code='runtime_reviews'")
            ).fetchone()
        )[0]
        with pytest.raises(CorpusError, match="отсутствует в seed run"):
            async with conn.transaction():
                await apply_seed_projection(conn, run_id=free, signal_id=other, gold=low_gold)


@pytest.mark.asyncio
async def test_concurrent_same_source_is_exactly_once(seeded: str) -> None:
    row = parse_reviews(CORPUS)[0]
    async with await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True) as conn:
        run_id = await new_run(conn, "T240 duplicate race", kind="free")

    async def once():
        async with await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True) as connection:
            return await import_reviews(connection, [row], run_id=run_id, source_code="concurrent_reviews")

    results = await asyncio.gather(once(), once())
    assert sum(x["accepted"] for x in results) == sum(x["duplicates"] for x in results) == 1


def test_cli_apply_json_then_csv_same_dataset_is_duplicate(
    seeded: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    import importlib.util
    import json
    import sys

    spec = importlib.util.spec_from_file_location("review_import_cli_pg", ROOT / "scripts/import_reviews.py")
    assert spec is not None and spec.loader is not None
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    with psycopg.connect(dsn(seeded), autocommit=True) as conn:
        run_id = conn.execute("select id from sim_runs where kind='baseline' order by id limit 1").fetchone()[0]
    from openpyxl import Workbook

    data = json.loads((ROOT / "data/import/messages/product_lines_sample.json").read_text())
    workbook = Workbook()
    sheet = workbook.active
    fields = list(data[0])
    sheet.append(fields)
    for row in data:
        sheet.append([json.dumps(row[key]) if key == "gold" else row[key] for key in fields])
    xlsx = tmp_path / "sample.xlsx"
    workbook.save(xlsx)
    workbook.close()
    monkeypatch.setenv("DATABASE_URL", seeded)
    for name, expected in [
        ("product_lines_sample.json", {"accepted": 3, "duplicates": 0}),
        ("product_lines_sample.csv", {"accepted": 0, "duplicates": 3}),
        (str(xlsx), {"accepted": 0, "duplicates": 3}),
    ]:
        path = ROOT / "data/import/messages" / name
        monkeypatch.setattr(sys, "argv", ["import_reviews.py", str(path), "--apply", "--run-id", str(run_id)])
        cli.main()
        assert json.loads(capsys.readouterr().out) == expected
