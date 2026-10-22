"""Реестр JSON-схем контрактов (contracts/events/**): загрузка, разыменование $ref, валидация (T-006/T-200).

Используется mock-провайдером (генерация объектов по схеме), провайдерами LLM (response_format) и валидаторами envelope."""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parents[3]
EVENTS = ROOT / "contracts/events"


@lru_cache
def _files() -> dict[str, Path]:
    return {p.name: p for p in EVENTS.rglob("*.schema.json")}


@lru_cache
def load(name: str) -> dict[str, Any]:
    """Схема по короткому имени: 'agent/classification', 'classification', 'classification.schema.json'."""
    fname = name.split("/")[-1]
    if not fname.endswith(".schema.json"):
        fname += ".schema.json"
    path = _files().get(fname)
    if path is None:
        raise KeyError(f"нет схемы {name!r} в {EVENTS}")
    doc: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return doc


def schema_id(name: str) -> str:
    return str(load(name).get("$id") or f"urn:cx:{name}")


@lru_cache
def registry() -> Registry:
    resources = []
    for p in _files().values():
        doc = json.loads(p.read_text(encoding="utf-8"))
        res = Resource.from_contents(doc, default_specification=DRAFT202012)
        uri = str(doc.get("$id") or p.as_uri())
        resources.append((uri, res))  # относительные $ref (../common.schema.json) разрешаются через $id-пространство
    return Registry().with_resources(resources)


@lru_cache
def validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(load(name), registry=registry())


def validate(obj: Any, name: str) -> list[str]:
    """Список ошибок (пусто — валидно)."""
    return [
        f"{'/'.join(str(x) for x in e.absolute_path) or '<root>'}: {e.message}"
        for e in validator(name).iter_errors(obj)
    ]


def _resolve_ref(ref: str, base: Path) -> tuple[dict[str, Any], Path]:
    file_part, _, pointer = ref.partition("#")
    if file_part:
        fname = file_part.split("/")[-1]
        path = _files()[fname]
    else:
        path = base
    doc = json.loads(path.read_text(encoding="utf-8"))
    node: Any = doc
    for part in [p for p in pointer.split("/") if p]:
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node, path


def deref(name: str) -> dict[str, Any]:
    """Схема с полностью подставленными $ref (для mock и response_format). Рекурсивные ссылки обрезаются до {}."""
    base = _files()[name.split("/")[-1] + ("" if name.endswith(".schema.json") else ".schema.json")]

    def walk(node: Any, path: Path, seen: tuple[str, ...]) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref = node["$ref"]
                key = f"{path.name}{ref}"
                if key in seen:
                    return {}
                target, tpath = _resolve_ref(ref, path)
                merged = {**walk(target, tpath, (*seen, key)), **{k: v for k, v in node.items() if k != "$ref"}}
                return merged
            return {k: walk(v, path, seen) for k, v in node.items() if k not in ("$id", "$schema")}
        if isinstance(node, list):
            return [walk(x, path, seen) for x in node]
        return copy.deepcopy(node)

    result: dict[str, Any] = walk(json.loads(base.read_text(encoding="utf-8")), base, ())
    return result


def validate_schema(obj: Any, schema: dict[str, Any]) -> list[str]:
    """Валидация по произвольной (разыменованной) схеме."""
    v = Draft202012Validator(schema, registry=registry())
    return [f"{'/'.join(str(x) for x in e.absolute_path) or '<root>'}: {e.message}" for e in v.iter_errors(obj)]
