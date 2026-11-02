"""Генераторы событий (ТЗ 4.2; T-033 операции, T-035 ошибки клиентов, T-016/T-034 сбои и сигналы) — минимум для демо.

Все генераторы пишут в таблицы домена и публикуют события через EventBus; интенсивности — на сим-час, масштабируются
к числу клиентов профиля (ТЗ рассчитано на demo = 5 000 клиентов)."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from typing import Any

import psycopg

from app.abs import service as abs_svc
from app.feed import service as feed_svc
from app.logging import get_logger
from app.sim.events import EventBus, dumps
from app.sim.rng import SimRng
from app.sim.sla import SlaEngine
from app.sim.teams import TeamEmulator
from app.sim.textgen import TextGen

log = get_logger(__name__)

DEFAULT_INTENSITIES: dict[str, float] = {"op": 450.0, "fault": 1.0, "client_error": 30.0, "signal_noise": 6.0}
OP_TYPES: dict[str, dict[str, float]] = {
    "deposit": {"deposit_open": 0.25, "deposit_topup": 0.5, "deposit_close": 0.05, "statement": 0.2},
    "debit_card": {"card_payment": 0.6, "transfer": 0.2, "login": 0.12, "statement": 0.06, "card_issue": 0.02},
    "credit": {"loan_payment": 0.6, "statement": 0.3, "limit_request": 0.1},
    "credit_card": {"card_payment": 0.6, "loan_payment": 0.2, "limit_request": 0.1, "login": 0.1},
}
SYSTEM_PATH: dict[str, list[str]] = {
    "deposit_open": ["mobile_app", "promo_engine", "sub_deposits", "core_abs", "notification_gw"],
    "deposit_topup": ["mobile_app", "sub_deposits", "core_abs"],
    "deposit_close": ["mobile_app", "sub_deposits", "core_abs"],
    "card_payment": ["processing", "sub_debit", "core_abs", "notification_gw"],
    "transfer": ["mobile_app", "antifraud", "processing", "core_abs"],
    "loan_payment": ["mobile_app", "sub_lending", "core_abs"],
    "card_issue": ["mobile_app", "sub_debit"],
    "limit_request": ["mobile_app", "sub_lending"],
    "promo_apply": ["mobile_app", "promo_engine"],
    "login": ["mobile_app"],
    "statement": ["web_bank", "core_abs"],
}
AMOUNTS: dict[str, list[int]] = {
    "deposit": [5000, 10000, 50000, 100000, 250000],
    "debit_card": [190, 450, 890, 1290, 3200, 5800, 12400],
    "credit": [8900, 15400, 23700, 41200],
    "credit_card": [990, 2300, 7800, 15600],
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
HOUR_PROFILE = [
    0.2,
    0.1,
    0.05,
    0.05,
    0.05,
    0.1,
    0.3,
    0.6,
    0.9,
    1.1,
    1.2,
    1.3,
    1.4,
    1.3,
    1.2,
    1.2,
    1.2,
    1.3,
    1.4,
    1.3,
    1.1,
    0.9,
    0.6,
    0.4,
]
CLIENT_ERROR_KINDS: dict[str, float] = {
    "wrong_details": 0.35,
    "fee_misread": 0.25,
    "promo_expired": 0.15,
    "missed_payment": 0.15,
    "app_misuse": 0.10,
}
CLIENT_ERROR_PRODUCT = {
    "wrong_details": "debit_card",
    "fee_misread": "debit_card",
    "promo_expired": "deposit",
    "missed_payment": "credit",
    "app_misuse": "debit_card",
}
SIGNAL_TYPE_BY_ERROR = {
    "PROC-QR-FEE-CHARGED": "tariff_terms",
    "PROMO-RATE-MISMATCH": "tariff_terms",
    "AF-FALSE-BLOCK": "tech_fault",
}
NOISE_TYPES: dict[str, float] = {"info_request": 0.5, "gratitude": 0.25, "suggestion": 0.15, "service_quality": 0.10}


@dataclass
class ClientRow:
    id: int
    segment: str
    psychotype: str
    region_code: str
    city: str
    products: list[str] = field(default_factory=list)
    card_last4: str = "0000"
    p_complain: float = 0.4
    complain_delay_min: tuple[int, int] = (10, 240)
    channel_weights: dict[str, float] = field(default_factory=lambda: {"chat": 1.0})


@dataclass
class PendingSignal:
    due_sim: dt.datetime
    client: ClientRow
    signal_type: str
    product: str
    source_operation_id: int | None
    source_fault_id: int | None
    error_code: str | None
    system: str | None
    correlation_id: uuid.UUID


class World:
    """Кэш клиентов, активных сбоев и отложенных сигналов для одного запуска."""

    def __init__(
        self,
        conn: psycopg.AsyncConnection[Any],
        bus: EventBus,
        rng: SimRng,
        run_id: int,
        intensities: dict[str, float] | None = None,
    ) -> None:
        self.conn, self.bus, self.rng, self.run_id = conn, bus, rng, run_id
        self.intensities = {**DEFAULT_INTENSITIES, **(intensities or {})}
        self.clients: list[ClientRow] = []
        self.by_product: dict[str, list[ClientRow]] = {}
        self.active_faults: list[dict[str, Any]] = []
        self.pending: list[PendingSignal] = []
        self.error_codes: dict[str, dict[str, Any]] = {}
        # Текст и мир разделяют сохраняемый sim_state.rng_state; второго RNG нет.
        self.textgen = TextGen(rng)
        self.scale = 1.0
        self.team_emulator = TeamEmulator(rng, conn, bus, run_id)
        self.sla_engine = SlaEngine(conn, bus, run_id)

    async def load(self) -> None:
        cur = await self.conn.execute(
            "select c.id, c.segment_code, c.psychotype_code, c.region_code, ci.name_ru, p.params, "
            "array_agg(cp.product_code order by cp.product_code) filter (where cp.status = 'active'), max(cp.card_last4) "
            "from clients c join cities ci on ci.id = c.city_id join psychotypes p on p.code = c.psychotype_code "
            "left join client_products cp on cp.client_id = c.id where c.is_active group by c.id, ci.name_ru, p.params"
        )
        self.clients = []
        for cid, seg, pt, reg, city, params, products, last4 in await cur.fetchall():
            row = ClientRow(
                cid,
                seg,
                pt,
                reg,
                city,
                list(products or []),
                last4 or "0000",
                float(params.get("p_complain", 0.4)),
                tuple(params.get("complain_delay_min", [10, 240]))[:2],
                dict(params.get("channel_weights", {"chat": 1.0})),
            )
            self.clients.append(row)
        self.by_product = {}
        for c in self.clients:
            for p in c.products:
                self.by_product.setdefault(p, []).append(c)
        self.scale = max(len(self.clients) / 5000.0, 0.2)  # интенсивности ТЗ 4.2 заданы для demo (5 000 клиентов)
        ec = await self.conn.execute(
            "select code, system_code, product_code, default_criticality, client_visible from error_codes"
        )
        self.error_codes = {
            r[0]: {"system": r[1], "product": r[2], "criticality": r[3], "client_visible": r[4]}
            for r in await ec.fetchall()
        }
        af = await self.conn.execute(
            "select id, system_code, error_code, started_sim from faults where run_id = %s and resolved_sim is null",
            (self.run_id,),
        )
        self.active_faults = [
            {
                "id": r[0],
                "system": r[1],
                "error_code": r[2],
                "started_sim": r[3],
                "expected_end": r[3] + dt.timedelta(minutes=90),
                "impact": 0,
                "clients": set(),
                "corr": uuid.uuid4(),
            }
            for r in await af.fetchall()
        ]  # после рестарта: добиваем 90 мин
        await self.team_emulator.load()
        await self.sla_engine.load()
        log.info(
            "world_loaded", clients=len(self.clients), active_faults=len(self.active_faults), scale=round(self.scale, 3)
        )

    # --- операции (T-033) -------------------------------------------------------------------------------------------
    async def gen_operations(self, t0: dt.datetime, minutes: float) -> int:
        if not self.clients:
            return 0
        lam = (
            self.intensities["op"]
            * self.scale
            * HOUR_PROFILE[t0.astimezone(dt.timezone(dt.timedelta(hours=3))).hour]
            * minutes
            / 60
        )
        n = self.rng.poisson(lam)
        for _ in range(n):
            client = self.rng.choice(self.clients)
            if not client.products:
                continue
            product = self.rng.choice(client.products)
            op_type = self.rng.weighted(OP_TYPES[product])
            path = SYSTEM_PATH[op_type]
            started = t0 + dt.timedelta(seconds=self.rng.random() * minutes * 60)
            amount: float | None = (
                float(self.rng.choice(AMOUNTS[product]))
                if op_type not in ("login", "statement", "limit_request", "card_issue")
                else None
            )
            method = (
                ("qr_sbp" if self.rng.random() < 0.45 else "card")
                if op_type == "card_payment"
                else "transfer"
                if op_type == "transfer"
                else "online"
            )
            fault = next((f for f in self.active_faults if f["system"] in path), None)
            status, error_code, fault_id, fee = "success", None, None, 0.0
            if fault and self.rng.random() < 0.6:
                status, error_code, fault_id = "failed", fault["error_code"], fault["id"]
                fault["impact"] += 1
                fault["clients"].add(client.id)
            elif (
                method == "qr_sbp" and amount and self.rng.random() < 0.03
            ):  # фоновая ошибочная комиссия за QR (сценарий 8)
                fee = round(amount * 0.015 + 90, 2)
                error_code = "PROC-QR-FEE-CHARGED"
            cur = await self.conn.execute(
                "insert into operations (run_id, client_id, product_code, op_type, system_path, amount_rub, method, merchant, fee_amount, status, error_code, fault_id, started_sim, finished_sim) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id",
                (
                    self.run_id,
                    client.id,
                    product,
                    op_type,
                    path,
                    amount,
                    method,
                    self.rng.choice(MERCHANTS) if op_type == "card_payment" else None,
                    fee,
                    status,
                    error_code,
                    fault_id,
                    started,
                    started + dt.timedelta(seconds=self.rng.randrange(1, 30)),
                ),
            )
            op_id = (await cur.fetchone())[0]  # type: ignore[index]
            await abs_svc.post_operation(
                self.conn,
                run_id=self.run_id,
                operation_id=op_id,
                client_id=client.id,
                amount_rub=amount,
                fee_amount=fee,
                status=status,
                error_code=error_code,
                merchant=None,
                posted_sim=started,
            )
            corr = fault["corr"] if fault is not None and fault_id else uuid.uuid4()
            payload = {
                "operation_id": op_id,
                "client_id": client.id,
                "segment": client.segment,
                "region_code": client.region_code,
                "product": product,
                "op_type": op_type,
                "system_path": path,
                "amount_rub": amount,
                "status": status,
                "error_code": error_code,
                "fault_id": fault_id,
                "started_sim": started.isoformat(),
                "method": method,
                "fee_amount": fee,
            }
            await self.bus.emit(
                self.run_id,
                "op.failed" if status == "failed" else "op.succeeded",
                payload,
                started,
                correlation_id=corr,
                causation_id=fault["corr"] if fault is not None and fault_id else None,
            )
            if status == "failed" or error_code:
                self._maybe_complain(
                    client,
                    product,
                    started,
                    op_id,
                    fault_id,
                    error_code,
                    (fault or {}).get("system") or self.error_codes.get(error_code or "", {}).get("system"),
                    corr,
                )
        return n

    def _maybe_complain(
        self,
        client: ClientRow,
        product: str,
        at: dt.datetime,
        op_id: int | None,
        fault_id: int | None,
        error_code: str | None,
        system: str | None,
        corr: uuid.UUID,
        *,
        base_p: float | None = None,
        stype: str | None = None,
    ) -> None:
        p = base_p if base_p is not None else client.p_complain
        if self.rng.random() >= p:
            return
        lo, hi = client.complain_delay_min
        delay = self.rng.randint(int(lo), max(int(lo), int(hi)))
        self.pending.append(
            PendingSignal(
                at + dt.timedelta(minutes=delay),
                client,
                stype or SIGNAL_TYPE_BY_ERROR.get(error_code or "", "tech_fault"),
                product,
                op_id,
                fault_id,
                error_code,
                system,
                corr,
            )
        )

    # --- сбои (ТЗ 4.2, fault.*) --------------------------------------------------------------------------------------
    async def gen_faults(self, t0: dt.datetime, minutes: float) -> int:
        started = 0
        for f in list(self.active_faults):
            if t0 >= f["expected_end"]:
                await self.conn.execute(
                    "update faults set resolved_sim = %s, impact_count = %s, affected_clients = %s where id = %s",
                    (t0, f["impact"], len(f["clients"]), f["id"]),
                )
                await self.bus.emit(
                    self.run_id,
                    "fault.resolved",
                    {
                        "fault_id": f["id"],
                        "system": f["system"],
                        "error_code": f["error_code"],
                        "product": self.error_codes[f["error_code"]]["product"],
                        "severity": self.error_codes[f["error_code"]]["criticality"],
                        "impact_count": f["impact"],
                        "affected_clients": len(f["clients"]),
                        "started_sim": f["started_sim"].isoformat(),
                        "resolved_sim": t0.isoformat(),
                    },
                    t0,
                    correlation_id=f["corr"],
                )
                self.active_faults.remove(f)
        n = self.rng.poisson(self.intensities["fault"] * minutes / 60)
        candidates = [
            c
            for c, m in self.error_codes.items()
            if c not in {f["error_code"] for f in self.active_faults} and m["client_visible"]
        ]
        for _ in range(min(n, len(candidates))):
            code = self.rng.choice(candidates)
            candidates.remove(code)
            meta = self.error_codes[code]
            at = t0 + dt.timedelta(seconds=self.rng.random() * minutes * 60)
            duration = self.rng.choice([30, 45, 60, 90, 120, 180])
            cur = await self.conn.execute(
                "insert into faults (run_id, system_code, error_code, started_sim, region_codes) values (%s, %s, %s, %s, %s) returning id",
                (self.run_id, meta["system"], code, at, []),
            )
            fid = (await cur.fetchone())[0]  # type: ignore[index]
            f = {
                "id": fid,
                "system": meta["system"],
                "error_code": code,
                "started_sim": at,
                "expected_end": at + dt.timedelta(minutes=duration),
                "impact": 0,
                "clients": set(),
                "corr": uuid.uuid4(),
            }
            self.active_faults.append(f)
            await self.bus.emit(
                self.run_id,
                "fault.started",
                {
                    "fault_id": fid,
                    "system": meta["system"],
                    "error_code": code,
                    "product": meta["product"],
                    "severity": meta["criticality"],
                    "region_codes": [],
                    "impact_count": 0,
                    "affected_clients": 0,
                    "expected_duration_min": duration,
                    "started_sim": at.isoformat(),
                },
                at,
                correlation_id=f["corr"],
            )
            started += 1
        return started

    # --- ошибки клиентов (T-035) -------------------------------------------------------------------------------------
    async def gen_client_errors(self, t0: dt.datetime, minutes: float) -> int:
        if not self.clients:
            return 0
        n = self.rng.poisson(self.intensities["client_error"] * self.scale * minutes / 60)
        for _ in range(n):
            kind = self.rng.weighted(CLIENT_ERROR_KINDS)
            product = CLIENT_ERROR_PRODUCT[kind]
            pool = self.by_product.get(product) or self.clients
            client = self.rng.choice(pool)
            at = t0 + dt.timedelta(seconds=self.rng.random() * minutes * 60)
            corr = await self.bus.emit(
                self.run_id,
                f"client_error.{kind}",
                {
                    "client_id": client.id,
                    "kind": kind,
                    "product": product,
                    "operation_id": None,
                    "details": {"psychotype": client.psychotype},
                    "sim_time": at.isoformat(),
                },
                at,
            )
            p = client.p_complain * (1.5 if client.psychotype == "novice" else 0.6)
            self._maybe_complain(
                client, product, at, None, None, None, None, corr, base_p=min(p, 0.95), stype="client_error"
            )
        return n

    # --- сигналы: отложенные жалобы + шум -----------------------------------------------------------------------------
    async def flush_signals(self, now: dt.datetime, minutes: float) -> int:
        due = [p for p in self.pending if p.due_sim <= now]
        self.pending = [p for p in self.pending if p.due_sim > now]
        n_noise = self.rng.poisson(self.intensities["signal_noise"] * self.scale * minutes / 60)
        for _ in range(n_noise):
            client = self.rng.choice(self.clients)
            due.append(
                PendingSignal(
                    now,
                    client,
                    self.rng.weighted(NOISE_TYPES),
                    self.rng.choice(client.products) if client.products else "debit_card",
                    None,
                    None,
                    None,
                    None,
                    uuid.uuid4(),
                )
            )
        for p in due:
            await self._emit_signal(p)
        return len(due)

    async def _card_last4(self, client_id: int) -> str | None:
        row = await (
            await self.conn.execute(
                "select card_last4 from client_products where client_id = %s and card_last4 is not null order by status = 'active' desc, id limit 1",
                (client_id,),
            )
        ).fetchone()
        return str(row[0]) if row else None

    async def _emit_signal(self, p: PendingSignal) -> None:
        g = self.textgen.generate(
            p.signal_type, p.product, psychotype=p.client.psychotype, city=p.client.city, card4=p.client.card_last4
        )
        channel = self.rng.weighted(p.client.channel_weights or {"chat": 1.0})
        if channel not in (
            "social",
            "call",
            "chat",
            "email",
            "branch",
            "landing",
            "telegram_bot",
            "proactive",
            "review_portal",
        ):
            channel = "chat"
        identified = channel not in ("social", "review_portal") or self.rng.random() < 0.3
        cur = await self.conn.execute(
            "insert into signals (run_id, channel_code, client_id, external_contact, text, received_sim, status, origin, source_operation_id, source_fault_id, sentiment, geo) values (%s, %s, %s, %s::jsonb, %s, %s, 'new', 'sim', %s, %s, %s, %s::jsonb) returning id",
            (
                self.run_id,
                channel,
                p.client.id if identified else None,
                None if identified else dumps({"nick": f"@user_{p.client.id}", "region_code": p.client.region_code}),
                g.text,
                p.due_sim,
                p.source_operation_id,
                p.source_fault_id,
                g.gold.get("sentiment"),
                dumps({"region_code": p.client.region_code, "city": p.client.city, "source": "client_profile"}),
            ),
        )
        sid = (await cur.fetchone())[0]  # type: ignore[index]
        if channel in ("social", "review_portal"):
            # пост на эмуляторе внешней площадки (ТЗ 21.2): сигнал ссылается на пост, пост — на сигнал
            post = await feed_svc.create_post(
                self.conn,
                run_id=self.run_id,
                platform=feed_svc.PLATFORM_BY_CHANNEL[channel],
                author_nick=f"@user_{p.client.id}",
                text=g.text,
                posted_sim=p.due_sim,
                origin="background",
                author_client_id=p.client.id if identified else None,
                match_confidence=0.95 if identified else round(0.3 + self.rng.random() * 0.4, 2),
                mentions={"city": p.client.city, "card_last4": await self._card_last4(p.client.id)}
                if not identified
                else {"city": p.client.city},
                reactions=self.rng.randint(0, 40),
                signal_id=sid,
            )
            await self.conn.execute("update signals set external_post_id = %s where id = %s", (post["post_id"], sid))
        await self.bus.emit(
            self.run_id,
            "signal.received",
            {
                "signal_id": sid,
                "channel": channel,
                "client_id": p.client.id if identified else None,
                "external_contact": None
                if identified
                else {"nick": f"@user_{p.client.id}", "region_code": p.client.region_code},
                "text": g.text,
                "received_sim": p.due_sim.isoformat(),
                "origin": "sim",
                "source_operation_id": p.source_operation_id,
                "source_fault_id": p.source_fault_id,
                "generator_hint": {
                    k: v
                    for k, v in {
                        "true_type": p.signal_type,
                        "true_product": p.product,
                        "true_system": p.system,
                        "psychotype": p.client.psychotype,
                    }.items()
                    if v
                },
            },
            p.due_sim,
            correlation_id=p.correlation_id,
        )
        await self.conn.execute(
            "select pg_notify('signals', %s)",
            (
                dumps(
                    {
                        "type": "created",
                        "run_id": self.run_id,
                        "data": {
                            "id": sid,
                            "channel_code": channel,
                            "client_id": p.client.id if identified else None,
                            "received_sim": p.due_sim,
                            "text": g.text[:200],
                        },
                    }
                ),
            ),
        )
