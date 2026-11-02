"""T262: private preparation известных Mock-сценариев, без policy/clock overrides."""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import zipfile
from typing import Any

import psycopg
from openpyxl import Workbook
from openpyxl.writer.excel import ExcelWriter
from psycopg.types.json import Jsonb

from app.api.common import fetch_all, fetch_one
from app.ingest.csi import import_rows, parse_xlsx, validate_row
from app.ingest.csi_cohorts import CohortRegistrationError, digest, install_scoped_sample
from app.sim.csi_scoped_corpus import generate_scoped

IDS = frozenset({"cabinet_red_words_report", "csi_and_branches"})
MIN_BASE, MAX_BASE, BLOCK_SIZE = 30000, 899400, 300  # Диапазон существующего generate_scoped.
KEY = "t262_inputs"


class PreparationError(ValueError):
    pass


def is_acceptance(scenario: dict[str, Any]) -> bool:
    return scenario.get("id") in IDS and scenario.get("kind") == "acceptance"


def require_mock(snapshot: dict[str, Any]) -> None:
    """capture уже применяет P1 explicit mock/offline execution к actual roles."""
    roles = snapshot.get("roles")
    if (
        not isinstance(roles, dict)
        or set(roles) != {"main", "fast", "twin"}
        or any(not isinstance(profile, dict) or profile.get("provider") != "mock" for profile in roles.values())
    ):
        raise PreparationError(
            "T262 пока поддерживает только effective Mock всех ролей; live/replay требуют отдельной приёмки/кассет"
        )


def workbook_bytes(rows: list[dict[str, Any]], at: dt.datetime) -> bytes:
    """Собственный deterministic XLSX: один и тот же source даёт тот же SHA при retry."""
    if at.utcoffset() is None:
        raise PreparationError("XLSX source clock требует timezone")
    fields = sorted({field for row in rows for field in row})
    workbook = Workbook()
    workbook.properties.created = workbook.properties.modified = at.astimezone(dt.UTC).replace(tzinfo=None)
    sheet = workbook.active
    sheet.title = "CSI sample"
    sheet.append(fields)
    for row in rows:
        sheet.append(
            [
                json.dumps(row[field], ensure_ascii=False) if isinstance(row.get(field), list) else row.get(field)
                for field in fields
            ]
        )
    temporary = io.BytesIO()
    # save_workbook сам заменяет modified на now; installed ExcelWriter сохраняет
    # явно заданные properties. Затем нормализуем только ZIP metadata своего файла.
    ExcelWriter(workbook, zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED)).save()
    workbook.close()
    result = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(temporary.getvalue())) as source, zipfile.ZipFile(result, "w") as target:
        for name in sorted(source.namelist()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, source.read(name))
    return result.getvalue()


async def _context(conn: psycopg.AsyncConnection[Any], run: int) -> tuple[dt.datetime, dict[str, Any]]:
    # Короткий planning/import TX следует существующему tick lock order. Модель
    # здесь не вызывается. NO KEY UPDATE блокирует status/header mutations,
    # но совместим с FK KEY SHARE обычного importer под csi_import lock.
    state = await fetch_one(conn, "select current_run_id,sim_time,running from sim_state where id=1 for update")
    header = await fetch_one(
        conn, "select kind,status,scenario_id,settings_snapshot from sim_runs where id=%s for no key update", (run,)
    )
    if (
        not state
        or state["current_run_id"] != run
        or state["running"]
        or not header
        or header["kind"] != "scenario"
        or header["status"] != "paused"
        or header["scenario_id"] != "csi_and_branches"
    ):
        raise PreparationError("CSI preparation требует собственного current paused scenario run без движения часов")
    return state["sim_time"], header["settings_snapshot"] or {}


async def _closed(conn: psycopg.AsyncConnection[Any], at: dt.datetime, code: str | None = None) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        "select id,code,closed_sim from branches where branch_status='closed' and closed_sim<=%s and closed_sim+interval '90 days'>%s and (%s::text is null or code=%s) order by code limit 1 for share",
        (at, at, code, code),
    )
    if not row:
        raise PreparationError(
            "Нет native closed ВСП в90-day window; нужен подходящий snapshot, автоматического reset/исправления дат нет"
        )
    return row


async def _free_bases(conn: psycopg.AsyncConnection[Any]) -> list[int]:
    rows = await fetch_all(
        conn,
        "select ((substring(value from 5)::int-1)/300)*300 as base from (select csi_no value from csi_responses union select external_id from ingest_messages where source_code='csi') x where value ~ '^CSI-[0-9]{3,6}$'",
    )
    occupied = {row["base"] for row in rows}
    headers = await fetch_all(
        conn, "select settings_snapshot->%s as plan from sim_runs where settings_snapshot ? %s", (KEY, KEY)
    )
    for row in headers:
        plan = validate_plan(row["plan"])
        for key in ("id_base", "extra_id_base"):
            base = plan.get(key)
            if type(base) is not int or not MIN_BASE <= base <= MAX_BASE or base % BLOCK_SIZE:
                raise PreparationError("Некорректный сохранённый CSI namespace")
            occupied.add(base)
    available = [base for base in range(MIN_BASE, MAX_BASE + 1, BLOCK_SIZE) if base not in occupied]
    if len(available) < 2:
        raise PreparationError("Нет двух свободных CSI namespace blocks; foreign IDs не переназначаются")
    return available[:2]


def validate_plan(value: Any) -> dict[str, Any]:
    """Неизвестный/повреждённый сохранённый manifest не чинится автоматически."""
    if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
        raise PreparationError("Неизвестный T262 plan")
    for key in ("id_base", "extra_id_base"):
        base = value.get(key)
        if type(base) is not int or not MIN_BASE <= base <= MAX_BASE or base % BLOCK_SIZE:
            raise PreparationError("Некорректный сохранённый CSI namespace")
    if value["id_base"] == value["extra_id_base"] or type(value.get("seed")) is not int:
        raise PreparationError("Некорректный сохранённый CSI allocation/seed")
    try:
        clock = dt.datetime.fromisoformat(value.get("clock", ""))
    except (TypeError, ValueError) as exc:
        raise PreparationError("Некорректный сохранённый CSI clock") from exc
    if clock.utcoffset() is None or not isinstance(value.get("closed_branch_code"), str):
        raise PreparationError("Некорректный сохранённый CSI clock/branch")
    if type(value.get("prepared")) is not bool:
        raise PreparationError("Некорректный сохранённый CSI preparation marker")
    for key in ("xlsx_sha256", "cohort_sha256"):
        digest_value = value.get(key)
        if (
            not isinstance(digest_value, str)
            or len(digest_value) != 64
            or any(c not in "0123456789abcdef" for c in digest_value)
        ):
            raise PreparationError("Некорректный сохранённый CSI source hash")
    return value


def _input(plan: dict[str, Any]) -> tuple[dict[str, Any], bytes, list[Any]]:
    corpus = generate_scoped(plan["seed"], id_base=plan["id_base"])
    extra = {
        "csi_no": f"CSI-{plan['extra_id_base'] + 1:06d}",
        "complaint_ru": f"Учебное CSI обращение: офис {plan['closed_branch_code']} закрыт. Клиенту не объяснили альтернативу обслуживания; прошу уточнить доступный офис.",
        "branch_code": plan["closed_branch_code"],
        "received_at": plan["clock"],
        "redirects": 0,
        "products": [],
    }
    blob = workbook_bytes([*corpus["complaints"], extra], dt.datetime.fromisoformat(plan["clock"]))
    parsed = parse_xlsx(blob)
    if len(parsed) != 301:
        raise PreparationError("CSI XLSX fixture не содержит301строку")
    if [validate_row(row.value) for row in parsed[:300]] != [validate_row(row) for row in corpus["complaints"]]:
        raise PreparationError("XLSX parser изменил canonical sample")
    return corpus, blob, parsed


async def reserve_csi(conn: psycopg.AsyncConnection[Any], run: int) -> dict[str, Any]:
    """Allocation фиксируется до import, не теряется при последующем rollback/restart."""
    async with conn.transaction():
        at, snapshot = await _context(conn, run)
        await conn.execute("select pg_advisory_xact_lock(hashtext('csi_cohort_import'))")
        old = snapshot.get(KEY)
        if old is not None:
            return validate_plan(old)
        base, extra_base = await _free_bases(conn)
        closed = await _closed(conn, at)
        corpus = generate_scoped(id_base=base)
        plan = {
            "version": 1,
            "id_base": base,
            "extra_id_base": extra_base,
            "seed": corpus["metadata"]["seed"],
            "clock": at.isoformat(),
            "closed_branch_code": closed["code"],
            "prepared": False,
        }
        source, blob, _ = _input(plan)
        plan.update(xlsx_sha256=hashlib.sha256(blob).hexdigest(), cohort_sha256=digest(source))
        await conn.execute(
            "update sim_runs set settings_snapshot=jsonb_set(coalesce(settings_snapshot,'{}'::jsonb),%s,%s) where id=%s",
            ([KEY], Jsonb(plan), run),
        )
        return plan


async def prepare_csi(conn: psycopg.AsyncConnection[Any], run: int) -> dict[str, Any]:
    async with conn.transaction():
        at, snapshot = await _context(conn, run)
        plan = validate_plan(snapshot.get(KEY))
        if dt.datetime.fromisoformat(plan["clock"]) != at:
            raise PreparationError(
                "Нет сохранённого T262 plan либо native clock изменился; создайте новый run без исправления истории"
            )
        await _closed(conn, at, plan["closed_branch_code"])
        await conn.execute("select pg_advisory_xact_lock(hashtext('csi_cohort_import'))")
        corpus, blob, parsed = _input(plan)
        if hashlib.sha256(blob).hexdigest() != plan["xlsx_sha256"] or digest(corpus) != plan["cohort_sha256"]:
            raise PreparationError("T262 source hash изменился; исходный namespace не переписывается")
        imported = await import_rows(conn, parsed)
        if imported["rejected"]:
            raise PreparationError("CSI normalizer отклонил XLSX; import TX откатывается")
        try:
            registered = await install_scoped_sample(conn, seed=plan["seed"], id_base=plan["id_base"])
        except CohortRegistrationError as exc:
            raise PreparationError(str(exc)) from exc
        if (
            registered["digest"] != plan["cohort_sha256"]
            or registered["members"] != 300
            or registered["visits"] != 2400
        ):
            raise PreparationError("CSI scoped registration не совпадает с plan")
        if not plan.get("prepared"):
            await conn.execute(
                "update sim_runs set settings_snapshot=jsonb_set(settings_snapshot,%s,%s) where id=%s",
                ([KEY], Jsonb({**plan, "prepared": True}), run),
            )
        return {
            "xlsx_sha256": plan["xlsx_sha256"],
            "cohort_sha256": registered["digest"],
            "id_base": plan["id_base"],
            "extra_id_base": plan["extra_id_base"],
            "imported": imported,
            "registered": registered,
            "closed_branch_code": plan["closed_branch_code"],
        }


async def evaluate_native(conn: psycopg.AsyncConnection[Any], scenario: dict[str, Any], run: int) -> dict[str, Any]:
    """Private checks используют только persisted факты своего run; неизвестные — not_verified."""
    from psycopg.rows import dict_row

    async def rows(sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        async with conn.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(sql, args)
            return list(await cursor.fetchall())

    signals = await rows("select * from signals where run_id=%s", (run,))
    agents = await rows("select id,outcome from agent_runs where sim_run_id=%s", (run,))
    checks: list[dict[str, Any]] = []
    for key, want in (scenario.get("expected") or {}).items():
        ok: bool | None = None
        detail = "not_verified: нет native проверки этого ключа"
        if key == "legal_pending_hitl":
            legal = [s for s in signals if s["red_words"] and s["client_id"] is not None]
            pending = await rows(
                "select signal_id from human_decisions where sim_run_id=%s and decision is null and reason='legal_regulatory'",
                (run,),
            )
            pending_ids = {r["signal_id"] for r in pending}
            ok = bool(legal) and all(
                s["id"] in pending_ids
                and s["product_line_code"] == "deposits"
                and (s["classification"] or {}).get("criticality") == "high"
                for s in legal
            )
            detail = f"identified red-word signals={len(legal)}, pending legal HITL={len(pending)}; human accept не выполняется"
        elif key == "ordinary_product_route":
            routes = await rows(
                "select s.signal_id,step.tool_calls from agent_runs s join agent_steps step on step.run_id=s.id join signals sig on sig.id=s.signal_id where s.sim_run_id=%s and step.node='act' and cardinality(sig.red_words)=0 and sig.product_line_code=%s",
                (run, want),
            )
            ok = any(
                call.get("name") == "route_to_product_team"
                and call.get("wraps") == ["route_to_department"]
                and (call.get("result") or {}).get("department") == "team_deposits"
                for row in routes
                for call in row["tool_calls"]
            )
            detail = f"обычный input: native facade deposits→team_deposits={ok}; не executed route legal input"
        elif key == "csi_registered_sample":
            header = await rows("select settings_snapshot from sim_runs where id=%s", (run,))
            try:
                plan = validate_plan(header[0]["settings_snapshot"].get(KEY)) if header else None
            except PreparationError:
                plan = None
            integrity = await rows("select is_complete from v_csi_cohort_integrity where run_id=%s", (run,))
            counts = (
                await rows(
                    "select (select count(*) from csi_responses c join signals s on s.id=c.signal_id where s.run_id=%s) responses,(select count(*) from csi_cohort_members where run_id=%s) members,(select sum(visits) from csi_cohort_visits where run_id=%s) visits",
                    (run, run, run),
                )
            )[0]
            extra = await rows(
                "select c.wait_min,c.service_min,c.employee_id,c.signal_id,b.branch_status from csi_responses c join signals s on s.id=c.signal_id join branches b on b.id=c.branch_id where s.run_id=%s and c.csi_no=%s and not exists(select 1 from csi_cohort_members m where m.signal_id=s.id)",
                (run, f"CSI-{plan['extra_id_base'] + 1:06d}" if plan else ""),
            )
            ok = (
                bool(plan and plan["prepared"])
                and counts == {"responses": 301, "members": 300, "visits": 2400}
                and len(integrity) == 10
                and all(r["is_complete"] for r in integrity)
                and len(extra) == 1
                and extra[0]["branch_status"] == "closed"
                and all(extra[0][k] is None for k in ("wait_min", "service_min", "employee_id"))
            )
            detail = f"native {counts}; complete cohorts={sum(r['is_complete'] for r in integrity)}; extra1 denominator unknown"
        checks.append({"code": key, "ok": ok, "detail": detail})
    native_passed = bool(checks) and all(c["ok"] is True for c in checks)
    checks.append(
        {
            "code": "native_mock_foundation",
            "ok": native_passed,
            "detail": "Только native backend Mock checks; не заменяют UI/replay acceptance",
        }
    )
    for index, pending in enumerate(scenario.get("pending_acceptance") or [], 1):
        checks.append({"code": f"pending_acceptance_{index}", "ok": None, "detail": f"not_verified: {pending}"})
    return {
        "passed": bool(checks) and all(c["ok"] is True for c in checks),
        "checks": checks,
        "counts": {
            "native_passed": native_passed,
            "signals": len(signals),
            "agent_runs": len(agents),
            "errors": sum(a["outcome"] in ("failed", "error") for a in agents),
            "not_verified": sum(c["ok"] is None for c in checks),
        },
    }
