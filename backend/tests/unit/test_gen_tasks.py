"""Генератор сохраняет подтверждённые критерии, но не переносит отметки на новый текст."""

from __future__ import annotations

import runpy
from pathlib import Path


def test_regeneration_preserves_checked_criteria(tmp_path, monkeypatch) -> None:
    root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    namespace = runpy.run_path(str(root / "scripts/gen_tasks.py"))
    main = namespace["main"]
    state = main.__globals__
    task = {**state["TASKS"][0], "accept": ["Проверено.", "Новое условие."]}
    monkeypatch.setitem(state, "OUT", tmp_path)
    monkeypatch.setitem(state, "TASKS", [task])
    main()
    card = next(tmp_path.glob("T-*.md"))
    original = card.read_text().replace("- [ ] Проверено.", "- [x] Проверено.")
    original = original.replace("- [ ] Новое условие.", "- [x] Старое условие.")
    original = original.replace("| Статус | `todo` |", "| Статус | `done` |")
    original = original.replace(state["REPORT_EMPTY"], "Фактический отчёт.")
    card.write_text(original)
    main()
    result = card.read_text()
    assert "- [x] Проверено." in result
    assert "- [ ] Новое условие." in result
    assert "Старое условие." not in result
    assert "| Статус | `done` |" in result
    assert "Фактический отчёт." in result
    main()
    assert card.read_text() == result
