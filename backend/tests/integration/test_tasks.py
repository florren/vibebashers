"""T-079/T-080: задачи сотрудников — список, готовность, выдача/замена/отклонение подарка через HTTP (seeded БД)."""

from __future__ import annotations

import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from app.config import get_settings
from app.main import create_app


@pytest.mark.integration
def test_tasks_gift_flow(seeded: str) -> None:
    os.environ["DATABASE_URL"] = seeded
    os.environ["APP_ENV"] = "test"
    get_settings.cache_clear()
    try:
        _checks(seeded)
    finally:
        get_settings.cache_clear()


def _seed_task(dsn: str, when: str) -> int:
    with psycopg.connect(dsn.replace("postgresql+psycopg://", "postgresql://"), autocommit=True) as conn:
        row = conn.execute(
            "select i.id, i.primary_client_id, i.run_id from incidents i join clients c on c.id = i.primary_client_id where c.segment_code in ('mass','premium') order by i.id limit 1"
        ).fetchone()
        assert row, "в сиде нет инцидентов"
        iid, cid, rid = row
        conn.execute("update incidents set status = 'resolved' where id = %s", (iid,))
        tid = conn.execute(
            "insert into tasks (run_id, kind, incident_id, client_id, assignee, payload, status, requires_hitl, created_sim) values (%s, 'gift', %s, %s, 'team_cx', %s, 'open', false, now()) returning id",
            (rid, iid, cid, Jsonb({"when": when, "gift": {"gift_code": "bonus_points", "points": 300, "when": when}})),
        ).fetchone()
        assert tid
        return int(tid[0])


def _checks(dsn: str) -> None:
    t1 = _seed_task(dsn, "after_resolved")
    t2 = _seed_task(dsn, "after_resolved")
    t3 = _seed_task(dsn, "now")
    with TestClient(create_app()) as c:
        lst = c.get("/api/tasks", params={"run_id": "all", "status": ["open"], "ready": "true", "limit": 50}).json()
        ids = {x["id"] for x in lst["items"]}
        assert {t1, t2, t3} <= ids and all(x["ready"] for x in lst["items"])
        assert lst["counts"].get("gift:open", 0) >= 3
        one = next(x for x in lst["items"] if x["id"] == t1)
        assert one["client"] and one["incident_public_id"].startswith("INC-") and one["gift_name"]

        # выдача: задача done, клиенту ушло уведомление по шаблону gift_offer, у инцидента флаг gift_issued
        r = c.post(f"/api/tasks/{t1}", json={"action": "approve"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "done" and "300" in r.json()["payload"]["issued"]["label"]
        assert c.post(f"/api/tasks/{t1}", json={"action": "approve"}).status_code == 409

        # замена подарком не для сегмента → 422; корректная замена → выдано
        r = c.post(f"/api/tasks/{t2}", json={"action": "change", "payload": {"gift_code": "business_class_discount"}})
        assert r.status_code == 422
        assert c.post(f"/api/tasks/{t2}", json={"action": "change"}).status_code == 422
        r = c.post(
            f"/api/tasks/{t2}",
            json={"action": "change", "payload": {"gift_code": "bonus_points", "points": 1000}, "comment": "удвоили"},
        )
        assert r.status_code == 200, r.text
        assert (
            r.json()["status"] == "done"
            and r.json()["payload"]["gift"]["points"] == 1000
            and r.json()["payload"]["decision"]["comment"] == "удвоили"
        )

        r = c.post(f"/api/tasks/{t3}", json={"action": "reject", "comment": "не положено"})
        assert r.status_code == 200 and r.json()["status"] == "rejected"
        assert c.post("/api/tasks/999999999", json={"action": "approve"}).status_code == 404

    with psycopg.connect(dsn.replace("postgresql+psycopg://", "postgresql://")) as conn:
        n = conn.execute(
            "select count(*) from notifications where template_code = 'gift_offer' and body like %s",
            ("%1000 бонусных баллов%",),
        ).fetchone()
        assert n and n[0] >= 1
        f = conn.execute(
            "select flags from incidents where id = (select incident_id from tasks where id = %s)", (t1,)
        ).fetchone()
        assert f and "gift_issued" in (f[0] or [])
