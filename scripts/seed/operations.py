"""T-017: детерминированная 14-дневная предыстория, потоковый COPY без накопления операций."""

from __future__ import annotations

import argparse
import bisect
import datetime as dt
import itertools
import json
import math
import random
import sys
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import psycopg

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.seed.common import ROOT, load_yaml, log

# Синтетические мерчанты, не названия реальных организаций.
MERCHANTS = ("Магазин «Рассвет»", "Кафе «Ромашка»", "Сервис «Маршрут»", "Аптека «Забота»")
COLUMNS = "run_id,client_id,product_code,op_type,system_path,amount_rub,method,merchant,fee_amount,status,error_code,started_sim,finished_sim"


def load_config() -> dict[str, Any]:
    config: dict[str, Any] = load_yaml("op_paths.yaml")
    systems = {row["code"] for row in load_yaml("systems.yaml")["systems"]}
    if config["history_days"] != 14:
        raise ValueError("history_days must be 14")
    for name, length in (("hour_weights", 24), ("weekday_weights", 7)):
        weights = config[name]
        if len(weights) != length or any(not math.isfinite(w) or w <= 0 for w in weights):
            raise ValueError(f"invalid {name}")
    for name in ("failure_probability", "qr_share", "qr_fee_probability"):
        if not 0 <= config[name] <= 1:
            raise ValueError(f"invalid {name}")
    schema = json.loads((ROOT / "contracts/events/sim/op.schema.json").read_text())
    allowed_ops = schema["properties"]["op_type"]["enum"]
    known_errors = {row["code"] for row in load_yaml("error_codes.yaml")["error_codes"]}
    if not config["failure_codes"] or not set(config["failure_codes"]) <= known_errors:
        raise ValueError("invalid technical failure codes")
    common = json.loads((ROOT / "contracts/events/common.schema.json").read_text())["$defs"]
    if set(config["products"]) != set(common["product"]["enum"]):
        raise ValueError("product configuration must match contract")
    if set(config["segment_weights"]) != set(common["segment"]["enum"]):
        raise ValueError("segment configuration must match contract")
    if set(config["operations_per_client"]) != {"lite", "demo", "stress"}:
        raise ValueError("missing history profile")
    for op, path in config["system_paths"].items():
        if op not in allowed_ops or not path or not set(path) <= systems:
            raise ValueError(f"invalid operation path: {op}")
    for product in config["products"].values():
        if any(not math.isfinite(product[key]) or product[key] <= 0 for key in ("amount_median_rub", "amount_sigma")):
            raise ValueError("invalid amount distribution")
        if not product["op_weights"]:
            raise ValueError("empty operation distribution")
        for op, weight in product["op_weights"].items():
            if op not in config["system_paths"] or not math.isfinite(weight) or weight <= 0:
                raise ValueError(f"invalid operation path: {op}")
    if any(not math.isfinite(weight) or weight <= 0 for weight in config["segment_weights"].values()):
        raise ValueError("invalid segment intensity")
    if any(not isinstance(count, int) or count <= 0 for count in config["operations_per_client"].values()):
        raise ValueError("invalid operation count")
    return config


def history_slots(now: dt.datetime, config: dict[str, Any]) -> tuple[list[dt.datetime], list[float]]:
    """Часовые интервалы с учётом неполных граничных часов; локальное сим-время."""
    if now.tzinfo is None:
        raise ValueError("sim_time must be timezone-aware")
    start = now - dt.timedelta(days=config["history_days"])
    cursor = start
    slots, weights = [], []
    while cursor < now:
        end = min(cursor.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1), now)
        slots.append(cursor)
        weights.append(
            config["hour_weights"][cursor.hour]
            * config["weekday_weights"][cursor.weekday()]
            * (end - cursor).total_seconds()
        )
        cursor = end
    return slots, list(itertools.accumulate(weights))


def operation_rows(
    clients: Sequence[tuple[int, str, Sequence[str]]],
    rnd: random.Random,
    run_id: int,
    sim_now: dt.datetime,
    config: dict[str, Any],
    errors: Sequence[tuple[str, str, str | None]],
    *,
    profile: str = "lite",
    per_client: int | None = None,
) -> Iterator[tuple[Any, ...]]:
    slots, cumulative = history_slots(sim_now, config)
    base = config["operations_per_client"][profile] if per_client is None else per_client
    if base < 1:
        raise ValueError("per_client must be positive")
    total_weight = sum(config["segment_weights"][segment] for _, segment, _ in clients)
    normalizer = len(clients) / total_weight if total_weight else 1
    targets = [base * config["segment_weights"][segment] * normalizer for _, segment, _ in clients]
    counts = [math.floor(target) for target in targets]
    # Largest remainders preserve segment ratios and the exact configured total.
    remainder = base * len(clients) - sum(counts)
    order = sorted(range(len(clients)), key=lambda index: (-(targets[index] - counts[index]), clients[index][0]))
    for index in order[:remainder]:
        counts[index] += 1
    for (client_id, _segment, products), count in zip(clients, counts, strict=True):
        if not products:
            raise ValueError(f"client {client_id} has no active products")
        for _ in range(count):
            product = rnd.choice(products)
            product_config = config["products"][product]
            ops = product_config["op_weights"]
            op = rnd.choices(list(ops), weights=list(ops.values()))[0]
            path = config["system_paths"][op]
            slot = slots[bisect.bisect_right(cumulative, rnd.random() * cumulative[-1])]
            end = min(slot.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1), sim_now)
            started = slot + dt.timedelta(seconds=rnd.random() * (end - slot).total_seconds())
            amount = (
                None
                if op in ("login", "statement", "limit_request")
                else round(
                    min(
                        rnd.lognormvariate(
                            math.log(product_config["amount_median_rub"]), product_config["amount_sigma"]
                        ),
                        999_999_999,
                    ),
                    2,
                )
            )
            method = (
                ("qr_sbp" if rnd.random() < config["qr_share"] else "card")
                if op == "card_payment"
                else "transfer"
                if op == "transfer"
                else "online"
            )
            status, error, fee = "success", None, 0.0
            if rnd.random() < config["failure_probability"]:
                eligible = [
                    code
                    for code, system, code_product in errors
                    if code in config["failure_codes"] and system in path and code_product in (product, None)
                ]
                if not eligible:
                    raise ValueError(f"no compatible error code for {product}/{op}")
                status, error = "failed", rnd.choice(eligible)
            elif method == "qr_sbp" and rnd.random() < config["qr_fee_probability"]:
                # Сохраняется отдельная модель ошибочной QR-комиссии BRD, не политика refund.
                fee = round((amount or 0) * rnd.choice([0.01, 0.015]) + rnd.choice([0, 90, 150]), 2) or 150.0
                error = "PROC-QR-FEE-CHARGED"
            yield (
                run_id,
                client_id,
                product,
                op,
                path,
                amount,
                method,
                rnd.choice(MERCHANTS) if op == "card_payment" else None,
                fee,
                status,
                error,
                started,
                min(started + dt.timedelta(seconds=rnd.randrange(1, 40)), sim_now),
            )


def seed_operations(
    cur: psycopg.Cursor[Any],
    rnd: random.Random,
    run_id: int,
    sim_now: dt.datetime,
    per_client: int | None = None,
    *,
    profile: str = "lite",
) -> None:
    if cur.execute("select exists(select 1 from operations where run_id=%s)", (run_id,)).fetchone()[0]:
        return
    config = load_config()
    clients = cur.execute(
        "select c.id,c.segment_code,array_agg(cp.product_code order by cp.id) from clients c join client_products cp on cp.client_id=c.id and cp.status='active' group by c.id,c.segment_code order by c.id"
    ).fetchall()
    errors = cur.execute("select code,system_code,product_code from error_codes order by code").fetchall()
    started = time.perf_counter()
    count = failed = qr = qr_fee = 0
    with cur.copy(f"COPY operations ({COLUMNS}) FROM STDIN") as copy:
        for row in operation_rows(
            clients, rnd, run_id, sim_now, config, errors, profile=profile, per_client=per_client
        ):
            copy.write_row(row)
            count += 1
            failed += row[9] == "failed"
            qr += row[6] == "qr_sbp"
            qr_fee += row[8] > 0
    log.info(
        "operations_done",
        total=count,
        failed=failed,
        qr=qr,
        qr_fee=qr_fee,
        seconds=round(time.perf_counter() - started, 3),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("lite", "demo", "stress"), default="lite")
    parser.add_argument(
        "--check", action="store_true", required=True, help="только проверка конфигурации; БД не изменяется"
    )
    parser.parse_args()
    config = load_config()
    log.info(
        "operation_config_ok",
        history_days=config["history_days"],
        operations_per_client=config["operations_per_client"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
