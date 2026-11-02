"""T-240: транзакционное хранение истории и явная граница legacy/all."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.corpus.history import HistoryRow


async def save_history(conn: psycopg.AsyncConnection[Any], rows: Sequence[HistoryRow]) -> None:
    """Запись принадлежит внешней транзакции seed; повтор заменяет только тот же ключ."""
    if conn.autocommit:
        raise ValueError("history write требует внешнюю транзакцию")
    for row in rows:
        await conn.execute(
            "insert into product_signal_history (run_id,product_line_code,month,signal_count,negative_count,"
            "sentiment_known_count,critical_count,by_source,is_synthetic,is_partial,coverage_start,coverage_end,loss_rub) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "on conflict (run_id,product_line_code,month) do update set "
            "signal_count=excluded.signal_count,negative_count=excluded.negative_count,"
            "sentiment_known_count=excluded.sentiment_known_count,critical_count=excluded.critical_count,"
            "by_source=excluded.by_source,is_synthetic=excluded.is_synthetic,is_partial=excluded.is_partial,"
            "coverage_start=excluded.coverage_start,coverage_end=excluded.coverage_end,loss_rub=excluded.loss_rub",
            (
                row.run_id,
                row.product_line.value,
                row.month,
                row.signal_count,
                row.negative_count,
                row.sentiment_known_count,
                row.critical_count,
                Jsonb(row.by_source),
                row.is_synthetic,
                row.is_partial,
                row.coverage_start,
                row.coverage_end,
                row.loss_rub,
            ),
        )


async def load_history(conn: psycopg.AsyncConnection[Any], *, scope: int | Literal["all"]) -> list[dict[str, Any]]:
    """Неизвестный owner включается только по явному all, никогда по умолчанию."""
    if scope != "all" and (isinstance(scope, bool) or not isinstance(scope, int) or scope <= 0):
        raise ValueError("history scope должен быть положительным run_id или явным all")
    where, params = ("", ()) if scope == "all" else ("where run_id=%s", (scope,))
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "select * from product_signal_history " + where + " order by month,product_line_code,id", params
        )
        return list(await cur.fetchall())


def summarize_history(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """При неизвестном качестве хотя бы одной строки итог не выдаётся за измерение."""
    total = sum(row["signal_count"] for row in rows)
    known = all(row["sentiment_known_count"] is not None for row in rows)
    known_count = sum(row["sentiment_known_count"] for row in rows) if known else None
    observed_loss = all(row["run_id"] is not None and row["loss_rub"] is not None for row in rows)
    return {
        "signal_count": total,
        "sentiment_known_count": known_count,
        "negative_count": sum(row["negative_count"] for row in rows) if known else None,
        "unknown_count": total - known_count if known_count is not None else None,
        "sentiment_quality": "known" if known else "unknown",
        "loss_rub": sum((row["loss_rub"] for row in rows), Decimal(0)) if observed_loss else None,
    }
