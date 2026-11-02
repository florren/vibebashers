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
    try:
        sql.execute(
            "update incident_economics set potential_loss_rub=999999999999.99,prevented_loss_rub=999999999999.97"
        )
        # Число строк может быть кратно 100: отдельно сохраняем ненулевые копейки,
        # иначе крупный целый SUM не поймает потерю precision в JSON/Excel.
        sql.execute(
            "update incident_economics set potential_loss_rub=potential_loss_rub-0.01,prevented_loss_rub=prevented_loss_rub-0.01 where incident_id=%s",
            (saved[0][0],),
        )
        expected = sql.execute(
            "select sum(potential_loss_rub),sum(prevented_loss_rub) from incident_economics"
        ).fetchone()
        assert all(value % 1 != 0 and Decimal(float(value)) != value for value in expected)
        assert expected[0] > Decimal("10000000000000")
        before = fingerprint(sql)
        data = client.get("/api/cabinet/report?product_line=all&period=quarter").json()
        assert Decimal(data["money_exact"]["kpi"]["potential_loss_rub"]) == expected[0]
        assert Decimal(data["money_exact"]["kpi"]["prevented_loss_rub"]) == expected[1]
        raw = client.get("/api/cabinet/report?product_line=all&period=quarter&format=xlsx")
        assert raw.status_code == 200
        wb = load_workbook(BytesIO(raw.content))
        cells = {row[0].value: row[1] for row in list(wb["KPI"].rows)[1:]}
        assert cells[data["kpi"][3]["label"]].data_type == "s"
        assert Decimal(cells[data["kpi"][3]["label"]].value) == expected[0]
        assert Decimal(cells[data["kpi"][4]["label"]].value) == expected[1]
        # Ряд по дням/месяцам тоже транспортирует сохранённые деньги точно.
        for row, exact in zip(list(wb["Динамика"].rows)[1:31], data["money_exact"]["daily"], strict=True):
            assert row[3].value == exact["potential_loss_rub"]
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
    assert sorted(samples)[math.ceil(len(samples) * 0.95) - 1] < 300
