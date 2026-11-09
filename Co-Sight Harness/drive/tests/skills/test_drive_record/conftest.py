"""Fixtures for drive-record tests.

提供 4 类 plan_dir：
- phase_completed_plan: 复用 workdir-demo 真实样本
- phase_executing_plan: 复用 workdir-demo 真实样本
- dag_plan: 手工合成（DAG 模式）
- residual_plan: 在 phase_completed 基础上删除 SUMMARY.md / 删事件

fixtures 直接指向 04-example/workdir-demo/.drive/plan-*（手工填的演示产物）。
residual fixture 用 tmp_path 复制后修改。
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PLUGIN_ROOT = PROJECT_ROOT / "03-drive-core"
DRIVE_RECORD_SCRIPTS = PLUGIN_ROOT / "skills" / "drive-record" / "scripts"

# 让测试用裸名 `from record_reader import ...` 直接 import drive-record 脚本
if str(DRIVE_RECORD_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(DRIVE_RECORD_SCRIPTS))


PLUGIN_ROOT = Path(__file__).resolve().parents[4]
WORKDIR_DEMO = PLUGIN_ROOT / "04-example" / "workdir-demo" / ".drive"
PHASE_COMPLETED = WORKDIR_DEMO / "plan-20260818-0930-fix-import-deadlock"
PHASE_EXECUTING = WORKDIR_DEMO / "plan-20260818-1045-add-user-auth"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def phase_completed_plan() -> Path:
    assert PHASE_COMPLETED.is_dir(), f"workdir-demo 真实样本不存在: {PHASE_COMPLETED}"
    return PHASE_COMPLETED


@pytest.fixture(scope="session")
def phase_executing_plan() -> Path:
    assert PHASE_EXECUTING.is_dir(), f"workdir-demo 真实样本不存在: {PHASE_EXECUTING}"
    return PHASE_EXECUTING


@pytest.fixture(scope="session")
def dag_plan_dir() -> Path:
    """DAG mode 合成 fixture。"""
    dag_path = FIXTURE_DIR / "dag-plan"
    if dag_path.is_dir():
        return dag_path
    dag_path.mkdir(parents=True, exist_ok=True)

    execute_state = {
        "schema_version": "drive.runtime.state.v1",
        "revision": 8,
        "active_stage": "execute",
        "status": "executing",
        "mode": "dag",
        "current_wave": 2,
        "waves_total": 3,
        "next_action": None,
        "confirmed_stages": ["start", "analyze", "plan"],
        "pending_confirmation": None,
        "created_at": "2026-08-15T10:00:00Z",
        "updated_at": "2026-08-15T10:30:00Z",
        "active_agents": [
            {"id": "researcher", "status": "completed", "started_at": "2026-08-15T10:00:00Z",
             "completed_at": "2026-08-15T10:10:00Z"},
            {"id": "summarizer", "status": "running", "started_at": "2026-08-15T10:10:00Z"},
        ],
    }
    (dag_path / "executeState.json").write_text(
        json.dumps(execute_state, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    run_meta = {
        "schema_version": "drive.runtime.run_meta.v1",
        "plan_name": "dag-demo",
        "plan_dir": dag_path.name,
        "git_head": "abc1234",
        "git_branch": "main",
        "workflow_hash": "sha256:fake",
        "input_digests": {},
        "started_at": "2026-08-15T10:00:00Z",
        "worktree": "/tmp/dag-demo",
    }
    (dag_path / "run-meta.json").write_text(
        json.dumps(run_meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    events = [
        {"ts": "2026-08-15T10:00:00+00:00", "event": "drive_startup",
         "plan_dir": dag_path.name, "plan_name": "dag-demo", "pid": 99999},
        {"ts": "2026-08-15T10:00:05+00:00", "event": "stage_advanced",
         "from": "start", "to": "analyze"},
        {"ts": "2026-08-15T10:05:00+00:00", "event": "stage_advanced",
         "from": "analyze", "to": "plan"},
        {"ts": "2026-08-15T10:10:00+00:00", "event": "stage_advanced",
         "from": "plan", "to": "execute"},
        {"ts": "2026-08-15T10:10:05+00:00", "event": "agent_spawned",
         "subagent_type": "researcher", "active_stage": "execute",
         "session_id": "sess-dag-001", "state_revision_at_spawn": 5},
        {"ts": "2026-08-15T10:10:30+00:00", "event": "agent_spawned",
         "subagent_type": "summarizer", "active_stage": "execute",
         "session_id": "sess-dag-001", "state_revision_at_spawn": 6},
    ]
    lines_text = "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n"
    (dag_path / "run-log.jsonl").write_text(lines_text, encoding="utf-8")

    (dag_path / "manifest.md").write_text(
        "# Manifest\ncomplexity: standard\n## Requirements\n- R1: dag demo\n", encoding="utf-8"
    )
    (dag_path / "intent.md").write_text("# Intent\ntest dag\n", encoding="utf-8")
    return dag_path


@pytest.fixture
def residual_plan(tmp_path: Path, phase_completed_plan: Path) -> Path:
    """基于 phase_completed_plan 复制 + 删除 SUMMARY.md 制造残缺。"""
    target = tmp_path / "residual-plan"
    shutil.copytree(phase_completed_plan, target)
    artifacts = target / "artifacts"
    if artifacts.is_dir():
        for child in artifacts.iterdir():
            summary = child / "SUMMARY.md"
            if summary.is_file():
                summary.unlink()
    return target


@pytest.fixture
def missing_record_dir(tmp_path: Path) -> Path:
    """空目录（所有 9 个核心文件全缺）。用于测试 missing_file gap。"""
    p = tmp_path / "empty-plan"
    p.mkdir()
    return p