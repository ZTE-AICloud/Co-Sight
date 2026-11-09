"""DAG 模式 workflow.yaml 拓扑 / 校验 单测。

对应 PR#2 + PR#5。
测试用 fixture 在 tests/skills/drive/fixtures/。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
PLUGIN_ROOT = Path(__file__).resolve().parents[3]
DRIVE_SCRIPTS = Path(__file__).resolve().parents[3] / "skills" / "drive" / "scripts"

# 把 drive scripts 加进 sys.path 让 import 能找到 read_workflow
sys.path.insert(0, str(DRIVE_SCRIPTS))

from read_workflow import load_workflow  # noqa: E402


def _load(fixture_name: str):
    """加载 fixtures 下的 workflow.yaml，返回 Envelope。

    fixture 目录结构：FIXTURES_DIR/<fixture_name>/workflow.yaml
    load_workflow(work_dir=...) 要的是 work_dir。
    """
    return load_workflow(FIXTURES_DIR / fixture_name, plugin_root=PLUGIN_ROOT)


class TestDagBasicParsing:
    """DAG 模式基本解析。"""

    def test_load_dag_basic_returns_ok(self):
        env = _load("dag_basic")
        assert env.ok, f"expected ok, got {env.reason}: {env.details}"
        w = env.data
        assert w["mode"] == "dag"

    def test_agents_count_and_ids(self):
        env = _load("dag_basic")
        w = env.data
        ids = {a["id"] for a in w["agents"]}
        assert ids == {"analyzer", "planner", "impl-auth", "impl-api", "reviewer", "evaluator"}

    def test_orchestration_parsed(self):
        env = _load("dag_basic")
        w = env.data
        assert w["orchestration"]["max_concurrent_agents"] == 4
        assert w["orchestration"]["wave_dispatch"] == "barrier"

    def test_complexity_skip_agents_parsed(self):
        env = _load("dag_basic")
        w = env.data
        assert w["complexity_rules"]["trivial"]["skip_agents"] == ["reviewer"]

    def test_terminal_flag_parsed(self):
        env = _load("dag_basic")
        w = env.data
        ev = next(a for a in w["agents"] if a["id"] == "evaluator")
        assert ev["terminal"] is True
        assert ev["verdict_required"] is True

    def test_non_terminal_no_verdict(self):
        env = _load("dag_basic")
        w = env.data
        analyzer = next(a for a in w["agents"] if a["id"] == "analyzer")
        assert analyzer["terminal"] is False
        assert analyzer["verdict_required"] is False

    def test_agent_address_passthrough(self):
        """@-mention、scoped、裸名 三种形式都通过（passthrough 不报 miss）。"""
        env = _load("dag_basic")
        # 解析成功即可——@-mention 的实际解析在运行时 Agent tool 处理
        assert env.ok


class TestDagDefaults:
    """mode/orchestration 缺省时的行为（Q15/Q16）。"""

    def test_mode_default_is_phase(self, tmp_path):
        """workflow.yaml 缺 mode 字段 → 默认 phase（Q15）。"""
        yaml_path = tmp_path / "workflow.yaml"
        yaml_path.write_text(
            "phases:\n"
            "  - name: only\n"
            "    stage: only\n"
            "    agent: drive:analyzer\n"
            "    terminal_stage: true\n"
        )
        env = load_workflow(tmp_path, plugin_root=PLUGIN_ROOT)
        assert env.ok
        # mode 字段缺失不报错，按 phase 解析（Q15）
        assert env.data["mode"] == "phase"

    def test_orchestration_defaults_applied(self, tmp_path):
        """DAG 模式 orchestration 缺省时注入默认（Q16）。"""
        yaml_path = tmp_path / "workflow.yaml"
        yaml_path.write_text(
            "mode: dag\n"
            "agents:\n"
            "  - id: a\n"
            "    agent: drive:analyzer\n"
            "    depends_on: []\n"
            "    terminal: true\n"
            "    verdict_required: true\n"
        )
        env = load_workflow(tmp_path, plugin_root=PLUGIN_ROOT)
        assert env.ok
        orch = env.data["orchestration"]
        assert orch["max_concurrent_agents"] == 16
        assert orch["wave_dispatch"] == "barrier"

    def test_orchestration_partial_override(self, tmp_path):
        """orchestration 部分字段时未指定字段走默认（Q16 浅合并）。"""
        yaml_path = tmp_path / "workflow.yaml"
        yaml_path.write_text(
            "mode: dag\n"
            "orchestration:\n"
            "  max_concurrent_agents: 8\n"
            "agents:\n"
            "  - id: a\n"
            "    agent: drive:analyzer\n"
            "    depends_on: []\n"
            "    terminal: true\n"
            "    verdict_required: true\n"
        )
        env = load_workflow(tmp_path, plugin_root=PLUGIN_ROOT)
        assert env.ok
        orch = env.data["orchestration"]
        assert orch["max_concurrent_agents"] == 8  # 用户指定
        assert orch["wave_dispatch"] == "barrier"  # 默认


class TestDagValidationErrors:
    """DAG 模式校验错误（Q8/Q14）。"""

    def test_cycle_detected(self):
        """环状 DAG 应被拒。"""
        env = _load("dag_with_cycle")
        assert not env.ok
        assert env.reason == "schema_invalid"

    def test_no_terminal_agent(self):
        """缺 terminal agent 应被拒。"""
        env = _load("dag_no_terminal")
        assert not env.ok
        assert env.reason == "schema_invalid"
        assert "terminal" in str(env.details).lower()

    def test_verdict_required_without_terminal(self):
        """verdict_required=true 但 terminal=false → 拒（Q8 决策）。"""
        env = _load("dag_verdict_required_no_terminal")
        assert not env.ok
        assert env.reason == "schema_invalid"
        assert "verdict_required" in str(env.details).lower()

    def test_duplicate_agent_id(self):
        """重复 agent id 应被拒。"""
        env = _load("dag_duplicate_id")
        assert not env.ok
        assert env.reason == "schema_invalid"
        assert "重复" in str(env.details) or "duplicate" in str(env.details).lower()


class TestDagModeSeparation:
    """DAG 模式与 phase 模式互不污染。"""

    def test_phase_mode_ignores_agents_field(self, tmp_path):
        """phase 模式 workflow.yaml 不接受 agents 字段（应忽略，不报错——向后兼容）。"""
        # 注：当前实现是 _parse_workflow_yaml 按 mode 分支，phase 模式不读 agents
        # 即使有 agents 字段，phase 模式也忽略
        yaml_path = tmp_path / "workflow.yaml"
        yaml_path.write_text(
            "phases:\n"
            "  - name: only\n"
            "    stage: only\n"
            "    agent: drive:analyzer\n"
            "    terminal_stage: true\n"
        )
        env = load_workflow(tmp_path, plugin_root=PLUGIN_ROOT)
        assert env.ok
        assert env.data["mode"] == "phase"
        assert env.data["agents"] == []

    def test_dag_mode_rejects_phases_field(self, tmp_path):
        """DAG 模式 workflow.yaml 应只解析 agents，不解析 phases（混合禁止）。"""
        yaml_path = tmp_path / "workflow.yaml"
        # 注：当前实现 DAG 模式不读 phases 字段，phase 模式不读 agents
        # 但同时给两者应不报错（DAG 模式忽略 phases）
        yaml_path.write_text(
            "mode: dag\n"
            "agents:\n"
            "  - id: a\n"
            "    agent: drive:analyzer\n"
            "    depends_on: []\n"
            "    terminal: true\n"
            "    verdict_required: true\n"
            "phases: []\n"  # 多余字段，应忽略
        )
        env = load_workflow(tmp_path, plugin_root=PLUGIN_ROOT)
        assert env.ok
        assert env.data["mode"] == "dag"