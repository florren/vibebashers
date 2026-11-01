"""T-021: проверка canonical golden/lite; seed вызывает общий loader без сети."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.bench.datasets import check_canonical, read_rows, validate_review  # noqa: E402

LITE = ROOT / "data/golden/lite_v1.jsonl"


def check(path: Path | None = None) -> list[str]:
    try:
        if path is None:
            check_canonical()
            validate_review()
        else:
            rows = read_rows(path, complete_gold=True)
            if not 30 <= len(rows) <= 40 or any("ambiguous" in row.get("tags", []) for row in rows):
                raise ValueError("lite: нужны30–40 кейсов без ambiguous")
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return [str(exc)]
    return []


def source_metadata(code: str) -> dict[str, str]:
    path = ROOT / "data/golden" / f"{code}.jsonl"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "family": code,
        "sha256": digest,
        "source": f"data/golden/{code}.jsonl",
        "content_version": f"{code}@{digest[:12]}",
    }


def seed_dataset(cur: Any, code: str, rows: list[dict[str, Any]]) -> None:
    # FOR UPDATE должен действовать на всю проверку/вставку, включая autocommit caller.
    with cur.connection.transaction():
        _seed_dataset(cur, code, rows)


def _seed_dataset(cur: Any, code: str, rows: list[dict[str, Any]]) -> None:
    """Повтор идентичен; непустой старый набор/история никогда не заменяются молча."""
    metadata = source_metadata(code)
    cur.execute(
        "insert into bench_datasets(code,title_ru,description) values(%s,%s,%s) on conflict(code) do nothing",
        (code, code, json.dumps(metadata)),
    )
    cur.execute("select id,description from bench_datasets where code=%s for update", (code,))
    dataset_id, description = cur.fetchone()
    try:
        stored_metadata = json.loads(description or "null")
    except json.JSONDecodeError:
        stored_metadata = None
    cur.execute(
        "select channel_code,segment_code,text,gold,tags from bench_cases where dataset_id=%s order by id",
        (dataset_id,),
    )
    previous = cur.fetchall()
    expected = [
        (
            row["channel"],
            row.get("segment"),
            row["text"],
            row["gold"],
            [*row.get("tags", []), f"dataset-case:{row['id']}"],
        )
        for row in rows
    ]
    if previous:
        if previous != expected or stored_metadata != metadata:
            raise ValueError(
                f"{code}: существующий набор сохранён; нужен согласованный upgrade в {metadata['content_version']}"
            )
        return
    cur.execute("select exists(select 1 from bench_runs where dataset_id=%s)", (dataset_id,))
    if cur.fetchone()[0]:
        raise ValueError(f"{code}: найден прогон без кейсов; история требует отдельного review")
    from psycopg.types.json import Jsonb

    cur.executemany(
        "insert into bench_cases(dataset_id,channel_code,segment_code,text,gold,tags) values(%s,%s,%s,%s,%s,%s)",
        [(dataset_id, channel, segment, text, Jsonb(gold), tags) for channel, segment, text, gold, tags in expected],
    )
    cur.execute("update bench_datasets set description=%s where id=%s", (json.dumps(metadata), dataset_id))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--plan", action="store_true", help="read-only план upgrade для явного DATABASE_URL")
    parser.add_argument(
        "--apply", action="store_true", help="явно применить согласованный --plan; старые cases/results сохраняются"
    )
    parser.add_argument("--plan-sha", help="plan_sha256 из read-only --plan")
    parser.add_argument(
        "--upgrade-plan", action="store_true", help="только metadata и предлагаемые version codes; без записи в БД"
    )
    args = parser.parse_args()
    if not args.check and not args.upgrade_plan and not args.plan and not args.apply:
        parser.error("укажите --check, --plan, --apply либо --upgrade-plan")
    errors = check()
    if errors:
        sys.stderr.write("\n".join(errors) + "\n")
        return 1
    if args.plan or args.apply:
        if args.plan and args.apply:
            parser.error("выберите --plan либо --apply")
        if args.apply and not args.plan_sha:
            parser.error("--apply требует --plan-sha из предварительного --plan")
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            parser.error("нужен явный DATABASE_URL; .env и localhost defaults не читаются")
        import psycopg

        from scripts.seed.bench_upgrade import apply_plan, build_plan

        try:
            with psycopg.connect(
                dsn.replace("postgresql+psycopg://", "postgresql://", 1), connect_timeout=5
            ) as connection:
                with connection.cursor() as cur:
                    if args.plan:
                        cur.execute("set transaction isolation level repeatable read read only")
                        plan = build_plan(cur)
                    else:
                        plan = apply_plan(cur, args.plan_sha)
            sys.stdout.write(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
            return int(plan["blocked"])
        except ValueError as exc:
            sys.stderr.write(str(exc) + "\n")
            return 1
        except psycopg.Error as exc:
            sys.stderr.write(
                f"транзакция upgrade отменена (SQLSTATE {exc.sqlstate or 'connection'}); повторите --plan\n"
            )
            return 1
    if args.upgrade_plan:
        sys.stdout.write(
            json.dumps([source_metadata(code) for code in ("golden_v1", "lite_v1")], ensure_ascii=False, indent=2)
            + "\n"
        )
    else:
        sys.stdout.write(
            "golden200/lite40: структура, баланс, strict subset, mirrors и independent case-level review98.5% корректны\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
