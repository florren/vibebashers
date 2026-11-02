"""T-240: moved instances корпуса, реальное покрытие и run-scoped история.

Только baseline seed: runtime/CLI по-прежнему игнорируют gold. Все новые signals
проходят normalizer; CSI имеет существующую ВСП, аудиоканалы содержат только текст.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from pathlib import Path
from typing import Any

import psycopg
import yaml
from app.contracts.enums import Channel, Criticality, ProductLine, Sentiment
from app.corpus.history import ActualSignal, HistoryConfig, build_history
from app.corpus.history_store import save_history
from app.corpus.reviews import CorpusError, message, platforms
from app.corpus.seed_plan import apply_seed_projection, coverage_plan, load_seed_corpus
from app.ingest.normalizer import create_signal, from_csi
from app.ingest.sync_bridge import async_seed_connection
from app.sim.rng import SimRng
from app.sim.textgen import TextGen
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[2]


def seed_reviews(cur: psycopg.Cursor[Any], *, run_id: int, anchor: dt.datetime, seed: int) -> None:
    """Один stage с receipt в общей транзакции; существующий T019 cohort не меняется."""
    asyncio.run(_seed(async_seed_connection(cur.connection), run_id=run_id, anchor=anchor, seed=seed))


async def _seed(conn: Any, *, run_id: int, anchor: dt.datetime, seed: int) -> None:
    if isinstance(seed, bool) or not isinstance(seed, int) or anchor.utcoffset() is None:
        raise CorpusError("seed требует int и aware anchor")
    rows = load_seed_corpus()
    manifest = yaml.safe_load((ROOT / "data/corpus/reviews/product_lines_v1/manifest.yaml").read_text())
    key = f"seed_product_reviews:{run_id}"
    found = await (await conn.execute("select value from settings where key=%s", (key,))).fetchone()
    if found:
        if (
            found[0].get("corpus_sha256") != manifest["sha256"]
            or found[0].get("seed") != seed
            or found[0].get("anchor") != anchor.astimezone(dt.UTC).isoformat()
        ):
            raise CorpusError("существующая seed instance имеет другую corpus revision; требуется явный rebuild")
        return
    run = await (await conn.execute("select kind from sim_runs where id=%s for update", (run_id,))).fetchone()
    if run != ("baseline",):
        raise CorpusError("review seed разрешён только в baseline")
    reference = dt.datetime.fromisoformat(manifest["reference_anchor"])
    offset = anchor - reference
    lines = frozenset(row.gold.product_line for row in rows if row.gold)
    indexed = {row.external_id: row for row in rows}
    delivered = {(row.gold.product_line, row.channel) for row in rows if row.gold}
    additions = [case for case in coverage_plan(rows, lines) if (case.product_line, case.channel) not in delivered]
    deliveries = [(row, row.channel, row.external_id) for row in rows]
    deliveries += [(indexed[case.review_id], case.channel, case.external_id) for case in additions]
    await conn.execute(
        "insert into ingest_sources(code,kind,channel_code,enabled,is_external) values "
        "('product_review_seed','file','review_portal',false,false) on conflict(code) do nothing"
    )
    branch = await (await conn.execute("select code from branches order by code limit 1")).fetchone()
    if branch is None:
        raise CorpusError("CSI coverage требует реальную seeded ВСП")
    for index, (row, channel, external) in enumerate(deliveries):
        at = dt.datetime.fromisoformat(row.date) + offset
        msg, _ = message(row, run_id=run_id)
        msg.update(
            channel=channel.value, external_id=f"run:{run_id}:{external}", timestamp=at.isoformat(), origin="sim"
        )
        msg["meta"]["seed_instance"] = {
            "reference_anchor": reference.isoformat(),
            "offset_seconds": offset.total_seconds(),
            "canonical_review_id": row.external_id,
            "text_only": channel in (Channel.VOICE_INPUT, Channel.BRANCH_AUDIO),
        }
        source = "product_review_seed"
        if channel == Channel.CSI_SURVEY:
            # Общая CSI identity не run-qualified по контракту; выбираем свободный
            # номер под тем же transaction lock, сохраняя собственный provenance.
            await conn.execute("select pg_advisory_xact_lock(hashtextextended('t240-seed-csi',0))")
            number = 700000 + (run_id * 1000 + index) % 100000
            for _ in range(100000):
                csi_no = f"CSI-{number:06d}"
                if (
                    await (
                        await conn.execute(
                            "select 1 from ingest_messages where source_code=%s and external_id=%s", ("csi", csi_no)
                        )
                    ).fetchone()
                    is None
                ):
                    break
                number = 700000 + (number - 700000 + 1) % 100000
            else:
                raise CorpusError("исчерпан диапазон CSI seed identities")
            csi_msg = from_csi(
                {"csi_no": csi_no, "complaint_ru": row.text, "branch_code": branch[0], "received_at": at.isoformat()}
            )
            csi_msg["meta"].update(msg["meta"])
            csi_msg["origin"] = "sim"
            msg, source = csi_msg, "csi"
        result = await create_signal(conn, msg, source_code=source, run_id=run_id, sim_time=at, emit_event=False)
        if result["status"] != "accepted":
            raise CorpusError("review seed не принят normalizer; stage отменён")
        assert row.gold is not None
        await apply_seed_projection(conn, run_id=run_id, signal_id=result["signal_id"], gold=row.gold)
        # Историческая editorial разметка не ставится в очередь runtime агента.
        await conn.execute("update signals set status='classified' where id=%s", (result["signal_id"],))
    supplement = await _supplement(conn, run_id=run_id, anchor=anchor, seed=seed)
    stored = await (
        await conn.execute(
            "select product_line_code,received_sim,meta->>'source_platform',"
            "classification->>'criticality',sentiment from signals where run_id=%s",
            (run_id,),
        )
    ).fetchall()
    actual = [
        ActualSignal(
            run_id,
            ProductLine(line) if line else None,
            at,
            source,
            Criticality(level) if level else None,
            Sentiment(sentiment) if sentiment else None,
        )
        for line, at, source, level, sentiment in stored
    ]
    # Всплески опираются на фактические faults текущего baseline и реальные линии
    # затронутых операций; чужие/неизвестные причинные связи не угадываются.
    faults = await (
        await conn.execute(
            "select distinct s.product_line_code,date_trunc('month',f.started_sim at time zone 'Europe/Moscow')::date "
            "from faults f join operations o on o.fault_id=f.id and o.run_id=f.run_id "
            "join signals s on s.run_id=f.run_id and s.source_operation_id=o.id "
            "where f.run_id=%s and s.product_line_code is not null",
            (run_id,),
        )
    ).fetchall()
    config = manifest["history"]
    history = build_history(
        seed=seed,
        run_id=run_id,
        anchor=anchor,
        actual=actual,
        product_lines=lines,
        known_platforms=frozenset(platforms()),
        fault_months=frozenset((ProductLine(line), month) for line, month in faults),
        config=HistoryConfig(tuple(config["seasonality"]), config["fault_spike_multiplier"], config["jitter_ratio"]),
    )
    await save_history(conn, history.rows)
    receipt = {
        "seed": seed,
        "anchor": anchor.astimezone(dt.UTC).isoformat(),
        "corpus_sha256": manifest["sha256"],
        "canonical_reviews": len(rows),
        "coverage_instances": len(additions),
        "supplement": supplement,
        "history_rows": len(history.rows),
        "unmapped_actual_count": history.unmapped_actual_count,
        "moved_instance": True,
        "reference_anchor": reference.isoformat(),
        "offset_seconds": offset.total_seconds(),
    }
    await conn.execute("insert into settings(key,value) values(%s,%s)", (key, Jsonb(receipt)))


async def _supplement(conn: Any, *, run_id: int, anchor: dt.datetime, seed: int) -> dict[str, int]:
    rows = await (
        await conn.execute(
            "select coalesce(classification->>'style','plain'),meta->'generator_hint' from signals where run_id=%s",
            (run_id,),
        )
    ).fetchall()
    generated = [hint for _, hint in rows if hint]
    hard = sum(style != "plain" for style, _ in rows)
    noise = sum(bool(hint.get("noise")) for hint in generated)
    tg, rng = TextGen(seed), SimRng(seed)
    count = extra_noise = 0
    while True:
        # Сохраняем точную долю noise исходного генератора, не размечая отзывы шумом.
        extra_noise = next(
            k for k in range(10000) if noise + k == round((len(generated) + count + k) * tg.corpus.noise_share)
        )
        if (hard + count) / (len(rows) + count + extra_noise) >= 0.25:
            break
        count += 1
    for index in range(count + extra_noise):
        is_noise = index >= count
        channel = "chat"
        g = (
            tg.noise(language="ru")
            if is_noise
            else tg.generate("tech_fault", "debit_card", channel=channel, language="ru", style="sarcasm")
        )
        if not is_noise and g.style != "sarcasm":
            raise CorpusError("hard supplement должен использовать реальный hard template")
        at = anchor - dt.timedelta(minutes=rng.randint(1, 14 * 24 * 60 - 1))
        msg = {
            "channel": channel,
            "external_id": f"run:{run_id}:t240-hard:{index}",
            "client": {},
            "text": g.text,
            "timestamp": at.isoformat(),
            "geo": {"source": "none"},
            "origin": "sim",
            "meta": {"generator_hint": g.gold, "t240_supplement": True},
        }
        result = await create_signal(
            conn, msg, source_code="product_review_seed", run_id=run_id, sim_time=at, emit_event=False
        )
        if result["status"] != "accepted":
            raise CorpusError("hard supplement отклонён normalizer")
        classification = (
            None
            if is_noise
            else {
                "signal_type": g.signal_type,
                "product": g.product,
                "criticality": "low",
                "sentiment": g.gold["sentiment"],
                "negativity": g.gold["negativity"],
                "flags": g.gold.get("flags", []),
                "style": g.style,
                "llm_source": "seed",
            }
        )
        await conn.execute(
            "update signals set status=%s,classification=%s,sentiment=%s,lang=%s where id=%s",
            (
                "noise" if is_noise else "answered",
                Jsonb(classification) if classification else None,
                None if is_noise else g.gold["sentiment"],
                g.gold["language"],
                result["signal_id"],
            ),
        )
    return {"hard": count, "noise": extra_noise}
