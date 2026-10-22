"""Роутер тега `public` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка T-119."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api._compliance_support import run_context
from app.api.common import db, fetch_all, fetch_one, resolve_run_id
from app.errors import NotImplementedYet
from app.feed import service as feed_svc
from app.ingest.normalizer import create_signal

router = APIRouter(tags=["public"])


@router.post("/api/public/claim", summary="Лендинг потенциального/неидентифицированного клиента")
async def post_public_claim(request: Request) -> Any:
    raise NotImplementedYet("T-119")


@router.get("/api/public/captcha", summary="Арифметическая антибот-проверка")
async def get_public_captcha(request: Request) -> Any:
    raise NotImplementedYet("T-119")


@router.get("/api/public/track/{token}", summary="Таймлайн обращения понятным языком")
async def get_public_track_token(request: Request) -> Any:
    raise NotImplementedYet("T-119")


@router.post("/api/public/track/{token}", summary="«Дополнить обращение» (ответ на уточняющий вопрос агента)")
async def post_public_track_token(request: Request) -> Any:
    raise NotImplementedYet("T-119")


@router.get("/api/public/bot/qr", summary="QR-код на Telegram-бота для жюри-режима и README")
async def get_public_bot_qr(request: Request) -> Any:
    raise NotImplementedYet("T-119")


@router.post(
    "/api/internal/tgbot/inbound", summary="Внутренний приём сообщений от сервиса tgbot (только из docker-сети)"
)
async def post_internal_tgbot_inbound(request: Request) -> Any:
    raise NotImplementedYet("T-119")


class ReviewMentions(BaseModel):
    card_last4: str | None = Field(None, pattern=r"^\d{4}$")
    phone_masked: str | None = None
    city: str | None = None


class ReviewBody(BaseModel):
    platform: Literal["review_portal", "telegram_channel"]
    author_nick: str = Field(min_length=3, max_length=32, pattern=r"^@?[A-Za-z0-9_\.]+$")
    text: str = Field(min_length=10, max_length=4000)
    mentions: ReviewMentions | None = None
    compare_with_mock: bool = False


@router.post(
    "/api/public/reviews", summary="Публикация отзыва на эмуляторе внешней площадки (BRD FR 1.1)", status_code=202
)
async def post_public_reviews(request: Request, body: ReviewBody) -> Any:
    """Пост → событие review.posted → сигнал канала review_portal/social → агент стартует немедленно (ТЗ 21.2, 21.4)."""
    channel = "review_portal" if body.platform == "review_portal" else "social"
    mentions = body.mentions.model_dump(exclude_none=True) if body.mentions else {}
    async with db() as conn:
        run_id, sim_time = await run_context(request, conn)
        client_id: int | None = None
        confidence: float | None = None
        if mentions.get("card_last4"):
            # сопоставление по последним 4 цифрам карты и городу (ТЗ 21.2: match_confidence)
            row = await fetch_one(
                conn,
                "select c.id, ci.name_ru as city from clients c join client_products cp on cp.client_id = c.id "
                "left join cities ci on ci.id = c.city_id where cp.card_last4 = %s and c.is_active order by cp.status = 'active' desc, c.id limit 1",
                (mentions["card_last4"],),
            )
            if row:
                client_id = int(row["id"])
                confidence = 0.9 if (mentions.get("city") and row["city"] == mentions["city"]) else 0.7
        post = await feed_svc.create_post(
            conn,
            run_id=run_id,
            platform=body.platform,
            author_nick=body.author_nick,
            text=body.text,
            posted_sim=sim_time,
            origin="api",
            author_client_id=client_id,
            match_confidence=confidence,
            mentions=mentions,
        )
        msg = {
            "external_id": f"review:{post['post_id']}",
            "channel": channel,
            "channel_subtype": body.platform,
            "origin": "review_portal",
            "timestamp": sim_time.isoformat(),
            "text": body.text,
            "client": {
                "client_id": client_id,
                "contact_hints": {"nickname": body.author_nick.lstrip("@"), "card_last4": mentions.get("card_last4")},
            },
            "geo": {"source": "none"},
            "meta": {"external_post_id": post["post_id"]},
        }
        res = await create_signal(conn, msg, source_code="review_portal_feed", run_id=run_id, sim_time=sim_time)
        if res.get("status") == "rejected":
            raise HTTPException(status_code=422, detail=res.get("error") or "сообщение отклонено нормализатором")
    return JSONResponse(
        {
            "post_id": post["post_id"],
            "public_id": post["public_id"],
            "signal_id": res.get("signal_id"),
            "agent_run_id": None,
        },
        status_code=202,
    )


@router.get("/api/public/feed", summary="Лента эмулятора площадки (без роли)")
async def get_public_feed(
    platform: str | None = Query(None),
    status: str | None = Query(None, description="через запятую"),
    run_id: str | None = Query(None),
    limit: int = Query(30, ge=1, le=200),
    cursor: str | None = Query(None),
) -> Any:
    statuses = [x for x in (status or "").split(",") if x]
    async with db() as conn:
        rid = await resolve_run_id(conn, run_id)
        where: list[str] = ["true"]
        args: list[Any] = []
        if rid is not None:
            where.append("p.run_id = %s")
            args.append(rid)
        if platform:
            where.append("p.platform = %s")
            args.append(platform)
        if statuses:
            where.append("p.status = any(%s)")
            args.append(statuses)
        if cursor:
            where.append("p.id < %s")
            args.append(int(cursor))
        rows = await fetch_all(
            conn,
            f"""
            select p.id, p.public_id, p.run_id, p.platform, p.author_nick, p.author_client_id, p.match_confidence::float as match_confidence,
                   p.text, p.mentions, p.posted_at, p.posted_sim, p.reactions, p.status, p.signal_id, p.origin,
                   (select count(*) from external_replies r where r.post_id = p.id) as replies_count,
                   (select min(r.latency_ms) from external_replies r where r.post_id = p.id and r.author = 'agent') as agent_reply_latency_ms,
                   s.classification->>'signal_type' as signal_type, s.sentiment,
                   ar.incident_id, ar.id as agent_run_id,
                   case when c.id is null then null else jsonb_build_object('id', c.id, 'public_id', c.public_id, 'display_name', c.display_name,
                        'segment_code', c.segment_code, 'region_code', c.region_code, 'is_active', c.is_active) end as author_client
            from external_posts p
            left join clients c on c.id = p.author_client_id
            left join signals s on s.id = p.signal_id
            left join lateral (select id, incident_id from agent_runs a where a.signal_id = p.signal_id order by a.id desc limit 1) ar on true
            where {" and ".join(where)} order by p.id desc limit %s
            """,
            (*args, limit + 1),
        )
        total = await fetch_one(
            conn, f"select count(*) as n from external_posts p where {' and '.join(where)}", tuple(args)
        )
    items = rows[:limit]
    next_cursor = str(items[-1]["id"]) if len(rows) > limit and items else None
    return JSONResponse(
        jsonable_encoder({"items": items, "next_cursor": next_cursor, "total": int(total["n"]) if total else 0})
    )


@router.get("/api/public/feed/{post_id}", summary="Пост с веткой ответов и временем реакции агента")
async def get_public_feed_post_id(post_id: int) -> Any:
    async with db() as conn:
        post = await fetch_one(
            conn,
            "select p.*, p.match_confidence::float as match_confidence, s.classification->>'signal_type' as signal_type, s.sentiment, s.status as signal_status, "
            "ar.incident_id, ar.id as agent_run_id, i.public_id as incident_public_id, i.status as incident_status, "
            "case when c.id is null then null else jsonb_build_object('id', c.id, 'public_id', c.public_id, 'display_name', c.display_name, "
            "'segment_code', c.segment_code, 'region_code', c.region_code, 'is_active', c.is_active) end as author_client "
            "from external_posts p left join clients c on c.id = p.author_client_id left join signals s on s.id = p.signal_id "
            "left join lateral (select id, incident_id from agent_runs a where a.signal_id = p.signal_id order by a.id desc limit 1) ar on true "
            "left join incidents i on i.id = ar.incident_id where p.id = %s",
            (post_id,),
        )
        if not post:
            raise HTTPException(status_code=404, detail=f"пост {post_id} не найден")
        replies = await fetch_all(
            conn,
            "select id, run_id, post_id, incident_id, agent_run_id, author, text, published_at, latency_ms, llm_source from external_replies where post_id = %s order by id",
            (post_id,),
        )
        refunds = (
            await fetch_all(
                conn,
                "select l.id, l.account_id, l.operation_id, l.kind, l.amount::float as amount, l.posted_sim, l.created_by, l.rule_id, l.agent_run_id "
                "from ledger_entries l join agent_runs ar on ar.id = l.agent_run_id where ar.signal_id = %s and l.kind = 'refund' order by l.id",
                (post["signal_id"],),
            )
            if post.get("signal_id")
            else []
        )
    agent_latency = next((r["latency_ms"] for r in replies if r["author"] == "agent"), None)
    refunded = sum(float(r["amount"]) for r in refunds)
    effect = None
    if refunds:
        effect = f"возвращено {refunded:.0f} ₽" + (
            f", ответ за {agent_latency / 1000:.1f} с" if agent_latency is not None else ""
        )
    return JSONResponse(
        jsonable_encoder(
            {
                **post,
                "replies": replies,
                "refund": refunds[0] if refunds else None,
                "refunds": refunds,
                "incident_ids": [post["incident_id"]] if post.get("incident_id") else [],
                "agent_reply_latency_ms": agent_latency,
                "effect_line_ru": effect,
            }
        )
    )


@router.get(
    "/api/public/mock-social-feed",
    summary="[ДТЗ FR-1.2] Встроенная mock-лента соцсети для polling-адаптера demo-профиля (массив сообщений единой схемы, курсор since)",
)
async def get_public_mock_social_feed(request: Request) -> Any:
    raise NotImplementedYet("T-119")
