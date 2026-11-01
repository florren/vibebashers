"""Регрессии T-191/T-197/T-208: команды выполняют работу и сообщают о неуспехе."""

from __future__ import annotations

import importlib.util
import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.stt.base import STTResult

ROOT = Path(__file__).resolve().parents[3]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stt = load_script("stt_bench")
transcripts = load_script("import_transcripts")


def wav(tmp_path, *, channels=1, width=2, rate=16000, frames=3200):
    path = tmp_path / "sample.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setparams((channels, width, rate, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0" * channels * width * frames)
    return path


class Stream:
    def __init__(self, silent=False):
        self.chunks = []
        self.silent = silent

    def feed(self, pcm):
        self.chunks.append(pcm)
        return [] if self.silent else [STTResult("partial", "здравствуйте")]

    def finish(self):
        return None if self.silent else STTResult("final", "Здравствуйте, всё хорошо!")


def test_benchmark_uses_recognized_final_and_all_pcm(tmp_path):
    stream = Stream()
    provider = SimpleNamespace(code="test", open_stream=lambda rate: stream)
    result = stt.benchmark(wav(tmp_path), "здравствуйте все хорошо", provider)
    assert result["wer"] == 0
    assert result["text"] == "Здравствуйте, всё хорошо!"
    assert result["audio_seconds"] == 0.2
    assert [len(c) for c in stream.chunks] == [3200, 3200]
    assert result["first_partial_processing_ms"] is not None
    assert result["first_final_processing_ms"] is not None


def test_benchmark_empty_recognition_is_failure_not_reference(tmp_path):
    provider = SimpleNamespace(code="test", open_stream=lambda rate: Stream(silent=True))
    result = stt.benchmark(wav(tmp_path), "эталон", provider)
    assert not result["ok"]
    assert result["text"] == ""
    assert result["wer"] == 1
    assert result["first_partial_processing_ms"] is None
    assert result["first_final_processing_ms"] is None


@pytest.mark.parametrize("options", [{"channels": 2}, {"width": 1}, {"rate": 8000}, {"frames": 0}])
def test_benchmark_rejects_unsupported_audio(tmp_path, options):
    with pytest.raises(ValueError):
        stt.benchmark(wav(tmp_path, **options), "эталон", None)


def test_custom_audio_requires_own_reference(tmp_path):
    with pytest.raises(SystemExit) as error:
        stt.main(["--file", str(tmp_path / "custom.wav")])
    assert error.value.code == 2


def test_benchmark_unavailable_is_not_success(monkeypatch):
    monkeypatch.setattr(
        stt,
        "VoskProvider",
        lambda path: SimpleNamespace(available=lambda: False, info=lambda: SimpleNamespace(note_ru="нет модели")),
    )
    assert stt.main([]) == 2


@pytest.mark.parametrize("silent,expected", [(False, 0), (True, 1)])
def test_benchmark_cli_recognition_exit_status(tmp_path, monkeypatch, silent, expected):
    provider = SimpleNamespace(code="test", available=lambda: True, open_stream=lambda rate: Stream(silent))
    monkeypatch.setattr(stt, "VoskProvider", lambda path: provider)
    monkeypatch.setattr(stt, "SAMPLE_WAV", wav(tmp_path))
    assert stt.main([]) == expected


def test_benchmark_cli_invalid_file_is_error(tmp_path, monkeypatch):
    monkeypatch.setattr(stt, "VoskProvider", lambda path: SimpleNamespace(available=lambda: True))
    monkeypatch.setattr(stt, "SAMPLE_WAV", tmp_path / "missing.wav")
    assert stt.main([]) == 2


def test_import_cli_error_does_not_expose_url(monkeypatch, capsys):
    def fail(base):
        raise httpx.ConnectError("http://secret:password@stand")

    monkeypatch.setattr(transcripts, "import_transcripts", fail)
    assert transcripts.main([]) == 2
    assert "password" not in capsys.readouterr().out


@pytest.mark.parametrize("rejected,expected", [(0, 0), (1, 1)])
def test_import_exit_status(monkeypatch, rejected, expected):
    report = {"files_found": 2, "accepted": 1, "duplicates": 1 - rejected, "rejected": rejected}
    monkeypatch.setattr(transcripts, "import_transcripts", lambda base: report)
    assert transcripts.main([]) == expected


def test_import_posts_to_existing_endpoint_and_accepts_duplicates():
    def handler(request):
        assert request.method == "POST"
        assert request.url == "http://stand/api/ingest/transcripts/import"
        return httpx.Response(202, json={"files_found": 2, "accepted": 0, "duplicates": 2, "rejected": 0})

    result = transcripts.import_transcripts("http://stand/", transport=httpx.MockTransport(handler))
    assert result["duplicates"] == 2


@pytest.mark.parametrize("status,payload", [(500, {}), (202, {}), (202, []), (202, {"files_found": True})])
def test_import_does_not_hide_server_errors(status, payload):
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=payload))
    with pytest.raises((httpx.HTTPStatusError, ValueError)):
        transcripts.import_transcripts("http://stand", transport=transport)


def test_make_commands_execute_real_tools_without_reset():
    result = subprocess.run(
        ["make", "-n", "stt-bench", "import-transcripts", "demo-offline"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "scripts/stt_bench.py" in result.stdout
    assert "scripts/import_transcripts.py" in result.stdout
    assert "./install.sh --offline" in result.stdout
    assert "--reset" not in result.stdout


def test_make_test_covers_compliance_and_frontend():
    result = subprocess.run(["make", "-n", "test"], cwd=ROOT, text=True, capture_output=True, check=True)
    for directory in ("unit", "integration", "scenarios", "compliance"):
        assert f"pytest -q tests/{directory}" in result.stdout
    assert "npm test -- --run" in result.stdout


def test_make_lint_checks_both_layers():
    result = subprocess.run(["make", "-n", "lint"], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "ruff check app tests" in result.stdout
    assert "mypy app" in result.stdout
    assert "npm run lint" in result.stdout
    assert "tsc --noEmit" in result.stdout
