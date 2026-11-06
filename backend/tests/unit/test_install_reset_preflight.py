"""Reset сохраняет данные при ошибках подготовки и посторонних держателях томов."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("failure", ["config", "build", "pull", "model", "foreign_holder", "oneoff_holder", "inspect"])
def test_reset_preflight_failure_preserves_stack(tmp_path: Path, failure: str) -> None:
    result, commands = run_install(tmp_path, failure)
    assert result.returncode != 0
    assert not any(" down " in f" {c} " or " up " in f" {c} " or " rm " in f" {c} " for c in commands)
    if "holder" in failure:
        assert "удерживает" in result.stderr
        assert "автоматически не удаляются" in result.stderr


@pytest.mark.parametrize("cached", [False, True])
def test_reset_build_before_down_and_cached_images_unchanged(tmp_path: Path, cached: bool) -> None:
    result, commands = run_install(tmp_path, "", cached=cached)
    assert result.returncode != 0
    assert "кодом 77" in result.stderr
    down = next(i for i, c in enumerate(commands) if " down " in f" {c} ")
    assert commands.index("compose build") < down < commands.index("compose up -d --no-build --pull never")
    pulls = [i for i, c in enumerate(commands) if c.startswith("pull ")]
    assert (not pulls) if cached else (len(pulls) == 1 and pulls[0] < down)
    assert not any("optional" in c for c in commands)


def test_reset_prepares_explicitly_enabled_optional_profile(tmp_path: Path) -> None:
    result, commands = run_install(tmp_path, "", optional=True)
    assert "кодом 77" in result.stderr
    assert "pull optional-image" in commands


def run_install(tmp_path: Path, failure: str, *, cached: bool = False, optional: bool = False):
    shutil.copyfile(ROOT / "install.sh", tmp_path / "install.sh")
    (tmp_path / "scripts").mkdir()
    shutil.copyfile(ROOT / "scripts/install_preflight.py", tmp_path / "scripts/install_preflight.py")
    (tmp_path / ".env").write_text("PROFILE=lite\nSIM_SEED=42\n")
    programs = tmp_path / "bin"
    programs.mkdir()
    log = tmp_path / "commands.jsonl"
    (programs / "docker").write_text(
        f"#!{sys.executable}\n"
        + """import json,os,sys
args=sys.argv[1:];failure=os.environ['FAILURE']
with open(os.environ['COMMANDS'],'a') as stream:stream.write(json.dumps(' '.join(args))+'\\n')
if args[:2]==['compose','config']:
 if failure=='config':print('secret-not-to-be-printed',file=sys.stderr);sys.exit(9)
 print(json.dumps({'name':'custom-project','services':{
 'postgres':{'image':'postgres:16','volumes':[{'type':'volume','source':'pgdata'}]},
 'backend':{'image':'built-image','build':{'context':'.'},'volumes':[{'type':'volume','source':'maintenance'}]},
 'personal':{'image':'built-image'},'optional':{'image':'optional-image','profiles':['telegram']}},
 'volumes':{'pgdata':{'name':'custom-project_pgdata'},'maintenance':{'name':'custom-project_maintenance'}}}))
elif args[:1]==['ps']:print('holder')
elif args[:1]==['inspect']:
 if failure=='inspect':sys.exit(9)
 print(json.dumps({'com.docker.compose.project':'other' if failure=='foreign_holder' else 'custom-project',
 'com.docker.compose.service':'backend','com.docker.compose.oneoff':'True' if failure=='oneoff_holder' else 'False'}))
elif args==['compose','build']:
 if failure=='build':sys.exit(9)
elif args[:2]==['image','inspect']:sys.exit(0 if args[-1]=='built-image' or os.environ['CACHED']=='1' else 1)
elif args[:1]==['pull']:
 if failure=='pull':sys.exit(9)
elif 'exec' in args:sys.exit(77)
"""
    )
    (programs / "python3").write_text(
        '#!/usr/bin/env bash\nif [ "$1" = scripts/stt_model.py ]; then [ "$FAILURE" != model ]; exit $?; fi\n'
        + f'exec "{sys.executable}" "$@"\n'
    )
    for name, body in {"ss": "exit 0", "curl": "printf '{}\\n'"}.items():
        (programs / name).write_text("#!/usr/bin/env bash\n" + body + "\n")
    for p in programs.iterdir():
        p.chmod(0o755)
    result = subprocess.run(
        ["bash", str(tmp_path / "install.sh"), "--reset", "--seed", "42"],
        env={
            **os.environ,
            "PATH": str(programs) + os.pathsep + os.environ["PATH"],
            "FAILURE": failure,
            "COMMANDS": str(log),
            "CACHED": "1" if cached else "0",
            "COMPOSE_PROFILES": "telegram" if optional else "",
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert "secret-not-to-be-printed" not in result.stderr
    return result, [json.loads(line) for line in log.read_text().splitlines()]
