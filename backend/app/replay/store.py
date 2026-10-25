"""Хранилище кассет: data/cassettes/<provider>.jsonl (строка = кассета). Ключ sha256(provider, model, normalized_messages, schema).

Схема строки совместима с таблицей llm_cassettes (request_hash, provider, model, response, chunks, usage, recorded_at)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

import psycopg

from app.llm.base import Message, normalize_messages
from app.logging import get_logger

log = get_logger(__name__)

_SKIP_PROVIDERS = frozenset({"mock", "replay"})


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
                    if rec.get("provider") in _SKIP_PROVIDERS:
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

    def _flush_provider(self, provider: str) -> None:
        recs = sorted(
            (r for r in self._index.values() if r.get("provider") == provider),
            key=lambda r: (r.get("recorded_at") or "", r.get("request_hash") or ""),
        )
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"{provider}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for rec in recs:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

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
        if provider in _SKIP_PROVIDERS:
            raise ValueError(f"кассеты не пишутся для провайдера {provider}")
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
            existing = self._index[key]
            if (existing.get("prompt_version") or "") == (prompt_version or ""):
                return existing
        self._index[key] = rec
        self._flush_provider(provider)
        return rec

    def summaries(self, current_version: str) -> list[dict[str, Any]]:
        if not self._loaded:
            self.load()
        groups: dict[tuple[Any, ...], dict[str, Any]] = {}
        for rec in self._index.values():
            gkey = (
                rec.get("scenario_id"),
                rec.get("provider"),
                rec.get("model"),
                rec.get("prompt_version"),
            )
            if gkey not in groups:
                groups[gkey] = {
                    "scenario_id": rec.get("scenario_id"),
                    "provider": rec.get("provider"),
                    "model": rec.get("model"),
                    "prompt_version": rec.get("prompt_version"),
                    "entries": 0,
                    "recorded_at": rec.get("recorded_at") or "",
                    "stale": (rec.get("prompt_version") or "") != current_version,
                }
            g = groups[gkey]
            g["entries"] += 1
            ra = rec.get("recorded_at") or ""
            if ra > g["recorded_at"]:
                g["recorded_at"] = ra
        return sorted(groups.values(), key=lambda s: (s.get("scenario_id") or "", s["provider"], s["model"]))

    def cassette_asset(self, scenario_id: str) -> dict[str, Any] | None:
        if not self._loaded:
            self.load()
        recs = [r for r in self._index.values() if r.get("scenario_id") == scenario_id]
        if not recs:
            return None
        from app.sim.scenarios import get as get_scenario

        scenario = get_scenario(scenario_id)
        title_ru = (scenario.get("title_ru") if scenario else None) or scenario_id
        providers = sorted({str(r["provider"]) for r in recs})
        path = f"data/cassettes/{providers[0]}.jsonl"
        payload = "\n".join(
            json.dumps(r, ensure_ascii=False, sort_keys=True)
            for r in sorted(recs, key=lambda r: (r.get("request_hash") or "", r.get("model") or ""))
        )
        checksum = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return {
            "kind": "cassette",
            "scenario_id": scenario_id,
            "title_ru": title_ru,
            "path": path,
            "checksum": checksum,
        }


def upsert_demo_asset(conn: psycopg.Connection[Any], row: dict[str, Any]) -> int:
    """Обновляет или создаёт demo_assets kind=cassette по path (без нового уникального ключа в схеме)."""
    cur = conn.execute(
        "select id from demo_assets where kind = 'cassette' and path = %s",
        (row["path"],),
    ).fetchone()
    if cur:
        conn.execute(
            "update demo_assets set checksum = %s, scenario_id = %s, title_ru = %s where id = %s",
            (row["checksum"], row.get("scenario_id"), row["title_ru"], cur[0]),
        )
        return int(cur[0])
    ins = conn.execute(
        "insert into demo_assets (kind, scenario_id, title_ru, path, checksum) values (%s, %s, %s, %s, %s) returning id",
        ("cassette", row.get("scenario_id"), row["title_ru"], row["path"], row["checksum"]),
    ).fetchone()
    assert ins
    return int(ins[0])
