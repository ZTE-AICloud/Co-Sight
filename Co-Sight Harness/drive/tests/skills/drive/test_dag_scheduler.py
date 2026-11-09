"""dag_flow + dag_init + dag_runtime 集成测试 —— 通过 subprocess 调 dag_runtime.py。

对应 PR#4 + PR#6。Phase 7 拆分后：
- dag_state_cli 已迁 dag-runtime/scripts/dag_runtime.py
- dag_scheduler 已拆 dag-runtime/scripts/dag_init.py（state 写）+ drive/scripts/dag_flow.py（决策）
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "dag_state"
PLUGIN_ROOT = Path(__file__).resolve().parents[3]
DRIVE_SCRIPTS = Path(__file__).resolve().parents[3] / "skills" / "drive" / "scripts"
DAG_RUNTIME_SCRIPTS = Path(__file__).resolve().parents[3] / "skills" / "dag-runtime" / "scripts"
STATE_SCRIPTS = Path(__file__).resolve().parents[3] / "skills" / "state-machine" / "scripts"

sys.path.insert(0, str(DRIVE_SCRIPTS))
sys.path.insert(0, str(DAG_RUNTIME_SCRIPTS))
sys.path.insert(0, str(STATE_SCRIPTS))

from read_workflow import load_workflow  # noqa: E402


def _init_planning_dir(tmp_path: Path) -> Path:
    """初始化 `.drive/<plan_dir>/` 目录。

    drive 内部约定 `.drive/<plan_dir>/` 由 startup 初始化；这里手动建一个空目录。
    dag_runtime 第一次调用会创建默认的 executeState.json。
    """
    planning = tmp_path / ".planning"
    planning.mkdir()
    return planning


def _run_dag_runtime(planning_dir: Path, *args: str) -> dict:
    """调 dag_runtime 子进程，返回 parsed JSON。"""
    cmd = ["python3", str(DAG_RUNTIME_SCRIPTS / "dag_runtime.py"), "--planning-dir", str(planning_dir)] + list(args)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    assert proc.returncode in (0, 1), f"unexpected rc={proc.returncode}: {proc.stderr}"
    return json.loads(proc.stdout)


class TestDagRuntimeBasic:
    """dag_runtime 子进程读写测试。"""

    def test_set_then_read_active_agents(self, tmp_path):
        planning = _init_planning_dir(tmp_path)
        agents = [
            {"id": "a", "wave": 1, "status": "running"},
            {"id": "b", "wave": 1, "status": "running"},
            {"id": "c", "wave": 2, "status": "running", "depends_on": ["a", "b"]},
        ]
        result = _run_dag_runtime(planning, "set-active-agents", "--json", json.dumps(agents))
        assert result["ok"], result

        read = _run_dag_runtime(planning, "read-active-agents")
        assert read["ok"]
        assert len(read["data"]["active_agents"]) == 3
        ids = {a["id"] for a in read["data"]["active_agents"]}
        assert ids == {"a", "b", "c"}

    def test_mark_completed(self, tmp_path):
        planning = _init_planning_dir(tmp_path)
        # 先初始化
        agents = [{"id": "a", "wave": 1, "status": "running"}]
        _run_dag_runtime(planning, "set-active-agents", "--json", json.dumps(agents))

        # mark-completed 现在 default-deny：先 confirm_node 再 mark-completed。
        confirm = subprocess.run(
            [sys.executable, str(DAG_RUNTIME_SCRIPTS / "confirm_node.py"),
             "--planning-dir", str(planning), "--agent-id", "a"],
            capture_output=True, text=True,
        )
        assert confirm.returncode == 0, confirm.stdout

        # 标记 completed
        result = _run_dag_runtime(planning, "mark-completed", "--agent-id", "a")
        assert result["ok"], result

        # 读回确认
        read = _run_dag_runtime(planning, "read-active-agents")
        a = next(x for x in read["data"]["active_agents"] if x["id"] == "a")
        assert a["status"] == "completed"
        assert "updated_at" in a

    def test_mark_failed_for_unknown_agent(self, tmp_path):
        planning = _init_planning_dir(tmp_path)
        # 不初始化 agents
        result = _run_dag_runtime(planning, "mark-failed", "--agent-id", "nonexistent")
        assert not result["ok"]
        assert result["reason"] == "invalid_agent"

    def test_advance_wave_increments(self, tmp_path):
        planning = _init_planning_dir(tmp_path)
        state_path = planning / "executeState.json"
        state_path.write_text(
            json.dumps({"current_wave": 0, "waves_total": 3}),
            encoding="utf-8",
        )
        result = _run_dag_runtime(planning, "advance-wave")
        assert result["ok"]
        # 读回 state 验证 current_wave 已进位
        state_read = subprocess.run(
            [sys.executable, str(STATE_SCRIPTS / "state_cli.py"),
             "read", "--planning-dir", str(planning)],
            capture_output=True, text=True,
        )
        assert state_read.returncode == 0, state_read.stderr
        state = json.loads(state_read.stdout)["data"]["state"]
        assert state["current_wave"] == 1


class TestDagFlowSubprocess:
    """dag_flow.py（drive）+ dag_init.py（dag-runtime）子进程调用。"""

    def test_dag_flow_help(self):
        """基本 smoke test：dag_flow --help 能跑。"""
        proc = subprocess.run(
            ["python3", str(DRIVE_SCRIPTS / "dag_flow.py"), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0
        assert "advance" in proc.stdout
        assert "finalize" in proc.stdout

    def test_dag_init_help(self):
        """dag_init --help 能跑。"""
        proc = subprocess.run(
            ["python3", str(DAG_RUNTIME_SCRIPTS / "dag_init.py"), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0
        assert "plan-waves" in proc.stdout

    def test_finalize_help(self):
        proc = subprocess.run(
            ["python3", str(DRIVE_SCRIPTS / "dag_flow.py"), "finalize", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0
        assert "--workflow" in proc.stdout
        assert "--planning-dir" in proc.stdout

    def test_plan_waves_consumes_caller_waves(self, tmp_path):
        """dag_init plan-waves 只消费 caller 算好的 waves（不再内部算）。"""
        from dag_init import plan_waves

        planning = _init_planning_dir(tmp_path)
        workflow = {
            "mode": "dag",
            "agents": [{"id": "a"}, {"id": "b", "depends_on": ["a"]}],
        }
        caller_waves = [["a"], ["b"]]
        result = plan_waves(workflow, caller_waves, planning_dir=planning)
        assert result["ok"], result
        assert result["data"]["waves"] == caller_waves

        read = _run_dag_runtime(planning, "read-active-agents")
        assert read["ok"]
        wave_map = {a["id"]: a["wave"] for a in read["data"]["active_agents"]}
        assert wave_map == {"a": 1, "b": 2}


class TestDagFlowFinalize:
    """dag_flow.finalize_workflow verdict gate。"""

    def _write_workflow_yaml(self, tmp_path: Path, agents: list[dict]) -> Path:
        """生成含至少一个 terminal agent 的 workflow.yaml。"""
        has_terminal = any(a.get("terminal") for a in agents)
        if not has_terminal:
            agents = list(agents) + [{"id": "sink", "terminal": True}]
        wf = tmp_path / "workflow.yaml"
        wf.write_text(
            "mode: dag\n"
            "agents:\n"
            + "".join(
                f"  - id: {a['id']}\n"
                f"    agent: '{a.get('agent', '@Explore')}'\n"
                f"    depends_on: {a.get('depends_on', [])}\n"
                + ("    terminal: true\n" if a.get("terminal") else "")
                + ("    verdict_required: true\n" if a.get("verdict_required") else "")
                for a in agents
            )
        )
        return wf

    def _init_planning(self, tmp_path: Path, verdict: str | None = None) -> Path:
        planning = tmp_path / ".planning"
        planning.mkdir()
        if verdict is not None:
            from state_write import update_fields

            update_fields(planning, verdict=verdict)
        return planning

    def test_finalize_no_verdict_required_ok(self, tmp_path):
        """workflow 里没有 verdict_required agent → finalize 直接 ok。"""
        from dag_flow import finalize_workflow

        agents = [{"id": "a"}, {"id": "b", "depends_on": ["a"]}]
        wf = self._write_workflow_yaml(tmp_path, agents)
        env = load_workflow(str(tmp_path))
        assert env.ok
        planning = self._init_planning(tmp_path)

        result = finalize_workflow(planning, env.data)
        assert result["ok"], result
        assert result["data"]["done"] is True
        assert result["data"]["reason"] == "no_verdict_required"

    def test_finalize_verdict_pass_ok(self, tmp_path):
        """workflow 有 verdict_required agent + state.verdict=pass → ok。"""
        from dag_flow import finalize_workflow

        agents = [
            {"id": "a"},
            {"id": "evaluator", "depends_on": ["a"], "terminal": True, "verdict_required": True},
        ]
        wf = self._write_workflow_yaml(tmp_path, agents)
        env = load_workflow(str(tmp_path))
        assert env.ok
        planning = self._init_planning(tmp_path, verdict="pass")

        result = finalize_workflow(planning, env.data)
        assert result["ok"], result
        assert result["data"]["done"] is True
        assert result["data"]["reason"] == "verdict_pass"
        assert result["data"]["verdict_required_agents"] == ["evaluator"]

    def test_finalize_verdict_missing_fails(self, tmp_path):
        """workflow 有 verdict_required agent + state 无 verdict → fail。"""
        from dag_flow import finalize_workflow

        agents = [
            {"id": "a"},
            {"id": "evaluator", "depends_on": ["a"], "terminal": True, "verdict_required": True},
        ]
        wf = self._write_workflow_yaml(tmp_path, agents)
        env = load_workflow(str(tmp_path))
        assert env.ok
        planning = self._init_planning(tmp_path, verdict=None)

        result = finalize_workflow(planning, env.data)
        assert not result["ok"], result
        assert result["reason"] == "verdict_not_pass"

    def test_finalize_cli_subprocess(self, tmp_path):
        """dag_flow finalize CLI 端到端。"""
        agents = [
            {"id": "a"},
            {"id": "evaluator", "depends_on": ["a"], "terminal": True, "verdict_required": True},
        ]
        wf = self._write_workflow_yaml(tmp_path, agents)
        planning = self._init_planning(tmp_path, verdict="pass")

        proc = subprocess.run(
            [
                "python3", str(DRIVE_SCRIPTS / "dag_flow.py"),
                "finalize",
                "--workflow", str(wf),
                "--planning-dir", str(planning),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0, f"rc={proc.returncode}: {proc.stderr}"
        env = json.loads(proc.stdout)
        assert env["ok"], env
        assert env["data"]["done"] is True

    def test_finalize_cli_fails_when_verdict_missing(self, tmp_path):
        """CLI 路径下 verdict 缺失 → 退出码非 0。"""
        agents = [
            {"id": "evaluator", "terminal": True, "verdict_required": True},
        ]
        wf = self._write_workflow_yaml(tmp_path, agents)
        planning = self._init_planning(tmp_path, verdict=None)

        proc = subprocess.run(
            [
                "python3", str(DRIVE_SCRIPTS / "dag_flow.py"),
                "finalize",
                "--workflow", str(wf),
                "--planning-dir", str(planning),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 1
        env = json.loads(proc.stdout)
        assert not env["ok"]
        assert env["reason"] == "verdict_not_pass"


class TestDagInitInvalidWorkflow:
    """dag_init CLI 在非法 workflow.yaml 下的失败路径。

    回归：dag_init.plan_waves 在非法 workflow 时输出 ok:false envelope + 退出码 1，不崩溃。
    """

    def _write_invalid_workflow(self, tmp_path: Path, content: str) -> Path:
        wf = tmp_path / "workflow.yaml"
        wf.write_text(content)
        return wf

    def test_plan_waves_invalid_workflow_clean_fail(self, tmp_path):
        """agents 为空 → 输出 ok:false envelope + 退出码 1，不崩溃。"""
        wf = self._write_invalid_workflow(tmp_path, "mode: dag\nagents: []\n")
        planning = _init_planning_dir(tmp_path)

        proc = subprocess.run(
            [
                "python3", str(DAG_RUNTIME_SCRIPTS / "dag_init.py"),
                "plan-waves",
                "--workflow", str(wf),
                "--planning-dir", str(planning),
                "--waves-json", "[[\"a\"]]",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 1, f"rc={proc.returncode}: {proc.stderr}"
        env = json.loads(proc.stdout)
        assert not env["ok"]
        assert env["reason"] == "schema_invalid"
        assert "agents" in env["details"]["hint"]

    def test_finalize_missing_workflow_clean_fail(self, tmp_path):
        """workflow.yaml 不存在 → 输出 ok:false envelope + 退出码 1，不崩溃。"""
        wf = tmp_path / "workflow.yaml"  # 不写文件
        planning = _init_planning_dir(tmp_path)

        proc = subprocess.run(
            [
                "python3", str(DRIVE_SCRIPTS / "dag_flow.py"),
                "finalize",
                "--workflow", str(wf),
                "--planning-dir", str(planning),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 1, f"rc={proc.returncode}: {proc.stderr}"
        env = json.loads(proc.stdout)
        assert not env["ok"]
        assert env["reason"] in ("file_missing", "yaml_decode_error", "schema_invalid")
        assert "AttributeError" not in proc.stderr
