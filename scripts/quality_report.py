"""Отчёт о качестве в файлы: data/reports/quality-<ts>.md и .json (docs/REPORTS.md).

make report                       # все запуски, из БД (DATABASE_URL), без HTTP-метрик
make report RUN=12                # один запуск эмуляции
python scripts/quality_report.py --base http://localhost:8000   # через API работающего стенда (с HTTP-метриками)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
OUT = ROOT / "data" / "reports"


async def _from_db(run_id: int | None) -> dict:
    import psycopg
    from psycopg.rows import dict_row

    from app.db.session import psycopg_dsn
    from app.observability.quality import build_quality_report

    async with await psycopg.AsyncConnection.connect(psycopg_dsn(), row_factory=dict_row) as conn:
        return await build_quality_report(conn, run_id, include_http=False)


def _from_api(base: str, run_id: int | None) -> dict:
    import httpx

    r = httpx.get(f"{base.rstrip('/')}/api/reports/quality", params={"run_id": run_id or "all"}, timeout=60)
    r.raise_for_status()
    return r.json()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--run", type=int, default=int(os.environ.get("RUN") or 0) or None, help="id запуска эмуляции; по умолчанию все"
    )
    ap.add_argument(
        "--base", default=os.environ.get("CX_BASE_URL"), help="URL стенда: отчёт берётся через API (с HTTP-метриками)"
    )
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--stdout", action="store_true", help="печатать Markdown в stdout вместо файлов")
    a = ap.parse_args()

    from app.observability.quality import render_markdown

    rep = _from_api(a.base, a.run) if a.base else asyncio.run(_from_db(a.run))
    md = render_markdown(rep)
    if a.stdout:
        print(md)  # noqa: T201
        return 0
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    (out / f"quality-{ts}.md").write_text(md, encoding="utf-8")
    (out / f"quality-{ts}.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (out / "latest.md").write_text(md, encoding="utf-8")
    s = rep["summary"]
    head = (
        f"отчёт: {out / f'quality-{ts}.md'} · здоровье {s['health']}/100 · рекомендаций {len(rep['recommendations'])}"
    )
    print(head)  # noqa: T201
    for r in rep["recommendations"][:5]:
        print(f"  [{r['severity']}] {r['text']}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
