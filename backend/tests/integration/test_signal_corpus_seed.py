"""T-019: настоящий seed сохраняет покрытие, языки, шум и идемпотентность."""

from __future__ import annotations

import random
from pathlib import Path

import psycopg
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


def test_seed_uses_channel_corpus_and_keeps_noise_out_of_true_labels(seeded, conn, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3]))
    from scripts.seed.clients import seed_history_signals
    from scripts.seed.coverage import compute_coverage

    run_id, finished = conn.execute(
        "select id,finished_sim from sim_runs where kind='baseline' order by id limit 1"
    ).fetchone()
    rows = conn.execute(
        "select id,text,status,channel_code,classification,meta,lang from signals where run_id=%s order by id",
        (run_id,),
    ).fetchall()
    generated = [r for r in rows if r[5] and r[5].get("generator_hint")]
    assert len(generated) >= 800
    noise = [r for r in generated if r[5]["generator_hint"].get("noise")]
    assert len(noise) == round(len(generated) * 0.03)
    assert all(r[2] == "noise" and r[4] is None for r in noise)
    assert all(r[6] == r[5]["generator_hint"]["language"] for r in generated)
    regular = [r for r in generated if not r[5]["generator_hint"].get("noise")]
    assert 0.02 <= sum(r[5]["generator_hint"]["language"] == "en" for r in regular) / len(regular) <= 0.08
    for _, text, _, channel, classification, meta, language in regular:
        hint = meta["generator_hint"]
        assert "generator_hint" not in classification
        assert language == hint["language"]
        assert hint["signal_type"] == classification["signal_type"]
        assert hint["product"] == classification["product"]
        assert hint["channel"] == channel
        if channel == "call":
            assert "00:00" in text and "\n" in text
        if channel == "email":
            assert text.startswith(("Тема:", "Subject:")) and "\n" in text
    with conn.cursor() as cur:
        coverage = compute_coverage(cur, run_id, persist=False)
        assert coverage["signal_combos_missing"] == [] and coverage["sla_cells_ok"]
    with psycopg.connect(seeded.replace("postgresql+psycopg://", "postgresql://")) as retry:
        with retry.cursor() as cur:
            seed_history_signals(cur, random.Random(999), run_id, finished, 800, 150, 999)
    assert (
        conn.execute(
            "select id,text,status,channel_code,classification,meta,lang from signals where run_id=%s order by id",
            (run_id,),
        ).fetchall()
        == rows
    )
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    try:
        # Без lifespan: только read API, без фоновых акторов/LLM.
        client = TestClient(create_app())
        try:
            response = client.get(f"/api/signals/{noise[0][0]}", params={"run_id": run_id})
            assert response.status_code == 200
            body = response.json()
            assert body["classification"] is None
            assert "meta" not in body and "generator_hint" not in response.text
        finally:
            client.close()
    finally:
        get_settings.cache_clear()
