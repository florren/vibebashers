"""browser — Web Speech API в браузере: аудио на сервер не идёт, клиент присылает готовые реплики текстом (бейдж «внешний STT»)."""

from __future__ import annotations

from app.stt.base import ProviderInfo, STTResult


class _TextStream:
    def feed(self, pcm: bytes) -> list[STTResult]:  # аудио не ожидается
        return []

    def finish(self) -> STTResult | None:
        return None


class BrowserProvider:
    code = "browser"

    def available(self) -> bool:
        return True

    def info(self, is_default: bool = False) -> ProviderInfo:
        return ProviderInfo(
            code=self.code,
            label_ru="Браузер (Web Speech API)",
            available=True,
            is_default=is_default,
            offline=False,
            streaming=True,
            channels=1,
            model="SpeechRecognition ru-RU",
            external_service=True,
            note_ru="Распознаёт браузер (Chrome/Edge): речь уходит сервису браузера; работает без модели на сервере",
        )

    def open_stream(self, sample_rate: int) -> _TextStream:
        return _TextStream()
