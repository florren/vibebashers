"""T-041: настоящий kill/restart процесса с production lifespan, ASGI API и PostgreSQL."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def test_kill_restart_then_graceful_restart_preserve_agent_effects(seeded, conn, tmp_path):
    output = tmp_path / "process.json"
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("GIGACHAT", "OPENROUTER", "OPENAI", "LOCAL_LLM", "LANGSMITH", "LANGCHAIN"))
    }
    env.update(
        APP_ENV="dev",
        ENV_FILE="/dev/null",
        LLM_PROVIDER="mock",
        LLM_RECORD="0",
        LOG_JSONL="false",
        DATABASE_URL=seeded,
        DATABASE_URL_TEST=seeded,
        PYTHONPATH=str(ROOT),
        DURABLE_OUTPUT=str(output),
    )
    fixture = ROOT / "tests/fixtures/durable_process.py"
    with (tmp_path / "crash.log").open("w") as log:
        process = subprocess.Popen(
            [sys.executable, str(fixture)],
            cwd=ROOT,
            env={**env, "DURABLE_PHASE": "crash"},
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 45
            while not output.exists():
                if process.poll() is not None:
                    pytest.fail((tmp_path / "crash.log").read_text()[-4000:])
                if time.monotonic() > deadline:
                    pytest.fail(
                        "Процесс не достиг durable close barrier за45s\n" + (tmp_path / "crash.log").read_text()[-4000:]
                    )
                time.sleep(0.05)
            proof = json.loads(output.read_text())
            # SIGKILL только собственного временного процесса, не пользовательского backend.
            process.kill()
            process.wait(timeout=10)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
    after_kill = conn.execute("select sim_time,rng_state,running from sim_state where id=1").fetchone()
    assert after_kill[2] is True
    for phase in ("recover", "graceful"):
        result = subprocess.run(
            [sys.executable, str(fixture)],
            cwd=ROOT,
            env={**env, "DURABLE_PHASE": phase},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=45,
        )
        assert result.returncode == 0, result.stdout[-4000:]
        report = json.loads(output.with_suffix(f".{phase}").read_text())
        assert report["resumed_after"] == report["resumed_before"] + 1
        assert report["agent_run_id"] == json.loads(output.with_suffix(".blocked").read_text())["agent_run_id"]
        assert report["tokens"] > 0
        if phase == "recover":
            assert report["sim_time_before"] == after_kill[0].isoformat()
        assert conn.execute("select status from sim_runs where id=%s", (proof["run_id"],)).fetchone()[0] == "paused"
        assert conn.execute("select running from sim_state where id=1").fetchone()[0] is False
