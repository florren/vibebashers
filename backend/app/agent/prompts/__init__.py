"""Загрузка версионированных промптов app/agent/prompts/vN/*.md с фронтматтером (AGENTS.md §6)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

PROMPTS_DIR = Path(__file__).resolve().parent
CURRENT_VERSION = "v1"
_FM = re.compile(r"^---\n(.*?)\n---\n", re.S)


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    meta: dict[str, Any]
    body: str

    def render(self, **vars: Any) -> str:
        out = self.body
        for k, v in vars.items():
            out = out.replace("{{" + k + "}}", str(v))
        return out


def _parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    m = _FM.match(text)
    if not m:
        return {}, text
    meta: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"')
    return meta, text[m.end() :]


@lru_cache(maxsize=64)
def load(name: str, version: str = CURRENT_VERSION) -> Prompt:
    path = PROMPTS_DIR / version / f"{name}.md"
    meta, body = _parse_front_matter(path.read_text(encoding="utf-8"))
    return Prompt(name=name, version=str(meta.get("version", version)), meta=meta, body=body.strip())


def prompt_version(version: str = CURRENT_VERSION) -> str:
    return load("system", version).version
