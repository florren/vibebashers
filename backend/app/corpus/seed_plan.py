"""T-240: план покрытия и строго отдельная проекция аннотаций seed-корпуса.

Этот модуль не вызывается importer CLI и не даёт runtime-входу права назначать
classification. CSI/audio bindings доставляются будущим seed adapter отдельно.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from app.contracts.enums import Channel, Criticality, ProductLine
from app.corpus.reviews import CorpusError, ReviewGold, ReviewRow


@dataclass(frozen=True)
class DeliveryCase:
    product_line: ProductLine
    channel: Channel
    review_id: str
    external_id: str


def coverage_plan(rows: list[ReviewRow], lines: frozenset[ProductLine]) -> tuple[DeliveryCase, ...]:
    grouped: dict[ProductLine, list[str]] = defaultdict(list)
    for row in rows:
        if row.gold is None:
            raise CorpusError("для seed plan требуется проверенный gold")
        grouped[row.gold.product_line].append(row.external_id)
    if set(grouped) != set(lines):
        raise CorpusError("seed corpus должен покрывать ровно справочник направлений")
    result = []
    for line in sorted(lines):
        variants = sorted(grouped[line])
        for index, channel in enumerate(Channel):
            review_id = variants[index % len(variants)]
            result.append(DeliveryCase(line, channel, review_id, f"{review_id}:{channel.value}"))
    return tuple(result)


async def apply_seed_projection(
    conn: psycopg.AsyncConnection[Any], *, run_id: int, signal_id: int, gold: ReviewGold
) -> None:
    """Только verified seed annotations после normalizer; не создаёт signal/commit."""
    if conn.info.transaction_status != TransactionStatus.INTRANS:
        raise CorpusError("seed projection требует внешнюю транзакцию")
    if any(isinstance(x, bool) or not isinstance(x, int) or x <= 0 for x in (run_id, signal_id)):
        raise CorpusError("run_id/signal_id должны быть положительными int")
    found = await (
        await conn.execute(
            "select s.red_words from signals s join sim_runs r on r.id=s.run_id "
            "where s.id=%s and s.run_id=%s and r.kind='baseline' for update of s",
            (signal_id, run_id),
        )
    ).fetchone()
    if found is None:
        raise CorpusError("сигнал отсутствует в seed run")
    level = Criticality.HIGH if found[0] else gold.criticality
    await conn.execute(
        "update signals set product_line_code=%s,classification=coalesce(classification,'{}'::jsonb)||%s "
        "where id=%s and run_id=%s",
        (
            gold.product_line.value,
            Jsonb({"product_line": gold.product_line.value, "criticality": level.value, "signal_level": level.value}),
            signal_id,
            run_id,
        ),
    )


def load_seed_corpus(directory: Path | None = None) -> list[ReviewRow]:
    """Проверяет version/hash/доли trusted seed-пакета; importer этот путь не вызывает."""
    import hashlib
    from collections import Counter

    import yaml

    from app.corpus.reviews import MAX_BYTES, ROOT, parse_reviews

    path = directory or ROOT / "data/corpus/reviews/product_lines_v1"
    manifest = yaml.safe_load((path / "manifest.yaml").read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("dataset") != "product_lines_v1"
        or manifest.get("synthetic") is not True
    ):
        raise CorpusError("неверный seed manifest")
    if type(manifest.get("version")) is not int or manifest["version"] != 1 or manifest.get("source") != "reviews.json":
        raise CorpusError("неподдерживаемая версия seed corpus")
    source = path / "reviews.json"
    with source.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise CorpusError("seed corpus превышает ограничение размера")
    if hashlib.sha256(raw).hexdigest() != manifest.get("sha256"):
        raise CorpusError("seed corpus checksum не совпадает")
    rows = parse_reviews(source, synthetic_only=True)
    if len(rows) != manifest.get("rows") or any(x.gold is None for x in rows):
        raise CorpusError("seed corpus требует разметку всех строк")
    refs = yaml.safe_load((ROOT / "data/product_lines.yaml").read_text())["product_lines"]
    expected = {x["code"]: x["demo_review_share"] * 3 for x in refs}
    if Counter(x.gold.product_line.value for x in rows if x.gold) != expected:
        raise CorpusError("seed corpus не сохраняет утверждённые пропорции")
    return rows
