"""Хранилище кассет: data/cassettes/<provider>.jsonl (строка = кассета). Ключ sha256(provider, model, normalized_messages, schema).

Схема строки совместима с таблицей llm_cassettes (request_hash, provider, model, response, chunks, usage, recorded_at)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

from app.llm.base import Message, normalize_messages
from app.logging import get_logger

log = get_logger(__name__)


def request_hash(provider: str, model: str, messages: list[Message], schema: dict[str, Any] | None) -> str:
    payload = json.dumps(
        {"provider": provider, "model": model, "messages": normalize_messages(messages), "schema": schema or {}},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CassetteStore:
    def __init__(self, directory: str | Path) -> None:
        self.dir = Path(directory)
        self._index: dict[str, dict[str, Any]] = {}
        self._loaded = False

    def load(self) -> int:
        self._index.clear()
        if self.dir.exists():
            for f in sorted(self.dir.glob("*.jsonl")):
                for line in f.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        log.warning("cassette_bad_line", file=f.name)
                        continue
                    self._index[f"{rec['request_hash']}:{rec['model']}"] = rec
        self._loaded = True
        log.info("cassettes_loaded", count=len(self._index), dir=str(self.dir))
        return len(self._index)

    def __len__(self) -> int:
        if not self._loaded:
            self.load()
        return len(self._index)

    def get(
        self, provider: str, model: str, messages: list[Message], schema: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if not self._loaded:
            self.load()
        return self._index.get(f"{request_hash(provider, model, messages, schema)}:{model}")

    def record(
        self,
        provider: str,
        model: str,
        messages: list[Message],
        schema: dict[str, Any] | None,
        *,
        response: dict[str, Any] | str,
        usage: dict[str, Any],
        chunks: list[dict[str, Any]] | None = None,
        scenario_id: str | None = None,
        prompt_version: str | None = None,
    ) -> dict[str, Any]:
        if not self._loaded:
            self.load()
        rec = {
            "request_hash": request_hash(provider, model, messages, schema),
            "provider": provider,
            "model": model,
            "scenario_id": scenario_id,
            "prompt_version": prompt_version,
            "response": response,
            "chunks": chunks or [],
            "usage": usage,
            "recorded_at": dt.datetime.now(dt.UTC).isoformat(),
            "messages": normalize_messages(messages),
        }
        key = f"{rec['request_hash']}:{model}"
        if key in self._index:
            return self._index[key]
        self._index[key] = rec
        self.dir.mkdir(parents=True, exist_ok=True)
        with (self.dir / f"{provider}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec
