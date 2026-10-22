#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cx — один скрипт вместо git worktree / cd / codex / gh (docs/WORKFLOW.md).

Запускается из любого места внутри основного клона репозитория (или из worktree). Все пути вычисляет сам.

Команды:
  cx doctor                  проверить, что установлены git, gh (авторизован), codex, uv, node
  cx next [--seat S1|S2|S3]  что брать следующим: пакет из docs/PLAN-14D.md на сегодня или карточку без незакрытых зависимостей
  cx start <T-213|B04> [--agent codex|cursor|manual] [--interactive]
                             создать worktree ../wt/<id> от origin/main, подготовить .env/зависимости, собрать промпт
                             и запустить агента (codex exec — без участия человека; cursor — открыть папку и показать промпт)
  cx check <id>              прогнать проверки в worktree: lint, test, contracts, owners (что из этого есть)
  cx pr <id>                 закоммитить остатки, запушить, открыть PR с отчётом агента; показать ссылку
  cx fix <id>                взять лог упавших проверок PR и запустить агента «исправь и повтори проверки»
  cx status                  таблица: id · ветка · изменения · PR · проверки CI
  cx done <id>               если PR слит — удалить worktree и ветку; иначе отказать
  cx clean                   done для всех слитых
  cx open <id>               напечатать путь worktree (для cd вручную, если очень нужно)

Состояние — в <repo>/.cx/state.json (в .gitignore). Worktree'и — в <repo>/../wt/<id>/.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ----------------------------------------------------------------------------- базовые утилиты

def sh(cmd: list[str], cwd: Path | None = None, check: bool = True, capture: bool = True, input_: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check, text=True, capture_output=capture, input=input_)


def out(cmd: list[str], cwd: Path | None = None, default: str = "") -> str:
    try:
        return sh(cmd, cwd=cwd).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return default


def repo_root() -> Path:
    """Корень ОСНОВНОГО клона (не worktree)."""
    common = out(["git", "rev-parse", "--git-common-dir"])
    if not common:
        die("Запустите cx внутри клона репозитория")
    git_dir = Path(common).resolve()
    return git_dir.parent


def die(msg: str, code: int = 1) -> None:
    print(f"cx: {msg}", file=sys.stderr)
    sys.exit(code)


def say(msg: str) -> None:
    print(f"▸ {msg}")


ROOT = repo_root() if out(["git", "rev-parse", "--git-common-dir"]) else Path.cwd()
WT_DIR = ROOT.parent / "wt"
STATE = ROOT / ".cx" / "state.json"


def load_state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"items": {}}


def save_state(s: dict) -> None:
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    gi = ROOT / ".gitignore"
    if gi.exists() and ".cx/" not in gi.read_text(encoding="utf-8"):
        gi.write_text(gi.read_text(encoding="utf-8").rstrip("\n") + "\n.cx/\n", encoding="utf-8")


def norm_id(raw: str) -> str:
    raw = raw.strip().upper()
    m = re.fullmatch(r"T-?(\d{1,3})", raw)
    if m:
        return f"T-{int(m.group(1)):03d}"
    m = re.fullmatch(r"B-?(\d{1,2})", raw)
    if m:
        return f"B{int(m.group(1)):02d}"
    die(f"не понимаю идентификатор {raw!r}: ожидается T-213 или B04")
    return ""


# ----------------------------------------------------------------------------- карточки и пакеты

def card_path(cid: str) -> Path | None:
    hits = sorted((ROOT / "docs/tasks").glob(f"{cid}-*.md"))
    return hits[0] if hits else None


def card_meta(cid: str) -> dict:
    p = card_path(cid)
    if not p:
        die(f"карточка {cid} не найдена в docs/tasks/")
    txt = p.read_text(encoding="utf-8")
    title = txt.splitlines()[0].split("—", 1)[-1].strip()
    layer = (re.search(r"\| Слой \| `(L\d)`", txt) or [None, "?"])[1]
    dep_line = next((l for l in txt.splitlines() if l.startswith("- Зависит от:")), "")
    deps = re.findall(r"\[T-(\d{3})\]", dep_line)
    demo = "В демо-минимуме | да" in txt
    return {"id": cid, "title": title, "layer": layer, "deps": [f"T-{d}" for d in deps], "demo_min": demo, "path": p}


def plan_packages() -> dict:
    """Пакеты Bxx из docs/PLAN-14D.md: {id: {seat, day, name, cards, cuts}}."""
    p = ROOT / "docs/PLAN-14D.md"
    if not p.exists():
        return {}
    pk, seat = {}, None
    for line in p.read_text(encoding="utf-8").splitlines():
        m = re.match(r"### (S\d) ", line)
        if m:
            seat = m.group(1)
        m = re.match(r"\| ([^|]+) \| \*\*(B\d{2}) ([^*]+)\*\* \| ([^|]+) \| ([^|]*)\|", line)
        if m and seat:
            day, bid, name, cards, cuts = (x.strip() for x in m.groups())
            pk[bid] = {"seat": seat, "day": day, "name": name, "cards": re.findall(r"T-\d{3}", cards), "cards_raw": cards, "cuts": cuts}
    return pk


def _day_in_range(day: str, today: dt.date) -> bool:
    """«22.10», «25–26.10», «31.10–1.11» → попадает ли сегодня в диапазон."""
    parts = re.split(r"[–-]", day.strip())
    dates = []
    for i, part in enumerate(parts):
        m = re.fullmatch(r"(\d{1,2})(?:\.(\d{2}))?", part.strip())
        if not m:
            return False
        month = m.group(2) or re.search(r"\.(\d{2})", parts[-1]).group(1)
        dates.append(dt.date(today.year, int(month), int(m.group(1))))
    return dates[0] <= today <= dates[-1]


# ----------------------------------------------------------------------------- команды

def cmd_doctor(_: argparse.Namespace) -> None:
    ok = True
    for tool, probe in [("git", ["git", "--version"]), ("gh", ["gh", "--version"]), ("codex", ["codex", "--version"]), ("uv", ["uv", "--version"]), ("node", ["node", "--version"])]:
        v = out(probe)
        print(f"  {'✓' if v else '✗'} {tool:6} {v.splitlines()[0] if v else 'не найден'}")
        ok &= bool(v) or tool in ("uv", "node")
    auth = out(["gh", "auth", "status"], default="")
    print(f"  {'✓' if 'Logged in' in auth else '✗'} gh auth  {'авторизован' if 'Logged in' in auth else 'выполните: gh auth login'}")
    remote = out(["git", "remote", "get-url", "origin"], cwd=ROOT)
    print(f"  {'✓' if 'github.com' in remote else '✗'} origin   {remote or 'нет'} (должен быть GitHub, зеркало в GitVerse делает CI)")
    print(f"  · worktree'и будут в {WT_DIR}")
    sys.exit(0 if ok else 1)


def cmd_next(a: argparse.Namespace) -> None:
    today = dt.date.today()
    pk = plan_packages()
    st = load_state()
    done = {k for k, v in st["items"].items() if v.get("status") == "done"}
    if pk:
        cands = [(b, m) for b, m in pk.items() if (not a.seat or m["seat"] == a.seat) and b not in done and b not in st["items"]]
        todays = [(b, m) for b, m in cands if _day_in_range(m["day"], today)]
        pick = (todays or cands)[:1]
        if pick:
            b, m = pick[0]
            say(f"пакет {b} «{m['name']}» ({m['seat']}, {m['day']}): карточки {m['cards_raw']}")
            if m["cuts"]:
                print(f"  урезания: {m['cuts']}")
            print(f"  запуск:   python scripts/cx.py start {b}")
            return
    # карточный режим: демо-минимум, минимальная волна, все зависимости done
    best = None
    for p in sorted((ROOT / "docs/tasks").glob("T-*.md")):
        cid = p.name[:5]
        if cid in st["items"]:
            continue
        m = card_meta(cid)
        if not m["demo_min"] or any(d not in done for d in m["deps"]):
            continue
        wave = int((re.search(r"\| Волна \| (\d) \|", p.read_text(encoding="utf-8")) or [0, "9"])[1])
        if best is None or wave < best[0]:
            best = (wave, m)
    if best:
        say(f"карточка {best[1]['id']} (волна {best[0]}, слой {best[1]['layer']}): {best[1]['title']}")
        print(f"  запуск:   python scripts/cx.py start {best[1]['id']}")
    else:
        say("нечего брать: всё в работе или зависимости не закрыты — посмотрите cx status")


def build_prompt(iid: str) -> str:
    tmpl = (ROOT / "scripts/prompts/task.md").read_text(encoding="utf-8")
    if iid.startswith("B"):
        pk = plan_packages().get(iid) or die(f"пакет {iid} не найден в docs/PLAN-14D.md")
        cards = "\n".join(f"- {c}: docs/tasks/{card_path(c).name}" for c in pk["cards"] if card_path(c))
        task = (f"Пакет {iid} «{pk['name']}» из docs/PLAN-14D.md (рабочее место {pk['seat']}, {pk['day']}).\n"
                f"Карточки пакета:\n{cards}\n\nУрезания для спринта (делать ТОЛЬКО так): {pk['cuts'] or 'нет'}.\n"
                f"Остальное из карточек, что не нужно для среза, не делать — перечислить в отчёте как «отложено».")
        layers = sorted({card_meta(c)["layer"] for c in pk["cards"] if card_path(c)})
        layer = "/".join(layers)
    else:
        m = card_meta(iid)
        task = f"Карточка {iid} — {m['title']} (слой {m['layer']}): docs/tasks/{m['path'].name}. Выполнить полностью по карточке."
        layer = m["layer"]
    return tmpl.replace("{{TASK}}", task).replace("{{ID}}", iid).replace("{{LAYER}}", layer).replace("{{BRANCH}}", branch_of(iid))


def branch_of(iid: str) -> str:
    return f"feat/{iid}" if iid.startswith("T-") else f"pkg/{iid}"


def wt_of(iid: str) -> Path:
    return WT_DIR / iid


def prepare_worktree(iid: str) -> Path:
    wt, br = wt_of(iid), branch_of(iid)
    sh(["git", "fetch", "origin", "--prune"], cwd=ROOT)
    if wt.exists():
        say(f"worktree уже есть: {wt}")
        return wt
    WT_DIR.mkdir(exist_ok=True)
    exists_remote = bool(out(["git", "ls-remote", "--heads", "origin", br], cwd=ROOT))
    if exists_remote:
        sh(["git", "worktree", "add", str(wt), "-B", br, f"origin/{br}"], cwd=ROOT)
    else:
        sh(["git", "worktree", "add", "-b", br, str(wt), "origin/main"], cwd=ROOT)
    say(f"создан worktree {wt} (ветка {br})")
    # окружение
    env = ROOT / ".env"
    if env.exists():
        shutil.copy(env, wt / ".env")
    for sub in ("backend", "."):
        if (wt / sub / "pyproject.toml").exists() and shutil.which("uv"):
            sh(["uv", "sync", "--frozen"], cwd=wt / sub, check=False, capture=False)
            break
    if (wt / "frontend/package-lock.json").exists() and shutil.which("npm"):
        sh(["npm", "ci", "--silent"], cwd=wt / "frontend", check=False, capture=False)
    return wt


def run_agent(iid: str, wt: Path, prompt: str, agent: str, interactive: bool, extra: str = "") -> None:
    pdir = wt / ".cx"
    pdir.mkdir(exist_ok=True)
    pfile = pdir / "prompt.md"
    pfile.write_text(prompt + ("\n\n" + extra if extra else ""), encoding="utf-8")
    report = pdir / "report.md"
    if agent == "manual":
        say(f"промпт сохранён: {pfile}\n  вставьте его в любой инструмент, рабочая папка — {wt}")
        return
    if agent == "cursor":
        if shutil.which("cursor"):
            subprocess.Popen(["cursor", str(wt)])
            say(f"Cursor открыт в {wt}; промпт — в {pfile} (скопируйте в чат агента Cursor)")
        else:
            say(f"команда `cursor` не найдена: откройте папку {wt} в Cursor вручную; промпт — {pfile}")
        return
    if not shutil.which("codex"):
        die("codex CLI не найден (npm i -g @openai/codex) — или используйте --agent cursor/manual")
    git_common = Path(out(["git", "rev-parse", "--git-common-dir"], cwd=ROOT)).resolve()
    if interactive:
        say("интерактивный Codex в worktree; промпт подставлен первой репликой")
        subprocess.run(["codex", "-C", str(wt), "-s", "workspace-write", "--add-dir", str(git_common),
                        "-c", "sandbox_workspace_write.network_access=true", prompt], check=False)
        return
    say(f"Codex работает без участия человека в {wt}; прогресс — ниже, итог — {report}")
    cmd = ["codex", "-a", "never", "-s", "workspace-write", "-C", str(wt), "--add-dir", str(git_common),
           "-c", "sandbox_workspace_write.network_access=true", "exec", "-o", str(report), "-"]
    r = subprocess.run(cmd, input=pfile.read_text(encoding="utf-8"), text=True, check=False)
    st = load_state()
    st["items"].setdefault(iid, {})["last_run"] = dt.datetime.now().isoformat(timespec="minutes")
    st["items"][iid]["exit"] = r.returncode
    save_state(st)
    if report.exists():
        print("\n— отчёт агента —\n" + report.read_text(encoding="utf-8")[-3000:])
    say(f"дальше: python scripts/cx.py check {iid}  →  python scripts/cx.py pr {iid}")


def cmd_start(a: argparse.Namespace) -> None:
    iid = norm_id(a.id)
    wt = prepare_worktree(iid)
    st = load_state()
    st["items"].setdefault(iid, {}).update({"status": "in_progress", "branch": branch_of(iid), "wt": str(wt), "agent": a.agent,
                                            "started": dt.datetime.now().isoformat(timespec="minutes")})
    save_state(st)
    run_agent(iid, wt, build_prompt(iid), a.agent, a.interactive)


def cmd_check(a: argparse.Namespace) -> None:
    iid = norm_id(a.id)
    wt = wt_of(iid)
    if not wt.exists():
        die(f"worktree для {iid} нет — сначала cx start {iid}")
    results = []
    steps = [("contracts", ["python", "scripts/contracts_check.py"]),
             ("owners", ["python", "scripts/check_owners.py", "--base", "origin/main"]),
             ("lint", ["make", "lint"]), ("test", ["make", "test"])]
    for name, cmd in steps:
        if name in ("lint", "test") and not (wt / "Makefile").exists():
            continue
        r = sh(cmd, cwd=wt, check=False)
        results.append((name, r.returncode == 0, (r.stdout + r.stderr)[-1500:]))
        print(f"  {'✓' if r.returncode == 0 else '✗'} {name}")
    bad = [r for r in results if not r[1]]
    for name, _, log in bad:
        print(f"\n— {name} —\n{log}")
    (wt / ".cx").mkdir(exist_ok=True)
    (wt / ".cx/check.log").write_text("\n\n".join(f"[{n}] {'ok' if o else 'FAIL'}\n{l}" for n, o, l in results), encoding="utf-8")
    sys.exit(1 if bad else 0)


def pr_body(iid: str, wt: Path) -> str:
    tmpl = ROOT / ".github/pull_request_template.md"
    body = tmpl.read_text(encoding="utf-8") if tmpl.exists() else ""
    rep = wt / ".cx/report.md"
    if rep.exists():
        body += "\n\n## Отчёт агента\n\n" + rep.read_text(encoding="utf-8")[-6000:]
    log = wt / ".cx/check.log"
    if log.exists():
        body += "\n\n<details><summary>Вывод проверок cx check</summary>\n\n```\n" + log.read_text(encoding="utf-8")[-4000:] + "\n```\n</details>\n"
    return body


def cmd_pr(a: argparse.Namespace) -> None:
    iid = norm_id(a.id)
    wt, br = wt_of(iid), branch_of(iid)
    if not wt.exists():
        die(f"worktree для {iid} нет")
    if out(["git", "status", "--porcelain", "--untracked-files=all", "--", ".", ":!.cx"], cwd=wt):
        sh(["git", "add", "-A", "--", ".", ":!.cx"], cwd=wt)
        sh(["git", "commit", "-q", "-m", f"{iid}: завершение работы агента"], cwd=wt)
    sh(["git", "fetch", "origin"], cwd=wt)
    r = sh(["git", "rebase", "origin/main"], cwd=wt, check=False)
    if r.returncode:
        sh(["git", "rebase", "--abort"], cwd=wt, check=False)
        die(f"конфликт с main — запустите: python scripts/cx.py fix {iid} --rebase")
    sh(["git", "push", "-u", "origin", br, "--force-with-lease"], cwd=wt, capture=False)
    touched = out(["git", "diff", "--name-only", "origin/main...HEAD"], cwd=wt).splitlines()
    flags = []
    if any(p.startswith("contracts/") for p in touched):
        flags.append("contract-change")
    chk = sh(["python", "scripts/check_owners.py", "--base", "origin/main"], cwd=wt, check=False)
    if chk.returncode == 1:
        flags.append("cross-layer")
    title = f"{iid}: " + (plan_packages().get(iid, {}).get("name") if iid.startswith("B") else card_meta(iid)["title"])
    if flags:
        title += " [" + ", ".join(flags) + "]"
    body_file = wt / ".cx/pr_body.md"
    body_file.write_text(pr_body(iid, wt), encoding="utf-8")
    existing = out(["gh", "pr", "view", br, "--json", "url", "-q", ".url"], cwd=wt)
    if existing:
        sh(["gh", "pr", "edit", br, "--title", title, "--body-file", str(body_file)], cwd=wt)
        url = existing
    else:
        url = out(["gh", "pr", "create", "--base", "main", "--head", br, "--title", title, "--body-file", str(body_file)], cwd=wt)
    st = load_state()
    st["items"].setdefault(iid, {}).update({"status": "pr", "pr": url, "flags": flags})
    save_state(st)
    say(f"PR: {url}" + (f"  ⚠ метки {flags}: сливает владелец L1" if flags else "  — сольётся по зелёному CI"))


def cmd_fix(a: argparse.Namespace) -> None:
    iid = norm_id(a.id)
    wt, br = wt_of(iid), branch_of(iid)
    if not wt.exists():
        die(f"worktree для {iid} нет")
    extra = ""
    if a.rebase:
        extra = ("Сначала выполни `git fetch origin && git rebase origin/main`, разреши конфликты, сохранив поведение обеих сторон, "
                 "затем прогони все проверки заново.")
    else:
        checks = out(["gh", "pr", "checks", br, "--json", "name,state,link", "-q", '.[] | select(.state!="SUCCESS") | "\\(.name): \\(.state) \\(.link)"'], cwd=wt)
        runs = out(["gh", "run", "list", "--branch", br, "--limit", "1", "--json", "databaseId", "-q", ".[0].databaseId"], cwd=wt)
        log = out(["gh", "run", "view", runs, "--log-failed"], cwd=wt)[-12000:] if runs else ""
        local = (wt / ".cx/check.log").read_text(encoding="utf-8")[-4000:] if (wt / ".cx/check.log").exists() else ""
        extra = f"Проверки PR не прошли:\n{checks or '(см. лог)'}\n\nЛог упавших шагов CI:\n```\n{log}\n```\n\nЛокальные проверки:\n```\n{local}\n```\n" \
                "Исправь причину (не ослабляй тесты и не отключай проверки), прогони проверки заново и обнови блок «Отчёт»."
    run_agent(iid, wt, build_prompt(iid), a.agent, a.interactive, extra=extra)
    say(f"после исправления: python scripts/cx.py pr {iid}")


def cmd_status(_: argparse.Namespace) -> None:
    st = load_state()
    rows = []
    for iid, it in sorted(st["items"].items()):
        wt = Path(it.get("wt", ""))
        dirty = "изменения" if wt.exists() and out(["git", "status", "--porcelain", "--", ".", ":!.cx"], cwd=wt) else "чисто"
        pr = it.get("pr", "")
        state = out(["gh", "pr", "view", it.get("branch", ""), "--json", "state,mergeable,statusCheckRollup",
                     "-q", '"\\(.state) · проверки: \\([.statusCheckRollup[]? | .conclusion // .status] | join(","))"'], cwd=ROOT) if pr else "нет PR"
        rows.append((iid, it.get("status", "?"), it.get("branch", ""), dirty, state, pr))
    if not rows:
        say("пусто — начните с: python scripts/cx.py next")
        return
    w = max(len(r[0]) for r in rows)
    for r in rows:
        print(f"  {r[0]:{w}}  {r[1]:11}  {r[3]:9}  {r[4]}  {r[5]}")


def cmd_done(a: argparse.Namespace) -> None:
    iid = norm_id(a.id)
    _finish(iid, force=a.force)


def _finish(iid: str, force: bool = False) -> bool:
    st = load_state()
    it = st["items"].get(iid) or {}
    br = it.get("branch", branch_of(iid))
    state = out(["gh", "pr", "view", br, "--json", "state", "-q", ".state"], cwd=ROOT)
    if state != "MERGED" and not force:
        say(f"{iid}: PR в состоянии {state or 'нет'} — не слит, worktree оставлен (--force, чтобы удалить всё равно)")
        return False
    wt = wt_of(iid)
    if wt.exists():
        sh(["git", "worktree", "remove", "--force", str(wt)], cwd=ROOT, check=False)
    sh(["git", "branch", "-D", br], cwd=ROOT, check=False)
    if state == "MERGED":
        sh(["git", "push", "origin", "--delete", br], cwd=ROOT, check=False)
    st["items"][iid] = {**it, "status": "done", "finished": dt.datetime.now().isoformat(timespec="minutes")}
    save_state(st)
    say(f"{iid}: закрыто, worktree удалён")
    return True


def cmd_clean(_: argparse.Namespace) -> None:
    st = load_state()
    n = sum(_finish(i) for i, it in list(st["items"].items()) if it.get("status") == "pr")
    sh(["git", "worktree", "prune"], cwd=ROOT, check=False)
    say(f"закрыто: {n}")


def cmd_open(a: argparse.Namespace) -> None:
    print(wt_of(norm_id(a.id)))


# ----------------------------------------------------------------------------- argparse

def main() -> None:
    ap = argparse.ArgumentParser(prog="cx", description="Одна команда вместо worktree/cd/codex/gh")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("doctor").set_defaults(f=cmd_doctor)
    p = sp.add_parser("next"); p.add_argument("--seat", choices=["S1", "S2", "S3"]); p.set_defaults(f=cmd_next)
    for name, f in (("start", cmd_start), ("fix", cmd_fix)):
        p = sp.add_parser(name); p.add_argument("id"); p.add_argument("--agent", choices=["codex", "cursor", "manual"], default="codex")
        p.add_argument("--interactive", action="store_true")
        if name == "fix":
            p.add_argument("--rebase", action="store_true")
        p.set_defaults(f=f)
    for name, f in (("check", cmd_check), ("pr", cmd_pr), ("open", cmd_open)):
        p = sp.add_parser(name); p.add_argument("id"); p.set_defaults(f=f)
    p = sp.add_parser("done"); p.add_argument("id"); p.add_argument("--force", action="store_true"); p.set_defaults(f=cmd_done)
    sp.add_parser("status").set_defaults(f=cmd_status)
    sp.add_parser("clean").set_defaults(f=cmd_clean)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
