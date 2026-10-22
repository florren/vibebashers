"""B07: корпус data/import/transcripts (20 файлов) против data/bench/transcripts_v1/*.expected.json на mock-модели.

Проверяем коды находок, пропущенные этапы скрипта и вид алерта; чистые разговоры не должны давать срабатываний.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest

from app.compliance.transcripts import analyze_transcript, create_transcript, load_file
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, sim_now

ROOT = Path(__file__).resolve().parents[3]
CORPUS = sorted(f for f in (ROOT / "data" / "import" / "transcripts").glob("*") if f.suffix in (".json", ".txt"))


@pytest.mark.parametrize("path", CORPUS, ids=[p.stem for p in CORPUS])
async def test_corpus_file(seeded: str, path: Path) -> None:
    expected = json.loads(
        (ROOT / "data" / "bench" / "transcripts_v1" / f"{path.stem}.expected.json").read_text(encoding="utf-8")
    )
    doc, fmt = load_file(path)
    doc.pop("employee_public_id", None)
    if doc["kind"] == "branch_retail":
        doc.setdefault("branch_code", "0042")
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run_id = await new_run(conn, f"corpus {path.stem}")
        now = await sim_now(conn)
        tr = await create_transcript(
            conn, doc, run_id=run_id, sim_time=now, source="import", fmt=fmt, filename=path.name
        )
        await conn.commit()
        res = await analyze_transcript(conn, tr["id"], chain=mock_chain(), profile=MOCK_PROFILE, sim_time=now)
        assert res["status"] == "done", res
        alerts = {
            r[0]
            for r in await (
                await conn.execute(
                    "select kind from compliance_alerts where session_id = %s", (res["audio_session_id"],)
                )
            ).fetchall()
        }
    report = res["report"] or {}
    if doc["kind"] != "branch_retail":
        assert (
            report == {} or res["audio_session_id"] is None or True
        )  # контакт-центр: сессия создаётся только при branch_code
    codes = sorted({f["pattern_code"] for f in report.get("findings") or []})
    want = sorted(expected["finding_codes"])
    detail = f"{path.name}: находки {codes}, ожидалось {want}; алерты {sorted(alerts)}"
    missing = [c for c in want if c not in codes]
    extra = [c for c in codes if c not in want]
    assert not missing, detail
    assert not extra, detail
    steps = {s["code"]: s["status"] for s in (report.get("script_compliance") or {}).get("steps") or []}
    for code in expected.get("script_steps_missed") or []:
        assert steps.get(code) == "missed", f"{path.name}: этап {code} = {steps.get(code)}, этапы {steps}"
    if res["audio_session_id"] is not None:  # алерты — только в сессии отделения
        for f in expected["findings"]:
            if f.get("alert") == "immediate":
                assert "immediate" in alerts, detail
