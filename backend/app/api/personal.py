"""T-269: анонимная сессия чата, общий normalizer и только собственные ответы."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import secrets
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api._compliance_support import run_context
from app.api.common import db, fetch_all, fetch_one
from app.config import get_settings
from app.ingest.normalizer import create_signal, from_landing

router = APIRouter(tags=["personal"])
COOKIE = "cx_personal"
TAG = "ui_pers_demo"


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def form_token(raw: str) -> str:
    return hmac.new(get_settings().app_secret.encode(), ("personal:" + raw).encode(), hashlib.sha256).hexdigest()


def same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if request.headers.get("sec-fetch-site") == "cross-site" or (
        origin and origin.rstrip("/") != str(request.base_url).rstrip("/")
    ):
        raise HTTPException(403, "Неверный источник запроса")


async def session(conn: Any, request: Request, lock: bool = False) -> dict[str, Any]:
    raw = request.cookies.get(COOKIE, "")
    if len(raw) > 200:
        raise HTTPException(401, "Сессия истекла, обновите страницу")
    row = await fetch_one(
        conn,
        "select * from personal_chat_sessions where created_at>now()-interval '1 day' and token_hash=%s"
        + (" for update" if lock else ""),
        (token_hash(raw),),
    )
    if not row:
        raise HTTPException(401, "Сессия истекла, обновите страницу")
    return row


async def visitor_name(conn: Any, session_id: int) -> str:
    row = await fetch_one(
        conn,
        "select coalesce(s.meta->>'visitor_name','') as name from personal_chat_messages m join signals s on s.id=m.signal_id where m.session_id=%s order by m.id desc limit 1",
        (session_id,),
    )
    return row["name"] if row else ""


@router.get("/api/personal/session", summary="Анонимная сессия и публичные справочники формы")
async def get_personal_session(request: Request, response: Response) -> Any:
    same_origin(request)
    async with db() as conn, conn.transaction():
        raw = request.cookies.get(COOKIE, "")
        row = (
            await fetch_one(
                conn,
                "select * from personal_chat_sessions where created_at>now()-interval '1 day' and token_hash=%s",
                (token_hash(raw),),
            )
            if raw and len(raw) <= 200
            else None
        )
        if not row:
            await conn.execute("select pg_advisory_xact_lock(269,1)")
            count = await fetch_one(
                conn, "select count(*) as n from personal_chat_sessions where created_at>now()-interval '1 hour'"
            )
            if count and count["n"] >= 200:
                raise HTTPException(429, "Слишком много новых чатов, попробуйте позже", headers={"Retry-After": "60"})
            raw = secrets.token_urlsafe(32)
            row = await fetch_one(
                conn, "insert into personal_chat_sessions(token_hash) values (%s) returning *", (token_hash(raw),)
            )
            response.set_cookie(
                COOKIE,
                raw,
                httponly=True,
                secure=request.url.scheme == "https",
                samesite="strict",
                max_age=86400,
                path="/",
            )
        if row is None:
            raise HTTPException(500, "Не удалось создать сессию")
        products = await fetch_all(conn, "select code,name_ru,name_en from products order by name_ru")
        regions = await fetch_all(conn, "select code,name_ru from regions order by name_ru")
        cities = await fetch_all(conn, "select id,name_ru,region_code from cities order by name_ru")
        display_name = await visitor_name(conn, row["id"])
    return {
        "display_name": display_name,
        "form_token": form_token(raw),
        "products": products,
        "regions": regions,
        "cities": cities,
        "tag": TAG,
        "minimum_form_ms": 2000,
    }


class PersonalMessageBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: uuid.UUID
    form_token: str = Field(min_length=64, max_length=64)
    text: str = Field(min_length=1, max_length=4000)
    display_name: str | None = Field(None, max_length=120, pattern=r"^[^\x00-\x1f\x7f-\x9f]*$")
    product_code: str | None = Field(None, max_length=100)
    region_code: str | None = Field(None, max_length=10)
    city_id: int | None = None
    website: str = Field("", max_length=200)  # honeypot, пользователю не показывается
    voice: bool = False


@router.post("/api/personal/messages", status_code=202, summary="Сообщение анонимного чата через единый normalizer")
async def post_personal_message(request: Request, body: PersonalMessageBody) -> Any:
    same_origin(request)
    if body.website or not hmac.compare_digest(body.form_token, form_token(request.cookies.get(COOKIE, ""))):
        raise HTTPException(403, "Не удалось проверить форму, обновите страницу")
    async with db() as conn, conn.transaction():
        s = await session(conn, request, True)
        fingerprint = body.model_dump(exclude={"request_id", "form_token", "website"})
        # Старые payload и сохранённые request_hash не содержат нового поля.
        if body.display_name is None:
            fingerprint.pop("display_name")
        request_hash = token_hash(json.dumps(fingerprint, sort_keys=True, ensure_ascii=False))
        existing = await fetch_one(
            conn,
            "select m.signal_id,m.request_hash,s.public_id,s.text from personal_chat_messages m join signals s on s.id=m.signal_id where m.session_id=%s and m.request_id=%s",
            (s["id"], body.request_id),
        )
        if existing:
            if existing["request_hash"] != request_hash:
                raise HTTPException(409, "Ключ сообщения уже использован")
            return {"public_id": existing["public_id"], "accepted": True}
        now = dt.datetime.now(dt.UTC)
        age = (now - (s["last_message_at"] or s["created_at"])).total_seconds()
        if age < 2:
            raise HTTPException(
                429, "Пожалуйста, подождите перед отправкой", headers={"Retry-After": str(max(1, int(3 - age)))}
            )
        if body.product_code and not await fetch_one(
            conn, "select code from products where code=%s", (body.product_code,)
        ):
            raise HTTPException(422, "Неизвестный продукт")
        if body.region_code and not await fetch_one(
            conn, "select code from regions where code=%s", (body.region_code,)
        ):
            raise HTTPException(422, "Неизвестный регион")
        if body.city_id and not await fetch_one(
            conn, "select id from cities where id=%s and region_code=%s", (body.city_id, body.region_code)
        ):
            raise HTTPException(422, "Город не относится к региону")
        await conn.execute("select pg_advisory_xact_lock(269,2)")
        count = await fetch_one(
            conn, "select count(*) as n from personal_chat_messages where created_at>now()-interval '1 minute'"
        )
        own = await fetch_one(
            conn,
            "select count(*) as n from personal_chat_messages where session_id=%s and created_at>now()-interval '1 minute'",
            (s["id"],),
        )
        if (count and count["n"] >= 60) or (own and own["n"] >= 5):
            raise HTTPException(429, "Ограничение частоты сообщений", headers={"Retry-After": "60"})
        rid, sim_time = await run_context(request, conn)
        if s["run_id"] is not None and rid != s["run_id"]:
            # Разговор не переносится в другой запуск незаметно для агента.
            raise HTTPException(409, "Запуск демонстрации изменился. Начните новый чат.")
        parent = await fetch_one(
            conn, "select signal_id from personal_chat_messages where session_id=%s order by id limit 1", (s["id"],)
        )
        if parent is None and len(body.text) < 10:
            raise HTTPException(422, "Опишите обращение: не менее 10 символов")
        total = await fetch_one(
            conn, "select count(*) as n from personal_chat_messages where session_id=%s", (s["id"],)
        )
        if total and total["n"] >= 200:
            raise HTTPException(409, "Этот чат заполнен. Начните новый чат.")
        await conn.execute(
            "insert into ingest_sources(code,kind,channel_code,config,enabled,interval_s,is_external) values ('ui_pers_demo','rest','landing','{}',true,5,false) on conflict do nothing"
        )
        msg = from_landing(
            contact={
                k: v for k, v in {"region_code": body.region_code, "city_id": body.city_id}.items() if v is not None
            },
            text=body.text,
            product_code=body.product_code,
            external_id=f"personal:{s['id']}:{body.request_id}",
            parent_signal_id=parent["signal_id"] if parent else None,
            voice_meta={"provider": "vosk", "source": "personal"} if body.voice else None,
        )
        msg["channel_subtype"] = TAG
        msg["meta"]["tags"] = [TAG]
        # Самопредставление — только контекст диалога, не контакт для identify_client.
        msg["meta"]["visitor_name"] = (
            body.display_name if body.display_name is not None else await visitor_name(conn, s["id"])
        )
        result = await create_signal(conn, msg, source_code=TAG, run_id=rid, sim_time=sim_time)
        if result["status"] not in ("accepted", "duplicate"):
            raise HTTPException(422, "Не удалось принять сообщение")
        await conn.execute(
            "insert into personal_chat_messages(session_id,request_id,signal_id,request_hash) values (%s,%s,%s,%s)",
            (s["id"], body.request_id, result["signal_id"], request_hash),
        )
        await conn.execute(
            "update personal_chat_sessions set run_id=%s,last_message_at=now() where id=%s", (rid, s["id"])
        )
    return {"accepted": True, "public_id": result["public_id"]}


@router.get("/api/personal/messages", summary="История только собственной анонимной сессии")
async def get_personal_messages(request: Request) -> Any:
    async with db() as conn:
        s = await session(conn, request)
        messages = await fetch_all(
            conn,
            "select s.public_id,s.text,s.status,s.received_at,coalesce(s.meta->>'visitor_name','') as display_name from personal_chat_messages m join signals s on s.id=m.signal_id where m.session_id=%s order by m.id limit 200",
            (s["id"],),
        )
        # Не выдаём внутренние рекомендации, задания, чужих клиентов, токены и операторские комментарии.
        answers = await fetch_all(
            conn,
            """select n.id,n.body,n.created_at from notifications n join personal_chat_messages m on m.signal_id=n.signal_id
            where m.session_id=%s and n.recipient_type='client' and n.status in ('sent','delivered') order by n.id limit 200""",
            (s["id"],),
        )
    return {
        "messages": messages,
        "answers": [{"id": r["id"], "text": r["body"], "at": r["created_at"]} for r in answers],
    }


@router.post("/api/personal/reset", status_code=204, summary="Забыть локальную анонимную сессию")
async def reset_personal(request: Request, response: Response) -> None:
    same_origin(request)
    response.delete_cookie(COOKIE, path="/")


@router.get("/api/personal/health", summary="Готовность публичного чата")
async def personal_health() -> Any:
    async with db() as conn:
        await conn.execute("select 1")
    return {"status": "ok"}
