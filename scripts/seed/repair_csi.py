"""T-272: добавочный ремонт CSI baseline. По умолчанию только план; запись — с --apply."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import psycopg

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
for candidate in (ROOT / "backend", Path("/app")):
    if (candidate / "app").is_dir():
        sys.path.insert(0, str(candidate))
        break

from app.ingest.normalizer import from_csi  # noqa: E402
from app.ingest.sync_bridge import create_signal_sync  # noqa: E402
from app.sim.textgen import TextGen  # noqa: E402

from scripts.seed.common import J, connect, get_setting, log, set_setting  # noqa: E402
from scripts.seed.coverage import compute_coverage  # noqa: E402


class RepairError(ValueError):
    pass


def repair(conn: psycopg.Connection[Any], *, apply: bool = False) -> dict[str, Any]:
    if conn.autocommit:
        raise RepairError("нужна общая транзакция без autocommit")
    with conn.cursor() as cur:
        if apply:
            cur.execute("select pg_advisory_xact_lock(272,0)")
        meta = get_setting(cur, "seed_done")
        if not isinstance(meta, dict) or not meta.get("run_id"):
            raise RepairError("нет seed_done.run_id; автоматический seed не выполняется")
        rid = int(meta["run_id"])
        row = cur.execute("select kind,status,finished_sim from sim_runs where id=%s", (rid,)).fetchone()
        if not row or row[0] != "baseline" or row[1] != "completed" or row[2] is None:
            raise RepairError("ремонт разрешён только завершённому историческому baseline")
        before = compute_coverage(cur, rid, persist=False)
        types = [x[0] for x in cur.execute("select code from signal_types order by code").fetchall()]
        products = [x[0] for x in cur.execute("select code from products order by code").fetchall()]
        have = set(
            cur.execute(
                "select distinct classification->>'signal_type',classification->>'product' from signals where run_id=%s and channel_code='csi_survey'",
                (rid,),
            ).fetchall()
        )
        missing = [(t, p) for t in types for p in products if (t, p) not in have]
        if not before["sla_cells_ok"] or before["signal_combos_total"] - before["signal_combos_covered"] != len(
            missing
        ):
            raise RepairError("есть пробелы вне CSI или SLA; этот ремонт их не изменяет")
        report = {
            "run_id": rid,
            "apply": apply,
            "before": before["signal_combos_covered"],
            "total": before["signal_combos_total"],
            "missing_csi": [f"{t}×{p}" for t, p in missing],
            "added": 0,
        }
        if not apply or not missing:
            return {**report, "after": report["before"]}
        branch = cur.execute("select code from branches order by code limit 1").fetchone()
        if not branch:
            raise RepairError("нет ВСП для исторического CSI")
        # Сид-история заканчивается утром; выбираем предыдущий рабочий день, 17:00 МСК.
        stamp = row[2].astimezone(ZoneInfo("Europe/Moscow")) - dt.timedelta(days=1)
        while stamp.weekday() >= 5:
            stamp -= dt.timedelta(days=1)
        stamp = stamp.replace(hour=17, minute=0, second=0, microsecond=0)
        used = {
            x[0]
            for x in cur.execute(
                "select csi_no from csi_responses where csi_no like 'CSI-8%' union select external_id from ingest_messages where source_code='csi' and external_id like 'CSI-8%'"
            ).fetchall()
        }
        cur.execute(
            "insert into ingest_sources(code,kind,channel_code,enabled,is_external) values('csi','file','csi_survey',false,false) on conflict(code) do nothing"
        )
        textgen = TextGen(int(meta.get("seed", 42)))
        number = 800000
        ids = []
        for signal_type, product in missing:
            while f"CSI-{number:06d}" in used and number <= 899999:
                number += 1
            if number > 899999:
                raise RepairError("исчерпан резерв CSI-800000..899999")
            csi_no = f"CSI-{number:06d}"
            used.add(csi_no)
            generated = textgen.generate(signal_type, product)
            msg = from_csi(
                {
                    "csi_no": csi_no,
                    "complaint_ru": generated.text,
                    "branch_code": branch[0],
                    "received_at": stamp.isoformat(),
                    "products": [product],
                }
            )
            msg["origin"] = "sim"
            msg["meta"]["historical_seed_repair"] = {
                "task": "T-272",
                "run_id": rid,
                "signal_type": signal_type,
                "product": product,
            }
            result = create_signal_sync(conn, msg, run_id=rid, sim_time=stamp)
            if result["status"] != "accepted":
                raise RepairError(f"CSI не добавлен: {result['status']}; старые строки не изменяются")
            sid = result["signal_id"]
            red = cur.execute("select red_words from signals where id=%s", (sid,)).fetchone()[0]
            classification = {
                "signal_type": signal_type,
                "product": product,
                "criticality": "high" if red else "low",
                "sentiment": generated.gold.get("sentiment", "neutral"),
                "negativity": generated.gold.get("negativity", 30),
                "flags": list(dict.fromkeys([*generated.gold.get("flags", []), *(["red_word"] if red else [])])),
                "style": generated.style,
                "llm_source": "seed",
            }
            if red:
                classification["red_words"] = red
            cur.execute(
                "update signals set status='closed',classification=%s,sentiment=%s where id=%s",
                (J(classification), classification["sentiment"], sid),
            )
            ids.append(sid)
        after = compute_coverage(cur, rid, persist=False)
        if after["signal_combos_missing"] or after["signal_combos_covered"] != after["signal_combos_total"]:
            raise RepairError("проверка покрытия не прошла; транзакция должна быть отменена")
        set_setting(cur, "coverage", after)
        return {**report, "added": len(ids), "after": after["signal_combos_covered"], "signal_ids": ids}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true", help="машиночитаемый результат для baseline.restore")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()
    try:
        with connect(args.database_url) as conn:
            result = repair(conn, apply=args.apply)
        log.info("csi_history_repair", **result)
        if args.json:
            sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        return 0
    except RepairError as exc:
        log.error("csi_history_repair_failed", reason=str(exc))
        if args.json:
            sys.stdout.write(json.dumps({"error": str(exc)}, ensure_ascii=False) + "\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
