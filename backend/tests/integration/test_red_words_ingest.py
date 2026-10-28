from __future__ import annotations

import asyncio

import psycopg

from app.agent.graph import process_signal
from app.ingest.normalizer import create_signal, from_api_signal
from tests.integration.test_agent import PROFILE, _chain


def test_ingest_red_words_preserved_and_hitl(seeded: str, conn: psycopg.Connection) -> None:
    async def run():
        async with await psycopg.AsyncConnection.connect(
            seeded.replace("postgresql+psycopg://", "postgresql://")
        ) as db:
            msg = from_api_signal(
                {"text": "Комиссия за карту не устраивает. Подаю иск в суд и жалобу в ЦБ.", "external_id": "red-test-1"}
            )
            result = await create_signal(db, msg, source_code="api", emit_event=False)
            await db.commit()
            assert result["status"] == "accepted"
            duplicate = await create_signal(db, msg, source_code="api", emit_event=False)
            assert duplicate["status"] == "duplicate"
            assert duplicate["signal_id"] == result["signal_id"]
            state = await process_signal(db, signal_id=result["signal_id"], chain=_chain(), profile=PROFILE)
            return result["signal_id"], state

    signal_id, state = asyncio.run(run())
    assert state["classification"]["criticality"] == "high"
    assert "red_word" in state["classification"]["flags"]
    assert state["outcome"] == "awaiting_human", state["errors"]
    assert state["decision"]["human_reason"] == "legal_regulatory"
    row = conn.execute(
        "select red_words, flags, meta, classification from signals where id = %s", (signal_id,)
    ).fetchone()
    assert {"иск", "суд", "цб"} <= set(row[0])
    assert "red_word" in row[1]
    assert row[2]["red_words"]["legal"] is True
    assert row[3]["red_words"] == row[0]
    audit = conn.execute(
        "select payload->'meta'->'red_words' from ingest_messages where signal_id = %s", (signal_id,)
    ).fetchone()[0]
    assert audit["matches"]
    normalized = conn.execute(
        "select red_words, flags from v_signal_normalized where signal_id = %s", (signal_id,)
    ).fetchone()
    assert normalized == (row[0], row[1])


def test_product_facade_persisted_in_steps(seeded: str, conn: psycopg.Connection, monkeypatch) -> None:
    from app.agent import nodes

    original = nodes._llm

    async def llm(deps, node, *args, **kwargs):
        obj, meta = await original(deps, node, *args, **kwargs)
        if node == "classify":
            obj = {**obj, "product_line": "deposits"}
        return obj, meta

    monkeypatch.setattr(nodes, "_llm", llm)
    cid = conn.execute(
        "select c.id from clients c left join signals s on s.client_id = c.id where c.segment_code = 'mass' group by c.id order by count(s.id), c.id limit 1"
    ).fetchone()[0]

    async def run():
        async with await psycopg.AsyncConnection.connect(
            seeded.replace("postgresql+psycopg://", "postgresql://")
        ) as db:
            result = await create_signal(
                db,
                from_api_signal(
                    {
                        "text": "Не могу войти в мобильное приложение, ошибка APP-LOGIN-500. Технический сбой, почините доступ к вкладу.",
                        "client_id": cid,
                    }
                ),
                source_code="api",
                emit_event=False,
            )
            await db.commit()
            return await process_signal(db, signal_id=result["signal_id"], chain=_chain(), profile=PROFILE)

    state = asyncio.run(run())
    assert state["outcome"] == "deferred", (state["decision"], state["errors"])
    assert state["errors"] == []
    calls = conn.execute(
        "select tool_calls from agent_steps where run_id = %s and node = 'act'", (state["agent_run_id"],)
    ).fetchone()[0]
    facade = [c for c in calls if c["name"] == "route_to_product_team"]
    assert len(facade) == 1, calls
    assert facade[0]["wraps"] == ["route_to_department"]
    assert facade[0]["result"]["department"] == "team_deposits"
    assert state["decision"]["router_action"] == "route"
    assert any(p["rule"] == "router_action_tools" and p["passed"] for p in state["decision"]["policy_checks"])


def test_product_line_audit_uses_natural_key(seeded: str, conn: psycopg.Connection) -> None:
    conn.execute(
        "insert into product_lines (code, name_ru, name_en, rate_code, owner_team_code) select 'audit_test', name_ru, name_en, rate_code, owner_team_code from product_lines where code = 'deposits'"
    )
    conn.execute("update product_lines set name_ru = 'Синтетическое направление' where code = 'audit_test'")
    conn.execute("delete from product_lines where code = 'audit_test'")
    entries = conn.execute(
        "select op, pk from db_activity_log where table_name = 'product_lines' and pk = 'audit_test' order by id"
    ).fetchall()
    assert entries == [("INSERT", "audit_test"), ("UPDATE", "audit_test"), ("DELETE", "audit_test")]
