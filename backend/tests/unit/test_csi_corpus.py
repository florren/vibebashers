from __future__ import annotations

import collections
import datetime as dt
import json
import math
import statistics

import pytest
import yaml
from scripts.seed import gen_csi_corpus
from scripts.seed.gen_csi_corpus import write

from app.ingest.csi import parse_json, parse_xlsx, validate_row
from app.sim import csi_corpus
from app.sim.csi_corpus import generate


def rank(values):
    ordered = sorted(values)
    return [statistics.mean(i + 1 for i, other in enumerate(ordered) if other == value) for value in values]


def spearman(xs, ys):
    a, b = rank(xs), rank(ys)
    am, bm = statistics.mean(a), statistics.mean(b)
    return sum((x - am) * (y - bm) for x, y in zip(a, b, strict=True)) / math.sqrt(
        sum((x - am) ** 2 for x in a) * sum((y - bm) ** 2 for y in b)
    )


def test_corpus_deterministic_valid_linked_and_bounded():
    corpus = generate()
    assert corpus == generate(42) and corpus != generate(43)
    assert corpus["metadata"]["synthetic"] is True
    rows = corpus["complaints"]
    assert len(rows) == len({r["csi_no"] for r in rows}) == 300
    assert len({r["complaint_ru"] for r in rows}) > 290
    staff = {e["employee_public_id"]: e for e in corpus["employees"]}
    assert len(staff) == 60
    for row in rows:
        assert validate_row(row)["csi_no"] == row["csi_no"]
        employee = staff[row["employee_public_id"]]
        assert row["branch_code"] == employee["branch_code"]
        assert row["tenure_position_days"] == employee["tenure_position_days"]
        assert dt.datetime.fromisoformat(row["received_at"]).date().isoformat() == corpus["visits"][0]["day"]
    with_complaints = {r["employee_public_id"] for r in rows}
    a = [e["tenure_position_days"] for e in staff.values() if e["employee_public_id"] in with_complaints]
    b = [e["tenure_position_days"] for e in staff.values() if e["employee_public_id"] not in with_complaints]
    assert len(a) == len(b) == 30 and statistics.mean(a) < statistics.mean(b)


def test_denominators_match_cells_and_expected_correlations():
    corpus = generate()
    numerator = collections.Counter()
    for row in corpus["complaints"]:
        wait = next(
            label
            for boundary, label in [(5, "0-5"), (15, "5-15"), (30, "15-30"), (61, "30+")]
            if row["wait_min"] < boundary
        )
        redirects = str(row["redirects"]) if row["redirects"] < 2 else "2+"
        numerator[row["branch_code"], row["received_at"][:10], wait, redirects] += 1
    denominator = {
        (v["branch_code"], v["day"], v["wait_bucket"], v["redirects_bucket"]): v["visits"] for v in corpus["visits"]
    }
    assert set(numerator) <= set(denominator)
    assert all(0 <= count <= denominator[key] for key, count in numerator.items())
    assert sum(denominator.values()) == 2400
    for index, labels, minimum in [(2, ["0-5", "5-15", "15-30", "30+"], 0.5), (3, ["0", "1", "2+"], 0.3)]:
        visits = [sum(count for key, count in denominator.items() if key[index] == label) for label in labels]
        complaints = [sum(count for key, count in numerator.items() if key[index] == label) for label in labels]
        assert spearman(range(len(labels)), [c / v for c, v in zip(complaints, visits, strict=True)]) > minimum


def test_json_and_xlsx_roundtrip_and_generation_idempotence(tmp_path):
    write(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    write(tmp_path)
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    first = [validate_row(row.value) for row in parse_json(before["complaints.json"])]
    second = [validate_row(row.value) for row in parse_xlsx(before["complaints.xlsx"])]
    assert len(first) == 300 and first == second
    assert json.loads(before["metadata.json"])["label_ru"] == "демонстрационные данные"


def test_cli_offline_outputs_are_separate_from_import_files(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["gen_csi_corpus", "--output", str(tmp_path / "corpus"), "--import-output", str(tmp_path / "import")],
    )
    gen_csi_corpus.main()
    assert {p.name for p in (tmp_path / "import").iterdir()} == {"complaints.json", "complaints.xlsx"}
    assert (tmp_path / "import/complaints.json").read_bytes() == (tmp_path / "corpus/complaints.json").read_bytes()
    monkeypatch.delenv("DATABASE_URL_TEST", raising=False)
    monkeypatch.setattr("sys.argv", ["gen_csi_corpus", "--check-db", "--output", str(tmp_path / "forbidden")])
    with pytest.raises(SystemExit) as error:
        gen_csi_corpus.main()
    assert error.value.code == 2 and not (tmp_path / "forbidden").exists()


@pytest.mark.parametrize(
    "key,value,message",
    [
        ("synthetic", False, "synthetic=true"),
        ("as_of", "2026-11-09T09:00:00", "timezone"),
        ("complaints_per_weight", 1000, "больше посещений"),
    ],
)
def test_invalid_dataset_design_fails_explicitly(tmp_path, monkeypatch, key, value, message):
    params = yaml.safe_load((csi_corpus.DATA / "csi_params.yaml").read_text())
    params[key] = value
    (tmp_path / "csi_params.yaml").write_text(yaml.safe_dump(params))
    (tmp_path / "branches.yaml").write_bytes((csi_corpus.DATA / "branches.yaml").read_bytes())
    monkeypatch.setattr(csi_corpus, "DATA", tmp_path)
    with pytest.raises(ValueError, match=message):
        generate()
