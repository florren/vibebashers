"""B13: тикетница, эскалации, действия оператора и нагрузка команд через HTTP (seeded БД)."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


@pytest.mark.integration
def test_tickets_escalations_actions(seeded: str) -> None:
    os.environ["DATABASE_URL"] = seeded
    os.environ["APP_ENV"] = "test"
    get_settings.cache_clear()
    try:
        _checks()
    finally:
        get_settings.cache_clear()


def _checks() -> None:
    with TestClient(create_app()) as c:
        lst = c.get("/api/tickets", params={"run_id": "all", "limit": 20}).json()
        assert {"items", "total"} <= set(lst)
        if not lst["items"]:
            pytest.skip("в сиде нет инцидентов")
        tk = next((x for x in lst["items"] if x["incident_status"] in ("routed", "classified", "new")), lst["items"][0])
        iid = tk["incident_id"]
        det = c.get(f"/api/tickets/{tk['ticket_id']}").json()
        assert det["incident_id"] == iid and "history" in det and "escalations" in det
        if det.get("decision_chain"):
            assert {"agent_run_id", "router_action", "llm_source", "steps"} <= set(det["decision_chain"])

        # действия оператора поверх FSM
        r = c.post(f"/api/incidents/{iid}/actions", json={"action": "change_priority", "priority": 1, "reason": "тест"})
        assert r.status_code == 200 and r.json()["priority"] == 1
        if tk["incident_status"] in ("routed", "classified", "new"):
            r = c.post(f"/api/incidents/{iid}/actions", json={"action": "take", "actor": "qa"})
            assert r.status_code == 200 and r.json()["status"] == "in_progress"
        r = c.post(f"/api/incidents/{iid}/actions", json={"action": "reroute", "team_code": "nope"})
        assert r.status_code == 404
        r = c.post(f"/api/incidents/{iid}/actions", json={"action": "mark_duplicate"})
        assert r.status_code == 422

        # ручная эскалация → очередь → ack → resolve → инцидент возвращается в работу
        r = c.post(
            "/api/escalations",
            json={"incident_id": iid, "reason": "VIP недоволен", "severity": "critical", "actor": "qa"},
        )
        assert r.status_code == 201
        esc = r.json()
        assert esc["status"] == "open" and esc["created_by"] == "human" and esc["public_id"].startswith("ESC-")
        q = c.get("/api/escalations", params={"run_id": "all", "status": ["open"]}).json()
        assert any(e["id"] == esc["id"] for e in q["items"]) and q["counts"].get("open", 0) >= 1
        one = c.get(f"/api/escalations/{esc['id']}").json()
        assert one["ticket"]["incident_id"] == iid
        r = c.post(f"/api/escalations/{esc['id']}/ack", json={"status": "resolved"})
        assert r.status_code == 422  # без резолюции нельзя
        r = c.post(f"/api/escalations/{esc['id']}/ack", json={"status": "acknowledged", "actor": "lead"})
        assert r.json()["status"] == "acknowledged" and r.json()["acknowledged_by"] == "lead"
        r = c.post(
            f"/api/escalations/{esc['id']}/ack",
            json={"status": "resolved", "resolution_ru": "Перезвонили клиенту", "actor": "lead"},
        )
        assert r.json()["status"] == "resolved"
        r = c.post(f"/api/escalations/{esc['id']}/ack", json={"status": "dismissed", "resolution_ru": "x"})
        assert r.status_code == 409
        hist = c.get(f"/api/tickets/{iid}").json()["history"]
        assert any(h["actor_type"] == "human" for h in hist)

        # закрыть и убедиться, что FSM не даёт закрыть дважды
        r = c.post(f"/api/incidents/{iid}/actions", json={"action": "close", "text": "решено в тесте"})
        assert r.status_code == 200 and r.json()["status"] == "closed"
        r = c.post(f"/api/incidents/{iid}/actions", json={"action": "reject"})
        assert r.status_code == 409

        teams = c.get("/api/teams/load", params={"run_id": "all"}).json()
        assert teams and {
            "team_code",
            "open",
            "in_progress",
            "sla_warning",
            "sla_breached",
            "sla_compliance_pct",
        } <= set(teams[0])
        arts = c.get(f"/api/incidents/{iid}/artifacts")
        assert arts.status_code == 200
