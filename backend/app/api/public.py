"""Роутер тега `public` (OpenAPI 1.4.0). Claim, трекинг, QR бота и приём Telegram — T-119."""

from __future__ import annotations

import io
import re
import secrets
import time
import uuid
from typing import Any, Literal

import qrcode
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from qrcode.image.svg import SvgPathImage

from app.agent.tools.write import PII_RE
from app.api._compliance_support import run_context
from app.api.common import db, fetch_all, fetch_one, resolve_run_id
from app.config import get_settings
from app.errors import NotImplementedYet, Problem
from app.feed import service as feed_svc
from app.i18n import communication_lang
from app.ingest.normalizer import create_signal, from_bot, from_landing
from app.sim.events import EventBus
from app.tracking_mail import send_tracking_receipt

router = APIRouter(tags=["public"])

_BOT_URL = "https://t.me/CXPulseControlBot"
_CLAIM_WINDOW_S = 60.0
_CLAIM_LIMIT = 5
_PHONE = re.compile(r"^\+7 900 00[0-9]-\d{2}-\d{2}$")
_EMAIL_DOMAINS = frozenset({"example.ru", "example.com"})
_TEAM_CODE = re.compile(r"team_[a-z0-9_]+")
_ERROR_CODE = re.compile(r"\b[A-Z]{2,6}(?:-[A-Z0-9]{2,12}){1,3}\b")
_WORKING = {
    "classified",
    "routed",
    "in_progress",
    "fix_proposed",
    "fix_deployed",
    "verifying",
    "escalated",
    "awaiting_human",
    "awaiting_client",
}
_RESOLVED = {"resolved", "closed"}
_ANSWERED_TEMPLATES = {"resolved", "refund_done", "gift_offer"}
_STATUS_RU = {
    "new": "Получено",
    "processing": "В работе у агента",
    "classified": "Разобрано",
    "linked": "Передано в работу",
    "deferred": "Отложено",
    "awaiting_human": "Ожидает решения сотрудника",
    "awaiting_client": "Нужен ваш ответ",
    "answered": "Дан ответ",
    "closed": "Закрыто",
    "noise": "Не требует реакции",
    "error": "Не удалось обработать",
}
_TIMELINE_LABELS = {
    "received": "Обращение получено",
    "agent_started": "Агент взял обращение в работу",
    "classified": "Обращение разобрано",
    "incident_created": "Создано обращение для команды",
    "team_working": "Команда работает над решением",
    "progress_update": "Есть промежуточное сообщение",
    "clarification_needed": "Нужно уточнение",
    "answered": "Дан ответ",
    "resolved": "Решение готово",
    "closed": "Обращение закрыто",
}
_STATUS_EN = {
    "new": "Received",
    "processing": "The agent is working on it",
    "classified": "Reviewed",
    "linked": "Passed to the team",
    "deferred": "Deferred",
    "awaiting_human": "Waiting for an employee",
    "awaiting_client": "Your reply is needed",
    "answered": "Answered",
    "closed": "Closed",
    "noise": "No action needed",
    "error": "Could not process",
}
_TIMELINE_EN = {
    "received": "Request received",
    "agent_started": "The agent started working on the request",
    "classified": "Request reviewed",
    "incident_created": "A case was opened for the team",
    "team_working": "The team is working on a solution",
    "progress_update": "There is an interim update",
    "clarification_needed": "A clarification is needed",
    "answered": "Answered",
    "resolved": "A solution is ready",
    "closed": "Request closed",
}
_ROLE_BUTTONS = [
    {"text": "Я клиент банка", "data": "is_client"},
    {"text": "Я ещё не клиент", "data": "not_client"},
]

_captchas: dict[str, int] = {}
_claim_hits: dict[str, list[float]] = {}
_bot_drafts: dict[int, dict[str, str]] = {}


class ClaimContact(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    nick: str | None = None
    region_code: str | None = None
    city_id: int | None = None
    telegram_chat_id: int | None = None


class CaptchaAnswer(BaseModel):
    id: str
    answer: int


class ClaimBody(BaseModel):
    contact: ClaimContact
    product_code: str | None = None
    text: str = Field(min_length=10, max_length=4000)
    consent: bool
    captcha: CaptchaAnswer
    voice_meta: dict[str, Any] | None = None


class TrackAppendBody(BaseModel):
    text: str = Field(max_length=4000)


class InboundBody(BaseModel):
    chat_id: int
    username: str | None = None
    kind: Literal["start", "is_client", "not_client", "free_text", "contact", "region", "append"]
    text: str
    payload: dict[str, Any] | None = None


def _qr_svg(payload: str) -> str:
    buffer = io.BytesIO()
    image = qrcode.make(payload, image_factory=SvgPathImage)
    image.save(buffer)
    return buffer.getvalue().decode("utf-8")


def _host(request: Request) -> str:
    client = request.client
    return client.host if client else "unknown"


def _claim_limited(host: str) -> bool:
    now = time.monotonic()
    recent = [stamp for stamp in _claim_hits.get(host, []) if now - stamp < _CLAIM_WINDOW_S]
    if len(recent) >= _CLAIM_LIMIT:
        _claim_hits[host] = recent
        return True
    recent.append(now)
    _claim_hits[host] = recent
    return False


def _email_ok(value: str) -> bool:
    local, sep, domain = value.partition("@")
    return bool(
        sep
        and len(value) <= 254
        and re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+", local)
        and domain.lower() in _EMAIL_DOMAINS
    )


def _contact_error(phone: str | None, email: str | None, lang: str = "ru") -> str | None:
    phone_s = (phone or "").strip() or None
    email_s = (email or "").strip() or None
    en = lang == "en"
    if phone_s is None and email_s is None:
        return "Share a fictional phone or email" if en else "Укажите вымышленный телефон или почту"
    if phone_s is not None and _PHONE.match(phone_s) is None:
        return (
            "The phone must be in the range +7 900 000-00-00 … +7 900 009-99-99"
            if en
            else "Телефон только в диапазоне +7 900 000-00-00 … +7 900 009-99-99"
        )
    if email_s is not None and not _email_ok(email_s):
        return (
            "The email must be at @example.ru or @example.com" if en else "Почта только на @example.ru или @example.com"
        )
    return None


def _draft_lang(draft: dict[str, str]) -> str:
    raw = draft.get("lang")
    if raw in ("ru", "en"):
        return raw
    return "ru"


def _accepted_reply(public_id: str, token: str, lang: str) -> str:
    if lang == "en":
        return f"Request {public_id} has been received. Track the status: /track/{token}"
    return f"Обращение {public_id} принято. Следить за статусом: /track/{token}"


def _human(text: str | None) -> str | None:
    if not text:
        return None
    if _TEAM_CODE.search(text) or any(not match.group().startswith("SIG-") for match in _ERROR_CODE.finditer(text)):
        return None
    return re.sub(r"\+7 900 \d{3}-\d{2}-\d{2}", "+7 900 ***-**-**", PII_RE.sub("****", text))


def _take_captcha(captcha_id: str, answer: int) -> bool:
    expected = _captchas.pop(captcha_id, None)
    return expected is not None and expected == answer


def _bot_reply(
    text: str,
    *,
    buttons: list[dict[str, str]] | None = None,
    signal_id: int | None = None,
    tracking_token: str | None = None,
) -> dict[str, Any]:
    return {
        "reply_text": text,
        "buttons": buttons or [],
        "signal_id": signal_id,
        "tracking_token": tracking_token,
    }


def _track_url(request: Request, token: str) -> str:
    return f"{str(request.base_url).rstrip('/')}/track/{token}"


async def _ensure_source(conn: Any, code: str, channel_code: str) -> None:
    """source_code из плана должен существовать в ingest_sources: на код есть внешний ключ."""
    await conn.execute(
        "insert into ingest_sources (code, kind, channel_code, config, enabled, interval_s, is_external) "
        "values (%s, 'rest', %s, '{}'::jsonb, true, 5, false) on conflict (code) do nothing",
        (code, channel_code),
    )


async def _ensure_refs(conn: Any, body: ClaimBody) -> None:
    contact = body.contact
    region = (contact.region_code or "").strip()
    if not region:
        raise Problem(422, "Неизвестный регион", "Укажите регион из справочника")
    if contact.city_id is None:
        raise Problem(422, "Неизвестный город", "Укажите город из справочника")
    city = await fetch_one(conn, "select id from cities where id = %s and region_code = %s", (contact.city_id, region))
    if not city:
        known_region = await fetch_one(conn, "select code from regions where code = %s", (region,))
        if not known_region:
            raise Problem(422, "Неизвестный регион", "Регион не найден в справочнике")
        raise Problem(422, "Неизвестный город", "Город не найден в справочнике")
    product = (body.product_code or "").strip()
    if product:
        known = await fetch_one(conn, "select code from products where code = %s", (product,))
        if not known:
            raise Problem(422, "Неизвестный продукт", "Продукт не найден в справочнике")


def _view_lang(raw: str | None) -> str:
    return raw if raw in ("ru", "en") else "ru"


def _status_label(status: str, lang: str) -> str:
    if lang == "en":
        return _STATUS_EN.get(status, "Request in progress")
    return _STATUS_RU.get(status, "Обращение в работе")


def _timeline_label(step: str, lang: str) -> str:
    table = _TIMELINE_EN if lang == "en" else _TIMELINE_LABELS
    return table[step]


def _timeline(
    signal: dict[str, Any],
    runs: list[dict[str, Any]],
    incidents: list[dict[str, Any]],
    notes: list[dict[str, Any]],
    followups: list[dict[str, Any]],
    lang: str = "ru",
) -> list[dict[str, Any]]:
    received = signal["received_sim"]
    statuses = {str(row["status"]) for row in incidents}
    templates = [str(row["template_code"]) for row in notes if row.get("template_code")]
    problem = _human(_problem_text(signal.get("classification")))
    clarify = signal["status"] == "awaiting_client" or any(
        row["status"] == "scheduled" and row["reason"] == "awaiting_client" for row in followups
    )
    flags = {
        "received": True,
        "agent_started": bool(runs),
        "classified": signal.get("classification") is not None,
        "incident_created": bool(incidents),
        "team_working": bool(statuses & _WORKING),
        "progress_update": "progress_update" in templates,
        "clarification_needed": clarify or "clarify_request" in templates,
        "answered": signal["status"] in {"answered", "closed"}
        or bool(set(templates) & _ANSWERED_TEMPLATES)
        or bool(statuses & _RESOLVED),
        "resolved": bool(statuses & _RESOLVED),
        "closed": signal["status"] == "closed" or "closed" in statuses,
    }
    texts = {
        "classified": problem,
        "clarification_needed": _human(_clarify_body(notes)),
    }
    stamps = {
        "received": received,
        "agent_started": (runs[0].get("started_sim") or runs[0].get("started_at")) if runs else None,
        "classified": received,
        "incident_created": incidents[0].get("created_sim") if incidents else None,
        "team_working": incidents[0].get("created_sim") if incidents else None,
        "progress_update": _note_time(notes, "progress_update"),
        "clarification_needed": _note_time(notes, "clarify_request") or received,
        "answered": _note_time_any(notes, _ANSWERED_TEMPLATES) or received,
        "resolved": next((row.get("resolved_sim") or row.get("created_sim") for row in incidents), None),
        "closed": next(
            (row.get("closed_sim") or row.get("resolved_sim") for row in incidents if row["status"] == "closed"), None
        )
        or received,
    }
    items: list[dict[str, Any]] = []
    labels = _TIMELINE_EN if lang == "en" else _TIMELINE_LABELS
    for step, label in labels.items():
        done = flags[step]
        item: dict[str, Any] = {
            "step": step,
            "label_ru": label,
            "text_ru": texts.get(step) if done else None,
            "done": done,
        }
        if done:
            item["at_sim"] = stamps.get(step) or received
        items.append(item)
    return items


def _problem_text(classification: Any) -> str | None:
    if not isinstance(classification, dict):
        return None
    summary = classification.get("problem_summary")
    if isinstance(summary, dict) and isinstance(summary.get("problem"), str):
        return str(summary["problem"])
    summary_ru = classification.get("summary_ru")
    return str(summary_ru) if isinstance(summary_ru, str) else None


def _clarify_body(notes: list[dict[str, Any]]) -> str | None:
    bodies = [str(row["body"]) for row in notes if row.get("template_code") == "clarify_request" and row.get("body")]
    return bodies[-1] if bodies else None


def _note_time(notes: list[dict[str, Any]], template: str) -> Any:
    stamps = [row.get("sent_sim") for row in notes if row.get("template_code") == template and row.get("sent_sim")]
    return stamps[-1] if stamps else None


def _note_time_any(notes: list[dict[str, Any]], templates: set[str]) -> Any:
    stamps = [row.get("sent_sim") for row in notes if row.get("template_code") in templates and row.get("sent_sim")]
    return stamps[-1] if stamps else None


async def _tracking_view(conn: Any, signal: dict[str, Any], lang: str | None = None) -> dict[str, Any]:
    signal_id = int(signal["id"])
    owned = await fetch_all(
        conn,
        "with recursive owned as (select id,run_id from signals where id=%s "
        "union select s.id,s.run_id from signals s join owned p on s.parent_signal_id=p.id and s.run_id=p.run_id) "
        "select id from owned",
        (signal_id,),
    )
    signal_ids = [int(row["id"]) for row in owned]
    runs = await fetch_all(
        conn,
        "select id, started_sim, started_at, outcome, incident_id from agent_runs "
        "where signal_id = any(%s) and kind = 'agent' order by id",
        (signal_ids,),
    )
    incidents = await fetch_all(
        conn,
        "select distinct i.id, i.status, i.created_sim, i.resolved_sim, i.closed_sim "
        "from incident_signals ls join incidents i on i.id = ls.incident_id "
        "where ls.signal_id = any(%s) order by i.id",
        (signal_ids,),
    )
    followups = await fetch_all(
        conn,
        "select status, reason, wake_sim from followups where signal_id = any(%s) order by id",
        (signal_ids,),
    )
    notes = await fetch_all(
        conn,
        "select id, channel_code, template_code, subject, body, status, sent_sim "
        "from notifications where recipient_type = 'client' and signal_id = any(%s) "
        "and status in ('sent','delivered') order by id",
        (signal_ids,),
    )
    notes = [
        {key: row.get(key) for key in ("id", "channel_code", "template_code", "status", "sent_sim")}
        | {"subject": _human(row.get("subject")), "body": _human(row.get("body"))}
        for row in notes
        if _human(row.get("body"))
    ]
    can_append = signal["status"] == "awaiting_client" or any(
        row["status"] == "scheduled" and row["reason"] == "awaiting_client" for row in followups
    )
    lang = lang or _view_lang(signal.get("lang") if isinstance(signal.get("lang"), str) else None)
    return {
        "public_id": signal["public_id"],
        "status_label_ru": _status_label(str(signal["status"]), lang),
        "timeline": _timeline(signal, runs, incidents, notes, followups, lang),
        "can_append": can_append,
        "question_from_agent": _human(_clarify_body(notes)) if can_append else None,
        "notifications": notes,
    }


async def _append_signal(
    conn: Any,
    parent: dict[str, Any],
    text: str,
    *,
    run_id: int,
    sim_time: Any,
    source_code: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    ext = parent.get("external_contact") or {}
    if not isinstance(ext, dict):
        ext = {}
    parent_id = int(parent["id"])
    external_id = f"track-{parent_id}-{request_id or uuid.uuid4().hex}"
    if request_id:
        existing = await fetch_one(
            conn,
            "select payload from ingest_messages where source_code=%s and external_id=%s",
            (source_code, external_id),
        )
        if existing and (existing.get("payload") or {}).get("text") != text:
            raise Problem(
                422, "Ключ повтора уже использован", "Для нового текста дополнения нужен новый Idempotency-Key"
            )
    if parent.get("channel_code") == "telegram_bot":
        chat_raw = ext.get("telegram_chat_id")
        if chat_raw is None:
            raise Problem(422, "Нет чата", "У обращения нет чата Telegram")
        msg = from_bot(
            chat_id=int(chat_raw),
            text=text,
            phone=ext.get("phone"),
            email=ext.get("email"),
            name=ext.get("name"),
            region_code=ext.get("region_code"),
            parent_signal_id=parent_id,
            external_id=external_id,
        )
    else:
        msg = from_landing(
            contact=ext,
            text=text,
            parent_signal_id=parent_id,
            external_id=external_id,
        )
    channel = "telegram_bot" if parent.get("channel_code") == "telegram_bot" else "landing"
    await _ensure_source(conn, source_code, channel)
    result = await create_signal(conn, msg, source_code=source_code, run_id=run_id, sim_time=sim_time, emit_event=False)
    if result.get("status") == "accepted":
        await EventBus(conn).emit(
            run_id,
            "signal.appended",
            {
                "signal_id": result["signal_id"],
                "parent_signal_id": parent_id,
                "channel": channel,
                "text": text,
                "received_sim": sim_time.isoformat(),
                "origin": "telegram_bot" if channel == "telegram_bot" else "landing",
            },
            sim_time,
        )
    return result


def _submit_public(request: Request, signal_id: int, sim_time: Any, parent_id: int | None = None) -> None:
    agent = getattr(request.app.state, "agent", None)
    if agent is not None and agent.enabled:
        if parent_id is None:
            agent.submit(signal_id, sim_time)
        else:
            agent.submit_client_reply(parent_id, signal_id, sim_time)


@router.get("/api/public/captcha", summary="Арифметическая антибот-проверка")
async def get_public_captcha() -> dict[str, str]:
    left = secrets.randbelow(9) + 1
    right = secrets.randbelow(9) + 1
    captcha_id = secrets.token_urlsafe()
    _captchas[captcha_id] = left + right
    return {"id": captcha_id, "question": f"{left} + {right} = ?"}


@router.post("/api/public/claim", summary="Лендинг потенциального/неидентифицированного клиента")
async def post_public_claim(request: Request, body: ClaimBody) -> JSONResponse:
    if body.consent is not True:
        raise Problem(422, "Нет согласия", "Нужно согласие на обработку обращения")
    contact_error = _contact_error(body.contact.phone, body.contact.email)
    if contact_error:
        raise Problem(422, "Неверный контакт", contact_error)
    async with db() as conn, conn.transaction():
        await _ensure_refs(conn, body)
        if not _take_captcha(body.captcha.id, body.captcha.answer):
            raise Problem(422, "Антибот-проверка", "Неверная или повторная антибот-проверка")
        if _claim_limited(_host(request)):
            raise Problem(
                422, "Слишком много обращений", "С этого адреса можно отправить не больше 5 обращений за минуту"
            )
        run_id, sim_time = await run_context(request, conn)
        token = secrets.token_urlsafe(24)
        await _ensure_source(conn, "landing", "landing")
        contact = body.contact.model_dump(exclude_none=True)
        msg = from_landing(
            contact=contact,
            text=body.text,
            product_code=(body.product_code or "").strip() or None,
            voice_meta=body.voice_meta if isinstance(body.voice_meta, dict) else None,
            tracking_token=token,
        )
        res = await create_signal(conn, msg, source_code="landing", run_id=run_id, sim_time=sim_time)
    if res.get("status") != "accepted":
        raise Problem(422, "Обращение не принято", res.get("error") or "сообщение отклонено нормализатором")
    _submit_public(request, int(res["signal_id"]), sim_time)
    track = str(res.get("tracking_token") or token)
    url = _track_url(request, track)
    if body.contact.email:
        async with db() as mail_conn:
            await send_tracking_receipt(
                mail_conn,
                signal_id=int(res["signal_id"]),
                run_id=run_id,
                recipient=body.contact.email.strip(),
                public_id=str(res["public_id"]),
                url=url,
                sim_time=sim_time,
                lang=communication_lang(body.text),
            )
    return JSONResponse(
        {"public_id": res.get("public_id"), "tracking_token": track, "track_url": url, "qr_svg": _qr_svg(url)},
        status_code=201,
    )


@router.get("/api/public/track/{token}", summary="Таймлайн обращения понятным языком")
async def get_public_track_token(request: Request, token: str) -> JSONResponse:
    if not re.fullmatch(r"[A-Za-z0-9_-]{24,}", token):
        raise Problem(404, "Не найдено", "Обращение с такой ссылкой не найдено")
    async with db() as conn:
        signal = await fetch_one(
            conn,
            "select id, public_id, status, received_sim, classification, lang from signals where tracking_token = %s",
            (token,),
        )
        if not signal:
            raise Problem(404, "Не найдено", "Обращение с такой ссылкой не найдено")
        raw_lang = request.headers.get("accept-language", "").split(",")[0].split("-")[0].split(";")[0]
        view = await _tracking_view(conn, signal, raw_lang if raw_lang in ("ru", "en") else None)
    return JSONResponse(jsonable_encoder(view))


@router.post("/api/public/track/{token}", summary="«Дополнить обращение» (ответ на уточняющий вопрос агента)")
async def post_public_track_token(request: Request, token: str, body: TrackAppendBody) -> Response:
    if not re.fullmatch(r"[A-Za-z0-9_-]{24,}", token):
        raise Problem(404, "Не найдено", "Обращение с такой ссылкой не найдено")
    text = body.text.strip()
    if not text:
        raise Problem(422, "Пустое дополнение", "Напишите текст дополнения")
    request_id = request.headers.get("Idempotency-Key")
    if request_id:
        try:
            request_id = str(uuid.UUID(request_id))
        except ValueError:
            raise Problem(422, "Неверный ключ повтора", "Используйте UUID для Idempotency-Key") from None
    async with db() as conn, conn.transaction():
        parent = await fetch_one(
            conn,
            "select id, run_id, channel_code, external_contact from signals where tracking_token = %s for update",
            (token,),
        )
        if not parent:
            raise Problem(404, "Не найдено", "Обращение с такой ссылкой не найдено")
        _, sim_time = await run_context(request, conn)
        res = await _append_signal(
            conn,
            parent,
            text,
            run_id=int(parent["run_id"]),
            sim_time=sim_time,
            source_code="track_append",
            request_id=request_id,
        )
    if res.get("status") not in {"accepted", "duplicate"}:
        raise Problem(422, "Дополнение не принято", res.get("error") or "сообщение отклонено нормализатором")
    if res.get("signal_id"):
        _submit_public(request, int(res["signal_id"]), sim_time, int(parent["id"]))
    return Response(status_code=202)


@router.get("/api/public/bot/qr", summary="QR-код на Telegram-бота для жюри-режима и README")
async def get_public_bot_qr() -> Response:
    token = (get_settings().telegram_bot_token or "").strip()
    if not token:
        raise Problem(404, "Бот выключен", "Telegram-бот не настроен")
    svg = _qr_svg(_BOT_URL)
    return Response(content=svg, media_type="image/svg+xml")


@router.post(
    "/api/internal/tgbot/inbound", summary="Внутренний приём сообщений от сервиса tgbot (только из docker-сети)"
)
async def post_internal_tgbot_inbound(request: Request, body: InboundBody) -> dict[str, Any]:
    async with db() as conn:
        return await _bot_turn(request, conn, body)


async def _bot_turn(request: Request, conn: Any, body: InboundBody) -> dict[str, Any]:
    chat_id = body.chat_id
    kind = body.kind
    if kind == "start":
        _bot_drafts[chat_id] = {"lang": "ru"}
        return _bot_reply(
            "Здравствуйте! Это помощник Банка. Выберите, кто вы. Используйте только вымышленные данные.",
            buttons=_ROLE_BUTTONS,
        )
    if kind in {"is_client", "not_client"}:
        draft = _bot_drafts.setdefault(chat_id, {})
        draft.setdefault("lang", "ru")
        draft["role"] = kind
        return _bot_reply("Запомнил. Опишите проблему своими словами, не короче 10 символов.")
    if kind == "free_text":
        text = body.text.strip()
        draft = _bot_drafts.setdefault(chat_id, {})
        lang = communication_lang(text)
        draft["lang"] = lang
        if len(text) < 10:
            if lang == "en":
                return _bot_reply("Please write more: at least 10 characters.")
            return _bot_reply("Напишите подробнее: нужно хотя бы 10 символов.")
        draft["text"] = text
        if lang == "en":
            return _bot_reply(
                "Please share a phone in the range +7 900 000-00-00 … +7 900 009-99-99 "
                "or an email at @example.ru / @example.com."
            )
        return _bot_reply(
            "Укажите телефон в диапазоне +7 900 000-00-00 … +7 900 009-99-99 или почту @example.ru / @example.com."
        )
    if kind == "contact":
        draft = _bot_drafts.setdefault(chat_id, {})
        lang = _draft_lang(draft)
        phone, email = _inbound_contact(body)
        error = _contact_error(phone, email, lang)
        if error:
            return _bot_reply(error)
        if phone:
            draft["phone"] = phone
            draft.pop("email", None)
        if email:
            draft["email"] = email
            if not phone:
                draft.pop("phone", None)
        if lang == "en":
            return _bot_reply("Please share a region: the region code or its name.")
        return _bot_reply("Укажите регион: код субъекта или название.")
    if kind == "region":
        return await _bot_region(request, conn, body)
    return await _bot_append(request, conn, body)


def _inbound_contact(body: InboundBody) -> tuple[str | None, str | None]:
    payload = body.payload or {}
    phone = payload.get("phone")
    email = payload.get("email")
    text = body.text.strip()
    if not phone and _PHONE.match(text):
        phone = text
    if not email and _email_ok(text):
        email = text
    phone_s = str(phone).strip() if phone else ""
    email_s = str(email).strip() if email else ""
    return phone_s or None, email_s or None


async def _bot_region(request: Request, conn: Any, body: InboundBody) -> dict[str, Any]:
    payload = body.payload or {}
    raw = str(payload.get("region_code") or body.text).strip()
    row = await fetch_one(
        conn,
        "select code from regions where code = %s or lower(name_ru) = lower(%s) limit 1",
        (raw, raw),
    )
    draft = _bot_drafts.setdefault(body.chat_id, {})
    lang = _draft_lang(draft)
    if not row:
        if lang == "en":
            return _bot_reply("Region not found. Send the region code or a name from the directory.")
        return _bot_reply("Регион не найден. Пришлите код субъекта или название из справочника.")
    draft["region_code"] = str(row["code"])
    if not _draft_ready(draft):
        return _bot_reply(_draft_missing(draft))
    run_id, sim_time = await run_context(request, conn)
    token = secrets.token_urlsafe(24)
    await _ensure_source(conn, "telegram_bot", "telegram_bot")
    msg = from_bot(
        chat_id=body.chat_id,
        text=draft["text"],
        phone=draft.get("phone"),
        email=draft.get("email"),
        region_code=draft["region_code"],
        tracking_token=token,
        external_id=f"tg-{body.chat_id}-{uuid.uuid4().hex[:12]}",
    )
    res = await create_signal(conn, msg, source_code="telegram_bot", run_id=run_id, sim_time=sim_time)
    if res.get("status") != "accepted":
        if lang == "en":
            return _bot_reply(res.get("error") or "Could not accept the request")
        return _bot_reply(res.get("error") or "Не удалось принять обращение")
    public_id = str(res.get("public_id") or "")
    track = str(res.get("tracking_token") or token)
    role = draft.get("role", "")
    kept = {"lang": lang}
    if role:
        kept["role"] = role
    _bot_drafts[body.chat_id] = kept
    return _bot_reply(
        _accepted_reply(public_id, track, lang),
        signal_id=int(res["signal_id"]) if res.get("signal_id") is not None else None,
        tracking_token=track,
    )


def _draft_ready(draft: dict[str, str]) -> bool:
    return bool(
        draft.get("role")
        and len(draft.get("text", "")) >= 10
        and (draft.get("phone") or draft.get("email"))
        and draft.get("region_code")
    )


def _draft_missing(draft: dict[str, str]) -> str:
    if _draft_lang(draft) == "en":
        if not draft.get("role"):
            return "First choose whether you are a client or not yet a client."
        if len(draft.get("text", "")) < 10:
            return "First describe the problem, at least 10 characters."
        return "First share a fictional phone or email."
    if not draft.get("role"):
        return "Сначала выберите: вы клиент банка или ещё нет."
    if len(draft.get("text", "")) < 10:
        return "Сначала опишите проблему, не короче 10 символов."
    return "Сначала укажите вымышленный телефон или почту."


async def _bot_append(request: Request, conn: Any, body: InboundBody) -> dict[str, Any]:
    text = body.text.strip()
    lang = communication_lang(text)
    if not text:
        return _bot_reply("Напишите текст дополнения.")
    parent = await fetch_one(
        conn,
        "select id, public_id, channel_code, external_contact from signals "
        "where channel_code = 'telegram_bot' and external_contact->>'telegram_chat_id' = %s "
        "and parent_signal_id is null order by id desc limit 1",
        (str(body.chat_id),),
    )
    if not parent:
        if lang == "en":
            return _bot_reply("No request was found in this chat. Please describe the problem first.")
        return _bot_reply("Не нашёл обращение в этом чате. Сначала опишите проблему.")
    run_id, sim_time = await run_context(request, conn)
    res = await _append_signal(conn, parent, text, run_id=run_id, sim_time=sim_time, source_code="telegram_bot")
    if res.get("status") != "accepted":
        if lang == "en":
            return _bot_reply(res.get("error") or "Could not accept the update")
        return _bot_reply(res.get("error") or "Не удалось принять дополнение")
    if lang == "en":
        reply = f"The update was added to request {parent['public_id']}."
    else:
        reply = f"Дополнение принято к обращению {parent['public_id']}."
    return _bot_reply(
        reply,
        signal_id=int(res["signal_id"]) if res.get("signal_id") is not None else None,
    )


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
