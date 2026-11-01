"""T-108: границы read inspector, legacy audit и честные оценки статистики."""

from contextlib import asynccontextmanager

import pytest

from app.api import engine


def test_nested_inspector_masks_contacts_secrets_and_raw_llm_payloads():
    row = engine._mask_row(
        {
            "id": 7,
            "payload": {"nested": [{"contact": {"phone": "+7 900 001-22-33"}, "api_key": "private-marker"}], "safe": 4},
            "prompt": "private-prompt",
            "body": "Напишите guest@example.com",
        }
    )
    assert row["id"] == 7 and row["payload"]["safe"] == 4
    assert row["payload"]["nested"][0]["contact"] is None
    assert row["payload"]["nested"][0]["api_key"] is None
    assert row["prompt"] is None
    assert "guest@example.com" not in row["body"]
    assert "private-marker" not in str(row)


@asynccontextmanager
async def fake_read():
    yield object()


async def test_large_all_scope_counts_use_marked_postgres_estimate(monkeypatch):
    async def fetch_all(_conn, sql, _args):
        if "pg_stat_user_tables" in sql:
            return [{"relname": table, "n_live_tup": 12000} for table in engine.DB_ALLOW]
        return []

    async def unexpected_exact(*_args):
        raise AssertionError("крупная all-таблица должна использовать явно отмеченную оценку")

    monkeypatch.setattr(engine, "read_db", fake_read)
    monkeypatch.setattr(engine, "fetch_all", fetch_all)
    monkeypatch.setattr(engine, "fetch_one", unexpected_exact)
    rows = await engine.get_engine_db_tables(run_id="all")
    assert len(rows) == len(engine.DB_ALLOW)
    assert all(row["rows"] == 12000 and row["exact"] is False for row in rows)


async def test_legacy_audit_projects_field_names_without_leaking_values(monkeypatch):
    async def fetch_all(*_args):
        return [
            {
                "id": 1,
                "run_id": None,
                "table_name": "signals",
                "summary": {"contacts": "private-marker", "status": "new"},
            }
        ]

    monkeypatch.setattr(engine, "read_db", fake_read)
    monkeypatch.setattr(engine, "fetch_all", fetch_all)
    rows = await engine.get_engine_db_activity(limit=50, cursor=None, run_id="all", table=None)
    assert rows[0]["summary"] == {"changed_fields": ["contacts", "status"]}
    assert "private-marker" not in str(rows)


@pytest.mark.parametrize("value", ["-1", "0", "abc", "1234567890123456789", "１２"])
async def test_invalid_run_is_rejected_before_database(value):
    with pytest.raises(engine.HTTPException) as error:
        await engine._db_scope(None, value)
    assert error.value.status_code == 422
