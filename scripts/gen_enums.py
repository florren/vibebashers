#!/usr/bin/env python3
"""contracts/events/common.schema.json ($defs с enum) → backend/app/contracts/enums.py (StrEnum)
и frontend/src/shared/contracts/enums.ts (если каталог frontend/src существует). Идемпотентно (T-006)."""

from __future__ import annotations

import json
import keyword
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "contracts/events/common.schema.json"
PY_OUT = ROOT / "backend/app/contracts/enums.py"
TS_OUT = ROOT / "frontend/src/shared/contracts/enums.ts"


def pascal(s: str) -> str:
    return "".join(w.capitalize() for w in re.split(r"[_\-\s]+", s))


def member(v: str) -> str:
    m = re.sub(r"\W+", "_", v).upper().strip("_")
    if not m or m[0].isdigit():
        m = "V_" + m
    return m + "_" if keyword.iskeyword(m.lower()) else m


def main() -> None:
    schema = json.loads(SRC.read_text(encoding="utf-8"))
    defs = schema.get("$defs") or schema.get("definitions") or {}
    enums = {
        k: v for k, v in defs.items() if isinstance(v.get("enum"), list) and all(isinstance(x, str) for x in v["enum"])
    }
    py = [
        '"""СГЕНЕРИРОВАНО scripts/gen_enums.py из contracts/events/common.schema.json — не редактировать руками."""',
        "from __future__ import annotations",
        "",
        "from enum import StrEnum",
        "",
    ]
    ts = ["// СГЕНЕРИРОВАНО scripts/gen_enums.py из contracts/events/common.schema.json — не редактировать руками.", ""]
    for name, d in enums.items():
        cls = pascal(name)
        doc = (d.get("description") or d.get("title") or "").replace('"""', "'''").strip()
        py += ["", f"class {cls}(StrEnum):"]
        if doc:
            py.append(f'    """{doc}"""')
        py += [f'    {member(v)} = "{v}"' for v in d["enum"]]
        py.append("")
        ts.append(f"export const {cls} = {{")
        ts += [f'  {member(v)}: "{v}",' for v in d["enum"]]
        ts += ["} as const;", f"export type {cls} = (typeof {cls})[keyof typeof {cls}];", ""]
    py += ["", "ALL_ENUMS = {" + ", ".join(f'"{n}": {pascal(n)}' for n in enums) + "}", ""]
    PY_OUT.parent.mkdir(parents=True, exist_ok=True)
    PY_OUT.write_text("\n".join(py), encoding="utf-8")
    if (ROOT / "frontend/src").exists():
        TS_OUT.parent.mkdir(parents=True, exist_ok=True)
        TS_OUT.write_text("\n".join(ts), encoding="utf-8")
    print(f"enums: {len(enums)} → {PY_OUT.relative_to(ROOT)}")  # noqa: T201


if __name__ == "__main__":
    main()
