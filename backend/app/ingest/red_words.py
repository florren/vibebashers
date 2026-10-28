"""Детерминированные правила клиентских красных слов (ТЗ 24.3), до LLM."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


@lru_cache(maxsize=1)
def _rules() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[3] / "data" / "red_words.yaml"
    # В checkout data находится рядом с backend; в контейнере — /data.
    if not path.exists():
        path = Path("/data/red_words.yaml")
    with path.open() as stream:
        return dict(yaml.safe_load(stream))


def detect(text: str) -> dict[str, Any]:
    rules = _rules()
    normalized = text.casefold().replace("ё", "е")
    exceptions = set(rules["exceptions"])
    matches = []
    for rule in rules["rules"]:
        for match in re.finditer(r"(?<!\w)(?:" + rule["pattern"] + r")(?!\w)", normalized):
            if match.group() not in exceptions:
                matches.append(
                    {
                        "code": rule["code"],
                        "text": match.group(),
                        "start": match.start(),
                        "end": match.end(),
                        "legal": rule["legal"],
                    }
                )
    matches.sort(key=lambda item: (item["start"], item["end"]))
    return {
        "version": rules["version"],
        "matches": matches,
        "words": list(dict.fromkeys(m["text"] for m in matches)),
        "legal": any(m["legal"] for m in matches),
    }
