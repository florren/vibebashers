"""Наблюдаемость: JSONL-приёмник, HTTP-счётчики, правила рекомендаций и индекс здоровья, Markdown (docs/REPORTS.md)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.observability import http as http_obs
from app.observability.jsonl import JsonlSink, read_tail, summarize
from app.observability.quality import _health, _recommend, render_markdown


def test_jsonl_sink_writes_and_filters(tmp_path: Path) -> None:
    sink = JsonlSink(tmp_path / "app.jsonl", min_level="info")
    sink(None, "info", {"event": "a", "level": "info", "x": 1})
    sink(None, "debug", {"event": "b", "level": "debug"})
    sink(None, "error", {"event": "http_request", "level": "error", "status": 500})
    recs = read_tail(tmp_path / "app.jsonl", limit=10, min_level="warning")
    assert [r["event"] for r in recs] == ["http_request"]
    assert read_tail(tmp_path / "app.jsonl", limit=10, min_level="debug")[-1]["event"] == "a"  # debug не записан
    s = summarize(tmp_path / "app.jsonl")
    assert s["items"][0]["event"] == "http_request" and s["items"][0]["count"] == 1


def test_jsonl_rotation(tmp_path: Path) -> None:
    sink = JsonlSink(tmp_path / "app.jsonl", max_bytes=50, backups=2)
    for i in range(10):
        sink(None, "info", {"event": "e", "level": "info", "i": i, "pad": "x" * 30})
    assert (tmp_path / "app.jsonl.1").exists()


def test_http_stats_snapshot_501_is_not_5xx() -> None:
    st = http_obs.HttpStats()
    st.record("GET", "/api/x", 200, 10, path="/api/x", request_id="r1", error=None)
    st.record("POST", "/api/y", 501, 5, path="/api/y", request_id="r2", error=None)
    st.record("GET", "/api/z", 500, 2500, path="/api/z", request_id="r3", error="RuntimeError: boom")
    st.record("GET", "/{path:path}", 404, 1, path="/favicon.ico", request_id="r4", error=None)
    snap = st.snapshot()
    assert snap["requests"] == 4 and snap["s5xx"] == 1 and snap["s501"] == 1 and snap["s4xx"] == 1 and snap["slow"] == 1
    assert snap["routes"][0]["route"] == "/api/z"  # худший маршрут первым
    assert [e["path"] for e in snap["recent_errors"]] == ["/api/z", "/api/y"]  # 404 статики не считается ошибкой


def test_middleware_records_requests() -> None:
    before = http_obs.stats.snapshot()["requests"]
    with TestClient(create_app()) as c:
        r = c.get("/api/health")
        assert r.status_code == 200
        c.get("/api/sim/baseline")  # 501-заглушка
    snap = http_obs.stats.snapshot()
    assert snap["requests"] >= before + 2
    assert any(r["route"] == "/api/sim/baseline" and r["s501"] >= 1 for r in snap["routes"])


def _summary(**over: object) -> dict:
    base: dict = {
        "agent_runs": 100,
        "agent_failed": 0,
        "agent_fallback_mock": 0,
        "scenarios_passed": 1,
        "steps": 800,
        "llm_steps": 300,
        "steps_fallback_pct": 0.0,
        "steps_error": 0,
        "hitl_decided": 10,
        "hitl_overridden": 0,
        "hitl_override_pct": 0.0,
        "hitl_pending": 2,
        "incidents": 40,
        "sla_breached": 0,
        "scenarios_failed": [],
        "compliance_alerts": 5,
        "compliance_false_pct": 0.0,
        "transcripts_failed": 0,
        "http_5xx": 0,
        "http_501": 0,
    }
    base.update(over)
    return base


def test_recommendations_and_health() -> None:
    ok = _recommend(_summary(), {}, [], [], None, [], [], [])
    assert ok[0]["area"] == "ok" and _health(_summary()) == 100

    nodes = {
        "classify": {
            "node": "classify",
            "total": 100,
            "ok": 80,
            "fallback": 0,
            "error": 15,
            "retry": 5,
            "skipped": 0,
            "error_rate": 20.0,
            "fallback_rate": 0.0,
        }
    }
    scen = [{"id": "x", "title_ru": "X", "passed": False, "failed_checks": [{"code": "c1", "detail": "d"}]}]
    http = {
        "s5xx": 3,
        "s501": 2,
        "slow": 0,
        "routes": [
            {"method": "GET", "route": "/api/a", "s5xx": 3, "s501": 0, "s4xx": 0, "slow": 0, "max_ms": 10},
            {"method": "POST", "route": "/api/b", "s5xx": 0, "s501": 2, "s4xx": 0, "slow": 0, "max_ms": 5},
        ],
    }
    s = _summary(
        agent_failed=2,
        steps_error=20,
        steps_fallback_pct=96.0,
        hitl_overridden=5,
        hitl_override_pct=50.0,
        scenarios_failed=["x"],
        http_5xx=3,
        http_501=2,
    )
    rec = _recommend(
        s,
        nodes,
        [{"changed_fields": ["team_code"]}],
        scen,
        http,
        [],
        [{"error": "timeout", "n": 2, "last_run_id": 1}],
        [{"node": "classify", "error": "schema", "n": 3, "last_run_id": 1}],
    )
    areas = {(r["severity"], r["area"]) for r in rec}
    assert ("high", "agent") in areas and ("medium", "llm") in areas and ("high", "scenario") in areas
    assert ("high", "api") in areas and ("medium", "product") in areas
    assert rec[0]["severity"] == "high" and rec[-1]["severity"] in ("medium", "low")
    assert any("/api/b" in r["text"] for r in rec if r["area"] == "product")
    assert _health(s) < 50


def test_render_markdown_sections() -> None:
    rep = {
        "version": "quality-v1",
        "summary": {**_summary(), "generated_at": "2026-10-22T12:00:00+00:00", "run_id": None, "health": 100},
        "agent": {"runs": [], "run_errors": [], "nodes": [], "step_errors": []},
        "hitl": {"by_decision": [], "overrides": [], "pending": {"n": 0, "oldest": None}},
        "incidents": {"by_status": [], "sla_breached": [], "signals_by_status": [], "followups_by_status": []},
        "scenarios": [{"id": "a", "title_ru": "A", "passed": True, "failed_checks": [], "last_run_at": None}],
        "compliance": {"alerts": [], "transcripts_by_status": [], "transcripts_failed": []},
        "http": None,
        "recommendations": [{"severity": "low", "area": "ok", "text": "Проблем нет", "where": "—"}],
    }
    md = render_markdown(rep)
    assert "## Сводка" in md and "## Что доработать" in md and "✓ a — A" in md and "100/100" in md
