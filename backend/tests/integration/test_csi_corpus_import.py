"""Native T-246 import, только собственная seeded fixture; никакого LLM."""

import io

import psycopg
import pytest
from fastapi.testclient import TestClient
from scripts.seed import gen_csi_corpus
from scripts.seed.gen_csi_corpus import check_roster, xlsx_bytes

from app.main import create_app
from app.sim.csi_corpus import generate


def test_corpus_native_import_and_json_xlsx_deduplication(seeded: str, conn: psycopg.Connection):
    corpus = generate()
    check_roster(conn, corpus)
    before = conn.execute("SELECT count(*) FROM csi_responses").fetchone()[0]
    with TestClient(create_app()) as client:
        first = client.post("/api/ingest/csi", json=corpus["complaints"])
        assert first.status_code == 202, first.text
        assert (first.json()["accepted"], first.json()["duplicates"], first.json()["rejected"]) == (300, 0, 0)
        second = client.post(
            "/api/ingest/csi",
            files={
                "file": (
                    "complaints.xlsx",
                    io.BytesIO(xlsx_bytes(corpus["complaints"])),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert second.status_code == 202, second.text
        assert (second.json()["accepted"], second.json()["duplicates"], second.json()["rejected"]) == (0, 300, 0)
    assert conn.execute("SELECT count(*) FROM csi_responses").fetchone()[0] == before + 300
    linked = conn.execute(
        "SELECT count(*),count(DISTINCT cr.employee_id),count(DISTINCT cr.branch_id) "
        "FROM csi_responses cr JOIN signals s ON s.id=cr.signal_id JOIN employees e ON e.id=cr.employee_id "
        "WHERE cr.csi_no=ANY(%s) AND s.channel_code='csi_survey' AND e.branch_id=cr.branch_id",
        ([r["csi_no"] for r in corpus["complaints"]],),
    ).fetchone()
    assert linked == (300, 30, 10)


def test_roster_mismatch_is_explicit_before_import(seeded: str, conn: psycopg.Connection):
    corpus = generate()
    corpus["employees"][0]["employee_public_id"] = "EMP-99999"
    with pytest.raises(ValueError, match="roster mismatch"):
        check_roster(conn, corpus)
    corpus = generate()
    corpus["employees"][0]["tenure_org_days"] += 1
    with pytest.raises(ValueError, match="tenure mismatch"):
        check_roster(conn, corpus)


def test_cli_roster_check_reads_only_before_file_generation(seeded, conn, tmp_path, monkeypatch):
    before = conn.execute("SELECT count(*) FROM db_activity_log").fetchone()[0]
    monkeypatch.setenv("DATABASE_URL_TEST", seeded)
    monkeypatch.setattr("sys.argv", ["gen_csi_corpus", "--check-db", "--output", str(tmp_path)])
    gen_csi_corpus.main()
    assert len(list(tmp_path.iterdir())) == 5
    assert conn.execute("SELECT count(*) FROM db_activity_log").fetchone()[0] == before
