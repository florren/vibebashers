import datetime as dt

from app.ingest.csi import validate_row
from app.sim.csi_corpus import generate
from app.sim.csi_scoped_corpus import generate_scoped


def test_scoped_corpus_is_explicit_portable_synthetic_design():
    first = generate_scoped()
    assert first == generate_scoped(42) and first != generate_scoped(43)
    assert first["metadata"]["synthetic"] is True
    assert first["metadata"]["version"] == "csi_scoped_v2"
    assert len(first["complaints"]) == 300 and sum(v["visits"] for v in first["visits"]) == 2400
    snapshots = {b["branch_code"]: b for b in first["directory_snapshot"]}
    start = dt.datetime.fromisoformat(first["metadata"]["observation_window"]["start"])
    end = dt.datetime.fromisoformat(first["metadata"]["observation_window"]["end"])
    assert end < dt.datetime.fromisoformat(first["metadata"]["seed_anchor"])
    for row in first["complaints"]:
        validate_row(row)
        assert start <= dt.datetime.fromisoformat(row["received_at"]) < end
        assert "учебному направлению" in row["complaint_ru"]
        line = first["metadata"]["branch_lines"][row["branch_code"]]
        assert line in snapshots[row["branch_code"]]["product_line_codes"]
    original_ids = {row["csi_no"] for row in generate()["complaints"]}
    assert original_ids.isdisjoint(row["csi_no"] for row in first["complaints"])
    assert all(
        row["product_line_code"] == first["metadata"]["branch_lines"][row["branch_code"]] for row in first["visits"]
    )
