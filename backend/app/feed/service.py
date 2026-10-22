"""Публичная лента: external_posts / external_replies, события review.*, правила публичного ответа (ТЗ 9.3, 21.2, 21.5).

Публичный ответ не содержит ПДн (номера карт/телефонов маскируются), не обещает сроков без факта (promise_check),
латентность считается от `posted_at` поста до публикации ответа.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

import psycopg

from app.logging import get_logger
from app.sim.events import EventBus, dumps

log = get_logger(__name__)

PII_RE = re.compile(
    r"\b\d{16}\b|\b\d{4}[ -]\d{4}[ -]\d{4}[ -]\d{4}\b|\+7\s?\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}\b|\b8\d{10}\b"
)
PROMISE_RE = re.compile(r"(гарантиру\w+|обязательно\s+верн\w+|100\s*%|в течение\s+\d+\s+минут)", re.IGNORECASE)
PLATFORM_BY_CHANNEL = {"review_portal": "review_portal", "social": "telegram_channel"}


class FeedError(ValueError):
    """Нарушение правил публичного ответа или отсутствующий пост."""


def _col(row: Any, i: int, key: str) -> Any:
    return row[key] if isinstance(row, dict) else row[i]


def sanitize_public_text(text: str) -> str:
    """Маскирование ПДн и снятие обещаний, которые агент не может гарантировать (promise_check)."""
    out = PII_RE.sub("••••", text or "").strip()
    out = PROMISE_RE.sub("постараемся решить как можно быстрее", out)
    return out[:1500]


async def create_post(
    conn: psycopg.AsyncConnection[Any],
    *,
    run_id: int,
    platform: str,
    author_nick: str,
    text: str,
    posted_sim: dt.datetime,
    origin: str = "api",
    author_client_id: int | None = None,
    match_confidence: float | None = None,
    mentions: dict[str, Any] | None = None,
    reactions: int = 0,
    signal_id: int | None = None,
    emit: bool = True,
) -> dict[str, Any]:
    """Пост на площадке + событие review.posted (топик WebSocket feed)."""
    nick = author_nick if author_nick.startswith("@") else f"@{author_nick}"
    row = await (
        await conn.execute(
            "insert into external_posts (run_id, platform, author_nick, author_client_id, match_confidence, text, mentions, posted_at, posted_sim, reactions, status, signal_id, origin) "
            "values (%s, %s, %s, %s, %s, %s, %s::jsonb, now(), %s, %s, 'new', %s, %s) returning id, public_id, posted_at",
            (
                run_id,
                platform,
                nick,
                author_client_id,
                match_confidence,
                text,
                dumps(mentions or {}),
                posted_sim,
                reactions,
                signal_id,
                origin,
            ),
        )
    ).fetchone()
    post = {
        "post_id": int(_col(row, 0, "id")),
        "public_id": _col(row, 1, "public_id"),
        "posted_at": _col(row, 2, "posted_at"),
    }
    if emit:
        await EventBus(conn, strict=False).emit(
            run_id,
            "review.posted",
            {
                "post_id": post["post_id"],
                "platform": platform,
                "author_nick": nick,
                "author_client_id": author_client_id,
                "match_confidence": match_confidence,
                "text": text[:1000],
                "mentions": mentions or {},
                "signal_id": signal_id,
                "origin": origin,
                "posted_at": post["posted_at"].isoformat(),
                "posted_sim": posted_sim.isoformat(),
            },
            posted_sim,
        )
    return post


async def link_signal(conn: psycopg.AsyncConnection[Any], post_id: int, signal_id: int) -> None:
    await conn.execute(
        "update external_posts set signal_id = %s, status = case when status = 'new' then 'processing' else status end where id = %s",
        (signal_id, post_id),
    )
    await conn.execute("update signals set external_post_id = %s where id = %s", (post_id, signal_id))


async def publish_reply(
    conn: psycopg.AsyncConnection[Any],
    *,
    run_id: int,
    post_id: int,
    text: str,
    author: str,
    sim_time: dt.datetime,
    incident_id: int | None = None,
    agent_run_id: int | None = None,
    llm_source: str | None = None,
    escalate_to_dm: bool = False,
) -> dict[str, Any]:
    """Ответ под постом: санитизация, latency_ms от posted_at, статус поста replied|escalated_to_dm, событие review.replied / review.escalated_to_dm."""
    post = await (
        await conn.execute(
            "select id, run_id, platform, author_nick, author_client_id, posted_at, status from external_posts where id = %s",
            (post_id,),
        )
    ).fetchone()
    if not post:
        raise FeedError(f"пост {post_id} не найден")
    clean = sanitize_public_text(text)
    if len(clean) < 5:
        raise FeedError("текст публичного ответа слишком короткий после очистки")
    if author == "agent":
        dup = await (
            await conn.execute(
                "select id, text, latency_ms, published_at from external_replies where post_id = %s and author = 'agent' and (%s::bigint is null or agent_run_id = %s::bigint) order by id limit 1",
                (post_id, agent_run_id, agent_run_id),
            )
        ).fetchone()
        if dup:
            return {
                "reply_id": int(_col(dup, 0, "id")),
                "text": _col(dup, 1, "text"),
                "latency_ms": _col(dup, 2, "latency_ms"),
                "duplicate": True,
            }
    posted_at: dt.datetime = _col(post, 5, "posted_at")
    latency_ms = max(0, int((dt.datetime.now(dt.UTC) - posted_at).total_seconds() * 1000))
    row = await (
        await conn.execute(
            "insert into external_replies (run_id, post_id, incident_id, agent_run_id, author, text, published_at, latency_ms, llm_source) "
            "values (%s, %s, %s, %s, %s, %s, now(), %s, %s) returning id, published_at",
            (run_id, post_id, incident_id, agent_run_id, author, clean, latency_ms, llm_source),
        )
    ).fetchone()
    reply_id = int(_col(row, 0, "id"))
    new_status = "escalated_to_dm" if escalate_to_dm else "replied"
    await conn.execute("update external_posts set status = %s where id = %s", (new_status, post_id))
    await EventBus(conn, strict=False).emit(
        run_id,
        "review.escalated_to_dm" if escalate_to_dm else "review.replied",
        {
            "post_id": post_id,
            "platform": _col(post, 2, "platform"),
            "author_nick": _col(post, 3, "author_nick"),
            "author_client_id": _col(post, 4, "author_client_id"),
            "reply_id": reply_id,
            "reply_latency_ms": latency_ms,
            "text": clean[:1000],
            "posted_at": posted_at.isoformat(),
            "posted_sim": sim_time.isoformat(),
        },
        sim_time,
    )
    log.info("feed_reply_published", post_id=post_id, author=author, latency_ms=latency_ms, status=new_status)
    return {
        "reply_id": reply_id,
        "text": clean,
        "latency_ms": latency_ms,
        "published_at": _col(row, 1, "published_at"),
        "status": new_status,
        "duplicate": False,
    }


async def feed_stats(conn: psycopg.AsyncConnection[dict[str, Any]], run_id: int | None) -> dict[str, Any]:
    """FeedStats по v_feed_latency + разбивка возвратов на автономные/HITL."""
    where = "where p.run_id = %s" if run_id is not None else ""
    args: tuple[Any, ...] = (run_id,) if run_id is not None else ()
    row = await (
        await conn.execute(
            f"""
            select count(*) as posts,
                   count(*) filter (where p.status in ('replied','escalated_to_dm')) as replied,
                   count(*) filter (where p.author_client_id is not null) as identified,
                   percentile_cont(0.5) within group (order by r.latency_ms) as reply_latency_p50_ms,
                   percentile_cont(0.95) within group (order by r.latency_ms) as reply_latency_p95_ms
            from external_posts p left join external_replies r on r.post_id = p.id and r.author = 'agent' {where}
            """,
            args,
        )
    ).fetchone()
    ref = await (
        await conn.execute(
            f"""
            select coalesce(sum(l.amount), 0)::float as refunded_rub,
                   count(*) filter (where l.created_by = 'agent' and not coalesce(ar.needed_human, false)) as autonomous_refunds,
                   count(*) filter (where l.created_by in ('human','scenario') or coalesce(ar.needed_human, false)) as hitl_refunds
            from ledger_entries l
            join agent_runs ar on ar.id = l.agent_run_id
            join external_posts p on p.signal_id = ar.signal_id
            where l.kind = 'refund' {"and p.run_id = %s" if run_id is not None else ""}
            """,
            args,
        )
    ).fetchone()
    return {
        "run_id": run_id or 0,
        "posts": int(row["posts"]) if row else 0,
        "replied": int(row["replied"]) if row else 0,
        "identified": int(row["identified"]) if row else 0,
        "reply_latency_p50_ms": row["reply_latency_p50_ms"] if row else None,
        "reply_latency_p95_ms": row["reply_latency_p95_ms"] if row else None,
        "refunded_rub": float(ref["refunded_rub"]) if ref else 0.0,
        "autonomous_refunds": int(ref["autonomous_refunds"]) if ref else 0,
        "hitl_refunds": int(ref["hitl_refunds"]) if ref else 0,
    }
