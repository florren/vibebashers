#!/usr/bin/env python3
"""Каркас роутеров по тегам contracts/api/openapi.yaml → backend/app/api/<tag>.py.

Создаёт файл тега, только если его ещё нет (реализованные роутеры не перезаписываются); внутри — по одной функции
на операцию, которая поднимает 501 problem+json с номером карточки. Таблица «путь → карточка» — CARD_BY_TAG ниже.
Полноту покрытия путей проверяет scripts/check_openapi_drift.py (T-200/T-221)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OA = yaml.safe_load((ROOT / "contracts/api/openapi.yaml").read_text(encoding="utf-8"))
OUT = ROOT / "backend/app/api"
METHODS = ("get", "post", "put", "patch", "delete")
CARD_BY_TAG = {
    "health": "T-004",
    "setup": "T-009",
    "settings": "T-009",
    "sim": "T-031",
    "scenarios": "T-042",
    "signals": "T-087",
    "incidents": "T-089",
    "hitl": "T-077",
    "tasks": "T-079",
    "clients": "T-091",
    "map": "T-088",
    "metrics": "T-093",
    "engine": "T-106",
    "bench": "T-129",
    "public": "T-119",
    "feed": "T-176",
    "abs": "T-171",
    "rules": "T-172",
    "compliance": "T-184",
    "stt": "T-181",
    "demo": "T-194",
    "ingest": "T-207",
    "tickets": "T-214",
    "escalations": "T-213",
    "agent": "T-214",
}


def fn_name(method: str, path: str) -> str:
    parts = [p for p in path.strip("/").split("/") if p not in ("api",)]
    name = "_".join(re.sub(r"\W+", "_", p.strip("{}")) for p in parts)
    name = re.sub(r"_+", "_", name).strip("_")
    return f"{method}_{name}"


def fa_path(path: str) -> str:
    return path  # FastAPI использует тот же синтаксис {param}


def main() -> None:
    by_tag: dict[str, list[tuple[str, str, dict]]] = {}
    for path, ops in OA["paths"].items():
        for m in METHODS:
            if m in ops:
                tag = (ops[m].get("tags") or ["misc"])[0]
                by_tag.setdefault(tag, []).append((m, path, ops[m]))
    OUT.mkdir(parents=True, exist_ok=True)
    created = 0
    for tag, ops in by_tag.items():
        f = OUT / f"{tag}.py"
        if f.exists():
            continue
        card = CARD_BY_TAG.get(tag, "T-200")
        lines = [
            f'"""Роутер тега `{tag}` (OpenAPI 1.4.0). Заглушки 501 — реализация: карточка {card}."""',
            "from __future__ import annotations",
            "",
            "from typing import Any",
            "",
            "from fastapi import APIRouter, Request",
            "",
            "from app.errors import NotImplementedYet",
            "",
            f'router = APIRouter(tags=["{tag}"])',
            "",
        ]
        for m, path, op in ops:
            if path.startswith("/ws/"):
                continue  # WebSocket — app/realtime
            summary = (op.get("summary") or "").replace('"', "'")
            lines += [
                "",
                f'@router.{m}("{fa_path(path)}", summary="{summary}")',
                f"async def {fn_name(m, path)}(request: Request) -> Any:",
                f'    raise NotImplementedYet("{card}")',
            ]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        created += 1
    print(f"api stubs: создано {created} файлов, тегов всего {len(by_tag)}")  # noqa: T201


if __name__ == "__main__":
    main()
