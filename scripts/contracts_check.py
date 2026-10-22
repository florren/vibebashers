"""Проверка контрактов: синтаксис DDL (pglast), мета-валидность JSON-схем, валидность OpenAPI,
соответствие перечислений schema.sql ↔ common.schema.json. Запуск: python scripts/contracts_check.py"""
from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
C = ROOT / "contracts"
errors: list[str] = []

# 1. DDL
try:
    import pglast

    pglast.parse_sql((C / "db/schema.sql").read_text(encoding="utf-8"))
except Exception as e:  # noqa: BLE001
    errors.append(f"schema.sql: {e}")

# 2. JSON-схемы
from jsonschema import Draft202012Validator  # noqa: E402
from referencing import Registry, Resource  # noqa: E402
from referencing.jsonschema import DRAFT202012  # noqa: E402

reg = Registry()
schemas: dict[str, dict] = {}
for p in glob.glob(str(C / "events/**/*.json"), recursive=True):
    s = json.load(open(p, encoding="utf-8"))
    try:
        Draft202012Validator.check_schema(s)
    except Exception as e:  # noqa: BLE001
        errors.append(f"{p}: {e}")
    schemas[p] = s
    reg = reg.with_resource(s["$id"], Resource.from_contents(s, default_specification=DRAFT202012))
for p, s in schemas.items():
    for ex in s.get("examples", []):
        errs = list(Draft202012Validator(s, registry=reg).iter_errors(ex))
        if errs:
            errors.append(f"{p}: пример не проходит: {errs[0].message}")

# 3. OpenAPI
import yaml  # noqa: E402
from openapi_spec_validator import validate  # noqa: E402

spec = yaml.safe_load((C / "api/openapi.yaml").read_text(encoding="utf-8"))
t = json.dumps(spec)
t = re.sub(r'"\$ref": "\.\./events/[^"]+"', '"type":"object"', t)
try:
    validate(json.loads(t))
except Exception as e:  # noqa: BLE001
    errors.append(f"openapi.yaml: {str(e)[:300]}")
for ref in set(re.findall(r"\.\./events/([^\"#]+)", (C / "api/openapi.yaml").read_text(encoding="utf-8"))):
    if not (C / "events" / ref).exists():
        errors.append(f"openapi.yaml: отсутствует файл {ref}")

# 4. Перечисления: CHECK в DDL ↔ common.schema.json
common = json.load(open(C / "events/common.schema.json", encoding="utf-8"))["$defs"]
ddl = (C / "db/schema.sql").read_text(encoding="utf-8")


def ddl_enum(table: str, column: str) -> set[str] | None:
    m = re.search(rf"CREATE TABLE {table} \((.*?)\n\);", ddl, re.S)
    if not m:
        return None
    m2 = re.search(rf"\n\s+{column}\s+text[^\n]*CHECK \({column} IN \(([^)]*)\)\)", m.group(1))
    return {v.strip().strip("'") for v in m2.group(1).split(",")} if m2 else None


pairs = [
    ("incidents", "status", "incident_status"),
    ("incidents", "complexity", "complexity"),
    ("incidents", "criticality", "criticality"),
    ("client_states", "state", "client_state"),
    ("client_reactions", "tone", "tone"),
]
for table, col, key in pairs:
    got = ddl_enum(table, col)
    want = set(common[key]["enum"])
    if got is not None and got != want:
        errors.append(f"{table}.{col} ≠ common.{key}: {sorted(got ^ want)}")

if errors:
    print("\n".join(errors))
    sys.exit(1)
print(f"contracts ok: {len(schemas)} схем, {len(spec['paths'])} путей OpenAPI")
