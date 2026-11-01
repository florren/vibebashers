"""T-191: локальный STT-бенчмарк WAV, без БД, сети и подстановки эталона в результат."""

from __future__ import annotations

import argparse
import re
import sys
import time
import wave
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.api.stt import SAMPLE_TEXT, SAMPLE_WAV, wer  # noqa: E402
from app.stt.base import STTProvider  # noqa: E402
from app.stt.vosk_provider import VoskProvider  # noqa: E402


def normalize(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold().replace("ё", "е")))


def benchmark(path: Path, reference: str, provider: STTProvider) -> dict[str, Any]:
    if not normalize(reference):
        raise ValueError("эталонный текст пуст")
    with wave.open(str(path), "rb") as audio:
        if audio.getnchannels() != 1 or audio.getsampwidth() != 2 or audio.getframerate() != 16000:
            raise ValueError("ожидается WAV PCM16 mono 16000 Hz")
        frames = audio.getnframes()
        if frames == 0:
            raise ValueError("аудиофайл пуст")
        stream = provider.open_stream(16000)
        texts: list[str] = []
        partial_ms: list[float] = []
        final_ms: list[float] = []
        started = time.perf_counter()
        # Чанки по 100 мс, без ожидания реального времени: latency — время вычисления.
        while pcm := audio.readframes(1600):
            for result in stream.feed(pcm):
                if result.text:
                    elapsed = (time.perf_counter() - started) * 1000
                    if result.type == "partial":
                        partial_ms.append(elapsed)
                    else:
                        texts.append(result.text)
                        final_ms.append(elapsed)
        tail = stream.finish()
        if tail and tail.text:
            texts.append(tail.text)
            final_ms.append((time.perf_counter() - started) * 1000)
        elapsed_ms = (time.perf_counter() - started) * 1000
    text = " ".join(texts)
    return {
        "provider": provider.code,
        "file": path.name,
        "text": text,
        "wer": round(wer(normalize(reference), normalize(text)), 4),
        "audio_seconds": frames / 16000,
        "processing_ms": round(elapsed_ms, 2),
        "first_partial_processing_ms": round(partial_ms[0], 2) if partial_ms else None,
        "first_final_processing_ms": round(final_ms[0], 2) if final_ms else None,
        "realtime_factor": round(elapsed_ms / 1000 / (frames / 16000), 4),
        "ok": bool(text),
    }


def main(argv: list[str] | None = None) -> int:
    import structlog
    from app.config import get_settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file",
        type=Path,
        help="WAV PCM16 mono 16000 Hz; по умолчанию встроенный образец",
    )
    parser.add_argument("--reference", type=Path, help="UTF-8 TXT с эталоном; обязателен для своего WAV")
    args = parser.parse_args(argv)
    if args.file is not None and args.reference is None:
        parser.error("для --file нужен --reference; встроенный эталон неприменим к другому WAV")
    structlog.configure(
        processors=[structlog.processors.JSONRenderer(ensure_ascii=False)],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
    )
    log = structlog.get_logger("stt_bench")
    provider = VoskProvider(get_settings().stt_model_path)
    if not provider.available():
        log.error("stt_bench_unavailable", detail=provider.info().note_ru)
        return 2
    try:
        reference = args.reference.read_text(encoding="utf-8") if args.reference else SAMPLE_TEXT
        result = benchmark(args.file or SAMPLE_WAV, reference, provider)
    except (OSError, ValueError, wave.Error, EOFError) as exc:
        log.error("stt_bench_failed", error_type=type(exc).__name__)
        return 2
    log.info("stt_bench", **result)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
