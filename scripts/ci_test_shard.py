"""T-145: полное покрытие pytest четырьмя изолированными CI runners, без xdist."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def collection_modules(output: str) -> list[str]:
    modules = sorted(
        {line.split("::", 1)[0] for line in output.splitlines() if line.startswith("tests/") and "::" in line}
    )
    if not modules:
        raise ValueError("pytest не собрал ни одного тестового модуля")
    for module in modules:
        path = PurePosixPath(module)
        if path.is_absolute() or ".." in path.parts or path.suffix != ".py":
            raise ValueError("недопустимый путь тестового модуля")
    return modules


def partition(modules: list[str], index: int, count: int) -> list[str]:
    if count < 1 or not 0 <= index < count or len(set(modules)) != len(modules):
        raise ValueError("некорректная разбивка тестов")
    selected = sorted(modules)[index::count]
    if not selected:
        raise ValueError("пустой shard: уменьшите count")
    return selected


def verify_manifests(paths: list[Path], count: int) -> None:
    if count < 1 or len(paths) != count:
        raise ValueError("отсутствует manifest одного из runners")
    manifests = [json.loads(path.read_text()) for path in paths]
    if {row["index"] for row in manifests} != set(range(count)):
        raise ValueError("повторяющийся или отсутствующий index runner")
    discovered = manifests[0]["discovered"]
    if not discovered or len(set(discovered)) != len(discovered):
        raise ValueError("некорректный список собранных модулей")
    nodeids = manifests[0]["nodeids"]
    if len(nodeids) != len(set(nodeids)) or collection_modules("\n".join(nodeids)) != discovered:
        raise ValueError("некорректная полная коллекция тестов")
    revision = manifests[0]["revision"]
    if not revision:
        raise ValueError("отсутствует revision")
    selected: list[str] = []
    for row in manifests:
        if (
            row["count"] != count
            or row["discovered"] != discovered
            or row["nodeids"] != nodeids
            or row["revision"] != revision
        ):
            raise ValueError("runners использовали разные наборы тестов")
        if row["selected"] != partition(discovered, row["index"], count):
            raise ValueError("runner не выполнил свою часть набора")
        expected_count = sum(node.split("::", 1)[0] in row["selected"] for node in nodeids)
        if row.get("exit_code") != 0 or row.get("executed_count") != expected_count:
            raise ValueError("runner не подтвердил успешное выполнение всех тестов")
        selected.extend(row["selected"])
    if sorted(selected) != sorted(discovered):
        raise ValueError("разбиение потеряло или продублировало тесты")


def pytest_addoption(parser: Any) -> None:
    parser.addini("ci_phase_dump_seconds", "Период диагностики текущей CI-фазы", default="60")


def pytest_configure(config: Any) -> None:
    """Загружается только явным -p в дочернем pytest; aggregate остаётся stdlib-only."""
    import asyncio
    import faulthandler
    import math
    import threading
    import traceback
    import weakref
    from time import monotonic

    import pytest

    interval = float(config.getini("ci_phase_dump_seconds"))
    if not math.isfinite(interval) or interval <= 0:
        raise pytest.UsageError("ci_phase_dump_seconds должен быть конечным положительным числом")
    path = os.environ.get("CX_CI_PHASE_LOG")
    if not path:
        return
    phase_stream = Path(path).open("a")
    stack_stream = Path(path).with_suffix(".stacks.log").open("a")
    encode = json.dumps
    timeout = float(config.getini("faulthandler_timeout"))
    from _pytest.faulthandler import fault_handler_stderr_fd_key

    class Diagnostics:
        def __init__(self) -> None:
            self.lock = threading.Lock()
            self.stop = threading.Event()
            self.current: tuple[str, str, float, list[Any]] | None = None
            self.thread: threading.Thread | None = None
            self.protocol_started = 0.0

        def emit(self, **row: Any) -> None:
            text = encode(row, ensure_ascii=False)
            with self.lock:
                phase_stream.write(text + "\n")
                phase_stream.flush()

        def begin(self, item: Any, phase: str) -> None:
            if phase == "setup":
                self.protocol_started = monotonic()
            elif phase == "teardown" and timeout > 0:
                # pytest отменяет watchdog после failed call; сохраняем общий deadline.
                faulthandler.dump_traceback_later(
                    max(0.001, timeout - (monotonic() - self.protocol_started)),
                    file=config.stash[fault_handler_stderr_fd_key],
                    exit=bool(config.getini("faulthandler_exit_on_timeout")),
                )
            loops = []
            for value in item.funcargs.values():
                if isinstance(value, asyncio.Runner):
                    try:
                        loops.append(weakref.ref(value.get_loop()))
                    except RuntimeError:
                        pass
            with self.lock:
                self.current = (item.nodeid, phase, monotonic(), loops)
            self.emit(nodeid=item.nodeid, phase=phase, state="started")

        def end(self, item: Any, phase: str) -> None:
            with self.lock:
                current, self.current = self.current, None
            self.emit(
                nodeid=item.nodeid,
                phase=phase,
                state="finished",
                seconds=monotonic() - current[2] if current else None,
            )

        def tasks(self, reference: Any, nodeid: str, phase: str) -> None:
            loop = reference()
            if loop is None:
                return
            with self.lock:
                stack_stream.write(f"\n[ci-tasks] {nodeid} phase={phase}\n")
                for task in asyncio.all_tasks(loop):
                    stack_stream.write(f"task={task.get_name()} done={task.done()} cancelling={task.cancelling()}\n")
                    for frame in task.get_stack(limit=12):
                        traceback.print_stack(frame, limit=12, file=stack_stream)
                stack_stream.flush()

        def watch(self) -> None:
            previous = None
            next_dump = 0.0
            while not self.stop.wait(min(1.0, interval)):
                with self.lock:
                    current = self.current
                if current is None:
                    continue
                nodeid, phase, started, loops = current
                if (nodeid, phase, started) != previous:
                    previous, next_dump = (nodeid, phase, started), started + interval
                if monotonic() < next_dump:
                    continue
                next_dump += interval
                self.emit(
                    nodeid=nodeid,
                    phase=phase,
                    state="waiting",
                    seconds=monotonic() - started,
                )
                with self.lock:
                    faulthandler.dump_traceback(file=stack_stream, all_threads=True)
                    stack_stream.flush()
                for reference in loops:
                    loop = reference()
                    if loop is not None and loop.is_running():
                        try:
                            loop.call_soon_threadsafe(self.tasks, reference, nodeid, phase)
                        except RuntimeError:
                            pass
                    del loop

        def pytest_sessionstart(self, session: Any) -> None:
            self.thread = threading.Thread(target=self.watch, daemon=True, name="ci-phase-observer")
            self.thread.start()

        def pytest_sessionfinish(self, session: Any, exitstatus: int) -> None:
            self.stop.set()
            if self.thread:
                self.thread.join(timeout=1)
            phase_stream.close()
            stack_stream.close()

        @pytest.hookimpl(hookwrapper=True, tryfirst=True)
        def pytest_runtest_setup(self, item: Any) -> Any:
            self.begin(item, "setup")
            try:
                yield
            finally:
                self.end(item, "setup")

        @pytest.hookimpl(hookwrapper=True, tryfirst=True)
        def pytest_runtest_call(self, item: Any) -> Any:
            self.begin(item, "call")
            try:
                yield
            finally:
                self.end(item, "call")

        @pytest.hookimpl(hookwrapper=True, tryfirst=True)
        def pytest_runtest_teardown(self, item: Any, nextitem: Any) -> Any:
            self.begin(item, "teardown")
            try:
                yield
            finally:
                self.end(item, "teardown")

    config.pluginmanager.register(Diagnostics(), "ci-phase-diagnostics")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=int)
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--manifest-dir", type=Path, default=Path("test-results"))
    parser.add_argument("--verify", type=Path, help="каталог скачанных manifests всех runners")
    args = parser.parse_args(argv)
    try:
        if args.verify is not None:
            verify_manifests(sorted(args.verify.rglob("manifest-*.json")), args.count)
            return 0
        if args.index is None:
            parser.error("нужен --index либо --verify")
        sys.stdout.write(f"[shard {args.index}/{args.count}] Collecting complete pytest suite\n")
        sys.stdout.flush()
        collected = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            cwd=ROOT / "backend",
            check=False,
            capture_output=True,
            text=True,
        )
        if collected.returncode:
            sys.stderr.write(collected.stdout + collected.stderr)
            return collected.returncode
        modules = collection_modules(collected.stdout)
        selected = partition(modules, args.index, args.count)
        args.manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest: dict[str, Any] = {
            "index": args.index,
            "count": args.count,
            "discovered": modules,
            "selected": selected,
            "nodeids": [line for line in collected.stdout.splitlines() if line.startswith("tests/") and "::" in line],
            "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "exit_code": None,
            "executed_count": None,
        }
        manifest_path = args.manifest_dir / f"manifest-{args.index}.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))
        junit = (args.manifest_dir / f"shard-{args.index}.xml").resolve()
        expected_count = sum(node.split("::", 1)[0] in selected for node in manifest["nodeids"])
        sys.stdout.write(
            f"[shard {args.index}/{args.count}] Collected {len(manifest['nodeids'])} tests in {len(modules)} modules; "
            f"running {expected_count} tests in {len(selected)} modules\n"
        )
        sys.stdout.flush()
        child_env = dict(os.environ)
        child_env["PYTHONPATH"] = str(ROOT) + os.pathsep + child_env.get("PYTHONPATH", "")
        child_env["CX_CI_PHASE_LOG"] = str((args.manifest_dir / f"phases-{args.index}.jsonl").resolve())
        result = subprocess.run(
            [
                sys.executable,
                "-u",
                "-m",
                "pytest",
                "-vv",
                "-p",
                "scripts.ci_test_shard",
                "-o",
                "faulthandler_timeout=300",
                "-o",
                "faulthandler_exit_on_timeout=true",
                f"--junitxml={junit}",
                *selected,
            ],
            cwd=ROOT / "backend",
            check=False,
            env=child_env,
        )
        manifest["exit_code"] = result.returncode
        if junit.exists():
            manifest["executed_count"] = len(ET.parse(junit).findall(".//testcase"))
        manifest_path.write_text(json.dumps(manifest, indent=2))
        sys.stdout.write(
            f"[shard {args.index}/{args.count}] Finished: exit_code={result.returncode}, "
            f"executed={manifest['executed_count']}/{expected_count}\n"
        )
        sys.stdout.flush()
        return result.returncode
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
