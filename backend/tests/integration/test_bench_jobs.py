"""T-129: фоновые задания и настоящий API, только синтетические/mock-провайдеры."""

from __future__ import annotations

import time
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.bench.service import BenchService
from app.config import get_settings
from app.llm.failover import ProviderChain
from app.llm.mock import MockProvider
from app.main import create_app


@pytest.fixture
def bench_db(seeded: str, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    yield seeded
    get_settings.cache_clear()


def profiles(conn: psycopg.Connection, *codes: str) -> list[int]:
    return [
        conn.execute(
            "insert into llm_profiles(code,provider,model,role,temperature,is_active) values(%s,'mock','mock-rules-v1','bench_only',0,true) returning id",
            (code,),
        ).fetchone()[0]
        for code in codes
    ]


def dataset(conn: psycopg.Connection) -> int:
    return conn.execute("select id from bench_datasets where code='lite_v1'").fetchone()[0]


def finished(client: TestClient, ids: list[int]) -> list[dict[str, Any]]:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        rows = [client.get(f"/api/bench/runs/{id_}").json() for id_ in ids]
        if all(r["status"] in ("done", "failed", "cancelled") for r in rows):
            return rows
        time.sleep(0.02)
    pytest.fail("benchmark did not finish within 15 s")


def test_selected_profiles_background_ws_persistence_export(
    bench_db: str, conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = profiles(conn, "bench_test_a", "bench_test_b")
    did = dataset(conn)
    case_count = conn.execute("select count(*) from bench_cases where dataset_id=%s", (did,)).fetchone()[0]
    conn.execute("update llm_profiles set price_in_per_1m=100,price_out_per_1m=200 where id=any(%s)", (ids,))

    def slow_chain(self: BenchService, profile, saved):
        provider = MockProvider(latency_ms=20)
        return ProviderChain([provider]), [provider], None

    monkeypatch.setattr(BenchService, "chain", slow_chain)
    with TestClient(create_app()) as client, client.websocket_connect("/ws/stream") as ws:
        ws.receive_json()
        ws.send_json({"type": "subscribe", "topics": ["bench"]})
        ws.receive_json()
        dry = client.post("/api/bench/runs", json={"dataset_id": did, "llm_profile_ids": ids, "dry_run": True})
        assert dry.status_code == 202 and dry.json()["run_ids"] == []
        assert [f["llm_profile_id"] for f in dry.json()["forecast"]] == ids
        assert conn.execute("select count(*) from bench_runs").fetchone()[0] == 0
        response = client.post("/api/bench/runs", json={"dataset_id": did, "llm_profile_ids": ids, "repeats": 2})
        assert response.status_code == 202, response.text
        run_ids = response.json()["run_ids"]
        assert len(run_ids) == 2
        event = ws.receive_json()
        assert event["topic"] == "bench" and event["type"] == "bench.progress"
        assert event["data"]["id"] in run_ids
        assert event["data"]["status"] == "running"
        rows = finished(client, run_ids)
        assert [r["llm_profile_code"] for r in rows] == ["bench_test_a", "bench_test_b"]
        assert all(r["status"] == "done" and r["progress"] == 1 and len(r["results"]) == case_count * 2 for r in rows)
        assert all(r["metrics"]["fallback_rate"] == 0 for r in rows)
        assert all(r["metrics"]["cost_estimate"] > 0 and r["metrics"]["stability"] == 1 for r in rows)
        assert conn.execute("select count(*) from bench_results").fetchone()[0] == case_count * 4
        exported = client.get(f"/api/bench/runs/{run_ids[0]}/export?format=json")
        assert exported.status_code == 200
        assert len(exported.json()["results"]) == case_count * 2
        csv = client.get(f"/api/bench/runs/{run_ids[0]}/export?format=csv")
        assert csv.status_code == 200 and "predicted" in csv.text.splitlines()[0]
    # Новый экземпляр приложения читает сохранённые результаты.
    with TestClient(create_app()) as client:
        recovered = client.get(f"/api/bench/runs/{run_ids[0]}").json()
        assert recovered["status"] == "done" and len(recovered["results"]) == case_count * 2


def test_reject_limits_inactive_unknown_and_invalid_repeats(bench_db: str, conn: psycopg.Connection) -> None:
    active, inactive = profiles(conn, "bench_tight", "bench_inactive")
    conn.execute("update llm_profiles set rpd_limit=1 where id=%s", (active,))
    conn.execute("update llm_profiles set is_active=false where id=%s", (inactive,))
    body = {"dataset_id": dataset(conn), "llm_profile_ids": [active]}
    with TestClient(create_app()) as client:
        dry = client.post("/api/bench/runs", json={**body, "dry_run": True})
        assert dry.status_code == 202
        assert dry.json()["forecast"][0]["fits_limits"] is False
        assert "rpd_limit" in dry.json()["forecast"][0]["warning"]
        assert client.post("/api/bench/runs", json=body).status_code == 409
        for id_ in (inactive, 999999):
            assert (
                client.post("/api/bench/runs", json={**body, "llm_profile_ids": [id_], "dry_run": True}).status_code
                == 422
            )
        for repeats in (0, 4):
            assert client.post("/api/bench/runs", json={**body, "repeats": repeats}).status_code == 422
    assert conn.execute("select count(*) from bench_runs").fetchone()[0] == 0


def test_cancel_queued_running_and_recover_interruption(
    bench_db: str, conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = profiles(conn, "bench_cancel")[0]

    def slow_chain(self: BenchService, profile, saved):
        p = MockProvider(latency_ms=200)
        return ProviderChain([p]), [p], None

    monkeypatch.setattr(BenchService, "chain", slow_chain)
    with TestClient(create_app()) as client:
        body = {"dataset_id": dataset(conn), "llm_profile_ids": [pid]}
        first = client.post("/api/bench/runs", json=body).json()["run_ids"][0]
        second = client.post("/api/bench/runs", json=body).json()["run_ids"][0]
        assert client.delete(f"/api/bench/runs/{second}").status_code == 204
        assert client.delete(f"/api/bench/runs/{first}").status_code == 204
        assert all(r["status"] == "cancelled" for r in finished(client, [first, second]))
    interrupted = conn.execute(
        "insert into bench_runs(dataset_id,llm_profile_id,prompt_version,status) values(%s,%s,'test','running') returning id",
        (dataset(conn), pid),
    ).fetchone()[0]
    with TestClient(create_app()) as client:
        detail = client.get(f"/api/bench/runs/{interrupted}").json()
        assert detail["status"] == "failed" and "interrupted" in detail["error"]


def test_provider_failure_never_becomes_mock_success(
    bench_db: str, conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.llm.base import ProviderError

    class Unavailable(MockProvider):
        name = "synthetic_unavailable"

        async def complete_structured(self, *args, **kwargs):
            raise ProviderError("rate_limit", "synthetic 429")

    def failed_chain(self: BenchService, profile, saved):
        p = Unavailable()
        return ProviderChain([p], append_mock=False), [p], None

    monkeypatch.setattr(BenchService, "chain", failed_chain)
    pid = profiles(conn, "bench_failure")[0]
    with TestClient(create_app()) as client:
        response = client.post("/api/bench/runs", json={"dataset_id": dataset(conn), "llm_profile_ids": [pid]})
        row = finished(client, response.json()["run_ids"])[0]
        assert row["status"] == "failed" and row["error"]
        assert row["results"] == [] and row["metrics"] is None
    assert conn.execute("select count(*) from bench_results").fetchone()[0] == 0


def test_dataset_list_excludes_empty_and_mixed(bench_db: str, conn: psycopg.Connection) -> None:
    empty = conn.execute(
        "insert into bench_datasets(code,title_ru) values('bench_empty','Пустой') returning id"
    ).fetchone()[0]
    mixed = conn.execute(
        "insert into bench_datasets(code,title_ru) values('bench_mixed','Смешанный') returning id"
    ).fetchone()[0]
    conn.execute(
        "insert into bench_cases(dataset_id,channel_code,text,gold) select %s,channel_code,text,gold from bench_cases where dataset_id=%s limit 1",
        (mixed, dataset(conn)),
    )
    conn.execute(
        "insert into bench_cases(dataset_id,channel_code,text,gold) select %s,channel_code,'Синтетический тест','{}'::jsonb from bench_cases limit 1",
        (mixed,),
    )
    pid = profiles(conn, "bench_datasets_test")[0]
    with TestClient(create_app()) as client:
        listed = client.get("/api/bench/datasets").json()
        assert dataset(conn) in {row["id"] for row in listed}
        assert not {empty, mixed} & {row["id"] for row in listed}
        for did in (empty, mixed):
            assert client.post("/api/bench/runs", json={"dataset_id": did, "llm_profile_ids": [pid]}).status_code == 422


@pytest.mark.parametrize("fail_first_commit", [False, True])
def test_key_usage_persists_exactly_once(
    bench_db: str, conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch, fail_first_commit: bool
) -> None:
    from app.bench import service

    class SyntheticOpenAI(MockProvider):
        def __init__(self, *args, **kwargs):
            super().__init__()

        async def aclose(self):
            pass

    monkeypatch.setattr(service, "OpenAICompatProvider", SyntheticOpenAI)
    pid = profiles(conn, "bench_key_accounting")[0]
    conn.execute("update llm_profiles set provider='openai_compatible' where id=%s", (pid,))
    set_setting = service.set_setting
    failures = 0

    async def flaky_save(*args, **kwargs):
        nonlocal failures
        if fail_first_commit and failures == 0:
            failures += 1
            raise psycopg.OperationalError("synthetic rollback")
        await set_setting(*args, **kwargs)

    monkeypatch.setattr(service, "set_setting", flaky_save)
    app = create_app()
    with TestClient(app) as client:
        key = client.post(
            "/api/settings/llm-keys",
            json={
                "provider": "openai_compatible",
                "label": "synthetic",
                "key": "synthetic-test-only",
                "tokens_limit": 10000000,
            },
        )
        assert key.status_code == 201, key.text
        response = client.post("/api/bench/runs", json={"dataset_id": dataset(conn), "llm_profile_ids": [pid]})
        assert response.status_code == 202, response.text
        row = finished(client, response.json()["run_ids"])[0]
        assert row["status"] == ("failed" if fail_first_commit else "done")
        assert len(row["results"]) == (
            1
            if fail_first_commit
            else conn.execute("select count(*) from bench_cases where dataset_id=%s", (dataset(conn),)).fetchone()[0]
        )
        tokens = sum(r["prompt_tokens"] + r["completion_tokens"] for r in row["results"])
        stored = conn.execute("select value from settings where key='llm_keys'").fetchone()[0][0]
        assert stored["tokens_used"] == tokens
        assert stored["requests_today"] == len(row["results"])
        cached = next(iter(app.state.bench.keys.values()))
        assert cached.tokens_used == tokens
        assert cached.requests_today == len(row["results"])
