"""T-223: форматы генерируемых public_id для следа и поиска."""

from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.integration

SR_RE = re.compile(r"^SR-\d{4}$")
AR_RE = re.compile(r"^AR-\d{6}$")


def test_sim_run_public_id_format(conn) -> None:
    pid = conn.execute(
        "insert into sim_runs (kind, label, seed, started_sim) values ('live','unit',42,now()) returning public_id"
    ).fetchone()[0]
    assert SR_RE.match(pid)


def test_agent_run_public_id_format(conn) -> None:
    run_id = conn.execute(
        "insert into sim_runs (kind, label, seed, started_sim) values ('live','unit-ar',1,now()) returning id"
    ).fetchone()[0]
    pid = conn.execute(
        """
        insert into agent_runs (kind, sim_run_id, prompt_version, graph_version)
        values ('agent', %s, 'v1', '1') returning public_id
        """,
        (run_id,),
    ).fetchone()[0]
    assert AR_RE.match(pid)
