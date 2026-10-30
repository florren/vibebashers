"""T-267: связь SIG→INC, поиск прошлых/терминальных состояний и неизменяемая поздняя информация."""

from __future__ import annotations

import asyncio
import datetime as dt
from contextlib import asynccontextmanager
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.api import hitl, signals
from app.ingest.normalizer import create_signal, from_api_signal
from app.main import create_app
from tests.helpers import dsn

pytestmark = pytest.mark.integration
NOW = dt.datetime(2026, 11, 10, 12, tzinfo=dt.UTC)


def make_case(conn: Any, url: str, label: str, cid: int) -> dict[str, Any]:
    rid = conn.execute(
        "insert into sim_runs(kind,label,seed,started_sim) values ('free',%s,42,%s) returning id", (label, NOW)
    ).fetchone()[0]

    async def ingest():
        async with await psycopg.AsyncConnection.connect(dsn(url)) as ac:
            result = await create_signal(
                ac,
                from_api_signal(
                    {
                        "channel_code": "chat",
                        "client_id": cid,
                        "text": f"Проверка непрерывности {label}",
                        "external_id": label,
                    },
                    origin="jury",
                ),
                source_code="api",
                run_id=rid,
                sim_time=NOW,
                emit_event=False,
            )
            await ac.commit()
            return result["signal_id"]

    sid = asyncio.run(ingest())
    ar = conn.execute(
        "insert into agent_runs(sim_run_id,signal_id,prompt_version,graph_version,outcome,started_sim) values (%s,%s,'v1.1','v1','deferred',%s) returning id",
        (rid, sid, NOW),
    ).fetchone()[0]
    iid = conn.execute(
        """insert into incidents(run_id,title,incident_type,product_code,team_code,complexity,criticality,priority,status,created_by,created_sim,sla_due_sim,take_due_sim,primary_client_id,agent_run_id) values (%s,'continuity','tariff_terms','debit_card','team_cx','easy','high',1,'escalated','scenario',%s,%s,%s,%s,%s) returning id""",
        (rid, NOW, NOW + dt.timedelta(days=1), NOW + dt.timedelta(hours=1), cid, ar),
    ).fetchone()[0]
    conn.execute(
        "insert into incident_signals(incident_id,signal_id,link_type,linked_sim) values (%s,%s,'primary',%s)",
        (iid, sid, NOW),
    )
    conn.execute("update agent_runs set incident_id=%s where id=%s", (iid, ar))
    conn.execute("update signals set status='deferred' where id=%s", (sid,))
    task = conn.execute(
        "insert into tasks(run_id,kind,incident_id,created_sim) values (%s,'manual_review',%s,%s) returning id",
        (rid, iid, NOW),
    ).fetchone()[0]
    hid = conn.execute(
        """insert into human_decisions(sim_run_id,agent_run_id,signal_id,incident_id,task_id,requested_sim,reason,agent_proposal,options)
      values (%s,%s,%s,%s,%s,%s,'repeat_negative','{"kind":"escalation"}','[]') returning id""",
        (rid, ar, sid, iid, task, NOW),
    ).fetchone()[0]
    esc = conn.execute(
        "insert into escalations(run_id,signal_id,incident_id,human_decision_id,reason,severity,to_role,status,created_by,created_sim) values (%s,%s,%s,%s,'repeat_negative','high','cx_lead','open','agent',%s) returning id",
        (rid, sid, iid, hid, NOW),
    ).fetchone()[0]
    refs = {
        kind: conn.execute(f"select public_id from {table} where id=%s", (key,)).fetchone()[0]
        for kind, table, key in [
            ("signal", "signals", sid),
            ("incident", "incidents", iid),
            ("human", "human_decisions", hid),
            ("agent", "agent_runs", ar),
            ("task", "tasks", task),
            ("escalation", "escalations", esc),
            ("run", "sim_runs", rid),
        ]
    }
    return dict(rid=rid, sid=sid, iid=iid, hid=hid, refs=refs)


def patch_db(monkeypatch: Any, url: str) -> None:
    @asynccontextmanager
    async def connect():
        async with await psycopg.AsyncConnection.connect(dsn(url), autocommit=True, row_factory=dict_row) as ac:
            yield ac

    monkeypatch.setattr(hitl, "db", connect)
    monkeypatch.setattr(signals, "db", connect)


def test_find_any_state_and_related_identifier(seeded: str, conn: Any, monkeypatch: Any) -> None:
    patch_db(monkeypatch, seeded)
    cid = conn.execute("select id from clients order by id limit 1").fetchone()[0]
    old = make_case(conn, seeded, "continuity-old", cid)
    new = make_case(conn, seeded, "continuity-new", cid)
    conn.execute("update sim_state set current_run_id=%s where id=1", (new["rid"],))
    ar = conn.execute("select agent_run_id from human_decisions where id=%s", (old["hid"],)).fetchone()[0]
    conn.execute(
        "insert into agent_steps(run_id,seq,node,status,input,output) values (%s,1,'wait_human','ok','{}',%s::jsonb)",
        (ar, '{"human_decision_id":' + str(old["hid"]) + "}"),
    )
    conn.execute("update agent_runs set outcome='awaiting_human' where id=%s", (ar,))
    # Даже прежний checkpoint того же AR не превращает non-blocking эскалацию в resume.

    with TestClient(create_app()) as client:
        for status in (
            "new",
            "processing",
            "classified",
            "linked",
            "deferred",
            "awaiting_human",
            "awaiting_client",
            "answered",
            "closed",
            "noise",
            "error",
        ):
            conn.execute("update signals set status=%s where id=%s", (status, old["sid"]))
            response = client.get("/api/signals", params={"run_id": "all", "q": old["refs"]["signal"]})
            assert response.status_code == 200, response.text
            assert [s["id"] for s in response.json()["items"]] == [old["sid"]]
            assert response.json()["items"][0]["incident_refs"] == [old["refs"]["incident"]]
        for ref in old["refs"].values():
            for path, key, expected in [("/api/signals", "id", old["sid"]), ("/api/hitl/queue", "id", old["hid"])]:
                response = client.get(path, params={"run_id": "all", "q": ref})
                assert response.status_code == 200, (ref, response.text)
                assert expected in [s[key] for s in response.json()["items"]], (ref, response.json())
                assert (
                    new["hid"] not in [s["id"] for s in response.json()["items"]]
                    if "hitl" in path
                    else new["sid"] not in [s["id"] for s in response.json()["items"]]
                )
        queue = client.get("/api/hitl/queue", params={"q": old["refs"]["signal"].lower()}).json()
        item = queue["items"][0]
        assert (
            item["signal"]["public_id"] == old["refs"]["signal"]
            and item["incident"]["public_id"] == old["refs"]["incident"]
        )
        assert not item["can_resume"] and item["decision"] is None
        assert item["related_incidents"][0]["public_id"] == old["refs"]["incident"]
        assert item["escalations"][0]["ref"] == old["refs"]["escalation"]
        assert (
            client.get("/api/hitl/queue", params={"q": old["refs"]["signal"], "run_id": new["rid"]}).json()["items"]
            == []
        )
        page = client.get("/api/hitl/queue", params={"limit": 1}).json()
        next_page = client.get("/api/hitl/queue", params={"limit": 1, "cursor": page["next_cursor"]}).json()
        assert page["items"][0]["id"] != next_page["items"][0]["id"] and page["total"] == next_page["total"]
        for path in ("/api/signals", "/api/hitl/queue"):
            assert client.get(path, params={"run_id": "all", "q": "' OR true --"}).json()["items"] == []
            assert client.get(path, params={"cursor": "invalid"}).status_code == 422


def test_feedback_after_timeout_and_after_human_decision_never_replays(
    seeded: str, conn: Any, monkeypatch: Any
) -> None:
    patch_db(monkeypatch, seeded)
    cid = conn.execute("select id from clients order by id limit 1").fetchone()[0]
    case = make_case(conn, seeded, "continuity-feedback", cid)
    hid = case["hid"]
    before = conn.execute(
        "select (select count(*) from ledger_entries),(select count(*) from agent_steps),(select count(*) from incidents)"
    ).fetchone()
    with TestClient(create_app()) as client:
        base = f"/api/hitl/{hid}"
        ar = conn.execute("select agent_run_id from human_decisions where id=%s", (hid,)).fetchone()[0]
        conn.execute("update agent_runs set outcome=null where id=%s", (ar,))
        conn.execute("update human_decisions set agent_proposal='{}' where id=%s", (hid,))
        assert client.post(base, json={"decision": "accept"}).status_code == 409
        assert conn.execute("select decision from human_decisions where id=%s", (hid,)).fetchone()[0] is None
        conn.execute("update agent_runs set outcome='deferred' where id=%s", (ar,))
        conn.execute("update human_decisions set agent_proposal=%s::jsonb where id=%s", ('{"kind":"escalation"}', hid))
        # Нет checkpoint wait_human: подтверждение эскалации не возобновляет граф.
        assert (
            client.post(base, json={"decision": "modify", "modified_proposal": {"gift": {"points": 99999}}}).status_code
            == 409
        )
        answered = client.post(base, json={"decision": "accept", "comment": "Запрос проверен"})
        assert answered.status_code == 200, answered.text
        assert (
            client.get("/api/hitl/queue", params={"q": case["refs"]["signal"]}).json()["items"][0]["decision"]
            == "accept"
        )
        assert client.get("/api/hitl/queue", params={"run_id": case["rid"]}).json()["items"] == []
        payload = {"comment": "Поздняя информация для продукта", "idempotency_key": "feedback-key"}
        first = client.post(base + "/feedback", json=payload)
        assert first.status_code == 201, first.text
        again = client.post(base + "/feedback", json=payload)
        assert again.status_code == 201 and again.json()["id"] == first.json()["id"]
        assert client.post(base + "/feedback", json={**payload, "comment": "Другое содержимое"}).status_code == 409
        assert client.post(base + "/feedback", json={"comment": " ", "idempotency_key": "bad"}).status_code == 422
        assert client.post(base + "/feedback", json={**payload, "amount_rub": 90000}).status_code == 422
        assert (
            client.post(
                base + "/feedback", json={**payload, "idempotency_key": "second", "comment": "Уточнение оператора"}
            ).status_code
            == 201
        )
        assert client.get(base).json()["feedback_count"] == 2
        history = client.get(base + "/feedback", params={"limit": 1}).json()
        older = client.get(base + "/feedback", params={"limit": 1, "cursor": history["next_cursor"]}).json()
        assert history["items"][0]["comment"] == "Уточнение оператора" and older["items"][0]["id"] == first.json()["id"]
        assert client.get("/api/hitl/queue", params={"q": "Поздняя информация"}).json()["items"][0]["id"] == hid
        conn.execute("update human_decisions set decision='modify',decided_by='timeout' where id=%s", (hid,))
        item = client.get("/api/hitl/queue", params={"run_id": case["rid"]}).json()["items"][0]
        assert item["automatic_decision"] and not item["can_resume"]
        assert (
            client.post(
                base + "/feedback",
                json={**payload, "idempotency_key": "timeout-note", "comment": "Ответ после таймаута"},
            ).status_code
            == 201
        )
        assert client.post(base, json={"decision": "accept"}).status_code == 409
        assert conn.execute("select decision,decided_by from human_decisions where id=%s", (hid,)).fetchone() == (
            "modify",
            "timeout",
        )
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute("update hitl_feedback set comment='overwrite' where id=%s", (first.json()["id"],))
        assert (
            before
            == conn.execute(
                "select (select count(*) from ledger_entries),(select count(*) from agent_steps),(select count(*) from incidents)"
            ).fetchone()
        )


def test_all_registered_entity_codes_reach_case(seeded: str, conn: Any, monkeypatch: Any) -> None:
    patch_db(monkeypatch, seeded)
    cid = conn.execute("select id from clients order by id limit 1").fetchone()[0]
    case = make_case(conn, seeded, "continuity-entities", cid)
    rid, sid, iid = case["rid"], case["sid"], case["iid"]
    ar = conn.execute("select agent_run_id from human_decisions where id=%s", (case["hid"],)).fetchone()[0]
    emp, branch = conn.execute("select id,branch_id from employees order by id limit 1").fetchone()
    audio = conn.execute(
        "insert into audio_sessions(run_id,branch_id,employee_id,client_id,incident_id,source,stt_provider,diarization_mode,started_sim) values (%s,%s,%s,%s,%s,'transcript','none','manual',%s) returning public_id,id",
        (rid, branch, emp, cid, iid, NOW),
    ).fetchone()
    tr = conn.execute(
        "insert into transcripts(run_id,kind,source,format,turns,received_sim,audio_session_id,branch_id,employee_id,signal_id) values (%s,'branch_retail','api','json','[]',%s,%s,%s,%s,%s) returning public_id,id",
        (rid, NOW, audio[1], branch, emp, sid),
    ).fetchone()
    post = conn.execute(
        "insert into external_posts(run_id,platform,author_nick,text,posted_sim,signal_id) values (%s,'review_portal','synthetic_case','Тест связей',%s,%s) returning public_id,id",
        (rid, NOW, sid),
    ).fetchone()
    conn.execute("update signals set transcript_id=%s,external_post_id=%s where id=%s", (tr[1], post[1], sid))
    ntf = conn.execute(
        "insert into notifications(run_id,signal_id,incident_id,recipient_type,channel_code,body) values (%s,%s,%s,'cx','internal','Тест связей') returning public_id",
        (rid, sid, iid),
    ).fetchone()[0]
    fup = conn.execute(
        "insert into followups(sim_run_id,agent_run_id,signal_id,incident_id,wake_sim,reason,payload) values (%s,%s,%s,%s,%s,'Тест связей','{}') returning public_id",
        (rid, ar, sid, iid, NOW),
    ).fetchone()[0]
    account = conn.execute("select id from accounts order by id limit 1").fetchone()[0]
    led = conn.execute(
        "insert into ledger_entries(run_id,account_id,kind,amount,posted_sim,correlation_id,agent_run_id,created_by) values (%s,%s,'debit',1,%s,'00000000-0000-0000-0000-000000000267',%s,'scenario') returning public_id",
        (rid, account, NOW, ar),
    ).fetchone()[0]
    rule = conn.execute("select code from business_rules order by code limit 1").fetchone()[0]
    conn.execute(
        "insert into rule_evaluations(run_id,signal_id,agent_run_id,rule_code,rule_version,result) values (%s,%s,%s,%s,1,'matched')",
        (rid, sid, ar, rule),
    )
    err = conn.execute("select code from error_codes order by code limit 1").fetchone()[0]
    conn.execute("update incidents set error_code=%s where id=%s", (err, iid))
    conn.execute(
        "insert into csi_responses(signal_id,csi_no,complaint_ru) values (%s,'CSI-999999','Тест связей')", (sid,)
    )
    token = "synthetic_tracking_token_for_continuity_267"
    conn.execute("update signals set tracking_token=%s where id=%s", (token, sid))
    refs = [
        token,
        "00000000-0000-0000-0000-000000000267",
        audio[0],
        tr[0],
        post[0],
        ntf,
        fup,
        led,
        rule,
        err,
        "CSI-999999",
        conn.execute("select public_id from clients where id=%s", (cid,)).fetchone()[0],
        conn.execute("select public_id from employees where id=%s", (emp,)).fetchone()[0],
        "VSP-" + conn.execute("select code from branches where id=%s", (branch,)).fetchone()[0].removeprefix("VSP-"),
    ]
    with TestClient(create_app()) as client:
        for ref in refs:
            response = client.get("/api/hitl/queue", params={"q": ref})
            assert response.status_code == 200, (ref, response.text)
            assert token not in response.text
            assert case["hid"] in [row["id"] for row in response.json()["items"]], (ref, response.json())


def test_related_entities_without_human_request(seeded: str, conn: Any, monkeypatch: Any) -> None:
    patch_db(monkeypatch, seeded)
    cid = conn.execute("select id from clients order by id limit 1").fetchone()[0]
    case = make_case(conn, seeded, "continuity-no-hitl", cid)
    conn.execute("update escalations set human_decision_id=null where human_decision_id=%s", (case["hid"],))
    conn.execute("delete from human_decisions where id=%s", (case["hid"],))
    with TestClient(create_app()) as client:
        response = client.get("/api/hitl/queue", params={"q": case["refs"]["signal"]})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["items"] == []
        refs = {row["ref"] for row in result["related_entities"]}
        assert {case["refs"][key] for key in ("signal", "incident", "agent", "task", "escalation", "run")} <= refs
        assert case["refs"]["human"] not in refs
        assert result["related_entities_truncated"] is False
        scoped = client.get("/api/hitl/queue", params={"q": case["refs"]["signal"], "run_id": case["rid"] + 100}).json()
        assert scoped["items"] == [] and scoped["related_entities"] == []


def test_timeout_does_not_replay_when_operator_answered_after_scan(seeded: str, conn: Any, monkeypatch: Any) -> None:
    from unittest.mock import AsyncMock

    from app.agent import graph
    from app.llm.base import LLMProfile
    from app.llm.failover import ProviderChain
    from app.llm.mock import MockProvider

    cid = conn.execute("select id from clients order by id limit 1").fetchone()[0]
    case = make_case(conn, seeded, "continuity-timeout-race", cid)
    conn.execute(
        "insert into settings(key,value) values ('policies','{\"hitl_timeout_escalate\":false}') on conflict(key) do update set value=excluded.value"
    )
    resume = AsyncMock()
    monkeypatch.setattr(graph, "resume_after_human", resume)

    async def race() -> None:
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as ac:

            class InterleavedConnection:
                async def execute(self, query: str, params: Any = None) -> Any:
                    if query.startswith("update human_decisions set decision = 'modify'"):
                        # Оператор ответил после чтения due-списка, до conditional UPDATE таймера.
                        conn.execute(
                            "update human_decisions set decision='accept',decided_by='operator' where id=%s",
                            (case["hid"],),
                        )
                    return await ac.execute(query, params)

                async def commit(self) -> None:
                    await ac.commit()

            await graph.expire_hitl(
                InterleavedConnection(),
                sim_time=NOW + dt.timedelta(hours=3),
                chain=ProviderChain([MockProvider()]),
                profile=LLMProfile(code="mock", provider="mock", model="mock-rules-v1", role="main"),
            )

    asyncio.run(race())
    resume.assert_not_awaited()
    assert conn.execute("select decision,decided_by from human_decisions where id=%s", (case["hid"],)).fetchone() == (
        "accept",
        "operator",
    )
