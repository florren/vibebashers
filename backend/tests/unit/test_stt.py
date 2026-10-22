"""B10: атрибуция спикера, разделение стерео, WER, реестр провайдеров."""

from __future__ import annotations

import array

from app.api.stt import wer
from app.stt import speakers
from app.stt.base import pcm_split_stereo
from app.stt.browser import BrowserProvider
from app.stt.vosk_provider import resolve_model_path


def test_speaker_attribution_markers() -> None:
    a = speakers.attribute("Страховка здесь это просто формальность, подпишите вот здесь", None)
    assert a["speaker"] == "employee" and a["confidence"] >= 0.7 and a["reason_ru"]
    b = speakers.attribute("А если я не хочу? Мне она не нужна, сколько это стоит?", "employee")
    assert b["speaker"] == "client" and b["confidence"] >= 0.7
    c = speakers.attribute("Да", "employee")
    assert c["speaker"] == "client" and c["confidence"] == 0.7
    d = speakers.attribute("Хорошо", None)
    assert d["speaker"] == "employee"


def test_pcm_split_stereo() -> None:
    a = array.array("h", [1, -1, 2, -2, 3, -3, 99])  # хвостовой байт-мусор отрезается
    left, right = pcm_split_stereo(a.tobytes())
    assert array.array("h", left).tolist() == [1, 2, 3] and array.array("h", right).tolist() == [-1, -2, -3]


def test_wer() -> None:
    assert wer("а б в", "а б в") == 0
    assert wer("а б в г", "а в г") == 0.25
    assert wer("а", "") == 1.0


def test_browser_provider_info() -> None:
    i = BrowserProvider().info(is_default=True)
    assert i.available and i.external_service and i.is_default and i.channels == 1


def test_resolve_model_path_missing(tmp_path) -> None:  # noqa: ANN001
    assert resolve_model_path(str(tmp_path / "nope")) is None
