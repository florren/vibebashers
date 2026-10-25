"""T-156: i18n_check отказывает на расхождении словарей и молчит на файлах репозитория."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import scripts.i18n_check as i18n_check  # noqa: E402


def _bind(monkeypatch, tmp_path: Path, ru: dict, en: dict, defs: dict | None = None) -> None:
    ru_path = tmp_path / "ru.json"
    en_path = tmp_path / "en.json"
    common = tmp_path / "common.schema.json"
    ru_path.write_text(json.dumps(ru, ensure_ascii=False), encoding="utf-8")
    en_path.write_text(json.dumps(en, ensure_ascii=False), encoding="utf-8")
    common.write_text(json.dumps({"$defs": defs or {}}), encoding="utf-8")
    monkeypatch.setattr(i18n_check, "RU", ru_path)
    monkeypatch.setattr(i18n_check, "EN", en_path)
    monkeypatch.setattr(i18n_check, "COMMON", common)


def test_missing_en_key(monkeypatch, tmp_path: Path, capsys) -> None:
    _bind(monkeypatch, tmp_path, {"a": "текст"}, {})
    assert i18n_check.main() == 1
    assert "нет ключа en: a" in capsys.readouterr().err


def test_extra_en_key(monkeypatch, tmp_path: Path, capsys) -> None:
    _bind(monkeypatch, tmp_path, {"a": "текст"}, {"a": "text", "b": "extra"})
    assert i18n_check.main() == 1
    assert "лишний ключ en: b" in capsys.readouterr().err


def test_empty_string(monkeypatch, tmp_path: Path, capsys) -> None:
    _bind(monkeypatch, tmp_path, {"a": ""}, {"a": "text"})
    assert i18n_check.main() == 1
    assert "пустое значение: a" in capsys.readouterr().err


def test_enum_without_translation(monkeypatch, tmp_path: Path, capsys) -> None:
    ru = {"signal": {"type": {"other": "другое"}}}
    en = {"signal": {"type": {"other": "other"}}}
    _bind(monkeypatch, tmp_path, ru, en, {"signal_type": {"enum": ["tech_fault"]}})
    assert i18n_check.main() == 1
    assert "нет перевода signal.type.tech_fault" in capsys.readouterr().err


def test_placeholder_mismatch(monkeypatch, tmp_path: Path, capsys) -> None:
    _bind(monkeypatch, tmp_path, {"sim": {"day": "день {{n}}"}}, {"sim": {"day": "day {{m}}"}})
    assert i18n_check.main() == 1
    assert "разные плейсхолдеры: sim.day" in capsys.readouterr().err


def test_repo_dictionaries_ok(capsys) -> None:
    assert i18n_check.main() == 0
    assert capsys.readouterr().err == ""
