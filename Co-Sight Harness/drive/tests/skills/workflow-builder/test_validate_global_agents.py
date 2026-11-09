"""workflow-builder/scripts/validate_workflow.py --global-agents-dir 行为。

修复 E1：之前裸名 agent 引用只查项目 .claude/agents/ + 插件 agents/。
用户全局 agent（~/.claude/agents/）解析不到 → 必须用 @-mention workaround。

新增 --global-agents-dir 参数：裸名 agent 在 project 不存在时 fallback 到
global 目录解析。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = PLUGIN_ROOT / "skills" / "workflow-builder" / "scripts" / "validate_workflow.py"

sys.path.insert(0, str(SCRIPT.parent))
import validate_workflow as vw  # noqa: E402


def _write_wf(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "workflow.yaml"
    p.write_text(content, encoding="utf-8")
    return p


def _write_agents(agents_dir: Path, *names: str) -> None:
    agents_dir.mkdir(parents=True, exist_ok=True)
    for n in names:
        (agents_dir / f"{n}.md").write_text(
            f"---\nname: {n}\n---\n# {n}\n", encoding="utf-8"
        )


# ---------- function-level test ----------


def test_bare_name_resolves_via_global_agents(tmp_path: Path):
    """裸名 agent 在 project 不存在但 global 存在 → 通过。"""
    project_agents = tmp_path / "project" / ".claude" / "agents"
    global_agents = tmp_path / "global" / ".claude" / "agents"
    _write_agents(project_agents, "project-agent")
    _write_agents(global_agents, "global-agent")

    ok, err = vw._validate_agent_ref(
        "global-agent",
        vw._scan_agent_names(project_agents),
        vw._scan_agent_names(PLUGIN_ROOT / "agents"),
        vw._scan_agent_names(global_agents),
    )
    assert ok is True
    assert err is None


def test_bare_name_falls_through_when_neither_has_it(tmp_path: Path):
    """project + global 都没有 → fail。"""
    project_agents = tmp_path / "project" / ".claude" / "agents"
    global_agents = tmp_path / "global" / ".claude" / "agents"
    _write_agents(project_agents, "proj-only")
    _write_agents(global_agents, "glob-only")

    ok, err = vw._validate_agent_ref(
        "ghost",
        vw._scan_agent_names(project_agents),
        vw._scan_agent_names(PLUGIN_ROOT / "agents"),
        vw._scan_agent_names(global_agents),
    )
    assert ok is False
    assert "ghost" in err
    assert "proj-only" in err
    assert "glob-only" in err


def test_project_takes_precedence_over_global(tmp_path: Path):
    """project 与 global 同名 → project 优先（不冲突，因为同名同 agent）。"""
    project_agents = tmp_path / "project" / ".claude" / "agents"
    global_agents = tmp_path / "global" / ".claude" / "agents"
    _write_agents(project_agents, "shared-agent")
    _write_agents(global_agents, "shared-agent")

    ok, _ = vw._validate_agent_ref(
        "shared-agent",
        vw._scan_agent_names(project_agents),
        vw._scan_agent_names(PLUGIN_ROOT / "agents"),
        vw._scan_agent_names(global_agents),
    )
    assert ok is True


# ---------- CLI-level test ----------


def test_cli_global_agents_dir_arg(tmp_path: Path):
    """--global-agents-dir CLI 参数生效。"""
    work_dir = tmp_path / "proj"
    work_dir.mkdir()
    global_agents = tmp_path / "glob" / ".claude" / "agents"
    _write_agents(global_agents, "glob-only")

    wf = _write_wf(
        work_dir,
        """mode: dag
agents:
  - id: only
    agent: glob-only
    depends_on: []
    terminal: true
    verdict_required: true
""",
    )
    result = subprocess.run(
        [
            "python3", str(SCRIPT),
            str(wf),
            "--work-dir", str(work_dir),
            "--global-agents-dir", str(global_agents.parent),
        ],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout
    out = json.loads(result.stdout)
    assert out["ok"] is True, out


def test_cli_without_global_agents_dir_fails(tmp_path: Path):
    """不传 --global-agents-dir 且 agent 只在 global → fail。"""
    work_dir = tmp_path / "proj"
    work_dir.mkdir()
    global_agents = tmp_path / "glob" / ".claude" / "agents"
    _write_agents(global_agents, "glob-only")

    wf = _write_wf(
        work_dir,
        """mode: dag
agents:
  - id: only
    agent: glob-only
    depends_on: []
    terminal: true
    verdict_required: true
""",
    )
    result = subprocess.run(
        [
            "python3", str(SCRIPT),
            str(wf),
            "--work-dir", str(work_dir),
        ],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    out = json.loads(result.stdout)
    assert out["ok"] is False
    assert "glob-only" in str(out)