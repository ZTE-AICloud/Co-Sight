"""workflow.yaml 解析与 fail-closed 校验（v2.2.1+ 新设计）。

PROP-20260805-002 §4.2 校验规则：
  1. stage 名称不重复
  2. gate.enforced_by 指向的 hook 必须存在
  3. allowed_back_jumps 引用的 stage 都在 phases 中
  4. 回跳目标必须在当前 stage 之前
  5. 有且仅有一个 terminal_stage: true，且在 phases 末尾
  6. 不能包含 stage: start（由 drive 内部调用 startup skill）

start 阶段已从工作流中移除（drive 内部自动调用）。
STAGES 白名单、VALID_TRANSITIONS 硬编码、STANDARD_ORDER 顺序校验都已删除。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = PLUGIN_ROOT / "skills" / "drive" / "scripts" / "read_workflow.py"

sys.path.insert(0, str(SCRIPT.parent))
import read_workflow as rw  # noqa: E402


def write_wf(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "workflow.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def load(tmp_path: Path):
    return rw.load_workflow(tmp_path, PLUGIN_ROOT)


# =============================================================================
# 默认 workflow（插件内置的 workflow.yaml）
# =============================================================================

class TestDefault:
    """插件内置 4 阶段 workflow（start 已内化到 drive 内部）"""

    def test_default_workflow_has_four_stages(self, tmp_path):
        """v2.2.1: start 已内化，默认只剩 4 个业务阶段"""
        env = load(tmp_path)
        assert env.ok
        assert env.data["source"] == "plugin-default"
        assert [p["stage"] for p in env.data["phases"]] == [
            "analyze", "plan", "execute", "evaluate"
        ]
        assert env.data["workflow_file"].endswith("skills/drive/scripts/workflow.yaml")

    def test_default_plan_gate_has_enforcer(self, tmp_path):
        env = load(tmp_path)
        plan = next(p for p in env.data["phases"] if p["stage"] == "plan")
        assert plan["gate"]["type"] == "human_review"
        assert plan["gate"]["enforced_by"].startswith("hooks/")

    def test_every_default_gate_with_type_has_enforcer(self, tmp_path):
        env = load(tmp_path)
        for phase in env.data["phases"]:
            gate = phase["gate"]
            if gate is not None:
                assert gate["enforced_by"], f"{phase['stage']} gate 缺 enforced_by"

    def test_default_complexity_rules_present(self, tmp_path):
        env = load(tmp_path)
        rules = env.data["complexity_rules"]
        assert rules["trivial"]["skip_phases"] == ["plan"]
        assert rules["trivial"]["evaluate_levels"] == ["L0", "L1"]


# =============================================================================
# 校验规则 1：stage 名称不重复
# =============================================================================

class TestDuplicateStages:
    def test_duplicate_stage_rejected(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: analyze
  - name: b
    stage: analyze
""")
        env = load(tmp_path)
        assert not env.ok
        assert env.reason == "schema_invalid"
        assert "重复" in env.details["message"]

    def test_unique_stages_pass(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
  - name: b
    stage: step-b
""")
        env = load(tmp_path)
        assert env.ok


# =============================================================================
# 校验规则 2：gate.enforced_by 指向的 hook 必须存在
# =============================================================================

class TestGateEnforcedBy:
    def test_gate_without_enforced_by_rejected(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
    gate:
      type: input_check
""")
        env = load(tmp_path)
        assert not env.ok
        assert env.reason == "schema_invalid"
        assert "enforced_by" in env.details["message"]

    def test_gate_with_nonexistent_hook_rejected(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
    gate:
      type: input_check
      enforced_by: hooks/does_not_exist.py
""")
        env = load(tmp_path)
        assert not env.ok
        assert "不存在" in env.details["message"]

    def test_gate_with_project_local_hook_resolved(self, tmp_path):
        """enforced_by 指向项目本地 .claude/hooks/xxx.mjs，read_workflow 应允许。"""
        (tmp_path / ".claude" / "hooks").mkdir(parents=True)
        (tmp_path / ".claude" / "hooks" / "phase3-subagent-gate.mjs").write_text(
            "// hook", encoding="utf-8"
        )
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
    gate:
      type: input_check
      enforced_by: phase3-subagent-gate.mjs
""")
        env = load(tmp_path)
        assert env.ok, env.details

    def test_gate_with_cosight_style_project_hook_resolved(self, tmp_path):
        """enforced_by 指向 .cosight/hooks/ 下的项目 hook。"""
        (tmp_path / ".cosight" / "hooks").mkdir(parents=True)
        (tmp_path / ".cosight" / "hooks" / "phase3-subagent-gate.mjs").write_text(
            "// hook", encoding="utf-8"
        )
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
    gate:
      type: input_check
      enforced_by: phase3-subagent-gate.mjs
""")
        env = load(tmp_path)
        assert env.ok, env.details

    def test_gate_with_relative_path_under_workdir_resolved(self, tmp_path):
        """enforced_by 指向 work_dir 根目录下的相对路径（含 .claude/hooks/xxx）。"""
        (tmp_path / ".claude" / "hooks").mkdir(parents=True)
        (tmp_path / ".claude" / "hooks" / "subagent-gate.mjs").write_text(
            "// hook", encoding="utf-8"
        )
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
    gate:
      type: input_check
      enforced_by: .claude/hooks/subagent-gate.mjs
""")
        env = load(tmp_path)
        assert env.ok, env.details

    def test_unknown_gate_type_rejected(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
    gate:
      type: telepathy_check
      enforced_by: hooks/planning_write_guard.py
""")
        env = load(tmp_path)
        assert not env.ok
        assert "type" in env.details["message"]

    def test_gate_missing_type_rejected(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
    gate:
      enforced_by: hooks/planning_write_guard.py
""")
        env = load(tmp_path)
        assert not env.ok

    def test_valid_gate_parses_skip_when_and_on_revise(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
  - name: b
    stage: step-b
    gate:
      type: human_review
      skip_when: [auto_mode, "complexity == trivial"]
      enforced_by: hooks/state_transition_guard.py
      on_revise: replan
""")
        env = load(tmp_path)
        assert env.ok
        gate = next(p for p in env.data["phases"] if p["stage"] == "step-b")["gate"]
        assert gate["skip_when"] == ["auto_mode", "complexity == trivial"]
        assert gate["on_revise"] == "replan"

    def test_gate_is_optional(self, tmp_path):
        """用户不写 gate 字段 = 该阶段自动流转，无需人工确认"""
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
""")
        env = load(tmp_path)
        assert env.ok
        assert all(p["gate"] is None for p in env.data["phases"])


# =============================================================================
# 校验规则 3 & 4：allowed_back_jumps 合法 + 回跳目标必须在当前 stage 之前
# =============================================================================

class TestBackJumps:
    def test_back_jump_to_undefined_stage_rejected(self, tmp_path):
        """回跳目标必须存在于 phases 中"""
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
  - name: b
    stage: step-b

allowed_back_jumps:
  step-b: [step-c]
""")
        env = load(tmp_path)
        assert not env.ok
        assert env.reason == "schema_invalid"

    def test_back_jump_to_source_not_defined_rejected(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a

allowed_back_jumps:
  step-x: [step-a]
""")
        env = load(tmp_path)
        assert not env.ok
        assert env.reason == "schema_invalid"

    def test_forward_jump_rejected(self, tmp_path):
        """回跳目标必须是更早的 stage，不能往前跳"""
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
  - name: b
    stage: step-b
  - name: c
    stage: step-c

allowed_back_jumps:
  step-b: [step-c]
""")
        env = load(tmp_path)
        assert not env.ok
        assert env.reason == "schema_invalid"
        assert "不在当前 stage 之前" in env.details["message"]

    def test_self_jump_rejected(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a

allowed_back_jumps:
  step-a: [step-a]
""")
        env = load(tmp_path)
        assert not env.ok

    def test_valid_back_jump_accepted(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
  - name: b
    stage: step-b
  - name: c
    stage: step-c

allowed_back_jumps:
  step-c: [step-a]
""")
        env = load(tmp_path)
        assert env.ok
        assert env.data["allowed_back_jumps"]["step-c"] == ["step-a"]

    def test_allowed_back_jumps_format(self, tmp_path):
        """allowed_back_jumps 必须是 mapping，values 是列表"""
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a

allowed_back_jumps:
  step-a: not_a_list
""")
        env = load(tmp_path)
        assert not env.ok


# =============================================================================
# 校验规则 5：terminal_stage 唯一且在末尾
# =============================================================================

class TestTerminalStage:
    def test_no_terminal_stage_is_legal(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
""")
        env = load(tmp_path)
        assert env.ok

    def test_single_terminal_stage_accepted(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
  - name: b
    stage: step-b
    terminal_stage: true
""")
        env = load(tmp_path)
        assert env.ok

    def test_terminal_in_middle_rejected(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
    terminal_stage: true
  - name: b
    stage: step-b
""")
        env = load(tmp_path)
        assert not env.ok

    def test_two_terminals_rejected(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
    terminal_stage: true
  - name: b
    stage: step-b
    terminal_stage: true
""")
        env = load(tmp_path)
        assert not env.ok


# =============================================================================
# 校验规则 6：不能包含 stage: start（已内化到 drive 内部）
# =============================================================================

class TestStartStageRejected:
    def test_start_stage_in_phases_rejected(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: s
    stage: start
  - name: a
    stage: analyze
""")
        env = load(tmp_path)
        assert not env.ok
        assert env.reason == "schema_invalid"
        assert "start" in env.details["message"].lower()

    def test_start_stage_only_rejected(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: s
    stage: start
""")
        env = load(tmp_path)
        assert not env.ok

    def test_stage_name_start_but_not_stage_field_rejected(self, tmp_path):
        """即使 name='start'，只要 stage 字段是别的名字就 OK"""
        write_wf(tmp_path, """
phases:
  - name: start
    stage: my-custom-step
""")
        env = load(tmp_path)
        assert env.ok


# =============================================================================
# stage 完全自由
# =============================================================================

class TestFreeStageNames:
    def test_custom_stage_names_accepted(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: collect
    stage: code-review
  - name: fix
    stage: fix-issues
  - name: verify
    stage: verify-fixes
    terminal_stage: true
""")
        env = load(tmp_path)
        assert env.ok

    def test_single_phase_workflow(self, tmp_path):
        """FDE 反馈场景：只用 planner"""
        write_wf(tmp_path, """
phases:
  - name: plan
    stage: plan
    terminal_stage: true
""")
        env = load(tmp_path)
        assert env.ok


# =============================================================================
# mode 校验（execute 阶段特有）
# =============================================================================

class TestExecMode:
    def test_valid_modes(self, tmp_path):
        for mode in ("code", "analysis"):
            write_wf(tmp_path, f"""
phases:
  - name: x
    stage: step-x
    mode: {mode}
""")
            env = load(tmp_path)
            assert env.ok, f"mode={mode} should pass"

    def test_invalid_mode_rejected(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: x
    stage: step-x
    mode: turbo
""")
        env = load(tmp_path)
        assert not env.ok

    def test_mode_and_wave_barrier_parse(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: x
    stage: step-x
    mode: analysis
    wave_barrier: true
""")
        env = load(tmp_path)
        assert env.ok
        phase = env.data["phases"][0]
        assert phase["mode"] == "analysis"
        assert phase["wave_barrier"] is True


# =============================================================================
# complexity_rules 校验
# =============================================================================

class TestComplexityRules:
    def test_valid_complexity_rules(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a

complexity_rules:
  trivial:
    skip_phases: [step-a]
    evaluate_levels: [L0, L1]
""")
        env = load(tmp_path)
        assert env.ok

    def test_max_tasks_rejected_as_agent_concern(self, tmp_path):
        """max_tasks 属 planner 履职细节，不属编排声明"""
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
complexity_rules:
  trivial:
    max_tasks: 3
""")
        env = load(tmp_path)
        assert not env.ok
        assert "max_tasks" in env.details["message"]

    def test_unknown_tier_rejected(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
complexity_rules:
  gigantic:
    skip_phases: []
""")
        env = load(tmp_path)
        assert not env.ok

    def test_invalid_evaluate_level_rejected(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
complexity_rules:
  trivial:
    evaluate_levels: [L0, L9]
""")
        env = load(tmp_path)
        assert not env.ok
        assert "L9" in env.details["message"]

    def test_skip_phases_to_undefined_stage_rejected(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
complexity_rules:
  trivial:
    skip_phases: [step-b]
""")
        env = load(tmp_path)
        assert not env.ok


# =============================================================================
# 基础校验
# =============================================================================

class TestBasics:
    def test_phases_must_be_list(self, tmp_path):
        write_wf(tmp_path, """
phases:
  start: yes
""")
        env = load(tmp_path)
        assert not env.ok

    def test_phases_must_be_nonempty(self, tmp_path):
        write_wf(tmp_path, "phases: []\n")
        env = load(tmp_path)
        assert not env.ok

    def test_phase_missing_stage_rejected(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: mystery
""")
        env = load(tmp_path)
        assert not env.ok
        assert "缺少 stage" in env.details["message"]

    def test_phase_missing_name_rejected(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - stage: step-a
""")
        env = load(tmp_path)
        assert not env.ok

    def test_yaml_decode_error(self, tmp_path):
        write_wf(tmp_path, "phases:\n  - stage: step-a\n   bad: indent\n")
        env = load(tmp_path)
        assert not env.ok
        assert env.reason == "json_decode_error"

    def test_empty_file_rejected(self, tmp_path):
        write_wf(tmp_path, "")
        env = load(tmp_path)
        assert not env.ok

    def test_non_mapping_top_level_rejected(self, tmp_path):
        write_wf(tmp_path, "- stage: step-a\n")
        env = load(tmp_path)
        assert not env.ok

    def test_workflow_yml_extension_supported(self, tmp_path):
        (tmp_path / "workflow.yml").write_text(
            """
phases:
  - name: a
    stage: step-a
""",
            encoding="utf-8",
        )
        env = load(tmp_path)
        assert env.ok
        assert env.data["source"] == "user-defined"

    def test_user_yaml_overrides_builtin(self, tmp_path):
        """项目根的 workflow.yaml 完全覆盖插件默认配置"""
        write_wf(tmp_path, """
phases:
  - name: only-planner
    stage: plan
    terminal_stage: true
""")
        env = load(tmp_path)
        assert env.ok
        assert env.data["source"] == "user-defined"
        assert [p["stage"] for p in env.data["phases"]] == ["plan"]

    def test_missing_work_dir_rejected(self, tmp_path):
        env = rw.load_workflow(tmp_path / "nope", PLUGIN_ROOT)
        assert not env.ok
        assert env.reason == "invalid_arg"


# =============================================================================
# schema 与 hook 强制器的一致性
# =============================================================================

def test_all_referenced_hooks_exist_in_repo():
    """插件内置 workflow.yaml 里声明的 enforced_by 必须都是仓库里真实存在的 hook。"""
    env = rw.load_workflow(PLUGIN_ROOT / "skills" / "drive", PLUGIN_ROOT)
    assert env.ok, env.details
    for phase in env.data["phases"]:
        gate = phase.get("gate")
        if gate is None:
            continue
        hook = PLUGIN_ROOT / gate["enforced_by"]
        assert hook.is_file(), f"{phase['stage']} gate 指向不存在的 hook: {hook}"


# =============================================================================
# CLI 契约
# =============================================================================

class TestCLI:
    def _run(self, tmp_path: Path, *args: str):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--work-dir", str(tmp_path),
             "--plugin-root", str(PLUGIN_ROOT), *args],
            capture_output=True, text=True,
        )
        return proc.returncode, json.loads(proc.stdout) if proc.stdout.strip() else {}

    def test_cli_exits_zero_on_valid(self, tmp_path):
        code, payload = self._run(tmp_path)
        assert code == 0
        assert payload.get("ok") is True

    def test_cli_exits_one_on_invalid(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
    mode: turbo
""")
        code, payload = self._run(tmp_path)
        assert code == 1
        assert payload.get("ok") is False

    def test_validate_flag_passes(self, tmp_path):
        code, payload = self._run(tmp_path, "--validate")
        assert code == 0
        assert payload.get("ok") is True

# =============================================================================
# Scoped agent 地址校验
# =============================================================================

class TestScopedAgent:
    """phases[].agent 字段：drive:<name> / 裸名 / 内置类型三种合法写法。"""

    def test_drive_prefix_resolves_to_plugin_agent(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: analyze
    agent: drive:analyzer
""")
        env = load(tmp_path)
        assert env.ok, env.details

    def test_bare_name_resolves_to_project_agent(self, tmp_path):
        (tmp_path / ".claude" / "agents").mkdir(parents=True)
        (tmp_path / ".claude" / "agents" / "my-analyzer.md").write_text(
            "---\nname: my-analyzer\n---\n# test\n", encoding="utf-8"
        )
        write_wf(tmp_path, """
phases:
  - name: a
    stage: analyze
    agent: my-analyzer
""")
        env = load(tmp_path)
        assert env.ok, env.details

    def test_builtin_agent_type_passes_whitelist(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: analyze
    agent: general-purpose
""")
        env = load(tmp_path)
        assert env.ok, env.details

    def test_drive_prefix_with_unknown_name_rejected(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: analyze
    agent: drive:does-not-exist
""")
        env = load(tmp_path)
        assert not env.ok
        assert env.reason == "schema_invalid"
        assert "does-not-exist" in env.details.get("message", "")

    def test_bare_name_not_in_project_rejected(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: analyze
    agent: ghost-agent
""")
        env = load(tmp_path)
        assert not env.ok
        assert env.reason == "schema_invalid"
        assert "ghost-agent" in env.details.get("message", "")

    def test_project_agent_name_takes_priority_over_drive(self, tmp_path):
        """项目本地同名 agent 应当能通过校验（不需 drive: 前缀）"""
        (tmp_path / ".claude" / "agents").mkdir(parents=True)
        (tmp_path / ".claude" / "agents" / "analyzer.md").write_text(
            "---\nname: analyzer\n---\n# project override\n", encoding="utf-8"
        )
        write_wf(tmp_path, """
phases:
  - name: a
    stage: analyze
    agent: analyzer
""")
        env = load(tmp_path)
        assert env.ok, env.details


# =============================================================================
# expected_state：阶段声明其 agent 会上报哪些状态字段
# =============================================================================

class TestExpectedState:
    def test_absent_yields_empty(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
""")
        env = load(tmp_path)
        assert env.ok, env.details
        assert env.data["phases"][0]["expected_state"] == {}

    def test_declared_fields_survive_parsing(self, tmp_path):
        """声明必须真的到得了编排层 —— 被解析器吞掉的字段等于没声明。"""
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
    expected_state:
      required: [status, output_path]
      optional: [current_stage]
""")
        env = load(tmp_path)
        assert env.ok, env.details
        declared = env.data["phases"][0]["expected_state"]
        assert declared["required"] == ["status", "output_path"]
        assert declared["optional"] == ["current_stage"]

    def test_only_required_is_legal(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
    expected_state:
      required: [status]
""")
        env = load(tmp_path)
        assert env.ok, env.details
        declared = env.data["phases"][0]["expected_state"]
        assert declared["required"] == ["status"]
        assert declared["optional"] == []

    def test_non_mapping_rejected(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
    expected_state: status
""")
        env = load(tmp_path)
        assert not env.ok
        assert env.reason == "schema_invalid"

    def test_non_list_required_rejected(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
    expected_state:
      required: status
""")
        env = load(tmp_path)
        assert not env.ok
        assert env.reason == "schema_invalid"

    def test_unknown_key_rejected(self, tmp_path):
        """写错 key（如 requried）不能静默忽略，否则声明形同虚设。"""
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
    expected_state:
      requried: [status]
""")
        env = load(tmp_path)
        assert not env.ok
        assert env.reason == "schema_invalid"

    def test_non_string_field_name_rejected(self, tmp_path):
        write_wf(tmp_path, """
phases:
  - name: a
    stage: step-a
    expected_state:
      required: [123]
""")
        env = load(tmp_path)
        assert not env.ok
        assert env.reason == "schema_invalid"
