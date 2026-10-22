"""Клиенты, продукты, счета, предыстория операций (T-013), сигналы и инциденты истории для матрицы покрытия (T-016)."""

from __future__ import annotations

import datetime as dt
import hashlib
import random
from typing import Any

import psycopg
from scripts.seed.common import J, log
from scripts.seed.textgen import TextGen

FIRST_F = [
    "Анна",
    "Мария",
    "Елена",
    "Ольга",
    "Наталья",
    "Ирина",
    "Татьяна",
    "Светлана",
    "Юлия",
    "Екатерина",
    "Галина",
    "Людмила",
    "Валентина",
    "Алина",
    "Дарья",
    "Ксения",
    "Виктория",
    "Полина",
    "Арина",
    "Вера",
]
FIRST_M = [
    "Александр",
    "Дмитрий",
    "Максим",
    "Сергей",
    "Андрей",
    "Алексей",
    "Артём",
    "Илья",
    "Кирилл",
    "Михаил",
    "Никита",
    "Владимир",
    "Николай",
    "Роман",
    "Егор",
    "Иван",
    "Денис",
    "Евгений",
    "Павел",
    "Олег",
]
LAST = [
    "Иванов",
    "Смирнов",
    "Кузнецов",
    "Попов",
    "Васильев",
    "Петров",
    "Соколов",
    "Михайлов",
    "Новиков",
    "Фёдоров",
    "Морозов",
    "Волков",
    "Алексеев",
    "Лебедев",
    "Семёнов",
    "Егоров",
    "Павлов",
    "Козлов",
    "Степанов",
    "Николаев",
    "Орлов",
    "Андреев",
    "Макаров",
    "Никитин",
    "Захаров",
    "Зайцев",
    "Соловьёв",
    "Борисов",
    "Яковлев",
    "Григорьев",
    "Романов",
    "Воробьёв",
    "Сергеев",
    "Кузьмин",
    "Фролов",
    "Александров",
    "Дмитриев",
    "Королёв",
    "Гусев",
    "Киселёв",
]
NICK_PARTS = [
    "lena",
    "max",
    "dima",
    "kate",
    "sergey",
    "anna",
    "olga",
    "ivan",
    "nastya",
    "artem",
    "yulia",
    "pavel",
    "vera",
    "nikita",
    "dasha",
]
CITY_SUFFIX = {
    "Москва": "msk",
    "Санкт-Петербург": "spb",
    "Казань": "kzn",
    "Екатеринбург": "ekb",
    "Новосибирск": "nsk",
    "Воронеж": "vrn",
    "Самара": "smr",
    "Краснодар": "krd",
    "Ростов-на-Дону": "rnd",
    "Нижний Новгород": "nn",
}
CHANNELS_FOR_SIGNALS = [
    "social",
    "call",
    "chat",
    "email",
    "branch",
    "landing",
    "telegram_bot",
    "proactive",
    "review_portal",
    "voice_input",
    "branch_audio",
]
OP_TYPES = {
    "deposit": ["open_deposit", "top_up", "interest_payout"],
    "debit_card": ["payment", "qr_payment", "transfer", "atm_withdraw", "salary_in"],
    "credit": ["loan_payment"],
    "credit_card": ["payment", "qr_payment", "repayment"],
}
SYSTEM_PATH = {
    "open_deposit": ["mobile_app", "sub_deposits", "core_abs"],
    "top_up": ["mobile_app", "sub_deposits", "core_abs"],
    "interest_payout": ["sub_deposits", "core_abs"],
    "payment": ["processing", "sub_debit", "core_abs"],
    "qr_payment": ["mobile_app", "processing", "core_abs"],
    "transfer": ["mobile_app", "processing", "core_abs"],
    "atm_withdraw": ["processing", "core_abs"],
    "salary_in": ["core_abs"],
    "loan_payment": ["mobile_app", "sub_lending", "core_abs"],
    "repayment": ["mobile_app", "sub_lending", "core_abs"],
}
MERCHANTS = [
    "Пятёрочка",
    "Магнит",
    "Яндекс Такси",
    "Wildberries",
    "Ozon",
    "Кафе «Ромашка»",
    "АЗС Лукойл",
    "Аптека 36,6",
    "Ситилинк",
    "Перекрёсток",
    "Додо Пицца",
    "РЖД",
]


def luhn_invalid_last4(rnd: random.Random, bin_prefix: str = "220220") -> str:
    """Последние 4 цифры номера карты, невалидного по Луну (AGENTS §6.6): синтетика, не похожая на реальные карты."""
    while True:
        body = "".join(rnd.choice("0123456789") for _ in range(16 - len(bin_prefix)))
        num = bin_prefix + body
        s = 0
        for i, ch in enumerate(reversed(num)):
            d = int(ch)
            if i % 2 == 1:
                d = d * 2 - 9 if d * 2 > 9 else d * 2
            s += d
        if s % 10 != 0:
            return num[-4:]


def weighted(rnd: random.Random, items: dict[str, float]) -> str:
    r = rnd.random() * sum(items.values())
    acc = 0.0
    for k, v in items.items():
        acc += v
        if r < acc:
            return k
    return next(iter(items))


def seed_clients(cur: psycopg.Cursor[Any], rnd: random.Random, n_clients: int, sim_now: dt.datetime) -> None:
    existing = cur.execute("select count(*) from clients").fetchone()[0]
    if existing >= n_clients:
        log.info("clients_exist", count=existing)
        return
    segments = {r[0]: float(r[1]) for r in cur.execute("select code, population_share from segments").fetchall()}
    clv = {r[0]: (r[1], r[2]) for r in cur.execute("select code, clv_min_rub, clv_max_rub from segments").fetchall()}
    mix: dict[str, dict[str, float]] = {}
    for seg, pt, share in cur.execute(
        "select segment_code, psychotype_code, share from segment_psychotype_mix"
    ).fetchall():
        mix.setdefault(seg, {})[pt] = float(share)
    regions = cur.execute("select code, population from regions").fetchall()
    cities_by_region: dict[str, list[tuple[int, str, int]]] = {}
    for cid, rc, name, pop in cur.execute("select id, region_code, name_ru, population from cities").fetchall():
        cities_by_region.setdefault(rc, []).append((cid, name, pop))
    reg_weights = {r[0]: float(r[1]) for r in regions if r[0] in cities_by_region}
    # города-якоря демо-сценариев получают гарантированных клиентов
    anchors = [
        "Казань",
        "Новосибирск",
        "Екатеринбург",
        "Воронеж",
        "Самара",
        "Москва",
        "Санкт-Петербург",
        "Краснодар",
        "Ростов-на-Дону",
        "Нижний Новгород",
    ]
    tg = TextGen(rnd.randrange(10**9))
    for i in range(existing + 1, n_clients + 1):
        seg = weighted(rnd, segments)
        pt = weighted(rnd, mix[seg])
        if i <= len(anchors) * 8:
            city_name = anchors[(i - 1) % len(anchors)]
            row = cur.execute(
                "select id, region_code, population from cities where name_ru = %s order by population desc limit 1",
                (city_name,),
            ).fetchone()
            cid, rc = row[0], row[1]
        else:
            rc = weighted(rnd, reg_weights)
            cands = cities_by_region[rc]
            cid, city_name, _ = rnd.choices(cands, weights=[max(c[2], 1000) for c in cands])[0]
        female = rnd.random() < 0.53
        fn = rnd.choice(FIRST_F if female else FIRST_M)
        ln = rnd.choice(LAST) + ("а" if female else "")
        display = f"{fn} {ln[0]}."
        handle = None
        if rnd.random() < 0.6:
            handle = {
                "platform": rnd.choice(["vk", "telegram", "ok"]),
                "handle": f"@{rnd.choice(NICK_PARTS)}_{CITY_SUFFIX.get(city_name, hashlib.sha1(city_name.encode()).hexdigest()[:3])}{rnd.randrange(10, 99)}",
            }
        phone_masked = f"+7 9{rnd.randrange(10, 99)} *** {rnd.randrange(10, 99)}-{rnd.randrange(10, 99)}"
        lo, hi = clv[seg]
        clv_est = int(rnd.triangular(lo, hi, (lo + hi) / 3))
        cur.execute(
            "insert into clients (display_name, segment_code, psychotype_code, region_code, city_id, contacts, consents, churn_risk, clv_estimate_rub, activity_baseline, social_handles, refunds_30d) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0) returning id",
            (
                display,
                seg,
                pt,
                rc,
                cid,
                J(
                    {
                        "phone_masked": phone_masked,
                        "email_masked": f"{fn[0].lower()}***@example.org",
                        "preferred": weighted(rnd, {"chat": 0.5, "call": 0.25, "email": 0.15, "telegram_bot": 0.1}),
                    }
                ),
                J({"marketing": rnd.random() < 0.7, "proactive": True}),
                rnd.randrange(0, 25),
                clv_est,
                round(rnd.uniform(2, 30), 2),
                J([handle] if handle else []),
            ),
        )
        row = cur.fetchone()
        if not row:
            continue
        client_id = row[0]
        # продукты: у всех дебетовая карта (в youth — 90 %), вклады/кредиты по сегменту
        products = ["debit_card"] if seg != "youth" or rnd.random() < 0.9 else []
        if (
            rnd.random()
            < {
                "mass": 0.3,
                "salary": 0.35,
                "social": 0.5,
                "youth": 0.1,
                "premium": 0.7,
                "vip": 0.85,
                "ultra_vip": 0.95,
            }[seg]
        ):
            products.append("deposit")
        if (
            rnd.random()
            < {"mass": 0.25, "salary": 0.3, "social": 0.1, "youth": 0.15, "premium": 0.3, "vip": 0.2, "ultra_vip": 0.1}[
                seg
            ]
        ):
            products.append("credit")
        if (
            rnd.random()
            < {"mass": 0.3, "salary": 0.35, "social": 0.1, "youth": 0.35, "premium": 0.5, "vip": 0.6, "ultra_vip": 0.5}[
                seg
            ]
        ):
            products.append("credit_card")
        opened_base = sim_now - dt.timedelta(days=rnd.randrange(30, 1500))
        for p in products:
            terms: dict[str, Any] = {}
            last4 = None
            if p in ("debit_card", "credit_card"):
                last4 = luhn_invalid_last4(rnd)
                terms = (
                    {"cashback_pct": 1.0}
                    if p == "debit_card"
                    else {"limit_rub": rnd.choice([50000, 100000, 200000, 500000]), "grace_days": 120, "rate_pct": 29.9}
                )
            elif p == "deposit":
                promo = rnd.random() < 0.2
                terms = {
                    "amount_rub": rnd.choice([100000, 250000, 400000, 750000, 1200000]),
                    "term_months": rnd.choice([3, 6, 12]),
                    "rate_pct": 14.0 if promo else 9.5,
                    "promo_code": "PROMO-DEP-14" if promo else None,
                }
            elif p == "credit":
                terms = {
                    "amount_rub": rnd.choice([150000, 300000, 600000, 1200000]),
                    "rate_pct": 19.9,
                    "insurance": rnd.random() < 0.4,
                    "monthly_payment_rub": rnd.choice([8900, 15400, 23700, 41200]),
                }
            cur.execute(
                "insert into client_products (client_id, product_code, status, terms, card_last4, opened_sim) values (%s, %s, 'active', %s, %s, %s) returning id",
                (client_id, p, J(terms), last4, opened_base + dt.timedelta(days=rnd.randrange(0, 30))),
            )
            cp_id = cur.fetchone()[0]
            if p in ("debit_card", "deposit", "credit_card"):
                bal = (
                    terms.get("amount_rub", rnd.choice([1200, 5400, 18300, 47000, 120000]))
                    if p != "credit_card"
                    else -rnd.choice([0, 3400, 12800, 45000])
                )
                cur.execute(
                    "insert into accounts (client_id, product_id, number_masked, currency, balance, status) values (%s, %s, %s, 'RUB', %s, 'active')",
                    (client_id, cp_id, f"408** **** {last4 or rnd.randrange(1000, 9999)}", bal),
                )
        if i % 500 == 0:
            log.info("clients_progress", done=i)
    log.info(
        "clients_done",
        total=cur.execute("select count(*) from clients").fetchone()[0],
        with_handles=cur.execute(
            "select count(*) from clients where jsonb_array_length(social_handles) > 0"
        ).fetchone()[0],
    )
    _ = tg


def ensure_history_run(cur: psycopg.Cursor[Any], seed: int, sim_now: dt.datetime, profile: str) -> int:
    row = cur.execute(
        "select id from sim_runs where kind = 'baseline' and label = 'История 14 дней (сид)' limit 1"
    ).fetchone()
    if row:
        return int(row[0])
    cur.execute(
        "insert into sim_runs (kind, label, seed, settings_snapshot, status, started_sim, finished_sim, summary) values ('baseline', 'История 14 дней (сид)', %s, %s, 'completed', %s, %s, %s) returning id",
        (seed, J({"profile": profile}), sim_now - dt.timedelta(days=14), sim_now, J({"source": "seed"})),
    )
    return int(cur.fetchone()[0])


def seed_operations(
    cur: psycopg.Cursor[Any], rnd: random.Random, run_id: int, sim_now: dt.datetime, per_client: int = 6
) -> None:
    if cur.execute("select count(*) from operations where run_id = %s", (run_id,)).fetchone()[0]:
        return
    rows = cur.execute(
        "select cp.client_id, cp.product_code, cp.card_last4 from client_products cp where cp.status = 'active'"
    ).fetchall()
    qr_total = qr_fee = 0
    for client_id, product, _last4 in rows:
        for _ in range(rnd.randrange(max(1, per_client - 3), per_client + 3)):
            op = rnd.choice(OP_TYPES[product])
            started = sim_now - dt.timedelta(minutes=rnd.randrange(0, 14 * 24 * 60))
            amount = {
                "deposit": rnd.choice([5000, 10000, 50000, 100000]),
                "debit_card": rnd.choice([190, 450, 890, 1290, 3200, 5800, 12400]),
                "credit": rnd.choice([8900, 15400, 23700]),
                "credit_card": rnd.choice([990, 2300, 7800, 15600]),
            }[product]
            method = (
                "qr_sbp"
                if op == "qr_payment"
                else "card"
                if op in ("payment",)
                else "transfer"
                if op == "transfer"
                else "cash"
                if op == "atm_withdraw"
                else "online"
            )
            fee = 0.0
            error = None
            status = "success"
            if op == "qr_payment":
                qr_total += 1
                if rnd.random() < 0.04:  # 3–5 % QR-операций с ошибочной комиссией (сценарий 8)
                    fee = round(amount * rnd.choice([0.01, 0.015]) + rnd.choice([0, 90, 150]), 2) or 150.0
                    error = "PROC-QR-FEE-CHARGED"
                    qr_fee += 1
            elif rnd.random() < 0.03:
                status = "failed"
                error = {
                    "deposit": "DEP-TIMEOUT-503",
                    "debit_card": rnd.choice(["PROC-DOUBLE-DEBIT", "APP-CRASH-PAY", "AF-FALSE-BLOCK"]),
                    "credit": "LEND-PAYMENT-NOT-POSTED",
                    "credit_card": "CC-GRACE-MISCALC",
                }[product]
            cur.execute(
                "insert into operations (run_id, client_id, product_code, op_type, system_path, amount_rub, method, merchant, fee_amount, status, error_code, started_sim, finished_sim) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    run_id,
                    client_id,
                    product,
                    op,
                    SYSTEM_PATH[op],
                    amount,
                    method,
                    rnd.choice(MERCHANTS) if op in ("payment", "qr_payment") else None,
                    fee,
                    status,
                    error,
                    started,
                    started + dt.timedelta(seconds=rnd.randrange(1, 40)),
                ),
            )
    log.info(
        "operations_done",
        total=cur.execute("select count(*) from operations where run_id = %s", (run_id,)).fetchone()[0],
        qr=qr_total,
        qr_fee=qr_fee,
        qr_fee_share=round(qr_fee / max(qr_total, 1), 3),
    )


def seed_history_signals(
    cur: psycopg.Cursor[Any],
    rnd: random.Random,
    run_id: int,
    sim_now: dt.datetime,
    n_signals: int,
    n_incidents: int,
    seed: int,
) -> None:
    """История сигналов и инцидентов: гарантирует матрицу покрытия (тип × продукт × канал ≥ 1, ячейка SLA ≥ 5 инцидентов в разных статусах)."""
    if cur.execute("select count(*) from signals where run_id = %s", (run_id,)).fetchone()[0]:
        return
    tg = TextGen(seed)
    clients = cur.execute(
        "select c.id, c.psychotype_code, ci.name_ru, c.region_code, c.segment_code from clients c join cities ci on ci.id = c.city_id order by c.id"
    ).fetchall()
    cards = {
        r[0]: r[1]
        for r in cur.execute(
            "select client_id, card_last4 from client_products where card_last4 is not null"
        ).fetchall()
    }
    combos = [(st, p, ch) for st, p in tg.all_combinations() for ch in CHANNELS_FOR_SIGNALS]
    rnd.shuffle(combos)
    plan = combos[:]
    while len(plan) < n_signals:
        plan.append(rnd.choice(combos))
    team_by_type = {
        "tech_fault": "team_processing",
        "client_error": "team_contact_center",
        "tariff_terms": "team_debit",
        "service_quality": "team_cx",
        "fraud_suspicion": "team_antifraud",
        "legal_regulatory": "team_compliance",
        "info_request": "team_contact_center",
        "gratitude": "team_cx",
        "suggestion": "team_cx",
        "churn": "team_cx",
    }
    sla = {
        (r[0], r[1]): (r[2], r[3], r[4])
        for r in cur.execute(
            "select complexity, criticality, fix_days, report_days, take_hours from sla_matrix"
        ).fetchall()
    }
    cells = [(c, k) for c in ("easy", "medium", "hard") for k in ("high", "medium", "low")]
    incident_plan: list[tuple[str, str]] = cells * 5
    while len(incident_plan) < n_incidents:
        incident_plan.append(rnd.choice(cells))
    rnd.shuffle(incident_plan)
    statuses_cycle = [
        "closed",
        "closed",
        "resolved",
        "in_progress",
        "routed",
        "awaiting_client",
        "closed",
        "escalated",
        "verifying",
        "new",
    ]
    styles = {"plain": 0, "sarcasm": 0, "slang": 0, "typos": 0, "caps": 0}
    inc_i = 0
    for n, (st, product, ch) in enumerate(plan):
        client = rnd.choice(clients)
        client_id, pt, city, region, seg = client
        identified = (
            ch not in ("social", "landing", "review_portal", "voice_input", "branch_audio") or rnd.random() < 0.3
        )
        g = tg.generate(st, product, psychotype=pt, city=city, card4=cards.get(client_id, "4512"))
        styles[g.style] += 1
        received = sim_now - dt.timedelta(minutes=rnd.randrange(60, 14 * 24 * 60))
        creates_incident = st not in ("info_request", "gratitude", "suggestion", "client_error") and inc_i < len(
            incident_plan
        )
        classification = {
            "signal_type": st,
            "product": product,
            "criticality": incident_plan[inc_i][1] if creates_incident else "low",
            "sentiment": g.gold.get("sentiment", "neutral"),
            "negativity": g.gold.get("negativity", 30),
            "flags": g.gold.get("flags", []),
            "system": g.gold.get("system"),
            "error_code": g.gold.get("error_code"),
            "llm_source": "seed",
            "style": g.style,
        }
        cur.execute(
            "insert into signals (run_id, channel_code, channel_subtype, client_id, external_contact, text, received_sim, status, origin, sentiment, classification, geo) values (%s, %s, %s, %s, %s, %s, %s, %s, 'sim', %s, %s, %s) returning id",
            (
                run_id,
                ch,
                None,
                client_id if identified else None,
                None if identified else J({"platform": "vk", "handle": f"@user_{n}"}),
                g.text,
                received,
                "closed"
                if creates_incident
                else rnd.choice(
                    ["answered", "closed", "noise" if st == "suggestion" and rnd.random() < 0.1 else "answered"]
                ),
                classification["sentiment"],
                J(classification),
                J({"region_code": region, "city": city}),
            ),
        )
        signal_id = cur.fetchone()[0]
        if not creates_incident:
            continue
        complexity, criticality = incident_plan[inc_i]
        inc_i += 1
        fix_days, report_days, take_hours = sla[(complexity, criticality)]
        due = received + dt.timedelta(days=fix_days * 7 / 5)  # рабочие дни ≈ календарные × 1.4
        status = statuses_cycle[inc_i % len(statuses_cycle)]
        resolved = (
            received + dt.timedelta(days=fix_days * rnd.uniform(0.3, 1.6)) if status in ("closed", "resolved") else None
        )
        breached = bool(resolved and resolved > due) or (status not in ("closed", "resolved") and due < sim_now)
        outcome = None
        if status in ("closed", "resolved"):
            outcome = "closed_late" if breached else rnd.choice(["closed_in_sla", "closed_in_sla_with_gift"])
        elif status == "rejected":
            outcome = "rejected"
        else:
            outcome = "open"
        inc_type = st if st != "churn" else "account_closure"
        team = (
            team_by_type[st]
            if not g.gold.get("error_code")
            else {
                "PROC-QR-FEE-CHARGED": "team_processing",
                "PROC-DOUBLE-DEBIT": "team_processing",
                "DEP-TIMEOUT-503": "team_deposits",
                "PROMO-RATE-MISMATCH": "team_promo",
                "NOTIF-DELAY": "team_notifications",
                "APP-LOGIN-FAIL": "team_front",
                "APP-CRASH-PAY": "team_front",
                "WEB-SESSION-DROP": "team_front",
                "CC-QUEUE-OVERFLOW": "team_contact_center",
                "AF-FALSE-BLOCK": "team_antifraud",
                "LEND-PAYMENT-NOT-POSTED": "team_lending",
                "CC-GRACE-MISCALC": "team_lending",
                "DEBIT-CASHBACK-MISS": "team_debit",
            }.get(g.gold["error_code"], team_by_type[st])
        )
        cur.execute(
            "insert into incidents (run_id, title, incident_type, product_code, system_code, error_code, team_code, complexity, criticality, priority, status, flags, region_code, primary_client_id, created_by, created_sim, sla_due_sim, take_due_sim, report_due_sims, taken_sim, resolved_sim, closed_sim, sla_breached, outcome_class, routing_status) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'agent', %s, %s, %s, %s, %s, %s, %s, %s, %s, 'routed') returning id",
            (
                run_id,
                g.text[:70].rstrip(" ,.!") + ("…" if len(g.text) > 70 else ""),
                inc_type,
                product,
                g.gold.get("system"),
                g.gold.get("error_code"),
                team,
                complexity,
                criticality,
                {"high": 1, "medium": 2, "low": 3}[criticality],
                status,
                g.gold.get("flags", []),
                region,
                client_id if identified else None,
                received,
                due,
                received + dt.timedelta(hours=take_hours),
                [received + dt.timedelta(days=d * 7 / 5) for d in report_days],
                received + dt.timedelta(hours=take_hours * rnd.uniform(0.2, 1.3)) if status != "new" else None,
                resolved,
                resolved + dt.timedelta(hours=2) if resolved and status == "closed" else None,
                breached,
                outcome,
            ),
        )
        incident_id = cur.fetchone()[0]
        cur.execute(
            "insert into incident_signals (incident_id, signal_id, link_type, linked_sim) values (%s, %s, 'primary', %s) on conflict do nothing",
            (incident_id, signal_id, received),
        )
        cur.execute(
            "insert into incident_status_history (incident_id, from_status, to_status, actor_type, actor_ref, reason, changed_sim) values (%s, null, %s, 'agent', 'seed', 'история (сид)', %s)",
            (incident_id, status, received),
        )
    total = cur.execute("select count(*) from signals where run_id = %s", (run_id,)).fetchone()[0]
    hard = sum(v for k, v in styles.items() if k != "plain")
    log.info("history_done", signals=total, incidents=inc_i, hard_share=round(hard / max(total, 1), 3), styles=styles)
