"""Vosk (Kaldi) — офлайн-распознавание русской речи; модель грузится один раз лениво, по рекогнайзеру на канал."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from app.logging import get_logger
from app.stt.base import ProviderInfo, STTResult

log = get_logger(__name__)

DEFAULT_MODEL_DIRNAME = "vosk-model-small-ru-0.22"


def resolve_model_path(configured: str | None) -> Path | None:
    cands: list[Path] = []
    if configured:
        p = Path(configured)
        cands += [
            p,
            Path(__file__).resolve().parents[3] / p,
            Path("/data") / p.relative_to("data") if p.parts[:1] == ("data",) else p,
        ]
    else:
        rel = Path("data/models/stt") / DEFAULT_MODEL_DIRNAME
        cands += [Path(__file__).resolve().parents[3] / rel, Path("/data/models/stt") / DEFAULT_MODEL_DIRNAME, rel]
    for c in cands:
        if (c / "am").exists() or (c / "conf").exists():
            return c.resolve()
    return None


class _Stream:
    def __init__(self, rec: Any) -> None:
        self.rec = rec
        self._t_speech: float | None = None

    def feed(self, pcm: bytes) -> list[STTResult]:
        if self._t_speech is None:
            self._t_speech = time.perf_counter()
        out: list[STTResult] = []
        if self.rec.AcceptWaveform(pcm):
            d = json.loads(self.rec.Result())
            text = (d.get("text") or "").strip()
            if text:
                words = [
                    {"w": w["word"], "t0": w["start"], "t1": w["end"], "conf": w.get("conf")}
                    for w in d.get("result", [])
                ]
                conf = (
                    (sum(w.get("conf", 1.0) for w in d.get("result", [])) / len(d["result"]))
                    if d.get("result")
                    else None
                )
                out.append(STTResult("final", text, words, conf, int((time.perf_counter() - self._t_speech) * 1000)))
            self._t_speech = None
        else:
            p = (json.loads(self.rec.PartialResult()).get("partial") or "").strip()
            if p:
                out.append(STTResult("partial", p, [], None, int((time.perf_counter() - self._t_speech) * 1000)))
        return out

    def finish(self) -> STTResult | None:
        d = json.loads(self.rec.FinalResult())
        text = (d.get("text") or "").strip()
        if not text:
            return None
        words = [{"w": w["word"], "t0": w["start"], "t1": w["end"], "conf": w.get("conf")} for w in d.get("result", [])]
        return STTResult("final", text, words, None, None)


class VoskProvider:
    code = "vosk"

    def __init__(self, model_path: str | None) -> None:
        self.model_dir = resolve_model_path(model_path)
        self._model: Any = None
        self._lock = threading.Lock()
        self._import_ok: bool | None = None

    def _importable(self) -> bool:
        if self._import_ok is None:
            try:
                import vosk  # noqa: F401

                self._import_ok = True
            except Exception:  # noqa: BLE001
                self._import_ok = False
        return self._import_ok

    def available(self) -> bool:
        return self.model_dir is not None and self._importable()

    def info(self, is_default: bool = False) -> ProviderInfo:
        note = None
        if not self._importable():
            note = "пакет vosk не установлен (uv sync)"
        elif self.model_dir is None:
            note = f"модель не найдена: положите {DEFAULT_MODEL_DIRNAME} в data/models/stt (make stt-model) или задайте STT_MODEL_PATH"
        return ProviderInfo(
            code=self.code,
            label_ru="Vosk (офлайн, в контейнере)",
            available=self.available(),
            is_default=is_default,
            offline=True,
            streaming=True,
            channels=2,
            model=self.model_dir.name if self.model_dir else None,
            external_service=False,
            note_ru=note,
        )

    def model(self) -> Any:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from vosk import Model, SetLogLevel

                    SetLogLevel(-1)
                    t = time.perf_counter()
                    self._model = Model(str(self.model_dir))
                    log.info(
                        "stt_model_loaded",
                        model=self.model_dir.name if self.model_dir else None,
                        ms=int((time.perf_counter() - t) * 1000),
                    )
        return self._model

    def open_stream(self, sample_rate: int) -> _Stream:
        from vosk import KaldiRecognizer

        rec = KaldiRecognizer(self.model(), float(sample_rate))
        rec.SetWords(True)
        return _Stream(rec)

    def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> tuple[str, int]:
        t = time.perf_counter()
        st = self.open_stream(sample_rate)
        parts: list[str] = []
        for i in range(0, len(pcm), 3200):
            parts += [r.text for r in st.feed(pcm[i : i + 3200]) if r.type == "final"]
        tail = st.finish()
        if tail:
            parts.append(tail.text)
        return " ".join(parts).strip(), int((time.perf_counter() - t) * 1000)
