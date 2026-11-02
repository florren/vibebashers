"""T-244: детерминированные выводы и безопасные настоящие XLSX."""

from io import BytesIO

import pytest
from fastapi import HTTPException
from openpyxl import load_workbook

from app.analytics.cabinet_report import bounded_json, workbook_bytes
from app.analytics.report_text import describe, status_label


def observed(n: int = 0, saved: float | None = None) -> dict:
    return {
        "kpi": {
            "signals": n,
            "negative": 0,
            "critical_share": None,
            "negative_share": None,
            "potential_loss_rub": None,
            "prevented_loss_rub": saved,
            "incidents": 0,
        },
        "sources": [],
    }


@pytest.mark.parametrize("lang", ["ru", "en"])
@pytest.mark.parametrize("n,saved", [(0, None), (0, 0), (3, 12.34)])
def test_main_edges_are_truthful_and_deterministic(lang, n, saved):
    result = describe(observed(n, saved), observed(), 0, 0, lang)
    assert result == describe(observed(n, saved), observed(), 0, 0, lang)
    assert len(result["summary"]) == 5
    import re

    assert len(re.split(r"(?<=[.!?])\s+", " ".join(result["summary"]))) == 5
    assert all(result["summary"])
    assert len(result["kpi"]) == 6
    assert result["kpi"][0]["delta"] == n
    assert result["kpi"][4]["value"] == saved
    assert result["kpi"][1]["value"] is None
    assert "полнота" in result["summary"][1] if lang == "ru" else "completeness" in result["summary"][1]
    assert all("в норме" not in k["verdict"] and "within norm" not in k["verdict"] for k in result["kpi"])


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_status_labels_are_words(lang):
    assert status_label("awaiting_human", lang) != "awaiting_human"
    assert status_label("resolved", lang) == status_label("closed", lang)


def test_json_limit_is_explicit(monkeypatch):
    monkeypatch.setattr("app.analytics.cabinet_report.MAX_BYTES", 8)
    with pytest.raises(HTTPException) as error:
        bounded_json({"text": "abcdefg"})
    assert error.value.status_code == 413


@pytest.mark.parametrize("attack", ['=HYPERLINK("https://invalid","x")', "+cmd", "-2+3", "@SUM(1)", "\t=1", "\n=1"])
def test_every_exported_string_is_text_not_formula_or_hyperlink(attack):
    view = {
        "daily": [],
        "monthly": [],
        "sources": [{"platform": {"name_ru": attack}, "signals": 1}],
        "regions": [
            {"name_ru": attack, "signals": 1, "negative": 0, "affected_clients": None, "identified_clients": 0}
        ],
    }
    data = {
        "lang": "ru",
        "money_exact": {"kpi": {}, "daily": [], "monthly": [], "previous": {}},
        "overview": view,
        "summary": [attack],
        "previous": {"note": attack, "kpi": {}},
        "kpi": [{"label": attack, "value": 1, "unit": attack, "delta": 0, "delta_unit": "count", "verdict": attack}],
        "signals": [
            {"public_id": attack, "received_sim": attack, "summary": attack, "status": attack, "source_platform": None}
        ],
        "method": {"formula_ru": [attack], "rules_version": [], "run_public_id": []},
        "top_problems": [
            {
                "problem": attack,
                "public_id": attack,
                "clients": None,
                "region": attack,
                "status": attack,
                "action": attack,
                "team": attack,
            }
        ],
        "attention": [{"problem": attack, "public_id": attack, "recommendation": attack, "team": attack}],
        "attention_total": 1,
        "sla_warning_count": 0,
        "sla_warning_note": attack,
        "red_phrase_signals": 0,
        "red_phrase_attention": [],
    }
    raw = workbook_bytes(data)
    assert raw.startswith(b"PK")
    wb = load_workbook(BytesIO(raw))
    assert wb.sheetnames == ["Главное", "KPI", "Сигналы", "Динамика", "Источники", "Регионы", "Методика"]
    attacks = 0
    for ws in wb:
        for row in ws:
            for cell in row:
                assert cell.data_type != "f"
                assert cell.hyperlink is None
                if cell.value == attack:
                    attacks += 1
                    assert cell.data_type == "s"
    assert attacks >= 8


def test_russian_saved_money_has_local_decimal_separator():
    result = describe(observed(1, 1234.56), observed(), 0, 0, "ru")
    assert "1\u00a0234,56" in result["summary"][3]


def test_unknown_runtime_type_is_not_silently_serialized():
    with pytest.raises(TypeError):
        bounded_json({"unsupported": object()})


@pytest.mark.parametrize("value", ["unsafe\x00text", "x" * 32768])
def test_unrepresentable_xlsx_text_rejected_before_opening_writers(value, monkeypatch):
    def unopened(*args, **kwargs):
        raise AssertionError("XML writers must not open for rejected text")

    monkeypatch.setattr("app.analytics.cabinet_report.Workbook", unopened)
    with pytest.raises(HTTPException) as error:
        workbook_bytes({"untrusted": value})
    assert error.value.status_code == 413


def test_main_topic_uses_recorded_types_and_declares_incomplete_coverage():
    from app.analytics.report_text import THEMES, main_topic
    from app.contracts.enums import SignalType

    assert set(THEMES) == set(SignalType)
    entries = [
        {"signal_type": "tech_fault"},
        {"signal_type": "tech_fault"},
        {"signal_type": None},
        {"signal_type": "legacy-unknown"},
    ]
    assert main_topic(entries, "ru") == "технические сбои — 2 из 2 сигналов с известным типом (4 всего)"
    assert main_topic(entries, "en") == "technical faults — 2 of 2 signals with a known type (4 total)"
    assert main_topic([{"signal_type": None}], "ru") is None


def test_all_kpi_observational_deltas_use_percentage_points_and_exact_decimal():
    from decimal import Decimal

    current, old = observed(8, Decimal("0.00")), observed(3, Decimal("0.01"))
    current["kpi"].update(
        negative_share=0.5, critical_share=0.25, potential_loss_rub=Decimal("900719925474099.93"), incidents=4
    )
    old["kpi"].update(negative_share=0.25, critical_share=0.125, potential_loss_rub=Decimal("0.01"), incidents=2)
    rows = {row["code"]: row for row in describe(current, old, 0, 0, "ru")["kpi"]}
    assert rows["signals"]["delta"] == 5 and rows["incidents"]["delta"] == 2
    assert rows["negative"]["delta"] == 25 and rows["critical"]["delta"] == 12.5
    assert rows["negative"]["delta_unit"] == "percentage_points"
    assert rows["loss"]["delta"] == Decimal("900719925474099.92")
    assert rows["prevented"]["delta"] == Decimal("-0.01")
    old["kpi"].update(negative_share=None, potential_loss_rub=None)
    rows = {row["code"]: row for row in describe(current, old, 0, 0, "ru")["kpi"]}
    assert rows["negative"]["delta"] is rows["loss"]["delta"] is None


def test_warning_requires_native_current_stage_deadline_and_nonterminal_state():
    import datetime as dt

    from app.analytics.cabinet_report import warning_current

    now = dt.datetime(2026, 11, 9, 6, tzinfo=dt.UTC)
    row = {
        "status": "in_progress",
        "stage_status": "in_progress",
        "stage_sim": now - dt.timedelta(hours=2),
        "created_sim": now - dt.timedelta(days=3),
        "release_sim": None,
        "warning_sim": now - dt.timedelta(hours=1),
        "warning_due_sim": now + dt.timedelta(hours=1),
        "sla_due_sim": now + dt.timedelta(hours=1),
    }
    assert warning_current(row, now)
    for patch in [
        {"status": "closed"},
        {"status": "resolved"},
        {"stage_status": "resolved"},
        {"stage_sim": None},
        {"release_sim": now},
        {"stage_sim": row["warning_sim"]},
        {"warning_sim": now + dt.timedelta(minutes=1)},
        {"warning_due_sim": now + dt.timedelta(hours=2)},
        {"warning_due_sim": "bad-date"},
        {"warning_due_sim": "2026-11-09T07:00:00"},
    ]:
        assert not warning_current({**row, **patch}, now), patch.keys()


def test_recorded_action_fallback_never_claims_an_actual_record_is_missing():
    from app.analytics.report_text import recorded_action

    assert recorded_action("release", "ru") == "Записан релиз исправления"
    assert recorded_action("take", "en") == "Work accepted"
    assert "(future_action)" in recorded_action("future_action", "en")
    assert recorded_action(None, "ru") == "Действие не записано"
