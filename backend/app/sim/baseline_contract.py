"""Совместимость архива с DB contract и всеми прикладными схемами PostgreSQL."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
# Не ограничиваем public: checkpoint-таблицы LangGraph принадлежат отдельной схеме.
# Два исходящих FK сохраняемых заголовков restore намеренно возвращает NOT VALID.
# Это единственное допустимое отличие; остальные constraints сравниваются точно.
SQL = """
select n.nspname,c.relname,c.relkind,
 (select jsonb_agg(jsonb_build_array(a.attname,format_type(a.atttypid,a.atttypmod),
   a.attnotnull,a.attidentity,a.attgenerated,pg_get_expr(d.adbin,d.adrelid)) order by a.attnum)
  from pg_attribute a left join pg_attrdef d on d.adrelid=a.attrelid and d.adnum=a.attnum
  where a.attrelid=c.oid and a.attnum>0 and not a.attisdropped),
 (select jsonb_agg(case when n.nspname='public' and c.relname='sim_runs'
    and k.conname in ('sim_runs_scenario_fk','sim_runs_llm_profile_fk')
    then replace(pg_get_constraintdef(k.oid,true),' NOT VALID','')
    else pg_get_constraintdef(k.oid,true) end order by k.conname)
  from pg_constraint k where k.conrelid=c.oid),
 (select jsonb_agg(pg_get_indexdef(i.indexrelid) order by i.indexrelid::regclass::text)
  from pg_index i where i.indrelid=c.oid)
from pg_class c join pg_namespace n on n.oid=c.relnamespace
where n.nspname<>'information_schema' and n.nspname !~ '^pg_'
 and c.relkind in ('r','p','v','m','S','f')
order by n.nspname,c.relname
"""


class ContractDrift(ValueError):
    pass


def fingerprint(rows: Any) -> str:
    sources = [ROOT / "contracts/db/schema.sql"]
    sources += sorted((ROOT / "backend/migrations").glob("*.sql"))
    sources += sorted((ROOT / "backend/alembic/versions").glob("*.py"))
    digest = hashlib.sha256()
    for path in sources:
        digest.update(str(path.relative_to(ROOT)).encode() + b"\0" + path.read_bytes() + b"\0")
    digest.update(json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str).encode())
    return digest.hexdigest()


def read_sync(cur: Any) -> str:
    return fingerprint(cur.execute(SQL).fetchall())


async def read(conn: Any) -> str:
    return fingerprint(await (await conn.execute(SQL)).fetchall())


def validate(meta: dict[str, Any], actual: str) -> None:
    if meta.get("db_contract_fingerprint") != actual:
        raise ContractDrift(
            "DB contract/миграции или прикладные схемы изменились либо архив legacy. "
            "Пересоздайте baseline после применения актуальных миграций и повторите restore; данные не менялись"
        )
