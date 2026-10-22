"""Отчёт о качестве на реальной схеме: все SQL-агрегаты выполняются, Markdown рендерится (docs/REPORTS.md)."""

from __future__ import annotations

import psycopg
import pytest
from psycopg.rows import dict_row

from app.observability.quality import build_quality_report, render_markdown
from tests.helpers import dsn


@pytest.mark.integration
@pytest.mark.asyncio
async def test_quality_report_on_seeded_db(seeded: str) -> None:
    async with await psycopg.AsyncConnection.connect(dsn(seeded), row_factory=dict_row) as conn:
        rep = await build_quality_report(conn, None, include_http=False)
        run_id = (await (await conn.execute("select max(id) from sim_runs")).fetchone()) or {}
        rid = next(iter(run_id.values()), None)
        if rid:
            scoped = await build_quality_report(conn, int(rid), include_http=True)
            assert scoped["summary"]["run_id"] == int(rid) and scoped["http"] is not None
    assert rep["version"] == "quality-v1" and 0 <= rep["summary"]["health"] <= 100
    assert rep["recommendations"] and {"severity", "area", "text", "where"} <= set(rep["recommendations"][0])
    assert len(rep["scenarios"]) >= 11
    md = render_markdown(rep)
    assert md.startswith("# Отчёт о качестве") and "## Что доработать" in md
