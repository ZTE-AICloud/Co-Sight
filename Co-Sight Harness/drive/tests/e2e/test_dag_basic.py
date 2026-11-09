"""E2E: DAG 模式 workflow.yaml 端到端跑（PR#14）。

不调 LLM。验证 DAG 模式核心流程：
- read_workflow 解析 DAG workflow.yaml
- drive → /wave-scheduling 委托算 wave 划分（agents_to_tasks → topo-sort-from-tasks → apply_concurrency_cap）
- dag_runtime 初始化 + 推进 active_agents
- executeState.json 字段符合 validate_dag_state 校验
- dag_flow.finalize verdict gate
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.script_loader import PLUGIN_ROOT, scripts_dir

DAG_BASIC = PLUGIN_ROOT.parent / "04-example" / "dag-basic"
READ_WORKFLOW = scripts_dir("drive") / "read_workflow.py"
DAG_RUNTIME_CLI = scripts_dir("dag-runtime") / "dag_runtime.py"
DAG_FLOW = scripts_dir("drive") / "dag_flow.py"
AGENTS_TO_TASKS = scripts_dir("drive") / "agents_to_tasks.py"
APPLY_CONCURRENCY_CAP = scripts_dir("drive") / "apply_concurrency_cap.py"
TOPO_SORT = scripts_dir("wave-scheduling") / "topo_sort.py"


def _run(cmd: list[str], input_data: str | None = None, timeout: int = 30) -> dict:
    proc = subprocess.run(
        cmd,
        input=input_data,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(DAG_BASIC),
    )
    if proc.returncode not in (0, 1):
        pytest.fail(f"cmd {cmd[0]} failed: rc={proc.returncode}\n{proc.stderr}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(f"cmd {cmd[0]} returned non-JSON: {proc.stdout[:200]}\n{exc}")


class TestDagBasicE2E:
    """dag-basic 示例端到端。"""

    def test_workflow_yaml_parses(self):
        """dag-basic/workflow.yaml 解析成功。"""
        result = _run([
            "python3", str(READ_WORKFLOW),
            "--work-dir", str(DAG_BASIC),
            "--plugin-root", str(PLUGIN_ROOT),
        ])
        assert result["ok"], result
        assert result["data"]["mode"] == "dag"
        assert len(result["data"]["agents"]) == 6

    def test_wave_computation(self):
        """wave 计算正确（planner → {auth,api} → reviewer → gate-human → evaluator）。

        端到端跑 drive → wave-scheduling 委托链：
            agents_to_tasks.py → topo-sort-from-tasks → apply_concurrency_cap.py
        """
        # 1. drive 把 workflow.yaml agents[] 转换为 wave-scheduling 接受的 tasks JSON
        att = _run([
            "python3", str(AGENTS_TO_TASKS),
            "--workflow", str(DAG_BASIC / "workflow.yaml"),
        ])
        assert att["ok"], att
        tasks_json = json.dumps(att["data"]["tasks"])

        # 2. 委托 /wave-scheduling skill 的 topo-sort-from-tasks 子命令
        topo = _run(
            ["python3", str(TOPO_SORT), "topo-sort-from-tasks"],
            input_data=tasks_json,
        )
        assert topo["ok"], topo
        assert topo["data"]["wave_count"] == 5

        # 3. drive 用 apply_concurrency_cap 切分超量 wave（无超量，透传）
        cap = _run(
            ["python3", str(APPLY_CONCURRENCY_CAP), "--max-concurrent", "16"],
            input_data=json.dumps(topo),
        )
        assert isinstance(cap, list)
        waves = cap

        # wave 1: planner（独立）
        assert "planner" in waves[0]
        # wave 2: impl-auth, impl-api（并行）
        assert set(waves[1]) == {"impl-auth", "impl-api"}
        # wave 3: reviewer
        assert waves[2] == ["reviewer"]
        # wave 4: gate-human
        assert waves[3] == ["gate-human"]
        # wave 5: evaluator
        assert waves[4] == ["evaluator"]

    def test_state_lifecycle(self, tmp_path):
        """完整的 state 生命周期：init → 推进 → 终态。"""
        # 用 tmp_path 隔离
        planning = tmp_path / ".planning"
        planning.mkdir()

        # 1. 初始化 active_agents（6 个）
        agents_payload = [
            {"id": "planner", "wave": 1, "status": "running"},
            {"id": "impl-auth", "wave": 2, "status": "running"},
            {"id": "impl-api", "wave": 2, "status": "running"},
            {"id": "reviewer", "wave": 3, "status": "running"},
            {"id": "gate-human", "wave": 4, "status": "running"},
            {"id": "evaluator", "wave": 5, "status": "running", "terminal": True},
        ]
        result = _run([
            "python3", str(DAG_RUNTIME_CLI),
            "--planning-dir", str(planning),
            "set-active-agents",
            "--json", json.dumps(agents_payload),
        ])
        assert result["ok"], result

        # 2. wave 1：planner 完成 —— 先 confirm_node（模拟人工放行），再 mark-completed。
        result = _run([
            "python3", str(scripts_dir("dag-runtime") / "confirm_node.py"),
            "--planning-dir", str(planning),
            "--agent-id", "planner",
        ])
        assert result["ok"], result
        result = _run([
            "python3", str(DAG_RUNTIME_CLI),
            "--planning-dir", str(planning),
            "mark-completed", "--agent-id", "planner",
        ])
        assert result["ok"]

        # 3. wave 2：impl-auth 失败 → cascade impl-api 为 skipped
        result = _run([
            "python3", str(DAG_RUNTIME_CLI),
            "--planning-dir", str(planning),
            "mark-failed", "--agent-id", "impl-auth",
        ])
        assert result["ok"]

        # 手动 cascade（PR#4 dag_flow.cascade_skip_downstream 的逻辑）
        result = _run([
            "python3", str(DAG_RUNTIME_CLI),
            "--planning-dir", str(planning),
            "mark-skipped", "--agent-id", "impl-api",
        ])
        assert result["ok"]

        # 4. 读回状态确认
        result = _run([
            "python3", str(DAG_RUNTIME_CLI),
            "--planning-dir", str(planning),
            "read-active-agents",
        ])
        assert result["ok"]
        agents = {a["id"]: a["status"] for a in result["data"]["active_agents"]}
        assert agents["planner"] == "completed"
        assert agents["impl-auth"] == "failed"
        assert agents["impl-api"] == "skipped"


class TestDagVerdictGateE2E:
    """dag_flow.finalize + dag_runtime.check-terminal-verdict 端到端。"""

    def test_finalize_denies_without_verdict(self, tmp_path):
        """verdict_required agent 完成，但 state 无 verdict → finalize deny。"""
        planning = tmp_path / ".planning"
        planning.mkdir()

        workflow_yaml = tmp_path / "workflow.yaml"
        workflow_yaml.write_text(
            "mode: dag\n"
            "agents:\n"
            "  - id: planner\n"
            "    agent: '@Explore'\n"
            "    depends_on: []\n"
            "  - id: evaluator\n"
            "    agent: '@Plan'\n"
            "    depends_on: [planner]\n"
            "    terminal: true\n"
            "    verdict_required: true\n"
        )

        proc = subprocess.run(
            [
                "python3", str(DAG_FLOW),
                "finalize",
                "--workflow", str(workflow_yaml),
                "--planning-dir", str(planning),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 1, f"应该被拒: stdout={proc.stdout}, stderr={proc.stderr}"
        env = json.loads(proc.stdout)
        assert not env["ok"]
        assert env["reason"] == "verdict_not_pass"
        assert "evaluator" in env["details"]["required_agents"]

    def test_finalize_passes_when_verdict_pass(self, tmp_path):
        """state.verdict=pass → finalize 通过。"""
        planning = tmp_path / ".planning"
        planning.mkdir()

        proc = subprocess.run(
            [
                "python3", str(DAG_RUNTIME_CLI),
                "--planning-dir", str(planning),
                "set-active-agents",
                "--json", json.dumps([
                    {"id": "planner", "wave": 1, "status": "completed"},
                    {"id": "evaluator", "wave": 2, "status": "completed", "terminal": True},
                ]),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0

        sys.path.insert(0, str(scripts_dir("state-machine")))
        from state_write import update_fields

        update_fields(planning, verdict="pass")

        workflow_yaml = tmp_path / "workflow.yaml"
        workflow_yaml.write_text(
            "mode: dag\n"
            "agents:\n"
            "  - id: planner\n"
            "    agent: '@Explore'\n"
            "    depends_on: []\n"
            "  - id: evaluator\n"
            "    agent: '@Plan'\n"
            "    depends_on: [planner]\n"
            "    terminal: true\n"
            "    verdict_required: true\n"
        )

        proc = subprocess.run(
            [
                "python3", str(DAG_FLOW),
                "finalize",
                "--workflow", str(workflow_yaml),
                "--planning-dir", str(planning),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0, f"应该过: stdout={proc.stdout}, stderr={proc.stderr}"
        env = json.loads(proc.stdout)
        assert env["ok"]
        assert env["data"]["done"] is True
        assert env["data"]["reason"] == "verdict_pass"

    def test_finalize_no_verdict_required_always_passes(self, tmp_path):
        """无 verdict_required agent → finalize 直接通过（无论 verdict）。"""
        planning = tmp_path / ".planning"
        planning.mkdir()

        workflow_yaml = tmp_path / "workflow.yaml"
        workflow_yaml.write_text(
            "mode: dag\n"
            "agents:\n"
            "  - id: planner\n"
            "    agent: '@Explore'\n"
            "    depends_on: []\n"
            "  - id: sink\n"
            "    agent: '@Plan'\n"
            "    depends_on: [planner]\n"
            "    terminal: true\n"
        )

        proc = subprocess.run(
            [
                "python3", str(DAG_FLOW),
                "finalize",
                "--workflow", str(workflow_yaml),
                "--planning-dir", str(planning),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0
        env = json.loads(proc.stdout)
        assert env["ok"]
        assert env["data"]["reason"] == "no_verdict_required"
