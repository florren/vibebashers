"""Справочники (T-011, T-012, T-178, T-190, T-219): data/*.yaml|csv → таблицы. Идемпотентно: ON CONFLICT DO UPDATE по коду."""

from __future__ import annotations

import datetime as dt
import random
from pathlib import Path
from typing import Any

import psycopg
from scripts.seed.common import DATA, J, load_csv, load_yaml, log

from app.sim.branch_directory import network_history, provider


def seed_geo(cur: psycopg.Cursor[Any]) -> None:
    for d in load_csv("federal_districts.csv"):
        cur.execute(
            "insert into federal_districts (code, name_ru, name_en) values (%(code)s, %(name_ru)s, %(name_en)s) on conflict (code) do update set name_ru = excluded.name_ru, name_en = excluded.name_en",
            d,
        )
    for r in load_csv("regions.csv"):
        cur.execute(
            "insert into regions (code, name_ru, name_en, district_code, population, centroid_lat, centroid_lon, svg_path_id, okato) values (%(code)s, %(name_ru)s, %(name_en)s, %(district_code)s, %(population)s, %(centroid_lat)s, %(centroid_lon)s, %(svg_path_id)s, %(okato)s) "
            "on conflict (code) do update set name_ru = excluded.name_ru, population = excluded.population, centroid_lat = excluded.centroid_lat, centroid_lon = excluded.centroid_lon, okato = excluded.okato",
            {**r, "okato": r.get("okato") or None},
        )
    existing = {row[0] for row in cur.execute("select id from cities").fetchall()}
    rows = [c for c in load_csv("cities.csv") if int(c["id"]) not in existing]
    if rows:  # id из CSV стабильны; COPY пишет в identity-колонку как OVERRIDING SYSTEM VALUE
        with cur.copy(
            "copy cities (id, region_code, name_ru, name_en, population, lat, lon, is_capital) from stdin"
        ) as cp:
            for c in rows:
                cp.write_row(
                    (
                        int(c["id"]),
                        c["region_code"],
                        c["name_ru"],
                        c["name_en"],
                        int(c["population"]),
                        c["lat"],
                        c["lon"],
                        c["is_capital"] == "true",
                    )
                )
        cur.execute("select setval(pg_get_serial_sequence('cities','id'), (select max(id) from cities), true)")
    log.info(
        "geo",
        regions=cur.execute("select count(*) from regions").fetchone()[0],
        cities=cur.execute("select count(*) from cities").fetchone()[0],
    )


def seed_segments(cur: psycopg.Cursor[Any]) -> None:
    for s in load_yaml("segments.yaml")["segments"]:
        cur.execute(
            "insert into segments (code, name_ru, name_en, population_share, first_response_min, priority_multiplier, clv_min_rub, clv_max_rub, tone, hitl_required, personal_manager) "
            "values (%(code)s, %(name_ru)s, %(name_en)s, %(population_share)s, %(first_response_min)s, %(priority_multiplier)s, %(clv_min_rub)s, %(clv_max_rub)s, %(tone)s, %(hitl_required)s, %(personal_manager)s) "
            "on conflict (code) do update set population_share = excluded.population_share, first_response_min = excluded.first_response_min, priority_multiplier = excluded.priority_multiplier, clv_min_rub = excluded.clv_min_rub, clv_max_rub = excluded.clv_max_rub, tone = excluded.tone, hitl_required = excluded.hitl_required, personal_manager = excluded.personal_manager",
            s,
        )
    ps = load_yaml("psychotypes.yaml")
    for code, p in ps["psychotypes"].items():
        cur.execute(
            "insert into psychotypes (code, name_ru, name_en, params) values (%s, %s, %s, %s) on conflict (code) do update set params = excluded.params, name_ru = excluded.name_ru",
            (code, p["name_ru"], p["name_en"], J(p["params"])),
        )
    for seg, mix in ps["segment_mix"].items():
        assert abs(sum(mix.values()) - 1.0) < 1e-6, f"доли психотипов {seg} ≠ 1"
        for pt, share in mix.items():
            cur.execute(
                "insert into segment_psychotype_mix (segment_code, psychotype_code, share) values (%s, %s, %s) on conflict (segment_code, psychotype_code) do update set share = excluded.share",
                (seg, pt, share),
            )


def seed_catalogs(cur: psycopg.Cursor[Any]) -> None:
    for p in load_yaml("products.yaml")["products"]:
        cur.execute(
            "insert into products (code, name_ru, name_en, tariffs, promos) values (%s, %s, %s, %s, %s) on conflict (code) do update set tariffs = excluded.tariffs, promos = excluded.promos",
            (p["code"], p["name_ru"], p["name_en"], J(p["tariffs"]), J(p["promos"])),
        )
    for s in load_yaml("systems.yaml")["systems"]:
        cur.execute(
            "insert into systems (code, name_ru, name_en, layer) values (%(code)s, %(name_ru)s, %(name_en)s, %(layer)s) on conflict (code) do update set name_ru = excluded.name_ru, layer = excluded.layer",
            s,
        )
    for t in load_yaml("teams.yaml")["teams"]:
        cur.execute(
            "insert into teams (code, name_ru, name_en, speed_profile, lead_display_name) values (%s, %s, %s, %s, %s) on conflict (code) do update set speed_profile = excluded.speed_profile, lead_display_name = excluded.lead_display_name",
            (t["code"], t["name_ru"], t["name_en"], J(t["speed_profile"]), t["lead_display_name"]),
        )
        for sc in t["systems"]:
            cur.execute(
                "insert into team_systems (team_code, system_code) values (%s, %s) on conflict do nothing",
                (t["code"], sc),
            )
    for c in load_yaml("channels.yaml")["channels"]:
        cur.execute(
            "insert into channels (code, name_ru, name_en, subtypes, identifies_client, is_public) values (%(code)s, %(name_ru)s, %(name_en)s, %(subtypes)s, %(identifies_client)s, %(is_public)s) on conflict (code) do update set subtypes = excluded.subtypes, is_public = excluded.is_public",
            c,
        )
    ec = load_yaml("error_codes.yaml")
    for e in ec["error_codes"]:
        cur.execute(
            "insert into error_codes (code, system_code, product_code, title_ru, default_complexity, default_criticality, client_visible, description_ru) values (%(code)s, %(system)s, %(product)s, %(title_ru)s, %(complexity)s, %(criticality)s, %(client_visible)s, %(description_ru)s) on conflict (code) do update set title_ru = excluded.title_ru, default_complexity = excluded.default_complexity, default_criticality = excluded.default_criticality",
            e,
        )
    for st in ec["signal_types"]:
        cur.execute(
            "insert into signal_types (code, name_ru, name_en, base_criticality, requires_hitl, creates_incident) values (%(code)s, %(name_ru)s, %(name_en)s, %(base_criticality)s, %(requires_hitl)s, %(creates_incident)s) on conflict (code) do update set base_criticality = excluded.base_criticality, requires_hitl = excluded.requires_hitl",
            st,
        )
    sla = load_yaml("sla.yaml")
    for r in sla["sla_matrix"]:
        cur.execute(
            "insert into sla_matrix (complexity, criticality, fix_days, report_days, take_hours) values (%(complexity)s, %(criticality)s, %(fix_days)s, %(report_days)s, %(take_hours)s) on conflict (complexity, criticality) do update set fix_days = excluded.fix_days, report_days = excluded.report_days, take_hours = excluded.take_hours",
            r,
        )
    cur.execute("delete from routing_rules")  # полная замена: таблица — проекция YAML
    for r in sla["routing_rules"]:
        cur.execute(
            "insert into routing_rules (priority, match, team_codes, notes_ru) values (%s, %s, %s, %s)",
            (r["priority"], J(r["match"]), r["team_codes"], r.get("notes_ru")),
        )
    for p in load_yaml("llm_profiles.yaml")["llm_profiles"]:
        cur.execute(
            "insert into llm_profiles (code, provider, model, base_url, role, temperature, rpm_limit, rpd_limit, price_in_per_1m, price_out_per_1m, supports_tools, supports_stream, is_active, extra) "
            "values (%(code)s, %(provider)s, %(model)s, %(base_url)s, %(role)s, %(temperature)s, %(rpm_limit)s, %(rpd_limit)s, %(price_in_per_1m)s, %(price_out_per_1m)s, %(supports_tools)s, %(supports_stream)s, %(is_active)s, %(extra)s) "
            "on conflict (code) do update set model = excluded.model, base_url = excluded.base_url, role = excluded.role, rpm_limit = excluded.rpm_limit, rpd_limit = excluded.rpd_limit",
            {**p, "base_url": p.get("base_url"), "extra": J(p.get("extra", {}))},
        )


def seed_economics(cur: psycopg.Cursor[Any]) -> None:
    for r in load_csv("dcltv_rates.csv"):
        cur.execute(
            "insert into dcltv_rates (code, name_ru, name_en, rate_rub, maps_to) values (%s, %s, %s, %s, %s) on conflict (code) do update set rate_rub = excluded.rate_rub, maps_to = excluded.maps_to",
            (r["code"], r["name_ru"], r["name_en"], r["rate_rub"], J(__import__("json").loads(r["maps_to"]))),
        )
    g = load_yaml("gifts.yaml")
    for gift in g["gift_catalog"]:
        cur.execute(
            "insert into gift_catalog (code, name_ru, name_en, segments, rule, partner_display_name) values (%s, %s, %s, %s, %s, %s) on conflict (code) do update set rule = excluded.rule, segments = excluded.segments",
            (
                gift["code"],
                gift["name_ru"],
                gift["name_en"],
                gift["segments"],
                J(gift["rule"]),
                gift.get("partner_display_name"),
            ),
        )
    e = g["economics_settings"]
    cur.execute(
        "insert into economics_settings (id, detractor_share, no_return_share, retention_factors, calibration_mode, fallback_rate_code, misselling_case_cost_rub, map_zone_thresholds) values (1, %s, %s, %s, %s, %s, %s, %s) "
        "on conflict (id) do update set detractor_share = excluded.detractor_share, no_return_share = excluded.no_return_share, retention_factors = excluded.retention_factors, misselling_case_cost_rub = excluded.misselling_case_cost_rub, map_zone_thresholds = excluded.map_zone_thresholds",
        (
            e["detractor_share"],
            e["no_return_share"],
            J(e["retention_factors"]),
            e["calibration_mode"],
            e["fallback_rate_code"],
            e["misselling_case_cost_rub"],
            J(e["map_zone_thresholds"]),
        ),
    )


def seed_product_lines(cur: psycopg.Cursor[Any]) -> None:
    """Существующий справочник необходим route_to_product_team, без сида истории T-240."""
    for line in load_yaml("product_lines.yaml")["product_lines"]:
        cur.execute(
            "insert into product_lines (code, name_ru, name_en, rate_code, owner_team_code, owner_is_proxy, product_codes, sort_order) "
            "values (%(code)s, %(name_ru)s, %(name_en)s, %(rate_code)s, %(owner_team_code)s, %(owner_is_proxy)s, %(product_codes)s, %(sort_order)s) "
            "on conflict (code) do update set name_ru = excluded.name_ru, name_en = excluded.name_en, "
            "rate_code = excluded.rate_code, owner_team_code = excluded.owner_team_code, owner_is_proxy = excluded.owner_is_proxy, "
            "product_codes = excluded.product_codes, sort_order = excluded.sort_order",
            line,
        )


def seed_templates(cur: psycopg.Cursor[Any]) -> None:
    t = load_yaml("templates/notifications.yaml")
    for tpl in t["templates"]:
        channels = t["channels_for_star"] if tpl["channel"] == "*" else [tpl["channel"]]
        lang = tpl.get("lang") or "ru"
        for ch in channels:
            cur.execute(
                "insert into notification_templates (code, channel_code, segment_code, lang, subject, body, variables) values (%s, %s, %s, %s, %s, %s, %s) on conflict (code, channel_code, COALESCE(segment_code,'*'), lang) do update set subject = excluded.subject, body = excluded.body, variables = excluded.variables",
                (tpl["code"], ch, tpl.get("segment"), lang, tpl.get("subject"), tpl["body"], tpl.get("variables", [])),
            )


def seed_abs_rules(cur: psycopg.Cursor[Any]) -> None:
    cur.execute("delete from tariffs")
    for t in load_yaml("tariffs.yaml")["tariffs"]:
        cur.execute(
            "insert into tariffs (product_code, operation_kind, method, fee_pct, fee_fixed, free_limit_rub, note_ru) values (%(product)s, %(operation_kind)s, %(method)s, %(fee_pct)s, %(fee_fixed)s, %(free_limit_rub)s, %(note_ru)s)",
            t,
        )
    for r in load_yaml("rules.yaml")["business_rules"]:
        cur.execute(
            "insert into business_rules (code, name_ru, name_en, condition, action, limits, owner_team_code, error_code, is_active) values (%s, %s, %s, %s, %s, %s, %s, %s, %s) on conflict (code) do update set condition = excluded.condition, action = excluded.action, limits = excluded.limits, is_active = excluded.is_active, version = business_rules.version + 1, updated_at = now()",
            (
                r["code"],
                r["name_ru"],
                r["name_en"],
                J(r["condition"]),
                r["action"],
                J(r.get("limits", {})),
                r["owner_team_code"],
                r.get("error_code"),
                r.get("is_active", True),
            ),
        )
    for p in load_yaml("misselling_patterns.yaml")["patterns"]:
        cur.execute(
            "insert into misselling_patterns (code, name_ru, name_en, description_ru, examples, counter_examples, keywords, weight, is_active, family, alert_policy, immediate_threshold, recommendation_ru, training_module) "
            "values (%(code)s, %(name_ru)s, %(name_en)s, %(description_ru)s, %(examples)s, %(counter_examples)s, %(keywords)s, %(weight)s, %(is_active)s, %(family)s, %(alert_policy)s, %(immediate_threshold)s, %(recommendation_ru)s, %(training_module)s) "
            "on conflict (code) do update set examples = excluded.examples, counter_examples = excluded.counter_examples, keywords = excluded.keywords, weight = excluded.weight, family = excluded.family, alert_policy = excluded.alert_policy, immediate_threshold = excluded.immediate_threshold, recommendation_ru = excluded.recommendation_ru",
            p,
        )
    for s in load_yaml("service_scripts.yaml")["service_scripts"]:
        cur.execute(
            "insert into service_scripts (code, kind, name_ru, steps, version) values (%s, %s, %s, %s, %s) on conflict (code) do update set steps = excluded.steps, version = excluded.version, updated_at = now()",
            (
                s["code"],
                s["kind"],
                s["name_ru"],
                J({"steps": s["steps"], "forbidden_phrases": s["forbidden_phrases"]}),
                s["version"],
            ),
        )
    for src in load_yaml("ingest_sources.yaml")["ingest_sources"]:
        cur.execute(
            "insert into ingest_sources (code, kind, channel_code, config, enabled, interval_s, is_external) values (%(code)s, %(kind)s, %(channel_code)s, %(config)s, %(enabled)s, %(interval_s)s, %(is_external)s) on conflict (code) do update set config = excluded.config, interval_s = excluded.interval_s, is_external = excluded.is_external",
            {**src, "config": J(src["config"])},
        )


def seed_branches(
    cur: psycopg.Cursor[Any],
    rnd: Any,
    *,
    seed: int = 42,
    sim_time: dt.datetime | None = None,
    mode: str = "synthetic",
    snapshot: Path | None = None,
) -> None:
    sim_time = sim_time or dt.datetime(2026, 11, 9, 9, tzinfo=dt.timezone(dt.timedelta(hours=3)))
    branches = provider(mode, snapshot).load(seed, sim_time)
    b = load_yaml("branches.yaml")
    legacy_codes = {br["code"] for br in b["branches"]}
    fixed = {("0042", 3): "Петров П. П.", ("0042", 5): "Сидорова А. А."}
    columns = list(branches[0].model_dump())
    query = (
        "insert into branches ("
        + ", ".join(columns)
        + ") values ("
        + ", ".join("%(" + c + ")s" for c in columns)
        + ") on conflict (code) do update set "
        + ", ".join(c + " = excluded." + c for c in columns if c != "code")
        + " returning id"
    )
    for branch in branches:
        cur.execute(query, branch.model_dump())
        bid = cur.fetchone()[0]
        employee_rng = rnd if branch.code in legacy_codes else random.Random(f"{seed}:{branch.code}:employees")
        for desk in range(1, branch.desks + 1):
            employee = cur.execute(
                "select id from employees where branch_id = %s and desk_no = %s", (bid, desk)
            ).fetchone()
            if employee:
                continue
            name = fixed.get((branch.code, desk))
            if not name:
                female = employee_rng.random() < 0.6
                fn = employee_rng.choice(b["first_names_f"] if female else b["first_names_m"])
                ln = employee_rng.choice(b["last_names"]) + ("а" if female else "")
                name = f"{ln} {fn[0]}. {employee_rng.choice('АВДЕИКМНОПРС')}."
            hired = sim_time - dt.timedelta(days=365 + desk * 73)
            cur.execute(
                "insert into employees (display_name, branch_id, desk_no, position, education, hired_sim, position_since_sim) values (%s,%s,%s,%s,%s,%s,%s)",
                (
                    name,
                    bid,
                    desk,
                    b["positions"][desk - 1],
                    "высшее" if desk % 2 else "среднее профессиональное",
                    hired,
                    hired + dt.timedelta(days=90),
                ),
            )
        cur.execute(
            "update employees set education=coalesce(education,%s), hired_sim=coalesce(hired_sim,%s), position_since_sim=coalesce(position_since_sim,%s) where branch_id = %s",
            ("высшее", sim_time - dt.timedelta(days=730), sim_time - dt.timedelta(days=365), bid),
        )
    for row in network_history(branches, sim_time):
        cur.execute(
            "insert into branch_network_history (month,region_code,open_count,closed_count,opened_in_month,closed_in_month) values (%(month)s,%(region_code)s,%(open_count)s,%(closed_count)s,%(opened_in_month)s,%(closed_in_month)s) on conflict (month,region_code) do update set open_count=excluded.open_count,closed_count=excluded.closed_count,opened_in_month=excluded.opened_in_month,closed_in_month=excluded.closed_in_month",
            row,
        )


def seed_scenarios(cur: psycopg.Cursor[Any]) -> None:
    import yaml

    for f in sorted((DATA / "scenarios").glob("*.yaml")):
        src = f.read_text(encoding="utf-8")
        d = yaml.safe_load(src)
        cur.execute(
            "insert into scenarios (id, title_ru, title_en, yaml_source, expected) values (%s, %s, %s, %s, %s) on conflict (id) do update set title_ru = excluded.title_ru, yaml_source = excluded.yaml_source, expected = excluded.expected",
            (d["id"], d["title_ru"], d["title_en"], src, J(d.get("expected", {}))),
        )


def seed_bench(cur: psycopg.Cursor[Any]) -> None:
    import json

    meta = {
        "sentiment_v1": "Тональность 3 класса (ДТЗ FR-2.1)",
        "hidden_negativity_v1": "Скрытый негатив: сарказм, пассивная агрессия, отток (ДТЗ FR-2.2)",
        "summary_v1": "Краткое резюме обращения (ДТЗ FR-2.4)",
        "red_phrases_v1": "Красные фразы сотрудника: мисселлинг и conduct (ДТЗ FR-4.2)",
        "golden_v1": "Golden-набор классификации: тип × продукт × канал",
    }
    for f in sorted((DATA / "bench").glob("*.jsonl")):
        code = f.stem
        cur.execute(
            "insert into bench_datasets (code, title_ru, description) values (%s, %s, %s) on conflict (code) do update set title_ru = excluded.title_ru returning id",
            (code, meta.get(code, code), f"data/bench/{f.name}"),
        )
        did = cur.fetchone()[0]
        if cur.execute("select count(*) from bench_cases where dataset_id = %s", (did,)).fetchone()[0]:
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            c = json.loads(line)
            cur.execute(
                "insert into bench_cases (dataset_id, channel_code, segment_code, text, gold, tags) values (%s, %s, %s, %s, %s, %s)",
                (did, c.get("channel", "chat"), c.get("segment"), c["text"], J(c["gold"]), c.get("tags", [])),
            )


def seed_all_refs(
    cur: psycopg.Cursor[Any],
    rnd: Any,
    *,
    seed: int = 42,
    sim_time: dt.datetime | None = None,
    branch_mode: str = "synthetic",
    branch_snapshot: Path | None = None,
) -> None:
    seed_geo(cur)
    seed_segments(cur)
    seed_catalogs(cur)
    seed_economics(cur)
    seed_product_lines(cur)
    seed_templates(cur)
    seed_abs_rules(cur)
    seed_branches(cur, rnd, seed=seed, sim_time=sim_time, mode=branch_mode, snapshot=branch_snapshot)
    seed_scenarios(cur)
    seed_bench(cur)
    log.info("refs_done")
