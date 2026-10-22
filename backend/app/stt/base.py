"""Интерфейс STT-провайдера (ТЗ 5.3): потоковые partial/final по PCM16 16 кГц либо готовые реплики текстом (browser)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass
class STTResult:
    type: Literal["partial", "final"]
    text: str
    words: list[dict[str, Any]] = field(default_factory=list)
    confidence: float | None = None
    latency_ms: int | None = None


class STTStream(Protocol):
    """Один канал одной сессии. feed() принимает PCM16 LE mono; finish() закрывает и отдаёт хвост."""

    def feed(self, pcm: bytes) -> list[STTResult]: ...

    def finish(self) -> STTResult | None: ...


@dataclass
class ProviderInfo:
    code: str
    label_ru: str
    available: bool
    is_default: bool = False
    offline: bool = True
    streaming: bool = True
    channels: int = 2
    model: str | None = None
    external_service: bool = False
    note_ru: str | None = None


class STTProvider(Protocol):
    code: str

    def info(self, is_default: bool = False) -> ProviderInfo: ...

    def available(self) -> bool: ...

    def open_stream(self, sample_rate: int) -> STTStream: ...


def pcm_split_stereo(pcm: bytes) -> tuple[bytes, bytes]:
    """Interleaved L/R PCM16 → два моноканала (1 — сотрудник, 2 — клиент)."""
    import array

    a = array.array("h")
    a.frombytes(pcm[: len(pcm) - (len(pcm) % 4)])
    return a[0::2].tobytes(), a[1::2].tobytes()
