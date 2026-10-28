from __future__ import annotations

import csv
import datetime as dt
import socket
from pathlib import Path

import pytest

from app.sim.branch_directory import (
    DATA,
    Branch,
    SnapshotBranchDirectory,
    SyntheticBranchDirectory,
    network_history,
    provider,
)

NOW = dt.datetime(2026, 11, 9, 9, tzinfo=dt.UTC)


def test_synthetic_reproducible_complete_and_no_real_addresses() -> None:
    first = SyntheticBranchDirectory().load(42, NOW)
    assert first == SyntheticBranchDirectory().load(42, NOW)
    assert first != SyntheticBranchDirectory().load(43, NOW)
    assert len(first) == 240
    assert len({b.code for b in first}) == 240
    assert sum(b.branch_status == "closed" for b in first) == 19
    assert {b.branch_type for b in first} == {"flagship", "standard", "additional", "mobile"}
    with (DATA / "regions.csv").open() as stream:
        regions = list(csv.DictReader(stream))
    assert {b.region_code for b in first} == {r["code"] for r in regions}
    assert {b.code for b in first[:10]} == {
        "0042",
        "0107",
        "0211",
        "0315",
        "0418",
        "0520",
        "0633",
        "0741",
        "0856",
        "0962",
    }
    assert all("синтетический адрес" in b.address_ru for b in first)
    assert all(b.branch_status == "open" for b in first[:10])
    known = {r["okato"] for r in regions if r["okato"]}
    assert len(known) == 85
    assert {"11100000000", "71100000000", "71140000000"} <= known


@pytest.mark.parametrize("extension", ["json", "csv"])
def test_snapshot_offline_preserves_scenarios(extension: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("network not permitted")

    monkeypatch.setattr(socket, "socket", forbidden)
    rows = SnapshotBranchDirectory(DATA / "import" / "branches" / f"example.{extension}").load(42, NOW)
    assert len(rows) == 12
    assert {b.code for b in rows[-2:]} == {"S0010", "S0011"}
    assert rows[:10] == SyntheticBranchDirectory().load(42, NOW)[:10]


def test_snapshot_path_and_mode_validation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="data/import/branches"):
        SnapshotBranchDirectory(tmp_path / "outside.json")
    with pytest.raises(ValueError, match="provider"):
        provider("network")
    with pytest.raises(ValueError, match="provider"):
        provider("snapshot_file")


def test_network_counts_are_consistent() -> None:
    branches = SyntheticBranchDirectory().load(42, NOW)
    rows = network_history(branches, NOW)
    assert len(rows) == 89 * 12
    months = sorted({r["month"] for r in rows})
    assert len(months) == 12
    latest = [r for r in rows if r["month"] == months[-1]]
    assert sum(r["open_count"] for r in latest) == 221
    assert sum(r["closed_count"] for r in latest) == 19
    assert sum(r["closed_in_month"] for r in rows) == 19


def test_snapshot_dates_and_enum_validation() -> None:
    row = SyntheticBranchDirectory().load(42, NOW)[0].model_dump()
    with pytest.raises(ValueError):
        Branch.model_validate({**row, "branch_status": "closed"})
    with pytest.raises(ValueError):
        Branch.model_validate({**row, "lat": 100})
    with pytest.raises(ValueError):
        Branch.model_validate({**row, "branch_type": "external"})


@pytest.mark.parametrize("change", [{"code": "0042"}, {"city_id": -1}, {"product_line_codes": ["unknown"]}])
def test_snapshot_invalid_row_reports_number(change, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    import shutil

    from app.sim import branch_directory as directory

    row = SyntheticBranchDirectory().load(42, NOW)[10].model_dump(mode="json")
    root = tmp_path / "data"
    folder = root / "import/branches"
    folder.mkdir(parents=True)
    for name in ["regions.csv", "cities.csv", "product_lines.yaml", "branches.yaml"]:
        shutil.copyfile(DATA / name, root / name)
    file = folder / "invalid.json"
    file.write_text(json.dumps([{**row, **change}]))
    monkeypatch.setattr(directory, "DATA", root)
    with pytest.raises(ValueError, match="строка 1"):
        SnapshotBranchDirectory(file).load(42, NOW)
