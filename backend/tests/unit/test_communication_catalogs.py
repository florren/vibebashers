"""T-015: полный каталог канал × сегмент × язык, без подключения к БД."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment, StrictUndefined, meta

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.seed.refs import seed_templates  # noqa: E402

from app.agent import gifts, policies  # noqa: E402
from app.agent.tools.write import render_template  # noqa: E402

CODES = (
    "ack_received",
    "proactive_fault",
    "clarify_request",
    "progress_update",
    "resolved",
    "gift_offer",
    "public_reply",
    "dm_invite",
    "closure_ack",
)
DOCUMENT = yaml.safe_load((ROOT / "data/templates/notifications.yaml").read_text())
SEGMENTS = [row["code"] for row in yaml.safe_load((ROOT / "data/segments.yaml").read_text())["segments"]]
CHANNELS = [row["code"] for row in yaml.safe_load((ROOT / "data/channels.yaml").read_text())["channels"]]
ENVIRONMENT = Environment(undefined=StrictUndefined)


class Catalog:
    def __init__(self):
        self.rows = {}
        seed_templates(self)

    def execute(self, sql, args):
        assert "on conflict" in sql
        self.rows[tuple(args[:4])] = tuple(args[4:6])

    async def fetchone(self, sql, args):
        if len(args) == 4:
            code, channel, segment, lang = args
            rows = [
                (key, value)
                for key, value in self.rows.items()
                if key[0] == code and key[1] == channel and key[3] == lang and key[2] in (None, segment)
            ]
        else:
            assert "(segment_code = %s or segment_code is null)" in sql
            code, segment, lang = args
            rows = [
                (key, value)
                for key, value in self.rows.items()
                if key[0] == code and key[3] == lang and key[2] in (None, segment)
            ]
        rows.sort(key=lambda item: (item[0][1] != "chat" if len(args) == 3 else False, item[0][2] is None))
        return rows[0][1] if rows else None


def variables():
    names = {v for row in DOCUMENT["templates"] for v in row.get("variables", [])}
    return {name: f"TEST_{name}" for name in names}


@pytest.mark.parametrize("lang", ["ru", "en"])
@pytest.mark.parametrize("segment", SEGMENTS)
async def test_every_code_renders_for_every_supported_channel(segment, lang):
    catalog = Catalog()
    for code in CODES:
        for channel in [*CHANNELS, "push", "sms", "social_reply", "tracking_page"]:
            subject, body = await render_template(catalog, code, channel, segment, variables(), lang)
            assert body, (code, channel, segment, lang)
            assert "{{" not in body and "{%" not in body
            assert policies.forbidden_phrases(body) == []
            if lang == "en":
                assert not re.search("[А-Яа-яЁё]", body), (code, channel, segment)
            if subject:
                assert "{{" not in subject


def test_jinja_equivalence_of_every_catalog_template():
    for row in DOCUMENT["templates"]:
        context = variables()
        for field in ("body", "subject"):
            text = row.get(field)
            if text is None:
                continue
            parsed = ENVIRONMENT.parse(text)
            assert meta.find_undeclared_variables(parsed) <= set(row.get("variables", []))
            assert "{%" not in text and "{#" not in text and "|" not in text
            actual = text
            for key, value in context.items():
                actual = actual.replace("{{ " + key + " }}", value).replace("{{" + key + "}}", value)
            assert actual.strip() == ENVIRONMENT.from_string(text).render(context).strip()


def test_template_seed_is_idempotent_and_covers_canonical_channels():
    catalog = Catalog()
    before = catalog.rows.copy()
    seed_templates(catalog)
    assert catalog.rows == before
    assert set(DOCUMENT["channels_for_star"]) == set(CHANNELS)


async def test_channel_fallback_never_selects_a_different_segment():
    catalog = Catalog()
    subject, body = await render_template(catalog, "ack_received", "sms", "mass", variables(), "ru")
    assert "TEST_manager" not in body
    assert "персональн" not in body.lower()
    _, vip = await render_template(catalog, "ack_received", "sms", "vip", variables(), "ru")
    assert "TEST_manager" in vip


@pytest.mark.parametrize(
    "bad",
    [None, {}, {"phrases": []}, {"phrases": [""]}, {"phrases": ["Bad"]}, {"phrases": ["bad", "bad"]}, {"phrases": [3]}],
)
def test_invalid_forbidden_configuration_fails_explicitly(tmp_path, bad):
    path = tmp_path / "phrases.yaml"
    path.write_text(yaml.safe_dump(bad))
    with pytest.raises(ValueError):
        policies._load_phrase_catalog(path)


def test_forbidden_catalog_preserves_previous_matching_and_order():
    phrases = policies.FORBIDDEN_PHRASES
    assert len(phrases) == 18
    assert policies.forbidden_phrases("ВЫ САМИ ВИНОВАТЫ. ГАРАНТИРУЕМ В ТЕЧЕНИЕ ЧАСА") == [
        "вы сами виноваты",
        "гарантируем",
        "в течение часа",
    ]
    assert policies.forbidden_phrases("Your fault, we guarantee refund immediately") == [
        "your fault",
        "guarantee",
        "refund immediately",
    ]
    assert policies.forbidden_phrases(None) == []
    assert policies.forbidden_phrases("Возврат выполнен. The fee has been returned.") == []


def test_partner_catalog_documents_existing_human_decision_requirement():
    catalog = yaml.safe_load((ROOT / "data/gifts.yaml").read_text())["gift_catalog"]
    partners = {row["code"]: row for row in catalog if row.get("partner_display_name")}
    assert set(partners) == policies.PARTNER_PRIVILEGES
    for row in partners.values():
        assert row["rule"]["requires_hitl"] is True
        assert set(row["segments"]) <= {"vip", "ultra_vip"}
        assert "(вымышл.)" in row["partner_display_name"]
    for segment in ("vip", "ultra_vip"):
        for criticality in ("low", "medium", "high"):
            for flags in ([], ["churn_intent"], ["repeat", "churn_intent"]):
                proposal = gifts.choose(segment, criticality, flags)
                if proposal["privilege_code"]:
                    assert proposal["requires_hitl"] is True


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_technical_identifiers_are_detected_only_as_complete_tokens(lang):
    for identifier in policies.TECHNICAL_IDENTIFIERS:
        text = f"Сбой ({identifier.upper()})" if lang == "ru" else f"Failure in {identifier.upper()}."
        assert policies.forbidden_phrases(text) == [identifier]
        for larger in (f"prefix_{identifier}", f"{identifier}_suffix", f"ERR-{identifier}-503", f"{identifier}2"):
            assert policies.forbidden_phrases(larger) == []
    assert policies.forbidden_phrases("The payment is processing; ожидается обработка платежа.") == []


def test_technical_catalog_tracks_unambiguous_system_codes_and_keeps_error_codes():
    systems = yaml.safe_load((ROOT / "data/systems.yaml").read_text())["systems"]
    expected = {
        row["code"]
        for row in systems
        if row["code"].startswith(("sub_", "core_"))
        or row["code"]
        in {"notification_gw", "promo_engine", "mobile_app", "web_bank", "contact_center", "social_listening"}
    }
    assert set(policies.TECHNICAL_IDENTIFIERS) == expected
    errors = yaml.safe_load((ROOT / "data/error_codes.yaml").read_text())["error_codes"]
    for error in errors:
        assert policies.forbidden_phrases(error["code"]) == []


@pytest.mark.parametrize(
    "identifiers", [[], [""], ["notification_gw", "notification_gw"], ["mobile_app.*"], ["Mobile_App"], [True]]
)
def test_invalid_technical_catalog_fails_explicitly(tmp_path, identifiers):
    path = tmp_path / "phrases.yaml"
    path.write_text(yaml.safe_dump({"phrases": ["bad"], "technical_identifiers": identifiers}))
    with pytest.raises(ValueError):
        policies._load_phrase_catalog(path)
