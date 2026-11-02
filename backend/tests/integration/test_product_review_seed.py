"""T-240: фактическая baseline матрица, receipt и точный хвост истории."""

from __future__ import annotations

from collections import Counter

import psycopg
import pytest

from tests.helpers import dsn


@pytest.mark.asyncio
async def test_actual_seed_coverage_tail_and_repeat_preserve_original_cohort(seeded: str) -> None:
    from scripts.seed.reviews import _seed

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, seed, anchor = await (
            await conn.execute("select id,seed,finished_sim from sim_runs where kind='baseline' order by id limit 1")
        ).fetchone()
        before = await (
            await conn.execute(
                "select id,text,status,classification,meta,received_sim from signals where run_id=%s order by id",
                (run,),
            )
        ).fetchall()
        historical = await (
            await conn.execute("select * from product_signal_history where run_id=%s order by id", (run,))
        ).fetchall()
        await _seed(conn, run_id=run, seed=seed, anchor=anchor)
        assert (
            await (
                await conn.execute(
                    "select id,text,status,classification,meta,received_sim from signals where run_id=%s order by id",
                    (run,),
                )
            ).fetchall()
            == before
        )
        assert (
            await (
                await conn.execute("select * from product_signal_history where run_id=%s order by id", (run,))
            ).fetchall()
            == historical
        )
        original = [
            row for row in before if (row[4] or {}).get("generator_hint") and not (row[4] or {}).get("t240_supplement")
        ]
        assert len(original) == 800
        receipt = (
            await (
                await conn.execute("select value from settings where key=%s", (f"seed_product_reviews:{run}",))
            ).fetchone()
        )[0]
        assert receipt["canonical_reviews"] == 162 and receipt["coverage_instances"] == 151
        assert receipt["moved_instance"] is True and receipt["history_rows"] == 180
        cells = await (
            await conn.execute(
                "select distinct product_line_code,channel_code from signals where run_id=%s and product_line_code is not null",
                (run,),
            )
        ).fetchall()
        assert len(cells) == 180
        real = await (
            await conn.execute(
                "select product_line_code,coalesce(meta->>'source_platform','unknown'),coalesce(classification->>'criticality','unknown'),count(*) from signals where run_id=%s and product_line_code is not null and received_sim>=%s-interval '14 days' and received_sim<%s group by 1,2,3",
                (run, anchor, anchor),
            )
        ).fetchall()
        expected = Counter({(line, source, severity): count for line, source, severity, count in real})
        found = Counter()
        tail = await (
            await conn.execute(
                "select product_line_code,signal_count,negative_count,sentiment_known_count,by_source,loss_rub from product_signal_history where run_id=%s and not is_synthetic",
                (run,),
            )
        ).fetchall()
        for line, total, negative, known, buckets, loss in tail:
            assert 0 <= negative <= known <= total and loss is None
            for source, severities in buckets.items():
                for severity, count in severities.items():
                    found[line, source, severity] += count
        assert found == expected  # Все реальные line/source/severity ячейки, расхождение 0%.
        assert sum(count for count in found.values()) == 313
        assert all(row[2] == "classified" for row in before if (row[4] or {}).get("seed_annotation"))
        audio = await (
            await conn.execute(
                "select count(*) from signals where run_id=%s and meta?'seed_instance' and channel_code in ('voice_input','branch_audio') and (voice_meta is not null or transcript_id is not null)",
                (run,),
            )
        ).fetchone()
        assert audio == (0,)
        csi = await (
            await conn.execute(
                "select count(*) from signals s join csi_responses cr on cr.signal_id=s.id join branches b on b.id=cr.branch_id where s.run_id=%s and s.meta?'seed_instance' and s.channel_code='csi_survey'",
                (run,),
            )
        ).fetchone()
        assert csi == (15,)


@pytest.mark.asyncio
async def test_seed_failure_rolls_back_receipt_and_all_new_signals_then_retry(seeded: str, monkeypatch) -> None:
    from scripts.seed import reviews

    from tests.helpers import new_run

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        anchor = (await (await conn.execute("select sim_time from sim_state where id=1")).fetchone())[0]
        run = await new_run(conn, "T240 atomic stage", kind="baseline")
        original_save = reviews.save_history

        async def fail_save(*args, **kwargs):
            raise RuntimeError("injected history write failure")

        monkeypatch.setattr(reviews, "save_history", fail_save)
        with pytest.raises(RuntimeError, match="injected history"):
            async with conn.transaction():
                await reviews._seed(conn, run_id=run, anchor=anchor, seed=42)
        assert await (await conn.execute("select count(*) from signals where run_id=%s", (run,))).fetchone() == (0,)
        assert await (
            await conn.execute("select count(*) from settings where key=%s", (f"seed_product_reviews:{run}",))
        ).fetchone() == (0,)
        monkeypatch.setattr(reviews, "save_history", original_save)
        await reviews._seed(conn, run_id=run, anchor=anchor, seed=42)
        assert await (
            await conn.execute("select count(*) from product_signal_history where run_id=%s", (run,))
        ).fetchone() == (180,)
        before = await (await conn.execute("select count(*) from signals where run_id=%s", (run,))).fetchone()
        await reviews._seed(conn, run_id=run, anchor=anchor, seed=42)
        assert await (await conn.execute("select count(*) from signals where run_id=%s", (run,))).fetchone() == before
