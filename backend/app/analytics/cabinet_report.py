"""T-244: один ограниченный read-only snapshot для JSON и XLSX, без расчёта денег."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import replace
from decimal import Decimal
from functools import partial
from io import BytesIO
from typing import Any

from fastapi import HTTPException
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font
from psycopg.types.json import set_json_loads
from starlette.responses import Response

from app import __version__
from app.analytics.cabinet import overview
from app.analytics.cabinet_scope import CabinetScope
from app.analytics.cabinet_signals import signals
from app.analytics.report_text import TEXT, describe, status_label
from app.api.common import fetch_all, fetch_one
from app.trace.privacy import mask
from app.trace.store import Conn

MAX_SIGNALS = 10_000
MAX_BYTES = 5 * 1024 * 1024


def bounded_json(data: dict[str, Any]) -> Response:
    def encode(value: Any) -> Any:
        if isinstance(value, dt.datetime):
            return value.isoformat().replace("+00:00", "Z")
        if isinstance(value, dt.date):
            return value.isoformat()
        if isinstance(value, Decimal):
            # Совместимый numeric overview; lossless money_exact уже содержит строки.
            return float(value)
        raise TypeError(f"Неподдерживаемый тип отчёта: {type(value).__name__}")

    body = json.dumps(data, default=encode, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_BYTES:
        raise HTTPException(413, "Отчёт превышает 5 MiB; выберите более узкий период или направление")
    return Response(body, media_type="application/json")


async def build_report(conn: Conn, scope: CabinetScope, lang: str, requested_run: str) -> dict[str, Any]:
    # Только эта connection: JSONB numeric сохраняет десятичные копейки до export.
    set_json_loads(partial(json.loads, parse_float=Decimal), conn)
    where, args = scope.predicate("f")
    incident_where, incident_args = scope.predicate("f", time_column="created_sim")
    count = await fetch_one(
        conn,
        f"SELECT (SELECT count(*) FROM v_cabinet_signal_facts f WHERE {where}) AS signals,(SELECT count(DISTINCT f.id) FROM v_cabinet_incident_facts f WHERE {incident_where}) AS incidents",
        [*args, *incident_args],
    )  # noqa: S608
    if count and max(count["signals"], count["incidents"]) > MAX_SIGNALS:
        raise HTTPException(
            413, "Отчёт содержит более 10000 сигналов или инцидентов; выберите более узкий период или направление"
        )
    current = await overview(conn, scope)
    previous_scope = replace(
        scope, now=scope.since - dt.timedelta(microseconds=1), since=scope.since - (scope.now - scope.since)
    )
    pw, pa = previous_scope.predicate("p")
    iw, ia = previous_scope.predicate("i", time_column="created_sim")
    prior = await fetch_one(
        conn,
        f"SELECT (SELECT count(*) FROM v_cabinet_signal_facts p WHERE {pw}) AS signals, (SELECT count(DISTINCT i.id) FROM v_cabinet_incident_facts i WHERE {iw}) AS incidents",
        [*pa, *ia],
    )  # noqa: S608
    assert prior is not None
    previous = {"kpi": prior}
    # False снимает presentation preset, чтобы JSON/XLSX совпадали с overview.
    entries = await signals(
        conn,
        scope,
        region=None,
        status=None,
        channel=None,
        red_words=False,
        sort="date",
        direction="asc",
        limit=MAX_SIGNALS,
        offset=0,
    )
    incident_where, incident_args = scope.predicate("f", time_column="created_sim")
    facts = await fetch_one(
        conn,
        f"""
        WITH selected AS MATERIALIZED (
          SELECT DISTINCT f.id FROM v_cabinet_incident_facts f WHERE {incident_where}
        ), details AS (
          SELECT i.id,i.public_id,i.title,i.status,i.criticality,i.sla_due_sim,i.sla_breached,
            i.resolution_summary,t.name_ru AS team_ru,t.name_en AS team_en,
            r.name_ru AS region_ru,r.name_en AS region_en,
            CASE WHEN count(s.id)>0 AND count(s.id)=count(s.client_id) THEN count(DISTINCT s.client_id) END AS clients,
            count(DISTINCT s.client_id) AS identified_clients,
            (i.criticality='high' AND i.status NOT IN ('closed','resolved','rejected','duplicate') OR
             i.status='awaiting_human' OR i.sla_breached OR
             i.sla_due_sim < %s AND i.status NOT IN ('closed','resolved','rejected','duplicate')) AS attention
          FROM selected x JOIN incidents i ON i.id=x.id JOIN teams t ON t.code=i.team_code
          LEFT JOIN regions r ON r.code=i.region_code
          LEFT JOIN incident_signals ix ON ix.incident_id=i.id
          LEFT JOIN v_cabinet_signal_facts s ON s.id=ix.signal_id AND s.run_id=i.run_id
            AND (%s::text[] IS NULL OR s.product_line_code=ANY(%s))
          GROUP BY i.id,t.name_ru,t.name_en,r.name_ru,r.name_en
        ) SELECT
          (SELECT count(*) FROM details WHERE attention) AS attention_total,
          (SELECT jsonb_agg(to_jsonb(p)) FROM (SELECT * FROM details ORDER BY attention DESC,clients DESC NULLS LAST,id LIMIT 5) p) AS problems,
          (SELECT jsonb_agg(to_jsonb(p)) FROM (SELECT * FROM details WHERE attention ORDER BY sla_due_sim,id LIMIT 10) p) AS attention,
          (SELECT jsonb_agg(DISTINCT ie.breakdown->>'formula_ru') FILTER(WHERE ie.breakdown->>'formula_ru' IS NOT NULL)
             FROM selected x JOIN incident_economics ie ON ie.incident_id=x.id) AS formula_ru,
          (SELECT jsonb_agg(DISTINCT jsonb_build_object('code',re.rule_code,'version',re.rule_version))
             FROM selected x JOIN incident_signals ix ON ix.incident_id=x.id
             JOIN v_cabinet_signal_facts s ON s.id=ix.signal_id AND s.received_sim BETWEEN %s AND %s AND (%s::text[] IS NULL OR s.product_line_code=ANY(%s)) JOIN incidents i ON i.id=x.id AND i.run_id=s.run_id
             JOIN rule_evaluations re ON re.signal_id=s.id AND re.run_id=s.run_id) AS rules
    """,
        [*incident_args, scope.now, scope.lines, scope.lines, scope.since, scope.now, scope.lines, scope.lines],
    )  # noqa: S608
    assert facts is not None
    t = TEXT[lang]
    red_signals = [row for row in entries["items"] if "red_word" in row["flags"]]
    red = len(red_signals)
    red_teams = await fetch_all(
        conn,
        "SELECT s.id,string_agg(DISTINCT t.name_ru, '; ' ORDER BY t.name_ru) AS ru,string_agg(DISTINCT t.name_en, '; ' ORDER BY t.name_en) AS en FROM signals s JOIN incident_signals ix ON ix.signal_id=s.id JOIN incidents i ON i.id=ix.incident_id AND i.run_id=s.run_id JOIN teams t ON t.code=i.team_code WHERE s.id=ANY(%s) GROUP BY s.id",
        [[row["id"] for row in red_signals[:10]]],
    )
    team_by_signal = {row["id"]: row[lang] for row in red_teams}
    theme = mask(facts["problems"][0]["title"], 180) if facts["problems"] else None
    words = describe(current, previous, facts["attention_total"], red, lang, theme)
    ru_words = describe(current, previous, facts["attention_total"], red, "ru", theme)

    def problem(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "public_id": row["public_id"],
            "problem": mask(row["title"], 180),
            "clients": row["clients"],
            "identified_clients": row["identified_clients"],
            "region": row["region_" + lang] or t["region_unknown"],
            "status": status_label(row["status"], lang),
            "team": row["team_" + lang],
            "action": mask(row["resolution_summary"], 180) if row["resolution_summary"] else t["not_recorded"],
        }

    runs = await fetch_all(
        conn,
        "SELECT id,public_id,kind FROM sim_runs WHERE (%s::bigint[] IS NULL OR id=ANY(%s)) ORDER BY id LIMIT 10001",
        [scope.run_ids, scope.run_ids],
    )
    if len(runs) > MAX_SIGNALS:
        raise HTTPException(413, "Отчёт охватывает более 10000 запусков; выберите точный run_id")
    # Только recorded rule_evaluations, не выдаём текущие business_rules за историю.
    formulas = sorted(set(facts["formula_ru"] or []))

    def exact(value: Any) -> str | None:
        return None if value is None else format(Decimal(value), "f")

    money_exact = {
        "kpi": {name: exact(current["kpi"][name]) for name in ("potential_loss_rub", "prevented_loss_rub")},
        "daily": [
            {
                "day": str(row["day"]),
                **{name: exact(row[name]) for name in ("potential_loss_rub", "prevented_loss_rub")},
            }
            for row in current["daily"]
        ],
        "monthly": [
            {"month": str(row["month"]), "potential_loss_rub": exact(row["potential_loss_rub"])}
            for row in current["monthly"]
        ],
    }
    data = {
        "money_exact": money_exact,
        "lang": lang,
        "overview": current,
        "summary_ru": ru_words["summary"],
        **words,
        "previous": {
            "since_sim": previous_scope.since,
            "sim_time": previous_scope.now,
            "signals": previous["kpi"]["signals"],
            "note": t["coverage"],
        },
        "signals": entries["items"],
        "top_problems": [problem(row) for row in facts["problems"] or []],
        "attention": [{**problem(row), "recommendation": t["action"]} for row in facts["attention"] or []],
        "attention_total": facts["attention_total"],
        "red_phrase_signals": red,
        "red_phrase_attention": [
            {
                "public_id": row["public_id"],
                "problem": row["summary"],
                "team": team_by_signal.get(row["id"], t["team_unknown"]),
            }
            for row in red_signals[:10]
        ],
        "red_phrase_action": t["red_action"],
        "method": {
            "formula_ru": formulas,
            "formula_note": t["formula_unknown"] if not formulas else t["chart_note"],
            "rules_version": sorted(facts["rules"] or [], key=lambda x: (x["code"], x["version"])),
            "rules_note": t["rules_unknown"] if not facts["rules"] else t["chart_note"],
            "app_version": __version__,
            "run_public_id": [r["public_id"] for r in runs],
            "requested_run": requested_run,
            "synthetic": t["synthetic"],
            "terms": t["method"],
            "generated_sim": scope.now,
            "signal_limit": MAX_SIGNALS,
            "byte_limit": MAX_BYTES,
        },
    }
    return data


def workbook_bytes(data: dict[str, Any]) -> bytes:
    """Явный текстовый cell type блокирует формулы во всех строковых значениях."""
    pending: list[Any] = [data]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, str) and (len(value) > 32767 or ILLEGAL_CHARACTERS_RE.search(value)):
            # До открытия XML writers: отказ не оставляет частично записанный XLSX.
            raise HTTPException(413, "Текст отчёта не помещается в безопасную XLSX-ячейку; используйте JSON")
    wb = Workbook(write_only=True)
    font = Font(name="Calibri", size=11)

    def sheet(name: str, rows: list[list[Any]]) -> None:
        from openpyxl.cell import WriteOnlyCell

        ws = wb.create_sheet(name)
        for row in rows:
            cells = []
            for value in row:
                value = value if not isinstance(value, (dict, list)) else str(value)
                if isinstance(value, str) and (len(value) > 32767 or ILLEGAL_CHARACTERS_RE.search(value)):
                    raise HTTPException(413, "Текст отчёта не помещается в безопасную XLSX-ячейку; используйте JSON")
                cell = WriteOnlyCell(ws, value=value)
                if isinstance(cell.value, str):
                    # Не меняем видимый текст и не создаём executable formula/hyperlink.
                    cell.data_type = "s"
                cell.font = font
                cells.append(cell)
            ws.append(cells)

    k = data["overview"]
    columns = TEXT[data["lang"]]["headers"]

    def labels(*names: str) -> list[str]:
        return [columns[name] for name in names]

    sheet("Главное", [[TEXT[data["lang"]]["synthetic"]], *[[x] for x in data["summary"]], [data["previous"]["note"]]])
    sheet(
        "KPI",
        [
            labels("label", "value", "unit", "delta", "verdict"),
            *[
                [
                    r["label"],
                    data["money_exact"]["kpi"]["potential_loss_rub" if r["code"] == "loss" else "prevented_loss_rub"]
                    if r["unit"] == "RUB"
                    else r["value"],
                    r["unit"],
                    r["delta"],
                    r["verdict"],
                ]
                for r in data["kpi"]
            ],
        ],
    )
    sheet(
        "Сигналы",
        [
            labels("public_id", "received_sim", "summary", "status", "source"),
            *[
                [
                    r["public_id"],
                    r["received_sim"].isoformat() if hasattr(r["received_sim"], "isoformat") else r["received_sim"],
                    r["summary"],
                    r["status"],
                    (r["source_platform"] or {}).get("name_" + data["lang"], TEXT[data["lang"]]["unknown_source"]),
                ]
                for r in data["signals"]
            ],
        ],
    )
    sheet(
        "Динамика",
        [
            labels("series", "date", "signals", "loss_rub"),
            *[
                ["daily", str(r["day"]), r["signals"], data["money_exact"]["daily"][n]["potential_loss_rub"]]
                for n, r in enumerate(k["daily"])
            ],
            *[
                ["monthly", str(r["month"]), r["signals"], data["money_exact"]["monthly"][n]["potential_loss_rub"]]
                for n, r in enumerate(k["monthly"])
            ],
        ],
    )
    sheet(
        "Источники",
        [
            labels("source", "signals"),
            *[
                [(r["platform"] or {}).get("name_" + data["lang"], TEXT[data["lang"]]["unknown_source"]), r["signals"]]
                for r in k["sources"]
            ],
        ],
    )
    sheet(
        "Регионы",
        [
            labels("region", "signals", "negative", "affected_clients", "identified_clients"),
            *[
                [r["name_" + data["lang"]], r["signals"], r["negative"], r["affected_clients"], r["identified_clients"]]
                for r in k["regions"]
            ],
        ],
    )
    method = data["method"]
    method_rows = [
        [name, str(value)]
        for name, value in method.items()
        if name not in ("formula_ru", "rules_version", "run_public_id")
    ]
    method_rows.extend([["formula_ru", formula] for formula in method["formula_ru"]])
    method_rows.extend([["rule", rule["code"], rule["version"]] for rule in method["rules_version"]])
    method_rows.extend([["run", ident] for ident in method["run_public_id"]])
    method_rows.append(["top_problems", "problem", "clients", "region", "status", "action", "team"])
    method_rows.extend(
        [
            [
                "problem",
                row["problem"] + " (" + row["public_id"] + ")",
                row["clients"],
                row["region"],
                row["status"],
                row["action"],
                row["team"],
            ]
            for row in data["top_problems"]
        ]
    )
    method_rows.append(["attention_total", data["attention_total"]])
    method_rows.extend(
        [
            ["attention", row["problem"] + " (" + row["public_id"] + ")", row["recommendation"], row["team"]]
            for row in data["attention"]
        ]
    )
    method_rows.append(["red_phrase_signals", data["red_phrase_signals"]])
    method_rows.extend(
        [
            ["red_phrase_attention", row["problem"] + " (" + row["public_id"] + ")", row["team"]]
            for row in data["red_phrase_attention"]
        ]
    )
    sheet("Методика", method_rows)
    out = BytesIO()
    wb.save(out)
    result = out.getvalue()
    if len(result) > MAX_BYTES:
        raise HTTPException(413, "XLSX превышает 5 MiB; выберите более узкий период или направление")
    return result
