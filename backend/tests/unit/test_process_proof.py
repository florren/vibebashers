"""Читатель никогда не видит пустой или частично записанный process proof."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tests.fixtures.process_proof import publish_json


@pytest.mark.parametrize("existing", [False, True])
def test_reader_sees_complete_proof_only_after_publication(tmp_path, monkeypatch, existing):
    output = tmp_path / "process.json"
    previous = {"run_id": 1}
    expected = {"run_id": 2, "signal_id": 3, "operation_id": 4}
    if existing:
        output.write_text(json.dumps(previous))
    opened = threading.Event()
    proceed = threading.Event()

    def delayed_write(path, data, *, encoding):
        # Воспроизводим окно исходной гонки: файл уже создан, но ещё пуст.
        with path.open("w", encoding=encoding) as stream:
            opened.set()
            assert proceed.wait(5)
            return stream.write(data)

    monkeypatch.setattr(Path, "write_text", delayed_write)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(publish_json, output, expected)
        try:
            assert opened.wait(5)
            if existing:
                assert json.loads(output.read_text()) == previous
            else:
                assert not output.exists()
        finally:
            proceed.set()
        future.result(timeout=5)
    assert json.loads(output.read_text()) == expected
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.parametrize("stage", ["write", "replace"])
def test_failed_publication_preserves_previous_proof_and_cleans_temporary(tmp_path, monkeypatch, stage):
    output = tmp_path / "process.json"
    previous = {"run_id": 1}
    output.write_text(json.dumps(previous))

    if stage == "write":

        def fail_write(path, data, *, encoding):
            path.touch()
            raise OSError("controlled write failure")

        monkeypatch.setattr(Path, "write_text", fail_write)
    else:

        def fail_replace(path, target):
            raise OSError("controlled replace failure")

        monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="controlled"):
        publish_json(output, {"run_id": 2})
    assert json.loads(output.read_text()) == previous
    assert list(tmp_path.iterdir()) == [output]
