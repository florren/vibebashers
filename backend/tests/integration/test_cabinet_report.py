"""T-244: настоящий HTTP/PG/XLSX, один источник и отсутствие writes/LLM."""

from io import BytesIO

import pytest
from openpyxl import load_workbook

from tests.integration import test_cabinet_api as helpers

cabinet_db = helpers.cabinet_db
client = helpers.client
sql = helpers.sql
assert_schema = helpers.assert_schema
fingerprint = helpers.fingerprint
preset = helpers.preset


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_report_real_json_xlsx_overview_readonly(client, sql, monkeypatch, lang):
    async def bomb(*args, **kwargs):
        raise AssertionError("report must not invoke LLM or economics write producer")

    monkeypatch.setattr("app.llm.failover.ProviderChain.complete_structured", bomb)
    monkeypatch.setattr("app.economics.dcltv.compute_incident", bomb)
    before = fingerprint(sql)
    query = {"product_line": "deposits", "period": "month", "lang": lang}
    response = client.get("/api/cabinet/report", params=query)
    assert response.status_code == 200, response.text[:300]
    data = response.json()
    assert_schema(data, "CabinetReport")
    assert data["overview"] == client.get("/api/cabinet/overview", params=query).json()
    assert len(data["summary_ru"]) == len(data["summary"]) == 5
    assert len(data["signals"]) == data["overview"]["kpi"]["signals"]
    xlsx = client.get("/api/cabinet/report", params={**query, "format": "xlsx"})
    assert xlsx.status_code == 200
    assert len(xlsx.content) <= 5 * 1024 * 1024
    wb = load_workbook(BytesIO(xlsx.content))
    assert [row[0].value for row in list(wb["Главное"].rows)[1:6]] == data["summary"]
    for row, kpi in zip(list(wb["KPI"].rows)[1:], data["kpi"], strict=True):
        if kpi["unit"] == "RUB":
            assert (
                row[1].value
                == data["money_exact"]["kpi"]["potential_loss_rub" if kpi["code"] == "loss" else "prevented_loss_rub"]
            )
        else:
            # Только fractions: Excel хранит 15–16 значащих цифр. Деньги проверяются text exact.
            assert (
                row[1].value is None
                if kpi["value"] is None
                else row[1].value == pytest.approx(kpi["value"], rel=0, abs=1e-14)
            )
    assert wb["Сигналы"].max_row - 1 == len(data["signals"])
    for sheet in wb:
        assert all(cell.data_type != "f" and cell.hyperlink is None for row in sheet for cell in row)
    assert fingerprint(sql) == before


@pytest.mark.parametrize(
    "product,headers,status",
    [
        ("all", {"X-Cx-Role": "product_manager", "X-Cx-Product-Line": "deposits"}, 403),
        ("mortgage", {"X-Cx-Role": "product_manager", "X-Cx-Product-Line": "deposits"}, 403),
        ("deposits", {"X-Cx-Role": "product_manager"}, 403),
        ("invalid", {}, 422),
    ],
)
@pytest.mark.parametrize("format", ["json", "xlsx"])
def test_export_guard_before_data(client, sql, product, headers, status, format):
    with preset(sql, "strict"):
        response = client.get(
            "/api/cabinet/report", params={"product_line": product, "format": format}, headers=headers
        )
        assert response.status_code == status


@pytest.mark.parametrize("run", ["", "²", "١", "0", "-1", "9223372036854775808"])
def test_report_invalid_run(client, run):
    assert client.get("/api/cabinet/report", params={"product_line": "deposits", "run_id": run}).status_code == 422


def test_report_missing_current_is_not_all_and_no_fake_money(client, sql):
    old = sql.execute("select current_run_id from sim_state where id=1").fetchone()[0]
    sql.execute("update sim_state set current_run_id=null where id=1")
    try:
        data = client.get("/api/cabinet/report?product_line=deposits").json()
        assert all(
            r[0] in data["overview"]["scope"]["run_ids"]
            for r in sql.execute("select id from sim_runs where kind='baseline'")
        )
        assert data["overview"]["scope"]["run_ids"] is not None
        assert data["method"]["requested_run"] == "current"
    finally:
        sql.execute("update sim_state set current_run_id=%s where id=1", (old,))


def test_export_bound_no_silent_truncation(client, monkeypatch):
    monkeypatch.setattr("app.analytics.cabinet_report.MAX_SIGNALS", 0)
    for format in ["json", "xlsx"]:
        response = client.get("/api/cabinet/report", params={"product_line": "all", "format": format})
        assert response.status_code == 413


def test_report_all_current_foreign_scope_and_empty_window(client, sql):
    pointer = sql.execute("select current_run_id from sim_state where id=1").fetchone()[0]
    foreign = sql.execute(
        "insert into sim_runs(kind,label,seed,started_sim) select 'live','T244 isolated fixture',42,sim_time from sim_state where id=1 returning id"
    ).fetchone()[0]
    original = sql.execute(
        "select id,run_id from signals where product_line_code='deposits' order by received_sim desc limit 1"
    ).fetchone()
    try:
        sql.execute("update signals set run_id=%s where id=%s", (foreign, original[0]))
        sql.execute("update sim_state set current_run_id=null where id=1")
        own = client.get("/api/cabinet/report?product_line=deposits&period=quarter").json()
        chosen = client.get(
            "/api/cabinet/report", params={"product_line": "deposits", "period": "quarter", "run_id": foreign}
        ).json()
        all_runs = client.get("/api/cabinet/report?product_line=deposits&period=quarter&run_id=all").json()
        assert original[0] not in {s["id"] for s in own["signals"]}
        assert original[0] in {s["id"] for s in chosen["signals"]}
        assert len(all_runs["signals"]) == len(own["signals"]) + 1
        old_time = sql.execute("select sim_time from sim_state where id=1").fetchone()[0]
        try:
            sql.execute("update sim_state set sim_time=sim_time+interval '1000 days' where id=1")
            empty = client.get("/api/cabinet/report?product_line=deposits&period=day").json()
            assert empty["overview"]["kpi"]["signals"] == 0
            assert empty["signals"] == empty["top_problems"] == empty["attention"] == []
            assert "нет" in empty["summary_ru"][0]
        finally:
            sql.execute("update sim_state set sim_time=%s where id=1", (old_time,))
    finally:
        sql.execute("update signals set run_id=%s where id=%s", (original[1], original[0]))
        sql.execute("update sim_state set current_run_id=%s where id=1", (pointer,))
        sql.execute("delete from sim_runs where id=%s", (foreign,))


@pytest.fixture(scope="module")
def materialized_economics(cabinet_db):
    import asyncio

    import psycopg
    from psycopg.rows import dict_row

    from app.economics.dcltv import compute_incident

    async def prepare():
        async with await psycopg.AsyncConnection.connect(
            cabinet_db.replace("postgresql+psycopg:", "postgresql:"), row_factory=dict_row
        ) as conn:
            ids = await (await conn.execute("select id from incidents order by id")).fetchall()
            for row in ids:
                await compute_incident(conn, row["id"])

    asyncio.run(prepare())


def test_report_saved_formula_and_raw_contacts_never_escape(client, sql, materialized_economics, monkeypatch):
    def no_compute(*args, **kwargs):
        raise AssertionError("report cannot recalculate saved economics")

    monkeypatch.setattr("app.economics.dcltv.compute", no_compute)
    before = fingerprint(sql)
    data = client.get("/api/cabinet/report?product_line=all&period=quarter").json()
    assert data["method"]["formula_ru"]
    assert all("×" in formula or "*" in formula for formula in data["method"]["formula_ru"])
    expected = sql.execute("select sum(potential_loss_rub),sum(prevented_loss_rub) from incident_economics").fetchone()
    assert data["overview"]["kpi"]["potential_loss_rub"] == float(expected[0])
    assert data["overview"]["kpi"]["prevented_loss_rub"] == float(expected[1])
    assert before == fingerprint(sql)
    old = sql.execute(
        "select id,text,classification from signals where product_line_code='deposits' order by id limit 1"
    ).fetchone()
    from psycopg.types.json import Jsonb

    contact = "qa-private@example.com +7 900 123-45-67"
    try:
        sql.execute("update signals set text=%s,classification='{}'::jsonb where id=%s", (contact, old[0]))
        response = client.get("/api/cabinet/report?product_line=deposits&period=quarter")
        assert response.status_code == 200
        assert "qa-private@example.com" not in response.text
        assert "+7 900 123-45-67" not in response.text
        raw = client.get("/api/cabinet/report?product_line=deposits&period=quarter&format=xlsx")
        wb = load_workbook(BytesIO(raw.content))
        values = " ".join(str(cell.value) for ws in wb for row in ws for cell in row)
        assert "qa-private@example.com" not in values
        assert "+7 900 123-45-67" not in values
    finally:
        sql.execute("update signals set text=%s,classification=%s where id=%s", (old[1], Jsonb(old[2]), old[0]))


def test_large_saved_money_preserves_cents_exactly_in_json_and_xlsx(client, sql, materialized_economics):
    from decimal import Decimal

    saved = sql.execute(
        "select incident_id,potential_loss_rub,prevented_loss_rub from incident_economics order by incident_id"
    ).fetchall()
    assert len(saved) >= 11  # SUM допустимых numeric(14,2) пересекает 15 значащих цифр.
    import datetime as dt

    now = sql.execute("select sim_time from sim_state where id=1").fetchone()[0]
    cutoff = now - dt.timedelta(days=7)
    try:
        # Предыдущее окно — известные сохранённые нули, текущее — большой aggregate.
        sql.execute(
            "update incident_economics e set potential_loss_rub=case when i.created_sim>=%s then 999999999999.99 else 0 end, prevented_loss_rub=case when i.created_sim>=%s then 999999999999.97 else 0 end from incidents i where i.id=e.incident_id",
            (cutoff, cutoff),
        )
        first = sql.execute(
            "select e.incident_id from incident_economics e join incidents i on i.id=e.incident_id where i.created_sim between %s and %s order by i.id limit 1",
            (cutoff, now),
        ).fetchone()[0]
        sums = sql.execute(
            "select sum(e.potential_loss_rub),sum(e.prevented_loss_rub) from incident_economics e join incidents i on i.id=e.incident_id where i.created_sim between %s and %s",
            (cutoff, now),
        ).fetchone()
        # Подбирается fixture, не экономическая формула: обе суммы оканчиваются .99,
        # чтобы целое число строк не скрыло потерю копеек в float/Excel.
        adjustments = [value - (value // 1 - 1 + Decimal("0.99")) for value in sums]
        sql.execute(
            "update incident_economics set potential_loss_rub=potential_loss_rub-%s,prevented_loss_rub=prevented_loss_rub-%s where incident_id=%s",
            (*adjustments, first),
        )
        expected = sql.execute(
            "select sum(potential_loss_rub),sum(prevented_loss_rub) from incident_economics"
        ).fetchone()
        assert all(value % 1 == Decimal(".99") and Decimal(float(value)) != value for value in expected)
        assert expected[0] > Decimal("10000000000000")
        before = fingerprint(sql)
        for period in ["quarter", "week"]:
            data = client.get("/api/cabinet/report", params={"product_line": "all", "period": period}).json()
            assert Decimal(data["money_exact"]["kpi"]["potential_loss_rub"]) == expected[0]
            assert Decimal(data["money_exact"]["kpi"]["prevented_loss_rub"]) == expected[1]
            if period == "week":
                assert Decimal(data["money_exact"]["previous"]["potential_loss_rub"]) == 0
                assert Decimal(data["money_exact"]["previous"]["prevented_loss_rub"]) == 0
                assert Decimal(data["money_exact"]["kpi"]["potential_loss_delta_rub"]) == expected[0]
                assert Decimal(data["money_exact"]["kpi"]["prevented_loss_delta_rub"]) == expected[1]
            raw = client.get("/api/cabinet/report", params={"product_line": "all", "period": period, "format": "xlsx"})
            assert raw.status_code == 200
            wb = load_workbook(BytesIO(raw.content))
            cells = list(wb["KPI"].rows)[1:]
            assert cells[3][1].data_type == "s"
            assert Decimal(cells[3][1].value) == expected[0]
            assert Decimal(cells[4][1].value) == expected[1]
            if period == "week":
                assert cells[3][3].data_type == "s" and Decimal(cells[3][3].value) == expected[0]
                assert cells[4][3].data_type == "s" and Decimal(cells[4][3].value) == expected[1]
            for row, exact in zip(list(wb["Динамика"].rows)[1:31], data["money_exact"]["daily"], strict=True):
                assert row[3].value == exact["potential_loss_rub"]
                assert row[4].value == exact["prevented_loss_rub"]
        assert before == fingerprint(sql)
    finally:
        for ident, potential, prevented in saved:
            sql.execute(
                "update incident_economics set potential_loss_rub=%s,prevented_loss_rub=%s where incident_id=%s",
                (potential, prevented, ident),
            )


def test_demo_report_p95_includes_first_get(client, sql):
    import math
    import time

    assert sql.execute("select count(*) from clients").fetchone()[0] == 5000
    samples = []
    for _ in range(30):
        start = time.perf_counter()
        response = client.get("/api/cabinet/report?product_line=all&period=quarter")
        samples.append((time.perf_counter() - start) * 1000)
        assert response.status_code == 200
    assert sorted(samples)[math.ceil(len(samples) * 0.95) - 1] < 300, {"samples_ms": samples}


@pytest.fixture
def native_sla_case(sql, cabinet_db):
    """Настоящий normalizer/tools/SlaEngine; GET проверяется после fixture commit."""
    import asyncio
    import datetime as dt

    import psycopg

    from app.agent.tools.base import ToolContext
    from app.agent.tools.write import create_incident, update_incident
    from app.ingest.normalizer import create_signal, from_api_signal
    from app.sim.events import EventBus
    from app.sim.sla import SlaEngine

    now = sql.execute("select sim_time from sim_state where id=1").fetchone()[0]
    run = sql.execute(
        "insert into sim_runs(kind,label,seed,started_sim) values('free','T244 native warning fixture',42,%s) returning id",
        (now - dt.timedelta(days=3),),
    ).fetchone()[0]
    foreign = sql.execute(
        "insert into sim_runs(kind,label,seed,started_sim) values('free','T244 foreign warning fixture',42,%s) returning id",
        (now,),
    ).fetchone()[0]

    async def prepare():
        async with await psycopg.AsyncConnection.connect(
            cabinet_db.replace("postgresql+psycopg:", "postgresql:")
        ) as conn:
            created = now - dt.timedelta(days=3)
            signal = await create_signal(
                conn,
                from_api_signal(
                    {
                        "text": "Проверка записанного риска по вкладу.",
                        "external_id": f"t244-native-{run}",
                        "channel_code": "chat",
                    }
                ),
                source_code="api",
                run_id=run,
                sim_time=created,
            )
            sid = signal["signal_id"]
            await conn.execute(
                "update signals set product_line_code='deposits',classification='{"
                + '"criticality":"medium","signal_type":"tariff_terms"'
                + "}'::jsonb where id=%s",
                (sid,),
            )
            agent = (
                await (
                    await conn.execute(
                        "insert into agent_runs(sim_run_id,signal_id,prompt_version,started_sim) values(%s,%s,'t244-native-fixture',%s) returning id",
                        (run, sid, created),
                    )
                ).fetchone()
            )[0]
            ctx = ToolContext(conn, run_id=run, agent_run_id=agent, sim_time=created, llm_source="mock")
            incident = await create_incident(
                ctx,
                sid,
                None,
                {
                    "title_ru": "Проверка native SLA для вклада",
                    "team": "team_deposits",
                    "product": "deposit",
                    "complexity": "medium",
                    "criticality": "medium",
                    "sla": {
                        "due_sim": (now + dt.timedelta(hours=2)).isoformat(),
                        "take_due_sim": (now + dt.timedelta(hours=1)).isoformat(),
                    },
                },
            )
            iid = incident["incident_id"]
            ctx.sim_time = created + dt.timedelta(minutes=1)
            await update_incident(ctx, iid, "in_progress", "fixture: работа принята")
            engine = SlaEngine(conn, EventBus(conn), run)
            await engine.load()
            await engine.tick(now - dt.timedelta(minutes=15), now)
            event = await (
                await conn.execute(
                    "select id,payload from sim_events where run_id=%s and event_type='sla.warning' and payload->>'incident_id'=%s",
                    (run, str(iid)),
                )
            ).fetchone()
            assert event is not None and event[1]["remaining_pct"] < 25
            return {
                "run": run,
                "foreign": foreign,
                "incident": iid,
                "public_id": incident["public_id"],
                "agent": agent,
                "now": now,
                "event": event[0],
                "payload": event[1],
            }

    try:
        yield asyncio.run(prepare())
    finally:
        sql.execute("update sim_state set sim_time=%s where id=1", (now,))
        sql.execute("delete from sim_runs where id=ANY(%s)", ([run, foreign],))


@pytest.mark.parametrize(
    "state", ["current", "closed", "reopened", "release", "changed_deadline", "same_clock", "foreign"]
)
def test_native_sla_warning_current_stage_scope_and_recorded_actions(client, sql, cabinet_db, native_sla_case, state):
    import asyncio
    import datetime as dt

    import psycopg

    from app.agent.tools.base import ToolContext
    from app.agent.tools.write import update_incident
    from app.sim.events import EventBus

    case = native_sla_case

    async def transition():
        async with await psycopg.AsyncConnection.connect(
            cabinet_db.replace("postgresql+psycopg:", "postgresql:")
        ) as conn:
            ctx = ToolContext(
                conn,
                run_id=case["run"],
                agent_run_id=case["agent"],
                sim_time=case["now"] + dt.timedelta(minutes=1),
                llm_source="mock",
            )
            if state in ("closed", "reopened"):
                await update_incident(ctx, case["incident"], "resolved", "fixture: завершение стадии")
                ctx.sim_time += dt.timedelta(minutes=1)
                await update_incident(
                    ctx, case["incident"], "closed" if state == "closed" else "in_progress", "fixture: следующая стадия"
                )
            elif state == "same_clock":
                ctx.sim_time = case["now"]
                await update_incident(ctx, case["incident"], "fix_proposed", "fixture: новая стадия")
                await update_incident(ctx, case["incident"], "in_progress", "fixture: возврат в работу")
            elif state == "foreign":
                # Валидированный negative fixture через native EventBus, не fake API ответ.
                await EventBus(conn).emit(case["foreign"], "sla.warning", case["payload"], ctx.sim_time)

    asyncio.run(transition())
    if state == "release":
        # Явная synthetic запись действия: проверяем legacy release без смены status.
        sql.execute(
            "insert into team_actions(run_id,incident_id,team_code,action,action_sim) values(%s,%s,'team_deposits','release',%s)",
            (case["run"], case["incident"], case["now"] + dt.timedelta(minutes=1)),
        )
    if state == "changed_deadline":
        sql.execute("update incidents set sla_due_sim=sla_due_sim+interval '1 hour' where id=%s", (case["incident"],))
    sql.execute("update sim_state set sim_time=%s where id=1", (case["now"] + dt.timedelta(minutes=3),))
    params = {"product_line": "deposits", "period": "week", "run_id": str(case["run"])}
    before = fingerprint(sql)
    response = client.get("/api/cabinet/report", params=params)
    assert response.status_code == 200, response.text[:200]
    data = response.json()
    assert_schema(data, "CabinetReport")
    expected = state in ("current", "foreign")
    assert data["sla_warning_count"] == int(expected)
    matches = [row for row in data["attention"] if row["public_id"] == case["public_id"]]
    assert bool(matches) == expected
    if expected:
        assert matches[0]["sla_warning_event_id"] == case["event"]
        assert matches[0]["sla_warning_current"] is True
    if state == "release":
        row = next(row for row in data["top_problems"] if row["public_id"] == case["public_id"])
        assert row["action"] == "Записан релиз исправления"
    absent = client.get("/api/cabinet/report", params={**params, "run_id": "current"}).json()
    assert absent["sla_warning_count"] == 0
    assert case["public_id"] not in {row["public_id"] for row in absent["top_problems"]}
    if state == "foreign":
        all_runs = client.get("/api/cabinet/report", params={**params, "run_id": "all"}).json()
        assert all_runs["sla_warning_count"] == 1  # Чужое warning не удваивает cohort.
    assert before == fingerprint(sql)


@pytest.mark.parametrize("period", ["day", "week"])
def test_all_kpi_deltas_match_raw_scoped_observations_and_exact_saved_money(
    client, sql, materialized_economics, period
):
    import datetime as dt
    from decimal import Decimal

    data = client.get("/api/cabinet/report", params={"product_line": "all", "period": period}).json()
    run_ids = data["overview"]["scope"]["run_ids"]

    def observed(start, end):
        signals = sql.execute(
            "select count(*),count(*) filter(where sentiment in ('positive','neutral','negative')),count(*) filter(where sentiment='negative'),count(*) filter(where classification->>'criticality' in ('high','medium','low')),count(*) filter(where classification->>'criticality'='high') from signals where origin is distinct from 'proactive' and run_id=ANY(%s) and received_sim between %s and %s",
            (run_ids, start, end),
        ).fetchone()
        money = sql.execute(
            "select count(*),count(e.computed_at),sum(e.potential_loss_rub),sum(e.prevented_loss_rub) from incidents i left join incident_economics e on e.incident_id=i.id where i.run_id=ANY(%s) and i.created_sim between %s and %s",
            (run_ids, start, end),
        ).fetchone()
        return signals, money

    current = observed(data["overview"]["scope"]["since_sim"], data["overview"]["scope"]["sim_time"])
    previous = observed(data["previous"]["since_sim"], data["previous"]["sim_time"])
    assert dt.datetime.fromisoformat(data["previous"]["sim_time"]) < dt.datetime.fromisoformat(
        data["overview"]["scope"]["since_sim"]
    )
    assert dt.datetime.fromisoformat(data["previous"]["sim_time"]) - dt.datetime.fromisoformat(
        data["previous"]["since_sim"]
    ) == dt.datetime.fromisoformat(data["overview"]["scope"]["sim_time"]) - dt.datetime.fromisoformat(
        data["overview"]["scope"]["since_sim"]
    )
    old = data["previous"]["kpi"]
    assert [old[key] for key in ["signals", "sentiment_known", "negative", "criticality_known", "critical"]] == list(
        previous[0]
    )
    assert old["incidents"] == previous[1][0] and old["economics_known"] == previous[1][1]
    rows = {row["code"]: row for row in data["kpi"]}
    assert rows["signals"]["delta"] == current[0][0] - previous[0][0]
    assert rows["incidents"]["delta"] == current[1][0] - previous[1][0]
    for code, numerator, denominator in [("negative", 2, 1), ("critical", 4, 3)]:
        if current[0][denominator] and previous[0][denominator]:
            expected = (
                current[0][numerator] / current[0][denominator] - previous[0][numerator] / previous[0][denominator]
            ) * 100
            assert rows[code]["delta"] == pytest.approx(expected, rel=0, abs=1e-12)
        else:
            assert rows[code]["delta"] is None
        assert rows[code]["delta_unit"] == "percentage_points"
    for code, column, key in [("loss", 2, "potential_loss_delta_rub"), ("prevented", 3, "prevented_loss_delta_rub")]:
        assert rows[code]["delta_unit"] == "RUB"
        if (
            current[1][0] == current[1][1]
            and previous[1][0] == previous[1][1]
            and current[1][column] is not None
            and previous[1][column] is not None
        ):
            assert Decimal(data["money_exact"]["kpi"][key]) == current[1][column] - previous[1][column]
        else:
            assert data["money_exact"]["kpi"][key] is None
    raw = client.get("/api/cabinet/report", params={"product_line": "all", "period": period, "format": "xlsx"}).content
    wb = load_workbook(BytesIO(raw))
    cells = list(wb["KPI"].rows)[1:]
    assert cells[1][1].number_format == "0.0%" and "п.п." in cells[1][3].number_format
    assert cells[3][3].value == data["money_exact"]["kpi"]["potential_loss_delta_rub"]
    assert cells[4][3].value == data["money_exact"]["kpi"]["prevented_loss_delta_rub"]


def test_incomplete_previous_economics_is_unknown_delta_without_materialization(
    client, sql, materialized_economics, monkeypatch
):
    from psycopg import sql as pgsql
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb

    def bomb(*args, **kwargs):
        raise AssertionError("missing saved facts must not be repaired by a report")

    monkeypatch.setattr("app.economics.dcltv.compute", bomb)
    data = client.get("/api/cabinet/report?product_line=all&period=week").json()
    with sql.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "select e.* from incident_economics e join incidents i on i.id=e.incident_id where i.created_sim between %s and %s order by i.id limit 1",
            (data["previous"]["since_sim"], data["previous"]["sim_time"]),
        ).fetchone()
    assert row is not None
    sql.execute("delete from incident_economics where incident_id=%s", (row["incident_id"],))
    try:
        before = fingerprint(sql)
        missing = client.get("/api/cabinet/report?product_line=all&period=week").json()
        assert missing["previous"]["kpi"]["economics_known"] < missing["previous"]["kpi"]["incidents"]
        assert missing["money_exact"]["previous"]["potential_loss_rub"] is None
        assert missing["money_exact"]["kpi"]["potential_loss_delta_rub"] is None
        assert missing["money_exact"]["kpi"]["prevented_loss_delta_rub"] is None
        assert before == fingerprint(sql)
    finally:
        values = [Jsonb(value) if isinstance(value, (dict, list)) else value for value in row.values()]
        sql.execute(
            pgsql.SQL("insert into incident_economics ({}) values ({})").format(
                pgsql.SQL(",").join(map(pgsql.Identifier, row)),
                pgsql.SQL(",").join([pgsql.Placeholder() for _ in values]),
            ),
            values,
        )
