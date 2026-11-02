"""Deterministic identifier grammar, shared by trace resolution and search."""

from __future__ import annotations

import re
from uuid import UUID

PREFIXES = dict(
    zip(
        (
            "SIG",
            "INC",
            "CL",
            "POST",
            "TR",
            "ESC",
            "AS",
            "EMP",
            "AR",
            "SR",
            "TSK",
            "NTF",
            "LED",
            "HD",
            "FUP",
            "CSI",
            "VSP",
        ),
        (
            "signal",
            "incident",
            "client",
            "post",
            "transcript",
            "escalation",
            "audio_session",
            "employee",
            "agent_run",
            "sim_run",
            "task",
            "notification",
            "ledger",
            "human_decision",
            "followup",
            "csi",
            "branch",
        ),
        strict=True,
    )
)


def parse(query: str) -> dict[str, str | None]:
    q = re.sub(r"[‐‑‒–—−]", "-", query.strip())
    match = re.fullmatch(r"(SIG|INC|CL|POST|TR|ESC|AS|EMP|AR|SR|TSK|NTF|LED|HD|FUP|CSI|VSP|ВСП)[\s-]*(\d+)", q, re.I)
    kind: str | None = None
    ref = q
    if match:
        prefix, number = match.groups()
        prefix = "VSP" if prefix.upper() == "ВСП" else prefix.upper()
        kind = PREFIXES[prefix]
        width = 4 if prefix in ("SR", "VSP") else 5 if prefix == "EMP" else 6
        ref = f"{prefix}-{int(number):0{width}d}" if prefix != "CSI" else f"CSI-{int(number)}"
    elif re.fullmatch(r"RULE-[A-Z0-9-]+", q, re.I):
        kind, ref = "rule", q.upper()
    elif re.fullmatch(r"[A-Z]{2,}-[A-Z0-9-]+", q, re.I):
        kind, ref = "error_code", q.upper()
    else:
        try:
            ref, kind = str(UUID(q)), "correlation"
        except ValueError:
            # int() принимает Unicode decimal, но не все isdigit (например, ²).
            if q.isdecimal():
                kind, ref = "number", str(int(q))
            elif re.fullmatch(r"[A-Za-z0-9_-]{24,}", q):
                kind = "tracking"
    mode = "id" if kind else "hints" if q.startswith(("@", "+", "*")) else "text"
    return {"mode": mode, "kind": kind, "ref": ref if kind else None, "normalized": ref}
