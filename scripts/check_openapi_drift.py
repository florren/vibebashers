#!/usr/bin/env python3
"""Дрейф contracts/api/openapi.yaml ↔ маршруты FastAPI (backend/app/main.py).

Красный, если в коде нет пути+метода из OpenAPI или в коде есть путь, которого нет в OpenAPI (кроме /docs, /openapi.json).
--tags a,b — проверять только эти теги. Запускается из корня репозитория или из backend/."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("APP_ENV", "test")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tags")
    a = ap.parse_args()
    tags = set(a.tags.split(",")) if a.tags else None
    oa = yaml.safe_load((ROOT / "contracts/api/openapi.yaml").read_text(encoding="utf-8"))
    spec: set[tuple[str, str]] = set()
    for path, ops in oa["paths"].items():
        for m in ("get", "post", "put", "patch", "delete"):
            if m in ops and (tags is None or (ops[m].get("tags") or ["misc"])[0] in tags):
                spec.add((m.upper(), path))
    from app.main import create_app  # noqa: E402

    app = create_app()
    code: set[tuple[str, str]] = set()

    def walk(routes: list[object]) -> list[object]:
        flat: list[object] = []
        for r in routes:
            inner = getattr(r, "original_router", None)  # FastAPI ≥ 0.125: _IncludedRouter
            flat.extend(walk(list(inner.routes)) if inner is not None else [r])
        return flat

    for r in walk(list(app.routes)):
        path = getattr(r, "path", "")
        if path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect") or path.startswith("/static"):
            continue
        if getattr(r, "include_in_schema", True) is False:  # SPA-фолбэк фронта и прочие служебные маршруты
            continue
        methods = getattr(r, "methods", None)
        if methods:
            code |= {(m, path) for m in methods if m not in ("HEAD", "OPTIONS")}
        elif path.startswith("/ws/"):
            code.add(("GET", path))
    if tags is not None:
        code = {c for c in code if c in spec or any(c[1] == p for _, p in spec)}
    missing = sorted(spec - code)
    extra = sorted(code - spec) if tags is None else []
    for m, p in missing:
        print(f"нет в коде:     {m} {p}")  # noqa: T201
    for m, p in extra:
        print(f"нет в OpenAPI:  {m} {p}")  # noqa: T201
    print(f"openapi drift: spec={len(spec)} code={len(code)} missing={len(missing)} extra={len(extra)}")  # noqa: T201
    return 1 if missing or extra else 0


if __name__ == "__main__":
    sys.exit(main())
