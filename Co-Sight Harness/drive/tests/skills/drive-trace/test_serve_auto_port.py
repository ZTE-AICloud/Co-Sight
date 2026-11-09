"""drive-trace/scripts/serve.py --auto-port 端口探测。

修复 E2：之前 --port 写死，多 plan 并行时 8080 被占需手工 lsof 探测。
新增 --auto-port：从 --port 起向上探测空闲端口（最多 50 次）。
"""
from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "skills" / "drive-trace" / "scripts"))

import serve as srv  # noqa: E402


# ---------- pure-function port detection ----------


def test_find_free_port_returns_free_port():
    """调用返回一个可绑定的端口。"""
    host = "127.0.0.1"
    found = srv._find_free_port(host, 38000, max_attempts=10)
    # 验证返回的端口真的可绑
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, found))  # 不抛异常即可


def test_find_free_port_skips_occupied():
    """占用起始端口 → 跳到下一空闲。"""
    host = "127.0.0.1"
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind((host, 0))
    busy_port = occupied.getsockname()[1]
    try:
        found = srv._find_free_port(host, busy_port, max_attempts=20)
        assert found > busy_port, f"应跳过 busy_port={busy_port}, got {found}"
    finally:
        occupied.close()


# ---------- argparse wiring ----------


def test_auto_port_flag_in_help(capsys):
    """CLI help 显式 --auto-port 选项。"""
    import subprocess
    result = subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "skills" / "drive-trace" / "scripts" / "serve.py"), "--help"],
        capture_output=True, text=True,
    )
    assert "--auto-port" in result.stdout
    assert "--port" in result.stdout