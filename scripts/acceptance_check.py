"""T262: проверка существующих read API/XLSX после native Mock подготовки.

Не утверждает UI/replay приёмку и не создаёт кассеты/решения HITL.
"""

from __future__ import annotations

import io
from typing import Any

import httpx
from openpyxl import load_workbook


async def verify_reads(
    http: httpx.AsyncClient,
    scenario_id: str,
    run: int,
    plan: dict[str, Any] | None,
    signal_refs: list[str] | None = None,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def check(code: str, ok: bool, detail: str) -> None:
        checks.append({"code": code, "ok": ok, "detail": detail})

    if scenario_id == "cabinet_red_words_report":
        preview = await http.get(
            "/api/metrics/economics/preview",
            params={"rate_code": "deposit", "affected": 1},
        )
        preview.raise_for_status()
        value = preview.json()
        check(
            "canonical_rate_961",
            value.get("rate_code") == "deposit" and value.get("rate_rub") == 961,
            "read-only canonical deposit rate; формула не меняется",
        )
        report_params = {"run_id": str(run), "product_line": "deposits", "period": "day", "lang": "ru"}
        headers = {"X-Cx-Role": "product_manager", "X-Cx-Product-Line": "deposits"}
        report = await http.get("/api/cabinet/report", params=report_params, headers=headers)
        report.raise_for_status()
        report_refs = {r["public_id"] for r in report.json()["signals"]}
        check(
            "native_inputs_in_report",
            bool(signal_refs) and set(signal_refs or []) <= report_refs,
            "оба native input refs присутствуют в product-scoped report",
        )
        response = await http.get(
            "/api/cabinet/report",
            params={
                "run_id": str(run),
                "product_line": "deposits",
                "period": "day",
                "format": "xlsx",
                "lang": "ru",
            },
            headers={"X-Cx-Role": "product_manager", "X-Cx-Product-Line": "deposits"},
        )
        response.raise_for_status()
        workbook = load_workbook(
            io.BytesIO(response.content),
            read_only=True,
            data_only=False,
            keep_links=False,
        )
        try:
            check(
                "actual_xlsx_report",
                {"Главное", "KPI", "Сигналы", "Методика"} <= set(workbook.sheetnames)
                and any(True for _ in workbook["Сигналы"].iter_rows(min_row=2)),
                "существующий HTTP exporter; настоящий XLSX parser",
            )
        finally:
            workbook.close()
    else:
        response = await http.get("/api/csi/analytics", params={"run_id": str(run), "period": "quarter"})
        response.raise_for_status()
        data = response.json()
        probability = data["probabilities"]
        check(
            "scoped_probability_denominator",
            probability.get("sample_complaints") == 300
            and probability.get("sample_visits") == 2400
            and probability.get("complete_cohorts") == 10,
            "registered native 300/2400; extra1 без знаменателя",
        )
        check(
            "csi_coverage",
            data["coverage"]["complaints"] == 301
            and data["coverage"]["uncohorted"] == 1
            and len(data["top_branches"]) == 10,
            "native received scope, top10; unknown extra1 не становится sampled",
        )
        if not plan:
            check("closed_branch", False, "нет сохранённого allocation manifest")
        else:
            response = await http.get(
                "/api/branches/" + plan["closed_branch_code"],
                params={"run_id": str(run), "period": "quarter"},
            )
            response.raise_for_status()
            branch = response.json()
            # Shape определяется существующим branch API, без нового endpoint.
            check(
                "closed_branch",
                branch.get("branch", {}).get("branch_status") == "closed"
                and branch["signals"]["total"] == 1
                and branch["csi"]["probabilities"]["sample_visits"] is None,
                "native closed ВСП, без изменения даты/статуса",
            )
    return checks
