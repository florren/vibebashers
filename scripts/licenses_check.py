"""T-152: inventory закреплённых Python/npm зависимостей; неизвестная лицензия — ошибка."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = frozenset(
    [
        "MIT",
        "MIT-0",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "0BSD",
        "ISC",
        "MPL-2.0",
        "PSF-2.0",
        "Python-2.0",
        "Unlicense",
        "CC0-1.0",
        "CC-BY-4.0",
        "BlueOak-1.0.0",
        "LGPL-3.0-only",
        "LGPL-3.0-or-later",
    ]
)
DENIED = frozenset(
    [f"GPL-{version}{suffix}" for version in ("1.0", "2.0", "3.0") for suffix in ("", "-only", "-or-later", "+")]
    + [f"AGPL-{version}{suffix}" for version in ("1.0", "3.0") for suffix in ("", "-only", "-or-later", "+")]
    + ["SSPL-1.0"]
)


def license_allowed(expression: str) -> bool:
    """AND сильнее OR; все идентификаторы должны быть известны даже в невыбранной ветке.

    WITH не разрешается без адресной проверки exception; substring GPL не используется.
    """
    tokens = re.findall(r"[A-Za-z0-9.+-]+|[()]", expression)
    if "".join(tokens) != re.sub(r"\s+", "", expression) or not tokens:
        raise ValueError(f"некорректное SPDX выражение: {expression!r}")
    for token in tokens:
        if token not in ALLOWED | DENIED | {"AND", "OR", "(", ")"}:
            raise ValueError(f"неизвестный SPDX identifier/operator: {token}")
    position = 0

    def atom() -> bool:
        nonlocal position
        if position >= len(tokens):
            raise ValueError("неполное SPDX выражение")
        token = tokens[position]
        position += 1
        if token == "(":
            value = disjunction()
            if position >= len(tokens) or tokens[position] != ")":
                raise ValueError("не закрыта скобка SPDX")
            position += 1
            return value
        if token not in ALLOWED | DENIED:
            raise ValueError("ожидается SPDX identifier")
        return token in ALLOWED

    def conjunction() -> bool:
        nonlocal position
        value = atom()
        while position < len(tokens) and tokens[position] == "AND":
            position += 1
            right = atom()
            value = value and right
        return value

    def disjunction() -> bool:
        nonlocal position
        value = conjunction()
        while position < len(tokens) and tokens[position] == "OR":
            position += 1
            right = conjunction()
            value = value or right
        return value

    result = disjunction()
    if position != len(tokens):
        raise ValueError("лишние токены SPDX")
    return result


def python_inventory(root: Path) -> list[dict]:
    lock = tomllib.loads((root / "backend/uv.lock").read_text())
    cache = json.loads((root / "docs/licenses/python-metadata.json").read_text())
    reviewed = {(r["name"], r["version"]): r for r in cache}
    if len(reviewed) != len(cache):
        raise ValueError("повтор metadata name/version")
    packages = {p["name"]: p for p in lock["package"]}
    if len(packages) != len(lock["package"]):
        raise ValueError("несколько версий одного Python package: требуется явная поддержка inventory")
    project = packages["cx-pulse-backend"]
    runtime = set()

    def visit(name):
        if name in runtime:
            return
        runtime.add(name)
        package = packages[name]
        for edge in package.get("dependencies", []):
            visit(edge["name"])
        # extras тоже являются частью закреплённого runtime, учитываем консервативно.
        for edges in package.get("optional-dependencies", {}).values():
            for edge in edges:
                visit(edge["name"])

    for edge in project.get("dependencies", []):
        visit(edge["name"])
    rows = []
    for name, package in sorted(packages.items()):
        if name == "cx-pulse-backend":
            continue
        row = reviewed.get((name, package["version"]))
        if row is None:
            raise ValueError(f"нет проверенных metadata: {name}=={package['version']}")
        expressions = row["metadata"].get("License-Expression", [])
        if expressions and expressions != [row["expression"]]:
            raise ValueError(f"License-Expression противоречит inventory: {name}")
        if row.get("wheel_url"):
            wheels = {(w["url"], w["hash"]) for w in package.get("wheels", [])}
            if (row["wheel_url"], "sha256:" + row["wheel_sha256"]) not in wheels:
                raise ValueError(f"wheel evidence отсутствует в lock: {name}")
        # Подмена metadata локально/в CI не должна обходить gate.
        try:
            installed = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            installed = None
        if installed is None and not row.get("wheel_url"):
            raise ValueError(f"нет установленной metadata или lock-verified wheel: {name}")
        if installed is not None and installed.version != package["version"]:
            raise ValueError(f"установленная версия не совпадает с lock: {name}")
        if installed is not None:
            raw = metadata_fields(installed.metadata)
            for filename, digest in row.get("license_files_sha256", {}).items():
                import hashlib

                license_file = installed.locate_file(filename)
                if not license_file.is_file() or hashlib.sha256(license_file.read_bytes()).hexdigest() != digest:
                    raise ValueError(f"license notice изменился: {name} {filename}")
            if raw != row["metadata"]:
                raise ValueError(f"metadata изменились: {name}=={package['version']}")
        rows.append(
            {
                "ecosystem": "python",
                "name": name,
                "version": package["version"],
                "scope": "runtime" if name in runtime else "dev",
                "license": row["expression"],
                "source": row["source"],
            }
        )
    expected = {(p["name"], p["version"]) for p in lock["package"] if p["name"] != "cx-pulse-backend"}
    if set(reviewed) != expected:
        raise ValueError("python-metadata.json содержит устаревшие или лишние записи")
    return rows


def metadata_fields(metadata) -> dict:
    return {key: metadata.get_all(key, []) for key in ("License-Expression", "License", "Classifier")}


def npm_inventory(root: Path) -> list[dict]:
    lock = json.loads((root / "frontend/package-lock.json").read_text())
    if lock.get("lockfileVersion") != 3:
        raise ValueError("ожидается npm lockfileVersion=3")
    rows = []
    for path, package in sorted(lock["packages"].items()):
        if not path:
            continue
        if package.get("link"):
            raise ValueError(f"непроверенная npm link-зависимость: {path}")
        expression = package.get("license")
        if not isinstance(expression, str) or not expression:
            raise ValueError(f"нет SPDX license: {path}")
        rows.append(
            {
                "ecosystem": "npm",
                "name": path.rsplit("node_modules/", 1)[-1],
                "version": package["version"],
                "scope": "dev" if package.get("dev") else "runtime",
                "license": expression,
                "source": package.get("resolved", ""),
            }
        )
    return rows


def inventory(root: Path) -> list[dict]:
    rows = python_inventory(root) + npm_inventory(root)
    for row in rows:
        if not license_allowed(row["license"]):
            raise ValueError(
                f"запрещённая лицензия: {row['ecosystem']} {row['name']}=={row['version']}: {row['license']}"
            )
    return rows


def render(rows: list[dict]) -> str:
    lines = [
        "# Лицензии закреплённых зависимостей",
        "",
        "Сгенерировано `python scripts/licenses_check.py --write`; не редактировать вручную.",
        "",
        "Полный lock, включая platform-only, runtime и dev. Python: version-bound wheel/METADATA evidence в `docs/licenses/python-metadata.json`. npm: license из package-lock v3.",
        "",
        "| Экосистема | Пакет | Версия | Область | SPDX |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| " + " | ".join(str(row[key]) for key in ("ecosystem", "name", "version", "scope", "license")) + " |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="обновить THIRD_PARTY_LICENSES.md после проверки metadata",
    )
    args = parser.parse_args()
    try:
        rows = inventory(ROOT)
        report = render(rows)
        path = ROOT / "THIRD_PARTY_LICENSES.md"
        if args.write:
            path.write_text(report)
        elif not path.exists() or path.read_text() != report:
            raise ValueError("THIRD_PARTY_LICENSES.md устарел: запустите --write")
    except (ValueError, KeyError, OSError) as exc:
        sys.stderr.write(f"licenses-check: {exc}\n")
        return 1
    sys.stdout.write(f"licenses-check: ok, {len(rows)} distributions\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
