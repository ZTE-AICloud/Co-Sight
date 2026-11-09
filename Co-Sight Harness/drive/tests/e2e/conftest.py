"""E2E fixtures —— 端到端跑确定性路径，不调 LLM。

按生产方式驱动：每个岗位脚本以子进程执行，编排结构从 workflow.yaml 读，state
经 state-machine skill 的 CLI 写。agent 的语义产出（manifest / taskRecord 内容）
由 fixture 直接落盘代替，因为那部分才是 LLM 的活。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.script_loader import PLUGIN_ROOT, scripts_dir

STATE_CLI = scripts_dir("state-machine") / "state_cli.py"
CONFIRM_STAGE = scripts_dir("state-machine") / "confirm_stage.py"
READ_WORKFLOW = scripts_dir("drive") / "read_workflow.py"
INIT_PLANNING = scripts_dir("startup") / "init_planning.py"
TOPO_SORT = scripts_dir("wave-scheduling") / "topo_sort.py"


def run_script(script: Path, *args: str) -> tuple[int, dict]:
    """跑一个岗位脚本，返回 (exit_code, envelope)。"""
    proc = subprocess.run(
        [sys.executable, str(script), *args], capture_output=True, text=True
    )
    payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
    return proc.returncode, payload


def state_cli(planning_dir: Path, *args: str) -> tuple[int, dict]:
    return run_script(STATE_CLI, *args, "--planning-dir", str(planning_dir))


def confirm(planning_dir: Path, stage: str, *, note: str = "e2e") -> tuple[int, dict]:
    """代替人工放行某阶段。

    生产中这条命令不在任何 skill 的 allowed-tools 内，模型跑它会向用户请求授权
    —— 那个授权即人工确认。测试里直接调，等价于"用户点了允许"。
    """
    return run_script(
        CONFIRM_STAGE, "--planning-dir", str(planning_dir), "--stage", stage,
        "--note", note,
    )


def advance(planning_dir: Path, from_stage: str, to_stage: str) -> tuple[int, dict]:
    """确认当前阶段后推进 —— 正常路径的完整两步。"""
    confirm(planning_dir, from_stage)
    return state_cli(planning_dir, "transition", "--to", to_stage)


def read_state(planning_dir: Path) -> dict:
    code, payload = state_cli(planning_dir, "read")
    assert code == 0, payload
    return payload["data"]["state"]


def read_run_log(planning_dir: Path) -> list[dict]:
    path = planning_dir / "run-log.jsonl"
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_workflow(work_dir: Path) -> dict:
    code, payload = run_script(
        READ_WORKFLOW, "--work-dir", str(work_dir), "--plugin-root", str(PLUGIN_ROOT)
    )
    assert code == 0, payload
    return payload["data"]


def _git_init(work_dir: Path) -> None:
    for cmd in (
        ["git", "init"],
        ["git", "config", "user.email", "e2e@drive.local"],
        ["git", "config", "user.name", "drive-e2e"],
    ):
        subprocess.run(cmd, cwd=work_dir, capture_output=True, check=True)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """git 已初始化、含一份 proposal 的工作目录，尚无 .drive/。"""
    ws = tmp_path / "workspace"
    ws.mkdir()
    _git_init(ws)
    (ws / "proposal.md").write_text(
        "# Proposal\n\n## User Intent\n\n写一个 hello world CLI\n", encoding="utf-8"
    )
    return ws


TEST_PLAN_DIR = "plan-e2e"


@pytest.fixture
def started(workspace: Path) -> Path:
    """已跑过 startup 的工作目录：.drive/<plan_dir>/ 就绪，default_state() 落盘。

    default_state() 现在 active_stage=None（不是 "start"）——所以 fixture 不再
    手工补 transition。drive §3 phase-mode 调度会自己调 transition 推第一 phase。
    """
    code, payload = run_script(
        INIT_PLANNING,
        "--work-dir", str(workspace),
        "--plan-dir", TEST_PLAN_DIR,
        "--intent", "写一个 hello world CLI",
    )
    assert code == 0, payload
    # .current-plan 标记供 hook_io.find_active_plan_dir 找到当前 plan
    (workspace / ".drive" / ".current-plan").write_text(TEST_PLAN_DIR, encoding="utf-8")
    return workspace


@pytest.fixture
def at_stage(started: Path):
    """把工作流推到指定阶段，返回 (work_dir, planning_dir)。"""
    planning = started / ".drive" / TEST_PLAN_DIR
    routes = {
        "start": [],
        "analyze": ["analyze"],
        "plan": ["analyze", "plan"],
        "execute": ["analyze", "plan", "execute"],
        "evaluate": ["analyze", "plan", "execute", "evaluate"],
    }

    def _advance(target: str) -> tuple[Path, Path]:
        current = "start"
        for stage in routes[target]:
            code, payload = advance(planning, current, stage)
            assert code == 0, f"{current} → {stage} 失败: {payload}"
            current = stage
        return started, planning

    return _advance


@pytest.fixture
def write_task_record():
    """代 planner 落盘 taskRecord.yaml —— 内容本是 LLM 的产出。"""

    def _write(planning_dir: Path, tasks: list[dict]) -> Path:
        import yaml

        path = planning_dir / "taskRecord.yaml"
        path.write_text(
            yaml.safe_dump({"plan_id": "e2e-plan", "tasks": tasks}, allow_unicode=True),
            encoding="utf-8",
        )
        return path

    return _write
