"""T-273: отделяем старую заглушку polling от входов человека и настоящих источников."""

from __future__ import annotations

from typing import Any

MOCK_SOURCE_CODES = frozenset({"mock_social_polling", "review_portal_feed"})


def is_mock_source(row: dict[str, Any]) -> bool:
    return (row.get("config") or {}).get("adapter") == "mock" or row["code"] in MOCK_SOURCE_CODES


# Только код SQL с фиксированным alias s; значения пользовательских запросов сюда не подставляются.
LEGACY_MOCK_SQL = """coalesce((s.origin='polling' and coalesce(s.meta->>'synthetic_mode','')<>'manual'
 and s.external_contact->>'nick'='mock_feed' and s.text like 'Сообщение mock-ленты #%%'),false)"""
HISTORICAL_SEED_SQL = """coalesce((s.origin='sim' and exists(select 1 from sim_runs r where r.id=s.run_id and r.kind='baseline')),false)"""
AUTOMATIC_EXCLUDED_SQL = f"({LEGACY_MOCK_SQL} or {HISTORICAL_SEED_SQL})"
