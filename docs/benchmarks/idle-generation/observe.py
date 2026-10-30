"""Изолированный замер idle/start/pause/restart; имена тестовых ресурсов передаются в argv."""

import datetime as dt
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

label = sys.argv[1]
db = sys.argv[2]
container = sys.argv[3]
port = int(sys.argv[4])
base = f"http://localhost:{port}"
out = f"/tmp/cx-idle-{label}.json"
rows = []


def sample(phase):
    q = """select json_build_object('state',(select json_build_object('running',running,'run',current_run_id,'sim_time',sim_time) from sim_state where id=1),'runs',(select json_agg(json_build_object('id',id,'kind',kind,'status',status) order by id) from sim_runs),'signals',(select count(*) from signals),'sim_events',(select count(*) from sim_events),'posts',(select count(*) from external_posts),'agent_runs',(select count(*) from agent_runs),'ledger',(select count(*) from ledger_entries),'notifications',(select count(*) from notifications),'origins',(select jsonb_object_agg(origin,n) from(select origin,count(*) n from signals group by origin)t),'sources',(select jsonb_object_agg(source_code,n) from(select source_code,count(*) n from ingest_messages group by source_code)t),'agent_kinds',(select jsonb_object_agg(kind,n) from(select kind,count(*) n from agent_runs group by kind)t));"""
    d = json.loads(
        subprocess.check_output(
            [
                "docker",
                "exec",
                "cx-seed-review-pg",
                "psql",
                "-U",
                "cx",
                "-d",
                db,
                "-At",
                "-c",
                q,
            ],
            text=True,
        )
    )
    d.update(phase=phase, at=dt.datetime.now(dt.UTC).isoformat())
    rows.append(d)
    Path(out).write_text(json.dumps(rows, indent=2), encoding="utf-8")
    sys.stdout.write(
        json.dumps(
            {
                "phase": phase,
                **{
                    k: d[k]
                    for k in (
                        "state",
                        "signals",
                        "sim_events",
                        "posts",
                        "agent_runs",
                        "sources",
                    )
                },
            }
        )
        + "\n"
    )
    sys.stdout.flush()


def api(action):
    data = json.dumps({"action": action, "speed": 60} if action == "start" else {"action": action}).encode()
    request = urllib.request.Request(base + "/api/sim/control", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def window(name):
    sample(name + "_0")
    time.sleep(60)
    sample(name + "_60")
    time.sleep(60)
    sample(name + "_120")


sample("pre_startup")
subprocess.run(
    [
        "docker",
        "run",
        "-d",
        "--name",
        container,
        "--network",
        "cx-seed-review",
        "-p",
        f"127.0.0.1:{port}:8000",
        "-e",
        f"DATABASE_URL=postgresql+psycopg://cx:cx@cx-seed-review-pg:5432/{db}",
        "-e",
        "APP_ENV=dev",
        "-e",
        "PROFILE=lite",
        "-e",
        "LLM_PROVIDER=mock",
        "-e",
        "LLM_CHAIN=mock",
        sys.argv[5],
    ],
    check=True,
    stdout=subprocess.DEVNULL,
)
for _ in range(60):
    try:
        with urllib.request.urlopen(base + "/api/health", timeout=2) as response:
            response.read()
        break
    except (urllib.error.URLError, TimeoutError):
        time.sleep(1)
else:
    raise TimeoutError("backend health timeout")
window("idle")
api("start")
time.sleep(15)
sample("running")
api("pause")
window("paused")
subprocess.run(["docker", "restart", container], check=True, stdout=subprocess.DEVNULL)
for _ in range(60):
    try:
        with urllib.request.urlopen(base + "/api/health", timeout=2) as response:
            response.read()
        break
    except (urllib.error.URLError, TimeoutError):
        time.sleep(1)
else:
    raise TimeoutError("backend health timeout")
window("restarted_paused")
