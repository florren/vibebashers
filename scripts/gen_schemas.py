#!/usr/bin/env python3
"""contracts/events/**/*.schema.json → backend/app/contracts/events/<семейство>/<имя>.py (Pydantic v2, T-006/T-200/T-221).

Один файл схемы → один модуль; имя корневого класса — из имени файла (decision.schema.json → Decision), т. к. заголовки схем
русские. Ссылки на ../common.schema.json разрешаются локально (--allow-remote-refs). Пакеты app/agent, app/compliance,
app/rules, app/ingest реэкспортируют модели из app.contracts.events.* в своих schemas.py."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "contracts/events"
OUT = ROOT / "backend/app/contracts/events"
BIN = ROOT / "backend/.venv/bin/datamodel-codegen"
REEXPORT = {
    "agent": "backend/app/agent/schemas.py",
    "compliance": "backend/app/compliance/schemas.py",
    "rules": "backend/app/rules/schemas.py",
    "ingest": "backend/app/ingest/schemas.py",
}


def pascal(s: str) -> str:
    return "".join(w.capitalize() for w in re.split(r"[_\-]+", s))


def root_class(stem: str) -> str:
    """Имя корневого класса. Если имя файла совпадает с перечислением из common.schema.json (zone, …) — суффикс Event,
    иначе корневая модель затенит перечисление внутри модуля."""
    import json

    defs = json.loads((SRC / "common.schema.json").read_text(encoding="utf-8")).get("$defs", {})
    return pascal(stem) + ("Event" if stem in defs else "")


def main() -> int:
    exe = str(BIN) if BIN.exists() else "datamodel-codegen"
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    (OUT / "__init__.py").write_text(
        '"""СГЕНЕРИРОВАНО scripts/gen_schemas.py из contracts/events — не редактировать руками."""\n', encoding="utf-8"
    )
    families: dict[str, list[tuple[str, str]]] = {}
    for f in sorted(SRC.rglob("*.schema.json")):
        fam = f.parent.name if f.parent != SRC else "root"
        stem = f.name.replace(".schema.json", "")
        cls = root_class(stem)
        dest_dir = OUT / fam
        dest_dir.mkdir(exist_ok=True)
        (dest_dir / "__init__.py").touch()
        dest = dest_dir / f"{stem}.py"
        cmd = [
            exe,
            "--input",
            str(f),
            "--input-file-type",
            "jsonschema",
            "--output",
            str(dest),
            "--output-model-type",
            "pydantic_v2.BaseModel",
            "--target-python-version",
            "3.12",
            "--use-standard-collections",
            "--use-union-operator",
            "--disable-timestamp",
            "--class-name",
            cls,
            "--allow-remote-refs",
            "--formatters",
            "ruff-format",
            "--use-schema-description",
            "--field-constraints",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 and "Modular references" in r.stderr:
            # схема ссылается на соседние файлы → пакет <stem>/ с __init__.py (корневая модель) и подмодулями
            pkg = dest_dir / stem
            cmd[cmd.index("--output") + 1] = str(pkg)
            r = subprocess.run(cmd, capture_output=True, text=True)
            dest = pkg / "__init__.py"
        if r.returncode != 0:
            sys.stderr.write(f"{f}: {r.stderr[-500:]}\n")
            return 1
        txt = dest.read_text(encoding="utf-8")
        dest.write_text(
            f"# СГЕНЕРИРОВАНО scripts/gen_schemas.py из {f.relative_to(ROOT)} — не редактировать руками.\n" + txt,
            encoding="utf-8",
        )
        families.setdefault(fam, []).append((stem, cls))
    for fam, path in REEXPORT.items():
        names = families.get(fam, [])
        lines = [
            f'"""Pydantic-модели контрактов contracts/events/{fam} (реэкспорт; генерируется scripts/gen_schemas.py)."""',
            "from __future__ import annotations",
            "",
        ]
        lines += [f"from app.contracts.events.{fam}.{stem} import {cls}" for stem, cls in names]
        lines += ["", "__all__ = [" + ", ".join(f'"{cls}"' for _, cls in names) + "]", ""]
        (ROOT / path).write_text("\n".join(lines), encoding="utf-8")
    print(f"schemas: {sum(len(v) for v in families.values())} модулей → {OUT.relative_to(ROOT)}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
