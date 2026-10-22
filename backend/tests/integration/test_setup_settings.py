"""T-009/T-010: мастер настройки и настройки стенда через HTTP (seeded БД)."""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.llm import secrets as sec
from app.main import create_app


def test_secrets_roundtrip() -> None:
    tok = sec.encrypt("sk-or-v1-abcdef1234", "s3cret")
    assert tok.startswith("enc1:") and "abcdef" not in tok
    assert sec.decrypt(tok, "s3cret") == "sk-or-v1-abcdef1234"
    with pytest.raises(ValueError):
        sec.decrypt(tok, "other")
    assert sec.hint("sk-or-v1-abcdef1234") == "…1234"


@pytest.mark.integration
def test_setup_and_settings(seeded: str) -> None:
    os.environ["DATABASE_URL"] = seeded
    os.environ["APP_ENV"] = "test"
    get_settings.cache_clear()
    try:
        _checks()
    finally:
        get_settings.cache_clear()


def _checks() -> None:
    with TestClient(create_app()) as c:
        st = c.get("/api/setup/status").json()
        assert {"completed", "current_step", "steps_done"} <= set(st)

        # разделы мастера
        r = c.put(
            "/api/setup",
            json={
                "bank": {"name": "Тест-банк"},
                "policies": {"confidence_threshold": 0.8, "dedup_window_hours": 6},
                "sim": {"seed": 7, "fault_rate": 2.0},
            },
        )
        assert r.status_code == 200
        p = r.json()
        assert (
            p["bank"]["name"] == "Тест-банк"
            and p["policies"]["confidence_threshold"] == 0.8
            and p["sim"]["seed"] == 7
            and p["sim"]["intensities"]["fault"] == 2.0
        )
        st = c.get("/api/setup/status").json()
        assert {2, 3, 5} <= set(st["steps_done"])
        pol = c.get("/api/settings").json()["policies"]
        assert pol["confidence_threshold"] == 0.8 and pol["dedup_window_sim_hours"] == 6

        # LLM: mock-проверка и ключи
        assert c.post("/api/setup/test-llm", json={"provider": "mock", "model": "mock-rules-v1"}).json()["ok"] is True
        k = c.post(
            "/api/settings/llm-keys", json={"provider": "openai_compatible", "label": "t", "key": "sk-or-v1-abcdef1234"}
        )
        assert k.status_code == 201 and "key_enc" not in k.json() and k.json()["key_hint"] == "…1234"
        keys = c.get("/api/settings/llm-keys").json()
        assert keys and all("key_enc" not in x for x in keys)
        assert "llm_keys" not in c.get("/api/settings/export").json()["settings"]
        assert c.delete(f"/api/settings/llm-keys/{k.json()['id']}").status_code == 204

        # профили
        prof = {"code": "test_fast", "provider": "mock", "model": "mock-rules-v1", "role": "fast"}
        assert c.post("/api/settings/llm-profiles", json=prof).status_code == 201
        assert c.post("/api/settings/llm-profiles", json=prof).status_code == 409
        pid = next(x["id"] for x in c.get("/api/settings/llm-profiles").json() if x["code"] == "test_fast")
        assert c.patch(f"/api/settings/llm-profiles/{pid}", json={**prof, "model": "mock-rules-v2"}).status_code == 200
        assert c.delete(f"/api/settings/llm-profiles/{pid}").status_code == 204

        # SLA: валидация и round-trip
        sla = c.get("/api/settings/sla-matrix").json()
        assert len(sla) == 9
        assert c.put("/api/settings/sla-matrix", json=sla).status_code == 200
        assert c.put("/api/settings/sla-matrix", json=sla[:8]).status_code == 422
        bad = [dict(x) for x in sla]
        bad[0]["report_days"] = [99]
        assert c.put("/api/settings/sla-matrix", json=bad).status_code == 422

        # маршрутизация, шаблоны, подарки, экономика, психотипы — round-trip
        rules = c.get("/api/settings/routing-rules").json()
        assert c.put("/api/settings/routing-rules", json=rules).status_code == 200
        assert (
            c.put("/api/settings/routing-rules", json=[{"match": {}, "team_codes": ["no_such_team"]}]).status_code
            == 422
        )
        tpl = c.get("/api/settings/templates").json()
        assert c.put("/api/settings/templates", json=tpl).status_code == 200
        assert len(c.get("/api/settings/templates").json()) == len(tpl)
        gifts = c.get("/api/settings/gifts").json()
        assert c.put("/api/settings/gifts", json=gifts).status_code == 200
        econ = c.get("/api/settings/economics").json()
        assert "rates" in econ and econ["rates"]
        econ["detractor_share"] = 0.2
        assert c.put("/api/settings/economics", json=econ).status_code == 200
        assert c.get("/api/settings/economics").json()["detractor_share"] == 0.2
        ps = c.get("/api/settings/psychotypes").json()
        assert ps["psychotypes"] and ps["segment_mix"]
        assert c.put("/api/settings/psychotypes", json=ps).status_code == 200
        seg = next(iter(ps["segment_mix"]))
        broken = {"psychotypes": [], "segment_mix": {seg: {k: 0.1 for k in ps["segment_mix"][seg]}}}
        assert c.put("/api/settings/psychotypes", json=broken).status_code == 422

        # экспорт → импорт
        exp = c.get("/api/settings/export").json()
        assert exp["sla_matrix"] and exp["routing_rules"] and exp["economics_settings"]
        assert c.post("/api/settings/import", json=exp).status_code == 200

        # генерация данных (lite, идемпотентна на уже засеянной БД)
        r = c.post("/api/setup/generate", json={"profile": "lite", "seed": 42})
        assert r.status_code == 202 and r.json()["job_id"]
        for _ in range(120):
            g = c.get("/api/setup/generate").json()
            if g["status"] in ("done", "failed"):
                break
            time.sleep(0.5)
        assert g["status"] == "done", g["log"][-5:]
        assert g["coverage"] and g["progress"] == 1.0 and 9 in c.get("/api/setup/status").json()["steps_done"]

        # завершение мастера
        assert c.post("/api/setup").status_code == 204
        assert c.get("/api/setup/status").json()["completed"] is True
        assert c.post("/api/setup/test-tgbot", json={"token": "123456:ABCDEFGHIJK"}).json()["ok"] is False
