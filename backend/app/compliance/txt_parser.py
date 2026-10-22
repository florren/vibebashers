"""Парсер текстовых транскриптов (ДТЗ FR-1.1, T-208): «[чч:мм:сс] Роль: реплика» / «Роль: реплика» → объект ingest/transcript."""

from __future__ import annotations

import re
from typing import Any

EMPLOYEE_ALIASES = (
    "сотрудник",
    "оператор",
    "менеджер",
    "консультант",
    "специалист",
    "employee",
    "agent",
    "operator",
    "manager",
)
CLIENT_ALIASES = ("клиент", "абонент", "посетитель", "покупатель", "client", "customer", "caller")

_LINE = re.compile(
    r"^\s*(?:\[(?P<ts>\d{1,2}:\d{2}(?::\d{2})?)\]\s*)?(?P<role>[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9 .\-]{0,40}?)\s*[:—-]\s+(?P<text>.+?)\s*$"
)
_META = re.compile(r"^\s*#\s*(?P<key>[a-z_]+)\s*[:=]\s*(?P<val>.+?)\s*$", re.IGNORECASE)


class TranscriptParseError(ValueError):
    pass


def _role(raw: str) -> str | None:
    r = raw.strip().lower()
    r = re.sub(r"\s+\d+$", "", r)  # «Клиент 2» → «клиент»
    if any(r.startswith(a) for a in EMPLOYEE_ALIASES):
        return "employee"
    if any(r.startswith(a) for a in CLIENT_ALIASES):
        return "client"
    return None


def _ms(ts: str | None) -> int | None:
    if not ts:
        return None
    parts = [int(p) for p in ts.split(":")]
    if len(parts) == 2:
        parts = [0, *parts]
    h, m, s = parts
    return (h * 3600 + m * 60 + s) * 1000


def parse_txt(text: str, *, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    """TXT → {kind, branch_code, employee_public_id, desk_no, deal_product, turns[], meta}. Строки «# key: value» — метаданные.

    Многострочные реплики: строка без префикса роли приклеивается к предыдущей реплике.
    """
    meta: dict[str, Any] = {}
    turns: list[dict[str, Any]] = []
    unknown_roles: set[str] = set()
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            # «# kind: branch_retail; branch: VSP-0042; desk: 5; employee: Сидорова А. А.; product: deposit»
            for part in line.lstrip("# ").split(";"):
                mm = _META.match("# " + part.strip())
                if mm and mm.group("val").strip() not in ("-", "—", ""):
                    meta[mm.group("key").lower()] = mm.group("val").strip()
            continue
        m = _LINE.match(line)
        role = _role(m.group("role")) if m else None
        if m and role:
            t0 = _ms(m.group("ts"))
            turns.append(
                {"seq": len(turns) + 1, "speaker": role, "text": m.group("text").strip(), "t0_ms": t0, "t1_ms": None}
            )
        elif m and m.group("role") and not turns:
            unknown_roles.add(m.group("role").strip())
        elif turns:
            turns[-1]["text"] = (turns[-1]["text"] + " " + line.strip()).strip()
        else:
            unknown_roles.add(line.strip()[:40])
    if not turns:
        raise TranscriptParseError(
            "не найдено ни одной реплики вида «Сотрудник: …» / «Клиент: …»"
            + (f"; нераспознанные роли: {sorted(unknown_roles)[:3]}" if unknown_roles else "")
        )
    # t1 — начало следующей реплики, если есть временные метки
    for i, t in enumerate(turns):
        if t["t0_ms"] is not None and i + 1 < len(turns) and turns[i + 1]["t0_ms"] is not None:
            t["t1_ms"] = max(turns[i + 1]["t0_ms"], t["t0_ms"])
    d = dict(defaults or {})
    kind = meta.get("kind") or d.get("kind") or "branch_retail"
    out: dict[str, Any] = {
        "external_id": meta.get("external_id") or d.get("external_id"),
        "kind": kind,
        "branch_code": meta.get("branch") or meta.get("branch_code") or d.get("branch_code"),
        "employee_public_id": meta.get("employee") or meta.get("employee_public_id") or d.get("employee_public_id"),
        "desk_no": int(meta["desk"]) if str(meta.get("desk", "")).isdigit() else d.get("desk_no"),
        "client": {"client_id": int(meta["client_id"])}
        if str(meta.get("client_id", "")).isdigit()
        else d.get("client"),
        "deal_product": meta.get("deal_product") or meta.get("deal") or meta.get("product") or d.get("deal_product"),
        "started_at": meta.get("started_at") or d.get("started_at"),
        "geo": d.get("geo"),
        "analyses": d.get("analyses") or ["client_signal", "employee_quality"],
        "turns": turns,
        "meta": {
            k: v
            for k, v in meta.items()
            if k
            not in (
                "kind",
                "branch",
                "branch_code",
                "employee",
                "employee_public_id",
                "desk",
                "client_id",
                "deal_product",
                "deal",
                "started_at",
                "external_id",
            )
        },
    }
    return out


def normalize_turns(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Проставляет seq и обрезает пробелы; t0/t1 — как пришли."""
    out = []
    for i, t in enumerate(turns):
        out.append(
            {
                "seq": int(t.get("seq") or i + 1),
                "speaker": t["speaker"],
                "text": str(t["text"]).strip(),
                "t0_ms": t.get("t0_ms"),
                "t1_ms": t.get("t1_ms"),
            }
        )
    return out
