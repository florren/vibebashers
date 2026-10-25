"""Кассеты replay: stale по prompt_version, идемпотентность записи, cassette_asset (T-198)."""

from __future__ import annotations

import json
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

from app.agent.prompts import prompt_version
from app.config import Settings
from app.contracts.registry import deref
from app.llm.base import LLMProfile, Usage
from app.llm.failover import ProviderChain, live_recording_possible
from app.llm.mock import MockProvider
from app.llm.ratelimit import RateLimiter
from app.replay.store import CassetteStore

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = deref("agent/normalization")
PROFILE = LLMProfile(code="test_main", provider="gigachat", model="GigaChat-3-Pro")
MSGS = [{"role": "user", "content": "комиссия за QR"}]


class _LiveGood:
    name = "gigachat"

    async def complete_structured(self, messages, schema, profile, *, timeout_s: float):
        obj, _, raw = await MockProvider().complete_structured(messages, schema, profile, timeout_s=timeout_s)
        return (
            obj,
            Usage(
                prompt_tokens=1,
                completion_tokens=1,
                latency_ms=1,
                provider="gigachat",
                model=profile.model,
                source="live",
            ),
            raw,
        )

    async def stream(self, messages, profile, *, timeout_s: float):
        yield ""


@pytest.mark.asyncio
async def test_cassettes_fresh_prompt_version_swap(tmp_path) -> None:
    store = CassetteStore(tmp_path)
    chain = ProviderChain(
        [_LiveGood()],
        record_store=store,
        rate_limiter=RateLimiter(),
        scenario_id="qr_fee_public_review",
        prompt_version="v0.9",
    )
    current = prompt_version()
    await chain.complete_structured(MSGS, SCHEMA, PROFILE)
    stale_after_old = store.summaries(current)
    assert len(stale_after_old) == 1
    assert stale_after_old[0]["stale"] is True
    assert stale_after_old[0]["entries"] == 1

    chain.prompt_version = current
    await chain.complete_structured(MSGS, SCHEMA, PROFILE)
    lines = (tmp_path / "gigachat.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["prompt_version"] == current
    fresh = store.summaries(current)
    assert len(fresh) == 1
    assert fresh[0]["stale"] is False
    assert fresh[0]["entries"] == 1


@pytest.mark.asyncio
async def test_cassette_asset_checksum_stable(tmp_path) -> None:
    store = CassetteStore(tmp_path)
    chain = ProviderChain(
        [_LiveGood()],
        record_store=store,
        rate_limiter=RateLimiter(),
        scenario_id="qr_fee_public_review",
        prompt_version=prompt_version(),
    )
    await chain.complete_structured(MSGS, SCHEMA, PROFILE)
    asset = store.cassette_asset("qr_fee_public_review")
    assert asset is not None
    assert asset["kind"] == "cassette"
    assert asset["path"] == "data/cassettes/gigachat.jsonl"
    again = store.cassette_asset("qr_fee_public_review")
    assert again["checksum"] == asset["checksum"]


def test_live_recording_possible_without_keys() -> None:
    settings = Settings(
        gigachat_auth_key_1=None,
        gigachat_auth_key_2=None,
        openrouter_api_key=None,
        local_llm_base_url=None,
        llm_chain="gigachat,replay,mock",
    )
    assert live_recording_possible(settings) is False


def test_repo_cassettes_stale_warns() -> None:
    cdir = ROOT / "data" / "cassettes"
    store = CassetteStore(cdir)
    store.load()
    current = prompt_version()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for s in store.summaries(current):
            if s["stale"]:
                warnings.warn(
                    f"кассета stale: {s['scenario_id']} {s['provider']}/{s['model']} prompt={s['prompt_version']}",
                    UserWarning,
                    stacklevel=1,
                )
    stale = [s for s in store.summaries(current) if s["stale"]]
    if stale:
        assert any("stale" in str(w.message) for w in caught)
    else:
        assert len(caught) == 0


def test_empty_cassettes_dir_summaries(tmp_path) -> None:
    store = CassetteStore(tmp_path)
    assert store.summaries(prompt_version()) == []


def test_cassettes_record_empty_scenario_exit_code() -> None:
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "cassettes_record.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
