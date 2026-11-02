"""T-240: настоящая PG16 migration, legacy preservation и границы запуска."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from app.contracts.enums import Criticality, ProductLine, Sentiment
from app.corpus.history import ActualSignal, HistoryConfig, build_history
from app.corpus.history_store import load_history, save_history, summarize_history
from tests.helpers import dsn, new_run

SQL = (Path(__file__).resolve().parents[3] / "contracts/db/migrations/0014_product_history_scope.sql").read_text()


@pytest.mark.asyncio
async def test_actual_legacy_upgrade_reapply_guards_and_run_isolation(seeded: str) -> None:
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run = await new_run(conn, "T240 history owner", kind="free")
        other = await new_run(conn, "T240 history foreign", kind="free")
        # Изолированная namespace моделирует старую таблицу без изменений общей fixture.
        schema = "t240_legacy_" + uuid4().hex
        await conn.execute(psycopg.sql.SQL("create schema {}").format(psycopg.sql.Identifier(schema)))
        await conn.execute("select set_config('search_path',%s,true)", (schema + ",public",))
        await conn.execute("""create table product_signal_history (
            id bigint generated always as identity primary key,
            product_line_code text not null references public.product_lines(code), month date not null,
            signal_count integer not null default 0, negative_count integer not null default 0,
            critical_count integer not null default 0, by_source jsonb not null default '{}',
            loss_rub numeric(14,2) not null default 0, is_synthetic boolean not null default false,
            constraint operator_custom_unique unique(month,product_line_code))""")
        await conn.execute(
            "insert into product_signal_history(product_line_code,month,signal_count) values ('deposits','2025-01-01',7)"
        )
        legacy = await (await conn.execute("select id,signal_count,loss_rub from product_signal_history")).fetchone()
        await conn.execute(SQL)
        await conn.execute(SQL)
        assert (
            await (await conn.execute("select id,signal_count,loss_rub from product_signal_history")).fetchone()
            == legacy
        )
        row = await (
            await conn.execute(
                "select run_id,sentiment_known_count,coverage_start,is_partial from product_signal_history"
            )
        ).fetchone()
        assert row == (None, None, None, None)
        now = dt.datetime(2026, 3, 5, tzinfo=dt.UTC)

        def history(owner):
            return build_history(
                seed=42,
                run_id=owner,
                anchor=now,
                actual=[
                    ActualSignal(
                        owner,
                        ProductLine.DEPOSITS,
                        now - dt.timedelta(days=1),
                        None,
                        Criticality.HIGH,
                        Sentiment.NEGATIVE,
                    )
                ],
                product_lines=frozenset({ProductLine.DEPOSITS}),
                known_platforms=frozenset(),
                fault_months=frozenset(),
                config=HistoryConfig((1.0,) * 12, 2.0, 0.0),
            )

        await save_history(conn, history(run).rows)
        await save_history(conn, history(run).rows)
        await save_history(conn, history(other).rows)
        assert len(await load_history(conn, scope=run)) == 12
        assert len(await load_history(conn, scope=other)) == 12
        all_rows = await load_history(conn, scope="all")
        assert len(all_rows) == 25
        assert summarize_history(all_rows)["unknown_count"] is None
        with pytest.raises(ValueError):
            await load_history(conn, scope=None)  # type: ignore[arg-type]
        for statement in (
            "insert into product_signal_history(product_line_code,month) values ('deposits','2024-01-01')",
            "update product_signal_history set signal_count=signal_count where run_id is null",
            "update product_signal_history set sentiment_known_count=null where run_id is not null",
            "update product_signal_history set negative_count=signal_count+1 where run_id is not null",
            "update product_signal_history set coverage_end=coverage_start where run_id is not null",
            "update product_signal_history set is_partial=not is_partial where run_id is not null",
        ):
            with pytest.raises(psycopg.errors.CheckViolation):
                async with conn.transaction():
                    await conn.execute(statement)
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            async with conn.transaction():
                await conn.execute(
                    "update product_signal_history set run_id=9223372036854775807 where run_id=%s", (run,)
                )
        # Удаляем не текущий запуск; lifecycle pointer не относится к history CASCADE.
        await conn.execute("update public.sim_state set current_run_id=%s where current_run_id=%s", (run, other))
        await conn.execute("delete from public.sim_runs where id=%s", (other,))
        assert await load_history(conn, scope=other) == []
        assert len(await load_history(conn, scope="all")) == 13
        await conn.rollback()
