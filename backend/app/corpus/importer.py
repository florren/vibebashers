"""Отзывы импортируются одной внешней транзакцией только через normalizer."""

from __future__ import annotations

import re
from typing import Any

import psycopg

from app.corpus.reviews import CorpusError, ReviewRow, message
from app.ingest.normalizer import IngestError, create_signal


async def import_reviews(
    conn: psycopg.AsyncConnection[Any],
    rows: list[ReviewRow],
    *,
    run_id: int,
    source_code: str,
    timezone: str | None = None,
) -> dict[str, int]:
    if not 1 <= len(rows) <= 10_000 or len({x.external_id for x in rows}) != len(rows):
        raise CorpusError("ожидается ограниченный набор отзывов с уникальными external_id")
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", source_code):
        raise CorpusError("некорректный source_code")
    # Подготовка ВСЕХ строк до первого эффекта, включая валидацию run_id/date.
    prepared = [message(row, run_id=run_id, timezone=timezone) for row in rows]
    counts = {"accepted": 0, "duplicates": 0}
    async with conn.transaction():
        exists = await (await conn.execute("select id from sim_runs where id=%s for key share", (run_id,))).fetchone()
        if not exists:
            raise CorpusError("run_id отсутствует")
        # Один источник в одном запуске не создаёт конкурирующих одинаковых сигналов.
        await conn.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s,0))", (f"review-import:{source_code}:{run_id}",)
        )
        await conn.execute(
            "insert into ingest_sources(code,kind,channel_code,enabled,is_external) "
            "values(%s,'file','review_portal',false,false) on conflict(code) do nothing",
            (source_code,),
        )
        source = await (await conn.execute("select kind from ingest_sources where code=%s", (source_code,))).fetchone()
        if source != ("file",):
            raise CorpusError("source_code уже занят адаптером другого типа")
        for msg, at in prepared:
            try:
                result = await create_signal(conn, msg, source_code=source_code, run_id=run_id, sim_time=at)
            except IngestError as exc:
                raise CorpusError("normalizer отклонил строку; весь импорт отменён") from exc
            if result["status"] == "accepted":
                counts["accepted"] += 1
            elif result["status"] == "duplicate":
                counts["duplicates"] += 1
            else:
                raise CorpusError("normalizer отклонил строку; весь импорт отменён")
    return counts
