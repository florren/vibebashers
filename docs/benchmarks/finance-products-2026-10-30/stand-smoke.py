"""Ручной smoke локального демо: создаёт два новых counters-запуска, паузит их, временно включает mock и восстанавливает режим."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = os.environ.get("CX_BASE_URL", "http://localhost:8000")
OUT = Path(os.environ.get("CX_SMOKE_OUTPUT", "/tmp/finance-products-stand.json"))


def request(path: str, body: dict | None = None) -> dict:
    encoded = json.dumps(body).encode() if body is not None else None
    with urlopen(Request(BASE + path, data=encoded, headers={"Content-Type": "application/json"}), timeout=30) as response:
        return json.load(response)


def scenario(label: str) -> dict:
    created = request("/api/scenarios/qr_fee_public_review/run", {"label": label, "reset_mode": "counters"})
    rid = created["run"]["id"]
    request("/api/sim/control", {"action": "pause"})
    for _ in range(60):
        total = request(f"/api/v1/finance/impact/total?run_id={rid}")
        if total["incidents_resolved"]:
            break
        time.sleep(1)
    else:
        raise AssertionError(f"Нет решённого кейса в запуске {rid}")
    assessment = request(f"/api/v1/finance/impact/assessment?run_id={rid}")
    assert assessment["contours"][1]["risk_total_rub"] is None
    assert assessment["contours"][1]["fine_rub"] is None
    detail = request(f"/api/v1/finance/impact/incident/{total['items'][0]['incident_id']}?run_id={rid}")
    return {"run_id": rid, "total": total, "assessment": assessment, "risks": detail["proof"]["risks"]}


def main() -> None:
    health = request("/api/health")
    assert health["db"] and health["status"] == "ok"
    original = request("/api/demo/status")["llm_mode"]
    report: dict = {"previous_mode": original, "health": {"status": health["status"], "db": health["db"]}}
    try:
        request("/api/demo/failover", {"component": "llm", "to": "live"})
        report["live"] = scenario("T-266 finance products · live")
        request("/api/demo/failover", {"component": "llm", "to": "mock"})
        report["mock"] = scenario("T-266 finance products · demo validation")
        mock = report["mock"]
        assert mock["run_id"] != report["live"]["run_id"]
        assert mock["assessment"]["contours"][0]["known_clients"] > 0
        assert mock["assessment"]["contours"][0]["risk_total_rub"] > 0
        code = mock["total"]["items"][0]["product_code"]
        checks = []
        for mode in ("include", "exclude"):
            query = urlencode({"run_id": mock["run_id"], "product_mode": mode, "product_codes": code})
            total = request("/api/v1/finance/impact/total?" + query)
            assessed = request("/api/v1/finance/impact/assessment?" + query)
            assert total["incidents_resolved"] == assessed["contours"][0]["case_count"]
            assert all((item["product_code"] == code) == (mode == "include") for item in total["items"])
            assert assessed["contours"][1]["risk_total_rub"] is None
            checks.append({"mode": mode, "product": code, "count": total["incidents_resolved"], "demo_risk": assessed["contours"][0]["risk_total_rub"], "observed_risk": None})
        report["filter_checks"] = checks
    finally:
        restored = request("/api/demo/failover", {"component": "llm", "to": original})
        report["restored_mode"] = restored["llm_mode"]
        report["final_state"] = request("/api/sim/state")
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"runs": {key: report[key]["run_id"] for key in ("live", "mock")}, "restored_mode": report["restored_mode"], "filter_checks": report["filter_checks"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
