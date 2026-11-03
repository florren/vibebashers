"""T238: validated classification и физическое направление сохраняются в одном TX."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb


async def save(
    conn: psycopg.AsyncConnection[Any],
    signal_id: int,
    classification: dict[str, Any],
    *,
    status: str | None = None,
    decision: dict[str, Any] | None = None,
) -> None:
    """Не выводит направление из coarse product, не меняет модельный output.

    Уже проверенная editorial seed-проекция — независимый источник. Сохраняем
    её только при native baseline/ingest/receipt provenance, а не по raw meta.
    Runtime-классификация unknown очищает прежний runtime code до SQL NULL.
    Caller владеет транзакцией; здесь нет commit или дополнительных effects.
    """
    line = classification.get("product_line")
    await conn.execute(
        """UPDATE signals s SET classification=%s,
        product_line_code=CASE WHEN EXISTS (
          SELECT 1 FROM sim_runs r JOIN product_lines pl ON pl.code=s.product_line_code
          JOIN settings receipt ON receipt.key='seed_product_reviews:'||r.id::text
          WHERE r.id=s.run_id AND r.kind='baseline' AND s.origin='sim'
            AND s.meta->'seed_annotation'->>'source'='editorial_seed_gold'
            AND s.meta->'seed_annotation'->'fields' @> '["product_line"]'::jsonb
            AND receipt.value->>'corpus_sha256' ~ '^[0-9a-f]{64}$'
            AND receipt.value->>'seed'=r.seed::text
            AND receipt.value->>'reference_anchor'=s.meta->'seed_instance'->>'reference_anchor'
            AND receipt.value->'offset_seconds'=s.meta->'seed_instance'->'offset_seconds'
            AND jsonb_typeof(s.meta->'seed_instance')='object'
            AND nullif(s.meta->'seed_instance'->>'canonical_review_id','') IS NOT NULL
            AND EXISTS (SELECT 1 FROM ingest_messages im
              WHERE im.signal_id=s.id AND im.run_id=s.run_id AND im.status='accepted'
                AND im.payload->>'origin'='sim'
                AND im.payload->'meta'->'seed_instance'=s.meta->'seed_instance'
                AND (im.source_code='product_review_seed' OR (im.source_code='csi'
                  AND EXISTS(SELECT 1 FROM csi_responses cr WHERE cr.signal_id=s.id))))
        ) THEN s.product_line_code ELSE (SELECT code FROM product_lines WHERE code=%s) END,
        status=coalesce(%s,status), decision=CASE WHEN %s THEN %s::jsonb ELSE decision END,
        updated_at=now() WHERE s.id=%s""",
        (
            Jsonb(classification),
            line if isinstance(line, str) else None,
            status,
            decision is not None,
            Jsonb(decision),
            signal_id,
        ),
    )
