"""T-014: повторная загрузка справочников сохраняет их содержимое без дублей."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]


def test_reference_loading_is_idempotent(conn, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    from scripts.seed.refs import seed_catalogs, seed_geo

    queries = [
        "select code,system_code,product_code,title_ru,default_complexity,default_criticality,client_visible,description_ru from error_codes order by code",
        "select code,name_ru,name_en,base_criticality,requires_hitl,creates_incident from signal_types order by code",
        "select complexity,criticality,fix_days,report_days,take_hours from sla_matrix order by complexity,criticality",
        "select id,priority,match::text,team_codes,notes_ru from routing_rules order by priority,match::text",
    ]
    with conn.cursor() as cursor:
        seed_geo(cursor)
        seed_catalogs(cursor)
    before = [conn.execute(query).fetchall() for query in queries]
    assert len(before[0]) >= 25
    assert len(before[1]) == 10
    assert len(before[2]) == 9
    assert len(before[3]) >= 15
    conn.execute("update routing_rules set priority=1000, team_codes=array['team_compliance']")
    with conn.cursor() as cursor:
        seed_geo(cursor)
        seed_catalogs(cursor)
    assert [conn.execute(query).fetchall() for query in queries] == before
