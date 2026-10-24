#!/usr/bin/env python3
"""Проверка границ слоя в ветке/PR (docs/TEAM-SPLIT.md раздел 3).

Использование: python scripts/check_owners.py [--base main] [--layer L3] [--card 213] [--allow-cross]
Слой определяется (по убыванию приоритета): --layer; --card → карточка docs/tasks/T-NNN-*.md (строка «| Слой | `Lk` …»);
имя текущей ветки feat/T-NNN-*. Изменённые файлы — `git diff --name-only <base>...HEAD` плюс незакоммиченные.
Файл допустим, если среди его владельцев по CODEOWNERS есть @layer-<lk> (последнее совпадение приоритетнее).
Код возврата 1 — есть файлы вне слоя (кроме режима --allow-cross, который только печатает список).
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALL_LAYERS = {"L1", "L2", "L3", "L4", "L5"}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout


def load_codeowners() -> list[tuple[str, set[str]]]:
    rules: list[tuple[str, set[str]]] = []
    for line in (ROOT / "CODEOWNERS").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pattern, *owners = line.split()
        rules.append((pattern, {o.lstrip("@").lower() for o in owners}))
    return rules


def owners_for(path: str, rules: list[tuple[str, set[str]]]) -> set[str]:
    result: set[str] = set()
    for pattern, owners in rules:
        pat = pattern.lstrip("/")
        if pat.endswith("/"):
            hit = path.startswith(pat)
        elif "*" in pat or "?" in pat:
            hit = fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(path.split("/")[-1], pat)
        else:
            hit = path == pat or path.startswith(pat + "/")
        if hit:
            result = owners
    return result


def layer_tags(owners: set[str]) -> set[str]:
    return {owner.removeprefix("layer-").upper() for owner in owners if owner.startswith("layer-l")}


def branch_name() -> str:
    """В CI checkout PR — detached HEAD; имя ветки лежит в GITHUB_HEAD_REF."""
    ref = os.environ.get("GITHUB_HEAD_REF", "").strip()
    if ref:
        return ref
    name = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    return "" if name == "HEAD" else name


def layer_from_card(card: int) -> str | None:
    for f in (ROOT / "docs/tasks").glob(f"T-{card:03d}-*.md"):
        m = re.search(r"\| Слой \| `(L\d)`", f.read_text(encoding="utf-8"))
        if m:
            return m.group(1)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="main")
    ap.add_argument("--layer")
    ap.add_argument("--card", type=int)
    ap.add_argument("--allow-cross", action="store_true")
    a = ap.parse_args()

    branch = branch_name()
    layer = a.layer
    card = a.card
    if card is None:
        m = re.search(r"T-(\d{3})", branch)
        card = int(m.group(1)) if m else None
    if layer is None and card is not None:
        layer = layer_from_card(card)

    changed = set(filter(None, git("diff", "--name-only", f"{a.base}...HEAD").splitlines()))
    changed |= set(filter(None, git("diff", "--name-only").splitlines()))
    changed |= set(filter(None, git("ls-files", "--others", "--exclude-standard").splitlines()))

    rules = load_codeowners()
    if layer is None:
        specific: set[str] = set()
        for path in changed:
            tags = layer_tags(owners_for(path, rules))
            if tags and tags != ALL_LAYERS:
                specific |= tags
        if len(specific) == 1:
            layer = next(iter(specific))
        elif a.allow_cross:
            print(
                f"ветка {branch or 'HEAD'!r}: слои {', '.join(sorted(specific)) or 'не размечены'}; --allow-cross"
            )
            return 0
        else:
            print(
                f"check_owners: не удалось определить один слой (ветка {branch!r}, слои файлов: {', '.join(sorted(specific)) or 'нет меток @layer-lN в CODEOWNERS'}). "
                "Укажите --layer/--card или добавьте cross-layer в заголовок PR.",
                file=sys.stderr,
            )
            return 2
    layer_key = f"layer-{layer.lower()}"
    outside = sorted(p for p in changed if layer_key not in owners_for(p, rules))
    print(f"слой {layer} (карточка T-{card:03d})" if card else f"слой {layer}", f"— изменённых файлов: {len(changed)}")
    if outside:
        print("вне слоя:")
        for p in outside:
            print(f"  {p}  → владельцы: {', '.join(sorted(owners_for(p, rules))) or '—'}")
        if not a.allow_cross:
            print("Ошибка: PR меняет файлы вне своего слоя. Либо вынесите изменение в карточку нужного слоя, "
                  "либо пометьте PR меткой contract-change/cross-layer и перечислите эти файлы в описании (сливает владелец L1).")
            return 1
    else:
        print("ok: все изменения внутри слоя")
    return 0


if __name__ == "__main__":
    sys.exit(main())
