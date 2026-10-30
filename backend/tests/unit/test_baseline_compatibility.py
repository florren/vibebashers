"""#108: ошибки SQL отменяют транзакцию, включая exit=1."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.sim import baseline


@pytest.mark.parametrize("code", [1, 2])
def test_restore_fails_for_every_nonzero_exit(monkeypatch, code):
    monkeypatch.setattr(baseline, "_pg_tool", lambda name: name)

    def execute(command, **kwargs):
        if command[0] == "pg_restore":
            Path(command[command.index("-f") + 1]).write_text("-- archive SQL\n")
            return SimpleNamespace(returncode=0)
        assert "--single-transaction" in command and "--set=ON_ERROR_STOP=1" in command
        script = Path(command[-1]).read_text()
        assert script.index("DROP CONSTRAINT") < script.index("-- archive SQL") < script.index("ADD CONSTRAINT")
        return SimpleNamespace(returncode=code)

    monkeypatch.setattr(baseline.subprocess, "run", execute)
    with pytest.raises(baseline.BaselineToolingError, match="транзакция восстановления отменена"):
        baseline._run_pg_restore("dbname=isolated", Path("legacy.dump"))


def test_prepared_archive_requires_matching_source_and_output(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(baseline, "baseline_dir", lambda: tmp_path)
    source = tmp_path / "lite.dump"
    prepared = tmp_path / "lite.compatible.dump"
    source.write_bytes(b"original")
    prepared.write_bytes(b"prepared")
    with pytest.raises(baseline.BaselineToolingError, match="provenance"):
        baseline._restore_dump_path("lite")
    metadata = {"source_sha256": baseline._sha256_file(source), "output_sha256": baseline._sha256_file(prepared)}
    prepared.with_suffix(".dump.provenance.json").write_text(json.dumps(metadata))
    assert baseline._restore_dump_path("lite") == prepared
    source.write_bytes(b"new source")
    with pytest.raises(baseline.BaselineToolingError, match="суммы"):
        baseline._restore_dump_path("lite")
