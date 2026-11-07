"""Host network не делает чужой listener собственным портом контейнера."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "install_host_port", Path(__file__).resolve().parents[3] / "scripts/install_host_port.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize(
    "table,state,port,listener_inode,owned_inode,process_name,expected",
    [
        ("tcp", "0A", 8000, 111, 111, "1", True),
        ("tcp6", "0A", 8000, 111, 111, "37", True),
        ("tcp", "0A", 8000, 111, 222, "1", False),
        ("tcp", "01", 8000, 111, 111, "1", False),
        ("tcp", "0A", 8001, 111, 111, "1", False),
        ("tcp", "0A", 8000, 111, None, "1", False),
        ("tcp", "0A", 8000, 111, 111, "self", False),
    ],
)
def test_listener_must_belong_to_container_pid_namespace(
    tmp_path, table, state, port, listener_inode, owned_inode, process_name, expected
):
    (tmp_path / "net").mkdir()
    (tmp_path / "net" / table).write_text(
        f"header\n0: 00000000:{port:04X} 00000000:0000 {state} 0:0 0:0 0 0 0 {listener_inode}\n"
    )
    fd = tmp_path / process_name / "fd"
    fd.mkdir(parents=True)
    if owned_inode is not None:
        (fd / "7").symlink_to(f"socket:[{owned_inode}]")
    assert module.owns_listener(8000, tmp_path) is expected


def test_missing_ipv4_and_ipv6_tables_cannot_prove_ownership(tmp_path):
    assert not module.owns_listener(8000, tmp_path)
