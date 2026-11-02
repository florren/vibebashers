"""T-021: canonical seed идемпотентен, история неизменна, DB tags доходят до scoring."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from psycopg.types.json import Jsonb

from app.bench import datasets, runner
from app.bench.service import BenchService
from app.config import get_settings
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.llm.mock import MockProvider

ROOT = Path(__file__).resolve().parents[3]


def test_canonical_seed_keeps_ids_and_full_gold(seeded, conn, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    from scripts.seed.bench import seed_dataset, source_metadata

    with conn.cursor() as cur:
        for code, expected_count in (("golden_v1", 200), ("lite_v1", 40)):
            did, description = conn.execute(
                "select id,description from bench_datasets where code=%s", (code,)
            ).fetchone()
            assert json.loads(description) == source_metadata(code)
            before = conn.execute("select id from bench_cases where dataset_id=%s order by id", (did,)).fetchall()
            assert len(before) == expected_count
            rows = datasets.load_rows(code)
            seed_dataset(cur, code, rows)
            seed_dataset(cur, code, rows)
            assert (
                conn.execute("select id from bench_cases where dataset_id=%s order by id", (did,)).fetchall() == before
            )
            stored = conn.execute(
                "select gold,tags from bench_cases where dataset_id=%s order by id", (did,)
            ).fetchall()
            assert all(set(gold) == set(datasets.GOLD_FIELDS) for gold, _ in stored)
            assert all(f"dataset-case:{source['id']}" in tags for source, (_, tags) in zip(rows, stored, strict=True))


def test_changed_corpus_refuses_to_rewrite_historical_case_or_result(seeded, conn, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    from scripts.seed.bench import seed_dataset

    did = conn.execute("select id from bench_datasets where code='golden_v1'").fetchone()[0]
    profile = conn.execute("select id from llm_profiles where provider='mock' order by id limit 1").fetchone()[0]
    cid, text = conn.execute(
        "select id,text from bench_cases where dataset_id=%s order by id limit 1", (did,)
    ).fetchone()
    rid = conn.execute(
        "insert into bench_runs(dataset_id,llm_profile_id,prompt_version) values(%s,%s,'T021') returning id",
        (did, profile),
    ).fetchone()[0]
    result = conn.execute(
        "insert into bench_results(run_id,case_id,predicted,correct,json_valid_first_try,latency_ms) values(%s,%s,'{}','{}',true,1) returning id",
        (rid, cid),
    ).fetchone()[0]
    rows = copy.deepcopy(datasets.load_rows("golden_v1"))
    rows[0]["text"] += " Другая версия."
    with conn.cursor() as cur, pytest.raises(ValueError, match="сохранён"):
        seed_dataset(cur, "golden_v1", rows)
    assert conn.execute("select text from bench_cases where id=%s", (cid,)).fetchone() == (text,)
    assert conn.execute("select run_id,case_id from bench_results where id=%s", (result,)).fetchone() == (rid, cid)
    assert conn.execute("select count(*) from bench_cases where dataset_id=%s", (did,)).fetchone() == (200,)


async def test_db_ambiguous_tags_are_not_lost_before_runner(seeded, conn, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    try:
        did = conn.execute(
            "insert into bench_datasets(code,title_ru) values('t021_ambiguous','T021') returning id"
        ).fetchone()[0]
        source = datasets.load_rows("lite_v1")[0]
        conn.execute(
            "insert into bench_cases(dataset_id,channel_code,text,gold,tags) values(%s,%s,%s,%s,%s)",
            (did, source["channel"], source["text"], Jsonb(source["gold"]), ["ambiguous"]),
        )
        profile = conn.execute("select id from llm_profiles where provider='mock' order by id limit 1").fetchone()[0]
        _, cases, _, _ = await BenchService().context(did, [profile])
        assert cases[0].tags == ["ambiguous"]
        record = await runner.run(
            "t021_ambiguous",
            LLMProfile(code="mock", provider="mock", model="mock-rules-v1", temperature=0),
            cases=cases,
            chain=ProviderChain([MockProvider()], append_mock=False),
        )
        assert record.status == "done" and record.results[0]["correct"] == {}
        assert "accuracy_type" not in record.metrics and "recall_critical" not in record.metrics
    finally:
        get_settings.cache_clear()
