"""T-108: реальные agent writes → audit triggers → безопасный scoped API."""

from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from app.config import get_settings
from app.main import create_app
from tests.helpers import dsn, new_run, run_agent_on

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]


async def test_db_activity_chain_isolation_masking_and_idempotent_migration(seeded, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        # Повторное применение миграции не удаляет историю и не дублирует триггеры.
        migration = (ROOT / "contracts/db/migrations/0011_db_activity_scope.sql").read_text()
        await conn.execute(migration)
        await conn.execute(migration)
        before = (await (await conn.execute("select coalesce(max(id),0) from db_activity_log")).fetchone())[0]
        cid = (
            await (
                await conn.execute("select id from clients where segment_code='mass' order by id limit 1")
            ).fetchone()
        )[0]
        old = await new_run(conn, "T108 previous run")
        old_sid, _ = await run_agent_on(
            conn, "Не могу открыть вклад: ошибка 503 в мобильном приложении", client_id=cid, run_id=old
        )
        current = await new_run(conn, "T108 current run")
        sid, state = await run_agent_on(
            conn, "Не могу открыть вклад: ошибка 503 в мобильном приложении", client_id=cid, run_id=current
        )
        await conn.commit()
        incident = (
            await (await conn.execute("select incident_id from incident_signals where signal_id=%s", (sid,))).fetchone()
        )[0]
        audit = await (
            await conn.execute(
                "select table_name,op from db_activity_log where id>%s and run_id=%s order by id", (before, current)
            )
        ).fetchall()
        wanted = ["incidents", "incident_signals", "incident_status_history", "notifications"]
        inserts = [table for table, op in audit if op == "INSERT"]
        positions = [inserts.index(table) for table in wanted]
        assert positions == sorted(positions)
        # Проверяем DELETE существующей строки: аудит переживает удаление и сохраняет run_id.
        await conn.execute("delete from incident_status_history where incident_id=%s", (incident,))
        await conn.execute(
            "update signals set external_contact=%s where id=%s",
            (
                Jsonb(
                    {
                        "contacts": {"email": "guest@example.com"},
                        "password": "synthetic-private-marker",
                        "nick": "@sample",
                    }
                ),
                sid,
            ),
        )
        # Реальная benchmark-строка вне эмуляции даёт honest unknown-run audit, не выдуманный лог.
        unscoped_agent = (
            await (
                await conn.execute(
                    "insert into agent_runs(kind,prompt_version,graph_version,sim_run_id) values ('bench','T108-fixture','1',null) returning id"
                )
            ).fetchone()
        )[0]
        await conn.commit()
        with TestClient(create_app()) as client:
            res = client.get("/api/engine/db/activity", params={"limit": 500})
            assert res.status_code == 200
            events = res.json()
            assert events and all(row["run_id"] not in (old, None) for row in events)
            all_events = client.get(
                "/api/engine/db/activity", params={"run_id": "all", "table": "agent_runs", "limit": 500}
            ).json()
            assert any(row["run_id"] is None and row["pk"] == str(unscoped_agent) for row in all_events)
            assert any(
                row["table_name"] == "incident_status_history" and row["op"] == "DELETE" and row["run_id"] == current
                for row in events
            )
            assert "synthetic-private-marker" not in res.text and "guest@example.com" not in res.text
            filtered = client.get("/api/engine/db/activity", params={"table": "incident_signals"}).json()
            assert filtered and all(row["table_name"] == "incident_signals" for row in filtered)
            older = client.get("/api/engine/db/activity", params={"limit": 2, "cursor": str(events[1]["id"])}).json()
            assert all(row["id"] < events[1]["id"] for row in older)
            assert any(
                row["run_id"] == old
                for row in client.get("/api/engine/db/activity", params={"run_id": "all", "limit": 500}).json()
            )
            rows = client.get("/api/engine/db/tables/signals/rows").json()
            assert sid in [row["id"] for row in rows] and old_sid not in [row["id"] for row in rows]
            assert next(row for row in rows if row["id"] == sid)["external_contact"]["password"] is None
            assert "guest@example.com" not in str(rows)
            for name in ("agent_steps", "incident_economics", "incident_signals", "incident_status_history"):
                assert client.get(f"/api/engine/db/tables/{name}/rows").status_code == 200
            counts = client.get("/api/engine/db/tables").json()
            assert counts and all(row["exact"] for row in counts)
            actual = (
                await (
                    await conn.execute(
                        "select count(*) from signals s join sim_runs r on r.id=s.run_id where r.kind='baseline' or r.id=%s",
                        (current,),
                    )
                ).fetchone()
            )[0]
            assert next(row["rows"] for row in counts if row["table"] == "signals") == actual
            for path in ("/api/engine/db/tables/users/rows", "/api/engine/db/activity?table=users"):
                assert client.get(path).status_code == 403
            for value in ("oops", "-1", "0", "1 OR 1=1", "9999999999999999999999999"):
                assert client.get("/api/engine/db/activity", params={"run_id": value}).status_code == 422
            assert client.get("/api/engine/db/activity", params={"cursor": "oops"}).status_code == 422
            assert client.get("/api/engine/db/activity", params={"run_id": "99999999"}).status_code == 404
            assert (
                client.get("/api/engine/db/tables/signals/rows", params={"run_id": str(old)}).json()[0]["run_id"] == old
            )
            assert state["agent_run_id"] > 0
        # Без current pointer API не превращает current в all.
        await conn.execute("update sim_state set current_run_id=null where id=1")
        await conn.commit()
        with TestClient(create_app()) as client:
            assert all(row["run_id"] not in (old, current) for row in client.get("/api/engine/db/activity").json())
    get_settings.cache_clear()


def test_audit_downgrade_upgrade_preserves_evidence_and_notifies(seeded):
    import json
    import os
    import subprocess
    import sys

    from app.realtime.notify import route

    with psycopg.connect(dsn(seeded), autocommit=True) as conn:
        before = conn.execute("select count(*) from db_activity_log").fetchone()[0]
    for revision in ("0010", "head", "head"):
        action = "downgrade" if revision == "0010" else "upgrade"
        result = subprocess.run(
            [sys.executable, "-m", "alembic", action, revision],
            cwd=ROOT / "backend",
            env={**os.environ, "DATABASE_URL": seeded},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr[-1000:]
    with psycopg.connect(dsn(seeded), autocommit=True) as listener, psycopg.connect(dsn(seeded)) as conn:
        assert conn.execute("select count(*) from db_activity_log").fetchone()[0] == before
        assert conn.execute("select version_num from alembic_version").fetchone()[0] == "0011"
        from app.api.engine import DB_ALLOW

        triggers = conn.execute("select tgname from pg_trigger where not tgisinternal").fetchall()
        names = {row[0] for row in triggers}
        assert all(f"{table}_activity" in names for table in DB_ALLOW)

        listener.execute("listen db_activity")
        signal = conn.execute("select id,run_id,status from signals order by id limit 1").fetchone()
        conn.execute("update signals set updated_at=now() where id=%s", (signal[0],))
        conn.commit()
        notifications = list(listener.notifies(timeout=1, stop_after=1))
        assert len(notifications) == 1
        envelope = json.loads(notifications[0].payload)
        assert envelope == {"table": "signals", "op": "UPDATE", "pk": str(signal[0]), "run_id": signal[1]}
        routed = route(notifications[0].channel, notifications[0].payload)
        assert routed and routed[0] == "db" and routed[3] == signal[1]
