"""T-021: проверка canonical golden/lite; seed вызывает общий loader без сети."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.bench.datasets import check_canonical, read_rows  # noqa: E402

LITE = ROOT / "data/golden/lite_v1.jsonl"


def check(path: Path | None = None) -> list[str]:
    try:
        if path is None:
            check_canonical()
        else:
            rows = read_rows(path, complete_gold=True)
            if not 30 <= len(rows) <= 40 or any("ambiguous" in row.get("tags", []) for row in rows):
                raise ValueError("lite: нужны30–40 кейсов без ambiguous")
    except (ValueError, OSError) as exc:
        return [str(exc)]
    return []


def source_metadata(code: str) -> dict[str, str]:
    path = ROOT / "data/golden" / f"{code}.jsonl"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"family": code, "sha256": digest, "source": f"data/golden/{code}.jsonl", "proposed_version_code": f"{code}__{digest[:12]}"}


def seed_dataset(cur: Any, code: str, rows: list[dict[str, Any]]) -> None:
    """Повтор идентичен; непустой старый набор/история никогда не заменяются молча."""
    metadata = source_metadata(code)
    cur.execute("insert into bench_datasets(code,title_ru,description) values(%s,%s,%s) on conflict(code) do nothing", (code, code, json.dumps(metadata)))
    cur.execute("select id,description from bench_datasets where code=%s for update", (code,))
    dataset_id, description = cur.fetchone()
    try:
        stored_metadata = json.loads(description or "null")
    except json.JSONDecodeError:
        stored_metadata = None
    cur.execute("select channel_code,segment_code,text,gold,tags from bench_cases where dataset_id=%s order by id", (dataset_id,))
    previous = cur.fetchall()
    expected = [(row["channel"], row.get("segment"), row["text"], row["gold"], [*row.get("tags", []), f"dataset-case:{row['id']}"]) for row in rows]
    if previous:
        if previous != expected or stored_metadata != metadata:
            raise ValueError(f"{code}: существующий набор сохранён; нужен согласованный upgrade в {metadata['proposed_version_code']}")
        return
    cur.execute("select exists(select 1 from bench_runs where dataset_id=%s)", (dataset_id,))
    if cur.fetchone()[0]:
        raise ValueError(f"{code}: найден прогон без кейсов; история требует отдельного review")
    from psycopg.types.json import Jsonb

    cur.executemany("insert into bench_cases(dataset_id,channel_code,segment_code,text,gold,tags) values(%s,%s,%s,%s,%s,%s)", [(dataset_id, channel, segment, text, Jsonb(gold), tags) for channel, segment, text, gold, tags in expected])
    cur.execute("update bench_datasets set description=%s where id=%s", (json.dumps(metadata), dataset_id))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--upgrade-plan", action="store_true", help="только metadata и предлагаемые version codes; без записи в БД")
    args = parser.parse_args()
    if not args.check and not args.upgrade_plan:
        parser.error("укажите --check либо --upgrade-plan")
    errors = check()
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    if args.upgrade_plan:
        print(json.dumps([source_metadata(code) for code in ("golden_v1", "lite_v1")], ensure_ascii=False, indent=2))
    else:
        print("golden/lite: структура, баланс, strict subset и legacy mirrors корректны; independent review проверяется отдельно")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
