"""T238 prerequisite: реальная физическая projection и узкая editorial provenance."""

import asyncio

import psycopg
import pytest

from app.agent.classification_store import save
from tests.helpers import dsn


def test_verified_editorial_native_and_csi_are_preserved(seeded):
    async def check():
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            rows = await (
                await conn.execute(
                    "select distinct on(im.source_code) s.id,s.product_line_code from signals s join ingest_messages im on im.signal_id=s.id where s.meta->'seed_annotation'->>'source'='editorial_seed_gold' and im.source_code in('product_review_seed','csi') order by im.source_code,s.id"
                )
            ).fetchall()
            assert len(rows) == 2
            for signal_id, line in rows:
                await save(conn, signal_id, {"product_line": "not_catalogued"}, status="classified")
                row = await (
                    await conn.execute("select product_line_code,classification from signals where id=%s", (signal_id,))
                ).fetchone()
                assert row == (line, {"product_line": "not_catalogued"})

    asyncio.run(check())


@pytest.mark.parametrize(
    "damage", ["receipt_missing", "receipt_mismatch", "source", "instance", "ordinary_baseline", "forged_scenario"]
)
def test_incomplete_or_forged_provenance_never_preserves_known_code(seeded, damage):
    async def check():
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            signal_id, run = await (
                await conn.execute(
                    "select s.id,s.run_id from signals s join ingest_messages im on im.signal_id=s.id where s.meta->'seed_annotation'->>'source'='editorial_seed_gold' and im.source_code='product_review_seed' order by s.id limit 1"
                )
            ).fetchone()
            if damage == "receipt_missing":
                await conn.execute("delete from settings where key='seed_product_reviews:'||%s::text", (run,))
            elif damage == "receipt_mismatch":
                await conn.execute(
                    "update settings set value=jsonb_set(value,'{offset_seconds}','123456') where key='seed_product_reviews:'||%s::text",
                    (run,),
                )
            elif damage == "source":
                await conn.execute("update ingest_messages set source_code='api' where signal_id=%s", (signal_id,))
            elif damage == "instance":
                await conn.execute(
                    "update signals set meta=jsonb_set(meta,'{seed_instance,canonical_review_id}','\"forged\"') where id=%s",
                    (signal_id,),
                )
            elif damage == "ordinary_baseline":
                await conn.execute("update signals set meta=meta-'seed_annotation' where id=%s", (signal_id,))
            else:
                # Та же raw annotation в сценарном header не делает editorial authority.
                await conn.execute("update sim_runs set kind='free' where id=%s", (run,))
            await save(conn, signal_id, {"product_line": "not_catalogued"})
            assert (
                await (await conn.execute("select product_line_code from signals where id=%s", (signal_id,))).fetchone()
            )[0] is None
            await conn.rollback()  # Исходные seed facts не удаляются этим контрпримером.

    asyncio.run(check())


def test_runtime_known_unknown_and_missing_line_are_explicit_null(seeded):
    async def check():
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            signal_id = (
                await (
                    await conn.execute(
                        "select id from signals where meta->'seed_annotation' is null order by id limit 1"
                    )
                ).fetchone()
            )[0]
            await save(conn, signal_id, {"product_line": "deposits"}, status="classified", decision={"test": True})
            assert (
                await (await conn.execute("select product_line_code from signals where id=%s", (signal_id,))).fetchone()
            )[0] == "deposits"
            for classification in (
                {"product_line": "not_catalogued"},
                {},
                {"product_line": None},
                {"product_line": True},
            ):
                await save(conn, signal_id, classification)
                row = await (
                    await conn.execute("select product_line_code,decision from signals where id=%s", (signal_id,))
                ).fetchone()
                assert row == (None, {"test": True})

    asyncio.run(check())


def test_native_mock_direction_reaches_manager_report_without_output_override(seeded):
    from io import BytesIO

    from fastapi.testclient import TestClient
    from openpyxl import load_workbook

    from app.main import create_app
    from tests.helpers import new_run, run_agent_on, sim_now
    from tests.integration.test_cabinet_api import fingerprint

    async def produce():
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            client = (
                await (
                    await conn.execute("select id from clients where segment_code='mass' order by id limit 1")
                ).fetchone()
            )[0]
            run = await new_run(conn, "T238 native projection", kind="free")
            signal_id, state = await run_agent_on(
                conn,
                "Не могу открыть вклад, ошибка DEP-TIMEOUT-503. Подаю в суд и обращусь в налоговую.",
                client_id=client,
                run_id=run,
                sim_time=await sim_now(conn),
            )
            assert not state["errors"] and state["outcome"] == "awaiting_human"
            row = await (
                await conn.execute("select product_line_code,public_id from signals where id=%s", (signal_id,))
            ).fetchone()
            assert row[0] == state["classification"]["product_line"] == "deposits"
            return run, row[1]

    run, ref = asyncio.run(produce())
    headers = {"X-Cx-Role": "product_manager", "X-Cx-Product-Line": "deposits"}
    params = {"run_id": str(run), "product_line": "deposits", "period": "day"}
    with TestClient(create_app()) as client, psycopg.connect(dsn(seeded)) as sql:
        before = fingerprint(sql)
        overview = client.get("/api/cabinet/overview", params=params, headers=headers)
        assert overview.status_code == 200, overview.text
        report = client.get("/api/cabinet/report", params=params, headers=headers)
        assert report.status_code == 200, report.text
        assert ref in {row["public_id"] for row in report.json()["signals"]}
        assert report.json()["overview"] == overview.json()
        xlsx = client.get("/api/cabinet/report", params={**params, "format": "xlsx"}, headers=headers)
        assert xlsx.status_code == 200
        workbook = load_workbook(BytesIO(xlsx.content), read_only=True, data_only=False)
        try:
            assert any(ref == cell.value for row in workbook["Сигналы"] for cell in row)
        finally:
            workbook.close()
        assert fingerprint(sql) == before
