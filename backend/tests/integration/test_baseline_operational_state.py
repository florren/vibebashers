"""Чистое развёртывание: автоматический baseline, настройка LLM, штатный reset."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from app.main import create_app
from app.sim import baseline, baseline_contract, baseline_llm
from app.sim.engine import Simulator
from tests.helpers import dsn


@pytest.fixture
def operational_marker(seeded):
    uid = uuid4()
    bot_id = 9_100_100_000 + uid.int % 1_000_000_000
    try:
        yield uid, bot_id
    finally:
        with psycopg.connect(dsn(seeded)) as conn:
            conn.execute("delete from llm_runtime.credentials where uid=%s", (uid,))
            conn.execute(
                "delete from channel_runtime.telegram_chat_rate where bot_id=%s and chat_id=%s", (bot_id, bot_id)
            )


@pytest.mark.parametrize("full_archive", [False, True])
async def test_automatic_baseline_preserves_current_llm_and_delivery_state(
    seeded, tmp_path, full_archive, operational_marker
):
    # Fixture использует тот же seed CLI, что install.sh: dump/meta/sha создаются автоматически.
    installed = baseline.info("lite")
    assert installed["available"]
    source = Path(installed["path"])
    metadata = baseline._load_meta("lite")
    assert metadata and metadata["dump_sha256"] == baseline._sha256_file(source)
    uid, bot_id = operational_marker
    verifier = uid.bytes * 2
    with psycopg.connect(dsn(seeded)) as conn:
        conn.execute(
            "insert into llm_runtime.credentials(uid,provider,verifier,confirmed_tokens) values(%s,'gigachat',%s,123)",
            (uid, verifier),
        )
        conn.execute(
            "insert into channel_runtime.telegram_chat_rate(bot_id,chat_id,last_claimed_at) values(%s,%s,'2026-01-01')",
            (bot_id, bot_id),
        )
    if full_archive:
        # Старые prepared dumps могли содержать operational schemas: они также не откатываются.
        output = tmp_path / "full.dump"
        result = subprocess.run(
            [baseline._pg_tool("pg_dump"), "-Fc", "--no-owner", "--no-acl", "-f", str(output), dsn(seeded)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        source.write_bytes(output.read_bytes())
        baseline._write_artifacts("lite", source, metadata)
    prepared = source.with_suffix(".compatible.dump")
    prepared.write_bytes(b"obsolete legacy copy")
    prepared.with_suffix(".dump.provenance.json").write_text(
        json.dumps({"source_sha256": "obsolete", "output_sha256": baseline._sha256_file(prepared)})
    )
    with psycopg.connect(dsn(seeded)) as conn:
        initial_time = conn.execute("select sim_time from sim_state where id=1").fetchone()[0]
        main_id = conn.execute("select id from llm_profiles where role='main' order by id limit 1").fetchone()[0]
        conn.execute("update llm_profiles set temperature=0.37,rpm_limit=47 where id=%s", (main_id,))
        conn.execute(
            "insert into llm_api_keys(provider,label,encrypted_key,tokens_limit) values('gigachat','current-only',pgp_sym_encrypt('synthetic-current-key','test-only-secret'),54321)"
        )
        conn.execute(
            "insert into settings(key,value) values('llm',%s) on conflict(key) do update set value=excluded.value",
            (Jsonb({"openrouter_budget_usd": 3.5}),),
        )
        conn.execute(
            "insert into settings(key,value) values('setup_payload',%s) on conflict(key) do update set value=excluded.value",
            (Jsonb({"llm": {"main_profile_id": main_id}, "bank": {"name": "Changed bank"}}),),
        )
        conn.execute("update llm_runtime.credentials set confirmed_tokens=456 where uid=%s", (uid,))
        conn.execute(
            "update channel_runtime.telegram_chat_rate set last_claimed_at='2026-02-01' where bot_id=%s and chat_id=%s",
            (bot_id, bot_id),
        )
        conn.execute(
            "insert into llm_cassettes(request_hash,provider,model,response) values(%s,'mock','current-only','{}')",
            (str(uid),),
        )
        conn.execute("update clients set is_active=false")
        conn.execute("update sim_state set sim_time=sim_time+interval '3 days',running=false where id=1")
        before = baseline_llm.read_sync(conn.cursor())
        current_schema = baseline_contract.read_sync(conn.cursor())
    assert before != metadata["llm_config_fingerprint"]
    if full_archive:
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            await baseline.preflight_restore(conn, "lite")
            await baseline.restore(conn, profile="lite")
    else:
        app = create_app()
        with TestClient(app) as client:

            async def attach_simulator():
                sim = Simulator(dsn=seeded)
                await sim.load_state()
                app.state.sim = sim

            client.portal.call(attach_simulator)
            response = client.post("/api/sim/baseline/restore")
            assert response.status_code == 202, response.text
            state = client.get("/api/sim/state").json()
            assert state["running"] is False
            assert state["sim_time"].startswith(initial_time.isoformat()[:19])
    with psycopg.connect(dsn(seeded)) as conn:
        assert conn.execute("select count(*) from clients where is_active").fetchone()[0] == 200
        assert conn.execute("select sim_time,running from sim_state where id=1").fetchone() == (initial_time, False)
        assert baseline_llm.read_sync(conn.cursor()) == before
        assert baseline_contract.read_sync(conn.cursor()) == current_schema
        assert conn.execute("select value from settings where key='llm'").fetchone()[0] == {
            "openrouter_budget_usd": 3.5
        }
        assert conn.execute("select value->'bank' from settings where key='setup_payload'").fetchone()[0] != {
            "name": "Changed bank"
        }
        assert (
            conn.execute("select confirmed_tokens from llm_runtime.credentials where uid=%s", (uid,)).fetchone()[0]
            == 456
        )
        assert (
            conn.execute(
                "select last_claimed_at::date::text from channel_runtime.telegram_chat_rate where bot_id=%s and chat_id=%s",
                (bot_id, bot_id),
            ).fetchone()[0]
            == "2026-02-01"
        )
        assert conn.execute("select count(*) from llm_cassettes where request_hash=%s", (str(uid),)).fetchone()[0] == 1
        assert (
            conn.execute(
                "select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname like 'pg_temp%%' and c.relname like 'cx_restore_%%'"
            ).fetchone()[0]
            == 0
        )


def test_operational_guard_rolls_back_bank_and_configuration_together(seeded, monkeypatch):
    source = Path(baseline.info("lite")["path"])
    with psycopg.connect(dsn(seeded)) as conn:
        conn.execute("update clients set display_name='rollback-marker' where id=(select min(id) from clients)")
        before = baseline_llm.read_sync(conn.cursor())
        clock = conn.execute("select sim_time from sim_state where id=1").fetchone()[0]
    original = baseline.subprocess.run

    def corrupt_sql(command, **kwargs):
        result = original(command, **kwargs)
        if command[0].endswith("pg_restore") and "-f" in command and result.returncode == 0:
            with Path(command[command.index("-f") + 1]).open("a") as stream:
                stream.write("\nupdate public.llm_profiles set temperature=0.23;\n")
        return result

    monkeypatch.setattr(baseline.subprocess, "run", corrupt_sql)
    with pytest.raises(baseline.BaselineToolingError, match="транзакция восстановления отменена"):
        baseline._run_pg_restore(dsn(seeded), source)
    with psycopg.connect(dsn(seeded)) as conn:
        assert conn.execute("select display_name from clients order by id limit 1").fetchone()[0] == "rollback-marker"
        assert baseline_llm.read_sync(conn.cursor()) == before
        assert conn.execute("select sim_time from sim_state where id=1").fetchone()[0] == clock
