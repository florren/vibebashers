"""Полный personal → mock → Journey, включая чужую сессию и чужой run."""

import uuid

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.agent.graph import process_signal
from app.config import get_settings
from app.ingest.normalizer import create_signal, from_landing
from app.llm.failover import ProviderChain
from app.main import create_app
from app.public_chat import create_public_app
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("subject_index", [0, 1])
async def test_personal_journey_keeps_complete_own_conversation(seeded, monkeypatch, subject_index):
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    client = TestClient(create_public_app())
    boot = client.get("/api/personal/session").json()
    refs = []
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        for text in [
            "Тест стенда: в приложении не открывается вклад. Прошу помочь.",
            "Спасибо. Как проверить статус обращения?",
        ]:
            await conn.execute(
                "update personal_chat_sessions set created_at=now()-interval '3 seconds',last_message_at=now()-interval '3 seconds'"
            )
            await conn.commit()
            accepted = client.post(
                "/api/personal/messages",
                json={"request_id": str(uuid.uuid4()), "form_token": boot["form_token"], "text": text},
            )
            assert accepted.status_code == 202, accepted.text
            refs.append(accepted.json()["public_id"])
            sid, rid, at = await (
                await conn.execute("select id,run_id,received_sim from signals where public_id=%s", (refs[-1],))
            ).fetchone()
            state = await process_signal(conn, signal_id=sid, chain=mock_chain(), profile=MOCK_PROFILE, sim_time=at)
            await conn.commit()
        assert state["classification"]["signal_type"] == "info_request"
        assert state["decision"]["incident_action"] == "link_existing"
        assert state["decision"]["router_action"] == "none"
        assert (
            await (
                await conn.execute(
                    "select count(distinct x.incident_id),count(distinct x.signal_id) "
                    "from incident_signals x join signals s on s.id=x.signal_id where s.public_id=any(%s)",
                    (refs,),
                )
            ).fetchone()
        ) == (1, 2)
        assert state["decision"]["gift"] is None and not state["decision"]["needs_human"]
        history = client.get("/api/personal/messages").json()
        bodies = [answer["text"] for answer in history["answers"]]
        assert len(bodies) == 2
        assert "Обновления по вашему обращению появляются в этом чате" in bodies[1]
        assert "Спасибо за тёплые слова" not in bodies[1]
        session_id = (
            await (
                await conn.execute("select session_id from personal_chat_messages where signal_id=%s", (sid,))
            ).fetchone()
        )[0]
        # Искажённая legacy-связь parent не доказывает принадлежность диалогу.
        for foreign_run in [False, True]:
            other_run = await new_run(conn, "foreign conversation") if foreign_run else rid
            other = await create_signal(
                conn,
                from_landing(contact={}, text="Чужое синтетическое сообщение", parent_signal_id=sid),
                source_code="api",
                run_id=other_run,
                sim_time=at,
            )
            other_session = session_id
            if not foreign_run:
                other_session = (
                    await (
                        await conn.execute(
                            "insert into personal_chat_sessions(token_hash,run_id) values(%s,%s) returning id",
                            (uuid.uuid4().hex, rid),
                        )
                    ).fetchone()
                )[0]
            await conn.execute(
                "insert into personal_chat_messages(session_id,request_id,request_hash,signal_id) values(%s,%s,%s,%s)",
                (other_session, uuid.uuid4(), "0" * 64, other["signal_id"]),
            )
            await conn.execute(
                "insert into notifications(run_id,signal_id,recipient_type,channel_code,template_code,body,status,sent_sim,sent_at) values(%s,%s,'client','landing','ack_received','Чужая доставка','sent',%s,clock_timestamp())",
                (other_run, other["signal_id"], at),
            )
        await conn.commit()

    def forbidden(*args, **kwargs):
        raise AssertionError("Journey must not invoke LLM")

    monkeypatch.setattr(ProviderChain, "complete_structured", forbidden)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://test") as http:
        response = await http.get(f"/api/journey/{refs[subject_index]}", params={"run_id": str(rid)})
    assert response.status_code == 200, response.text
    model = response.json()
    assert [message["text_ru"] for message in model["client_lane"]] == bodies
    signal_events = [e for stage in model["stages"] for e in stage["events"] if e["kind"] == "signal_created"]
    assert all(any(ref in str(event) for event in signal_events) for ref in refs)
    assert all("Чужое синтетическое сообщение" not in event["brief_ru"] for event in signal_events)
