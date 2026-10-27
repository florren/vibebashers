"""T-157: шаблоны клиенту на языке сигнала, по умолчанию ru."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts.seed.refs import seed_templates  # noqa: E402

from app.agent import nodes  # noqa: E402
from app.agent.gifts import _gift_label as gift_label  # noqa: E402
from app.agent.gifts import _issue_gift_task_row  # noqa: E402
from app.agent.policies import forbidden_phrases  # noqa: E402
from app.agent.tools.base import ActFrame, ToolContext  # noqa: E402
from app.agent.tools.router_tools import notify_customer, request_clarification  # noqa: E402
from app.agent.tools.write import render_template  # noqa: E402
from app.api.public import (  # noqa: E402
    InboundBody,
    _accepted_reply,
    _bot_drafts,
    _bot_turn,
    _status_label,
    _timeline,
    _timeline_label,
)
from app.api.tasks import _catalog_gift_name  # noqa: E402
from app.api.tasks import _gift_label as task_gift_label  # noqa: E402
from app.contracts.registry import deref  # noqa: E402
from app.i18n import communication_lang  # noqa: E402
from app.llm.base import LLMProfile  # noqa: E402
from app.llm.mock import MockProvider  # noqa: E402

PROFILE = LLMProfile(code="mock", provider="mock", model="mock-rules-v1")
DATA = ROOT / "data" / "templates" / "notifications.yaml"
JURY_EN = "The fee was charged on my card again"


def _templates() -> list[dict[str, Any]]:
    doc = yaml.safe_load(DATA.read_text(encoding="utf-8"))
    return list(doc["templates"])


def _lang(row: dict[str, Any]) -> str:
    return str(row.get("lang") or "ru")


def _pair_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (str(row["code"]), str(row["channel"]), str(row.get("segment")))


class _Cur:
    def __init__(self, row: Any = None) -> None:
        self.row = row

    async def fetchone(self) -> Any:
        return self.row


class _Conn:
    def __init__(self, by_lang: dict[str, tuple[str, str] | None]) -> None:
        self.by_lang = by_lang
        self.langs: list[str] = []

    async def execute(self, sql: str, args: tuple[Any, ...] = ()) -> _Cur:
        lang = str(args[-1])
        self.langs.append(lang)
        return _Cur(self.by_lang.get(lang))


def _tool_ctx(by_lang: dict[str, tuple[str, str] | None]) -> tuple[ToolContext, _Conn]:
    conn = _Conn(by_lang)
    ctx = ToolContext(conn, run_id=1, agent_run_id=1, sim_time=dt.datetime(2026, 10, 26, tzinfo=dt.UTC))  # type: ignore[arg-type]
    return ctx, conn


class _Seed:
    def __init__(self) -> None:
        self.rows: dict[tuple[Any, ...], dict[str, Any]] = {}

    def execute(self, sql: str, args: tuple[Any, ...]) -> None:
        assert "on conflict" in sql and "subject = excluded.subject" in sql
        key = (args[0], args[1], args[2], args[3])
        self.rows[key] = {"subject": args[4], "body": args[5], "variables": list(args[6])}


class _Deps:
    def __init__(self, ctx: object) -> None:
        self.ctx = ctx


def test_en_template_pairs_share_variables() -> None:
    rows = [row for row in _templates() if row["code"] != "team_notice"]
    grouped: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_pair_key(row), {})[_lang(row)] = row
    assert grouped
    for key, langs in grouped.items():
        assert set(langs) == {"ru", "en"}, key
        assert langs["ru"].get("variables") == langs["en"].get("variables")
        body = str(langs["en"]["body"])
        assert "{{" not in body or "{{ " in body
        assert forbidden_phrases(body) == []
        subject = langs["en"].get("subject")
        if subject:
            assert forbidden_phrases(str(subject)) == []
        assert "Bank" not in body
    team = [row for row in _templates() if row["code"] == "team_notice"]
    assert len(team) == 1 and _lang(team[0]) == "ru"
    refund = next(row for row in rows if row["code"] == "refund_done" and _lang(row) == "en")
    assert "returned" in str(refund["body"]).lower()
    assert "within the hour" not in str(refund["body"]).lower()


def test_en_communication_lang() -> None:
    assert communication_lang("The fee was charged on my card") == "en"
    assert communication_lang("Списали комиссию за карту") == "ru"
    assert communication_lang("") == "ru"
    assert communication_lang("12345") == "ru"
    assert communication_lang("Hello, списали комиссию") == "ru"


async def test_en_mock_normalization_language() -> None:
    schema = deref("agent/normalization")
    en, *_ = await MockProvider().complete_structured(
        [{"role": "user", "content": JURY_EN}], schema, PROFILE, timeout_s=1
    )
    ru, *_ = await MockProvider().complete_structured(
        [{"role": "user", "content": "Списали комиссию за карту снова"}], schema, PROFILE, timeout_s=1
    )
    assert en["language"] == "en"
    assert ru["language"] == "ru"


def test_en_forbidden_phrases_skip_completed_refund() -> None:
    bad = forbidden_phrases("We guarantee a refund within the hour and will compensate everything")
    assert "guarantee" in bad
    assert "within the hour" in bad
    assert "compensate everything" in bad
    assert forbidden_phrases("The fee has been returned") == []
    assert forbidden_phrases("Your mistake caused this, it is your fault")


def test_en_seed_does_not_merge_langs() -> None:
    first, second = _Seed(), _Seed()
    seed_templates(first)  # type: ignore[arg-type]
    seed_templates(second)  # type: ignore[arg-type]
    langs = {key[3] for key in first.rows}
    assert langs == {"ru", "en"}
    ru_key = next(key for key in first.rows if key[0] == "ack_received" and key[3] == "ru")
    en_key = (ru_key[0], ru_key[1], ru_key[2], "en")
    assert first.rows[ru_key]["body"] == second.rows[ru_key]["body"]
    assert first.rows[en_key]["body"] == second.rows[en_key]["body"]
    assert first.rows[ru_key]["body"] != first.rows[en_key]["body"]
    assert "спасибо" in first.rows[ru_key]["body"].lower() or "Спасибо" in first.rows[ru_key]["body"]
    team = [key for key in first.rows if key[0] == "team_notice"]
    assert team and {key[3] for key in team} == {"ru"}


async def test_en_render_selects_body_and_falls_back() -> None:
    ctx, conn = _tool_ctx(
        {
            "en": ("We have received your request", "Thank you, {{ name }}. We are already looking into this."),
            "ru": ("Мы получили ваше обращение", "{{ name }}, спасибо за обращение."),
        }
    )
    subject, body = await render_template(ctx, "ack_received", "chat", None, {"name": "Ann"}, "en")
    assert subject == "We have received your request"
    assert body == "Thank you, Ann. We are already looking into this."
    assert conn.langs[0] == "en"

    missing, seen = _tool_ctx({"ru": ("Мы получили ваше обращение", "{{ name }}, спасибо за обращение.")})
    subject_ru, body_ru = await render_template(missing, "fee_refund_done", "chat", None, {"name": "Ann"}, "en")
    assert subject_ru == "Мы получили ваше обращение"
    assert "спасибо" in body_ru
    assert seen.langs[:2] == ["en", "en"]
    assert "ru" in seen.langs


async def test_en_model_text_uses_template_body() -> None:
    async def render(*_args: Any, **_kwargs: Any) -> tuple[str, str]:
        assert _args[-1] == "en" or _kwargs.get("lang") == "en"
        return ("We have received your request", "Thank you. We are already looking into this.")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(nodes.wt, "render_template", render)
    ru_model = "Мы уже разбираемся с вашим обращением и вернёмся с ответом."
    deps = _Deps(object())
    try:
        out = await nodes._render_client_text(deps, ru_model, "en", "ack_received", "chat", None, {})  # type: ignore[arg-type]
        kept = await nodes._render_client_text(deps, ru_model, "ru", "ack_received", "chat", None, {})  # type: ignore[arg-type]
    finally:
        monkeypatch.undo()
    assert out == "Thank you. We are already looking into this."
    assert kept == ru_model


def test_en_fixed_questions_have_no_deadline() -> None:
    for kind in ("identify", "fraud_data", "generic"):
        text = nodes._fixed_question(kind, "en")
        assert communication_lang(text) == "en"
        assert forbidden_phrases(text) == []
    assert nodes._fixed_question("identify", "ru").startswith("Чтобы помочь")
    assert "returned" in nodes._refund_text("Мы разбираемся", 450, lang="en").lower()
    assert nodes._refund_text("Комиссия уже возвращена.", 450).startswith("Комиссия уже")
    assert communication_lang(nodes._public_fallback({"name": "Ann"}, "en")) == "en"
    assert nodes._public_fallback({"name": "Анна"}).startswith("Анна")


async def test_en_router_spec_keeps_ack_template(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def notify(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        seen["template"] = _args[5]
        seen["lang"] = kwargs.get("lang", "ru")
        return {"notification_id": 1, "status": "sent"}

    monkeypatch.setattr("app.agent.tools.router_tools.write_notify_client", notify)
    ctx, _conn = _tool_ctx({})
    ctx.act_frame = ActFrame(signal_id=1, client_id=2, incident_id=None, link_incident_id=None, spec={})
    await notify_customer(ctx, "chat", "Мы уже разбираемся с вашим обращением.")
    assert seen["template"] == "ack_received" and seen["lang"] == "ru"
    ctx.act_frame = ActFrame(signal_id=1, client_id=2, incident_id=None, link_incident_id=None, spec={"lang": "en"})
    await notify_customer(ctx, "chat", "We are already looking into the card fee.")
    assert seen["template"] == "ack_received" and seen["lang"] == "en"


def test_en_tracking_labels_stay_in_label_ru() -> None:
    assert _timeline_label("received", "en") == "Request received"
    assert _timeline_label("received", "ru") == "Обращение получено"
    assert _status_label("new", "en") == "Received"
    assert _status_label("new", "ru") == "Получено"
    items = _timeline(
        {"status": "new", "received_sim": None, "classification": None},
        [],
        [],
        [],
        [],
        "en",
    )
    assert items[0]["label_ru"] == "Request received"
    assert all(communication_lang(str(item["label_ru"])) == "en" for item in items)
    assert _accepted_reply("SIG-000001", "token", "en") == (
        "Request SIG-000001 has been received. Track the status: /track/token"
    )
    assert "SIG-" in _accepted_reply("SIG-000001", "token", "ru")
    assert "/track/token" in _accepted_reply("SIG-000001", "token", "ru")


async def test_en_bot_stores_lang_after_free_text() -> None:
    start = await _bot_turn(None, None, InboundBody(chat_id=15701, kind="start", text="/start"))  # type: ignore[arg-type]
    assert "Здравствуйте" in start["reply_text"]
    reply = await _bot_turn(
        None,
        None,
        InboundBody(chat_id=15701, kind="free_text", text="The fee was charged on my card again"),
    )  # type: ignore[arg-type]
    assert _bot_drafts[15701]["lang"] == "en"
    assert communication_lang(reply["reply_text"]) == "en"
    assert "+7 900" in reply["reply_text"]


def test_en_gift_label_uses_name_en() -> None:
    assert task_gift_label({"gift_code": "bonus_points", "points": 300}, "Loyalty bonus points", "en") == (
        "300 bonus points"
    )
    assert task_gift_label({"gift_code": "lounge_pass"}, "Airport lounge pass", "en") == "Airport lounge pass"
    assert "бонусных" in task_gift_label({"gift_code": "bonus_points", "points": 300}, "Баллы", "ru")
    assert _catalog_gift_name("en", "Бонусные баллы", "Loyalty bonus points") == "Loyalty bonus points"
    assert gift_label({"gift_code": "bonus_points", "points": 600}, "Loyalty bonus points", "en") == "600 bonus points"


class _GiftCur:
    def __init__(self, row: Any) -> None:
        self.row = row

    async def fetchone(self) -> Any:
        return self.row


class _GiftConn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def execute(self, sql: str, args: Any = None) -> _GiftCur:
        self.calls.append((sql, args))
        if "notification_templates" in sql and args and args[0] == "en":
            return _GiftCur(("A small apology", "{{ name }}, we have added {{ gift }}."))
        return _GiftCur(None)


async def test_en_gift_offer_queries_lang() -> None:
    conn = _GiftConn()
    issued = await _issue_gift_task_row(
        conn,
        {
            "payload": {"gift": {"gift_code": "bonus_points", "points": 300}},
            "client_id": 1,
            "client_segment": "mass",
            "client_name": "Ann",
            "gift_name": "Бонусные баллы",
            "gift_name_en": "Loyalty bonus points",
            "signal_lang": "en",
            "run_id": 1,
            "incident_id": 2,
            "sim_time": None,
            "task_id": 3,
        },
    )
    assert issued is True
    template_calls = [args for sql, args in conn.calls if "notification_templates" in sql]
    assert template_calls and template_calls[0][0] == "en"
    inserted = next(args for sql, args in conn.calls if "insert into notifications" in sql)
    assert "300 bonus points" in inserted[4]


async def test_en_request_clarification_passes_lang(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def notify(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        seen["lang"] = kwargs.get("lang")
        seen["template"] = _args[5]
        return {"notification_id": 4, "status": "sent"}

    async def known(*_a: Any, **_k: Any) -> None:
        return None

    async def bind(*_a: Any, **_k: Any) -> tuple[dict[str, Any], bool]:
        return {"incident_id": 9}, False

    async def follow(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {"wake_sim": None}

    monkeypatch.setattr("app.agent.tools.router_tools.write_notify_client", notify)
    monkeypatch.setattr("app.agent.tools.router_tools._known_team", known)
    monkeypatch.setattr("app.agent.tools.router_tools._bind_ticket", bind)
    monkeypatch.setattr("app.agent.tools.router_tools.write_schedule_followup", follow)
    ctx, _conn = _tool_ctx({})
    ctx.act_frame = ActFrame(
        signal_id=1,
        client_id=2,
        incident_id=None,
        link_incident_id=None,
        spec={"lang": "en", "team": "team_cx", "title_ru": "Card fee was charged again today"},
    )
    await request_clarification(ctx, "Please share the date and amount of the fee.", "chat")
    assert seen["template"] == "clarify_request"
    assert seen["lang"] == "en"
