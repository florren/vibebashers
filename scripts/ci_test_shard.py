"""T-145: полное покрытие pytest четырьмя изолированными CI runners, без xdist."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def collection_modules(output: str) -> list[str]:
    modules = sorted(
        {line.split("::", 1)[0] for line in output.splitlines() if line.startswith("tests/") and "::" in line}
    )
    if not modules:
        raise ValueError("pytest не собрал ни одного тестового модуля")
    for module in modules:
        path = PurePosixPath(module)
        if path.is_absolute() or ".." in path.parts or path.suffix != ".py":
            raise ValueError("недопустимый путь тестового модуля")
    return modules


def partition(modules: list[str], index: int, count: int) -> list[str]:
    if count < 1 or not 0 <= index < count or len(set(modules)) != len(modules):
        raise ValueError("некорректная разбивка тестов")
    selected = sorted(modules)[index::count]
    if not selected:
        raise ValueError("пустой shard: уменьшите count")
    return selected


def verify_manifests(paths: list[Path], count: int) -> None:
    if count < 1 or len(paths) != count:
        raise ValueError("отсутствует manifest одного из runners")
    manifests = [json.loads(path.read_text()) for path in paths]
    if {row["index"] for row in manifests} != set(range(count)):
        raise ValueError("повторяющийся или отсутствующий index runner")
    discovered = manifests[0]["discovered"]
    if not discovered or len(set(discovered)) != len(discovered):
        raise ValueError("некорректный список собранных модулей")
    nodeids = manifests[0]["nodeids"]
    if len(nodeids) != len(set(nodeids)) or collection_modules("\n".join(nodeids)) != discovered:
        raise ValueError("некорректная полная коллекция тестов")
    revision = manifests[0]["revision"]
    if not revision:
        raise ValueError("отсутствует revision")
    selected: list[str] = []
    for row in manifests:
        if (
            row["count"] != count
            or row["discovered"] != discovered
            or row["nodeids"] != nodeids
            or row["revision"] != revision
        ):
            raise ValueError("runners использовали разные наборы тестов")
        if row["selected"] != partition(discovered, row["index"], count):
            raise ValueError("runner не выполнил свою часть набора")
        expected_count = sum(node.split("::", 1)[0] in row["selected"] for node in nodeids)
        if row.get("exit_code") != 0 or row.get("executed_count") != expected_count:
            raise ValueError("runner не подтвердил успешное выполнение всех тестов")
        selected.extend(row["selected"])
    if sorted(selected) != sorted(discovered):
        raise ValueError("разбиение потеряло или продублировало тесты")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=int)
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--manifest-dir", type=Path, default=Path("test-results"))
    parser.add_argument("--verify", type=Path, help="каталог скачанных manifests всех runners")
    args = parser.parse_args(argv)
    try:
        if args.verify is not None:
            verify_manifests(sorted(args.verify.rglob("manifest-*.json")), args.count)
            return 0
        if args.index is None:
            parser.error("нужен --index либо --verify")
        collected = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            cwd=ROOT / "backend",
            check=False,
            capture_output=True,
            text=True,
        )
        if collected.returncode:
            sys.stderr.write(collected.stdout + collected.stderr)
            return collected.returncode
        modules = collection_modules(collected.stdout)
        selected = partition(modules, args.index, args.count)
        args.manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest: dict[str, Any] = {
            "index": args.index,
            "count": args.count,
            "discovered": modules,
            "selected": selected,
            "nodeids": [line for line in collected.stdout.splitlines() if line.startswith("tests/") and "::" in line],
            "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "exit_code": None,
            "executed_count": None,
        }
        manifest_path = args.manifest_dir / f"manifest-{args.index}.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))
        junit = (args.manifest_dir / f"shard-{args.index}.xml").resolve()
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", f"--junitxml={junit}", *selected],
            cwd=ROOT / "backend",
            check=False,
        )
        manifest["exit_code"] = result.returncode
        if junit.exists():
            manifest["executed_count"] = len(ET.parse(junit).findall(".//testcase"))
        manifest_path.write_text(json.dumps(manifest, indent=2))
        return result.returncode
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
