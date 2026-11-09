"""Shared fixtures for the drive rewrite test suite.

Tests target 岗位脚本：skills/*/scripts/、agents/*/scripts/、hooks/。
No LLM calls — only deterministic SDK / runtime paths.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

_SCRIPT_DIRS = (
    PLUGIN_ROOT / "skills" / "drive" / "scripts",
    PLUGIN_ROOT / "skills" / "state-machine" / "scripts",
    PLUGIN_ROOT / "skills" / "wave-barrier" / "scripts",
    PLUGIN_ROOT / "skills" / "workflow-builder" / "scripts",
    PLUGIN_ROOT / "skills" / "drive-record" / "scripts",
    PLUGIN_ROOT / "hooks",
)


@pytest.fixture(autouse=True)
def sys_path_setup():
    """各 skill / hooks 的脚本同目录有同名 envelope.py，import 时会撞车。

    这里只把目录放进去，import 冲突由调用方按需 importlib 隔离。
    fixture 末尾原样还回，避免污染其它测试。
    """
    saved = list(sys.path)
    for d in _SCRIPT_DIRS:
        sys.path.insert(0, str(d))
    try:
        yield
    finally:
        for d in _SCRIPT_DIRS:
            try:
                sys.path.remove(str(d))
            except ValueError:
                pass


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """A temp workspace with an initialized git repo.

    Returns the workspace root. `.drive/<plan_dir>/` is NOT created here —
    the workflow layer owns that; tests that need it create it explicitly.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init"], cwd=workspace, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@drive.local"],
        cwd=workspace, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "drive-test"],
        cwd=workspace, capture_output=True, check=True,
    )
    return workspace


@pytest.fixture
def planning_dir(tmp_path: Path) -> Path:
    """A bare `.drive/<plan_dir>/` directory (no git, no state file)."""
    pdir = tmp_path / ".planning"
    pdir.mkdir()
    return pdir
