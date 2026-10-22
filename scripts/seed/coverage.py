"""Матрица покрытия (ТЗ 4.4, AGENTS §6.6): тип × продукт × канал ≥ 1 сигнал; ячейка SLA ≥ 5 инцидентов → settings.coverage."""

from __future__ import annotations

from typing import Any

import psycopg
from scripts.seed.common import log, set_setting


def compute_coverage(cur: psycopg.Cursor[Any], run_id: int) -> dict[str, Any]:
    types = [r[0] for r in cur.execute("select code from signal_types").fetchall()]
    products = [r[0] for r in cur.execute("select code from products").fetchall()]
    channels = [r[0] for r in cur.execute("select code from channels").fetchall()]
    have = {
        (r[0], r[1], r[2]): int(r[3])
        for r in cur.execute(
            "select classification->>'signal_type', classification->>'product', channel_code, count(*) from signals where run_id = %s group by 1, 2, 3",
            (run_id,),
        ).fetchall()
    }
    missing = [f"{t}×{p}×{c}" for t in types for p in products for c in channels if (t, p, c) not in have]
    sla_have = {
        (r[0], r[1]): int(r[2])
        for r in cur.execute(
            "select complexity, criticality, count(*) from incidents where run_id = %s group by 1, 2", (run_id,)
        ).fetchall()
    }
    sla_cells = {
        f"{c}×{k}": sla_have.get((c, k), 0) for c in ("easy", "medium", "hard") for k in ("high", "medium", "low")
    }
    statuses = {
        r[0]: int(r[1])
        for r in cur.execute(
            "select status, count(*) from incidents where run_id = %s group by 1", (run_id,)
        ).fetchall()
    }
    styles = {
        r[0]: int(r[1])
        for r in cur.execute(
            "select coalesce(classification->>'style', 'plain'), count(*) from signals where run_id = %s group by 1",
            (run_id,),
        ).fetchall()
    }
    total = sum(styles.values()) or 1
    cov = {
        "run_id": run_id,
        "signal_combos_total": len(types) * len(products) * len(channels),
        "signal_combos_covered": len(types) * len(products) * len(channels) - len(missing),
        "signal_combos_missing": missing[:50],
        "sla_cells": sla_cells,
        "sla_cells_ok": all(v >= 5 for v in sla_cells.values()),
        "incident_statuses": statuses,
        "hard_text_share": round(sum(v for k, v in styles.items() if k != "plain") / total, 3),
        "styles": styles,
    }
    set_setting(cur, "coverage", cov)
    log.info(
        "coverage",
        covered=cov["signal_combos_covered"],
        total=cov["signal_combos_total"],
        sla_ok=cov["sla_cells_ok"],
        hard_share=cov["hard_text_share"],
    )
    return cov
