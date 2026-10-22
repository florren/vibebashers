"""T-013/T-016/B21: сид lite (уменьшенный) на живой PostgreSQL — идемпотентность, матрица покрытия, инварианты данных."""

from __future__ import annotations

import json
from pathlib import Path

from tests.integration.conftest import _seed

ROOT = Path(__file__).resolve().parents[3]


def test_seed_is_idempotent(seeded: str, conn) -> None:
    before = {
        t: conn.execute(f"select count(*) from {t}").fetchone()[0]
        for t in (
            "clients",
            "signals",
            "incidents",
            "operations",
            "regions",
            "cities",
            "employees",
            "notification_templates",
        )
    }  # noqa: S608
    r = _seed(seeded)
    assert r.returncode == 0, r.stderr[-2000:]
    after = {t: conn.execute(f"select count(*) from {t}").fetchone()[0] for t in before}  # noqa: S608
    assert before == after


def test_reference_counts(conn) -> None:
    assert conn.execute("select count(*) from regions").fetchone()[0] == 89
    assert conn.execute("select count(*) from federal_districts").fetchone()[0] == 8
    assert conn.execute("select count(*) from cities").fetchone()[0] >= 300
    assert conn.execute("select count(*) from cities where is_capital").fetchone()[0] >= 80
    assert conn.execute("select count(*) from segments").fetchone()[0] == 7
    assert conn.execute("select count(*) from psychotypes").fetchone()[0] == 8
    assert conn.execute("select count(*) from teams").fetchone()[0] == 12
    assert conn.execute("select count(*) from channels").fetchone()[0] == 11
    assert conn.execute("select count(*) from sla_matrix").fetchone()[0] == 9
    assert conn.execute("select count(*) from employees").fetchone()[0] == 60
    assert conn.execute("select count(*) from branches where code = '0042'").fetchone()[0] == 1
    assert conn.execute("select count(*) from business_rules where code = 'RULE-QR-FEE-001'").fetchone()[0] == 1
    assert conn.execute("select count(*) from error_codes where code = 'PROC-QR-FEE-CHARGED'").fetchone()[0] == 1
    assert conn.execute("select count(*) from scenarios").fetchone()[0] == 11
    assert conn.execute("select count(*) from bench_datasets").fetchone()[0] >= 5
    assert abs(float(conn.execute("select sum(population_share) from segments").fetchone()[0]) - 1.0) < 1e-6
    for seg, total in conn.execute("select segment_code, sum(share) from segment_psychotype_mix group by 1").fetchall():
        assert abs(float(total) - 1.0) < 1e-6, seg


def test_coverage_matrix(conn) -> None:
    cov = conn.execute("select value from settings where key = 'coverage'").fetchone()[0]
    assert cov["signal_combos_missing"] == []
    assert cov["signal_combos_covered"] == cov["signal_combos_total"] == 10 * 4 * 11
    assert cov["sla_cells_ok"] is True
    assert all(v >= 5 for v in cov["sla_cells"].values())
    assert cov["hard_text_share"] >= 0.25
    assert len(cov["incident_statuses"]) >= 4
    assert conn.execute("select value from settings where key = 'seed_done'").fetchone()[0]["profile"] == "lite"


def test_client_invariants(conn) -> None:
    n = conn.execute("select count(*) from clients").fetchone()[0]
    assert n == 200
    handles = conn.execute("select count(*) from clients where jsonb_array_length(social_handles) > 0").fetchone()[0]
    assert 0.5 * n <= handles <= 0.7 * n
    # card_last4 — четыре цифры, не пусто, у каждой карты
    assert (
        conn.execute(
            "select count(*) from client_products where product_code in ('debit_card','credit_card') and card_last4 !~ '^[0-9]{4}$'"
        ).fetchone()[0]
        == 0
    )
    qr_total, qr_fee = conn.execute(
        "select count(*), count(*) filter (where error_code = 'PROC-QR-FEE-CHARGED') from operations where method = 'qr_sbp'"
    ).fetchone()
    assert qr_total > 0 and 0.02 <= qr_fee / qr_total <= 0.07
    assert conn.execute("select count(*) from v_tickets").fetchone()[0] > 0
    assert conn.execute("select count(*) from v_map_zones").fetchone()[0] > 0


def test_corpora_valid_against_contracts() -> None:
    from app.contracts.registry import validate

    files = sorted(f for f in (ROOT / "data" / "import" / "transcripts").glob("*") if f.suffix in (".json", ".txt"))
    assert len(files) == 20
    for f in files:
        if f.suffix == ".json":
            assert validate(json.loads(f.read_text(encoding="utf-8")), "ingest/transcript") == [], f.name
        else:
            assert "Сотрудник:" in f.read_text(encoding="utf-8")
        assert (ROOT / "data" / "bench" / "transcripts_v1" / f"{f.stem}.expected.json").exists()
    sizes = {f.stem: sum(1 for _ in f.open(encoding="utf-8")) for f in (ROOT / "data" / "bench").glob("*.jsonl")}
    assert (
        sizes["sentiment_v1"] == 300
        and sizes["hidden_negativity_v1"] == 120
        and sizes["summary_v1"] == 60
        and sizes["red_phrases_v1"] >= 120
    )
