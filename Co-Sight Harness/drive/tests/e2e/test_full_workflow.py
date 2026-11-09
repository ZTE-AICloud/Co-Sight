"""端到端：编排结构从声明读、state 由岗位脚本写、非法路径被拦。

不调 LLM。验证的是确定性骨架：声明怎么被解析、阶段怎么推进、留痕怎么落盘、
哪些操作会被拒。agent 的语义产出由 fixture 代写。
"""
from __future__ import annotations

import sys

import pytest
import yaml

from tests.e2e.conftest import (
    TOPO_SORT,
    advance,
    confirm,
    load_workflow,
    read_run_log,
    read_state,
    run_script,
    state_cli,
)

pytestmark = pytest.mark.e2e


# =============================================================================
# start：建骨架
# =============================================================================

class TestStart:
    def test_creates_planning_skeleton(self, started):
        planning = started / ".drive" / "plan-e2e"
        assert planning.is_dir()
        assert (planning / "inputs").is_dir()
        assert (planning / "artifacts").is_dir()

    def test_records_intent(self, started):
        text = (started / ".drive" / "plan-e2e" / "intent.md").read_text(encoding="utf-8")
        assert "hello world CLI" in text

    def test_state_starts_at_start_stage(self, started):
        assert read_state(started / ".drive" / "plan-e2e")["active_stage"] == "start"

    def test_refuses_second_init(self, started):
        from tests.e2e.conftest import INIT_PLANNING

        code, payload = run_script(
            INIT_PLANNING,
            "--work-dir", str(started),
            "--plan-dir", "plan-e2e",
        )
        assert code == 1
        assert payload["reason"] == "already_exists"


# =============================================================================
# 编排结构来自声明
# =============================================================================

class TestWorkflowDeclaration:
    def test_default_workflow_has_four_stages(self, workspace):
        """v2.2.1: start 已内化，默认只剩 4 个业务阶段"""
        data = load_workflow(workspace)
        assert data["source"] == "plugin-default"
        assert [p["stage"] for p in data["phases"]] == [
            "analyze", "plan", "execute", "evaluate"
        ]

    def test_user_workflow_yaml_takes_over(self, workspace):
        """用户配置覆盖默认配置，且不应包含 start"""
        # scoped 地址规则：项目本地 agent 走裸名，需在 .claude/agents/ 有对应 name:
        (workspace / ".claude" / "agents").mkdir(parents=True)
        (workspace / ".claude" / "agents" / "my-analyzer.md").write_text(
            "---\nname: my-analyzer\n---\n# test\n",
            encoding="utf-8",
        )
        (workspace / "workflow.yaml").write_text(
            "phases:\n"
            "  - name: analyze\n"
            "    stage: analyze\n"
            "    agent: my-analyzer\n"
            "  - name: plan\n"
            "    stage: plan\n"
            "  - name: execute\n"
            "    stage: execute\n"
            "  - name: evaluate\n"
            "    stage: evaluate\n",
            encoding="utf-8",
        )
        data = load_workflow(workspace)
        assert data["source"] == "user-defined"
        assert [p["stage"] for p in data["phases"]] == [
            "analyze", "plan", "execute", "evaluate"
        ]
        assert data["phases"][0]["agent"] == "my-analyzer"

    def test_gate_removal_is_how_you_disable_a_gate(self, workspace):
        """关掉一道卡 = 从 phase 删掉 gate 字段，不再有 gates.yaml。"""
        (workspace / "workflow.yaml").write_text(
            "phases:\n"
            "  - name: analyze\n"
            "    stage: analyze\n"
            "  - name: plan\n"
            "    stage: plan\n",
            encoding="utf-8",
        )
        data = load_workflow(workspace)
        assert all(p["gate"] is None for p in data["phases"])

    def test_default_gates_all_declare_enforcer(self, workspace):
        for phase in load_workflow(workspace)["phases"]:
            if phase["gate"] is not None:
                assert phase["gate"]["enforced_by"].startswith("hooks/")

    def test_broken_workflow_yaml_fails_closed(self, workspace):
        """结构有错必须开工前就拒，不能带着错配置跑。"""
        (workspace / "workflow.yaml").write_text(
            "phases:\n  - stage: start\n  - stage: execute\n", encoding="utf-8"
        )
        from tests.e2e.conftest import READ_WORKFLOW
        from tests.script_loader import PLUGIN_ROOT

        code, payload = run_script(
            READ_WORKFLOW, "--work-dir", str(workspace),
            "--plugin-root", str(PLUGIN_ROOT),
        )
        assert code == 1
        assert payload["reason"] == "schema_invalid"

    def test_complexity_rules_drive_scope(self, workspace):
        rules = load_workflow(workspace)["complexity_rules"]
        assert rules["trivial"]["skip_phases"] == ["plan"]
        assert rules["trivial"]["evaluate_levels"] == ["L0", "L1"]
        assert rules["standard"]["evaluate_levels"] == ["L0", "L1", "L2"]


# =============================================================================
# 阶段推进
# =============================================================================

class TestStageProgression:
    def test_full_forward_path(self, at_stage):
        _, planning = at_stage("evaluate")
        assert read_state(planning)["active_stage"] == "evaluate"

    def test_each_hop_is_audited(self, at_stage):
        _, planning = at_stage("evaluate")
        hops = [
            (e.get("from"), e.get("to"))
            for e in read_run_log(planning)
            if e["event"] == "stage_advanced"
        ]
        assert hops == [
            ("start", "analyze"), ("analyze", "plan"),
            ("plan", "execute"), ("execute", "evaluate"),
        ]

    def test_revision_grows_monotonically(self, at_stage):
        _, planning = at_stage("plan")
        assert read_state(planning)["revision"] >= 3

    def test_illegal_skip_is_rejected(self, started):
        planning = started / ".drive" / "plan-e2e"
        code, payload = state_cli(planning, "transition", "--to", "execute")
        assert code == 1
        assert payload["reason"] == "invalid_transition"

    def test_rejected_transition_leaves_state_untouched(self, started):
        planning = started / ".drive" / "plan-e2e"
        before = read_state(planning)
        state_cli(planning, "transition", "--to", "evaluate")
        after = read_state(planning)
        assert after["active_stage"] == before["active_stage"]
        assert after["revision"] == before["revision"]


# =============================================================================
# 回退：evaluate 不合格回 plan
# =============================================================================

class TestRollback:
    def test_evaluate_can_roll_back_to_plan(self, at_stage):
        _, planning = at_stage("evaluate")
        code, _ = advance(planning, "evaluate", "plan")
        assert code == 0
        assert read_state(planning)["active_stage"] == "plan"

    def test_execute_can_roll_back_to_plan(self, at_stage):
        _, planning = at_stage("execute")
        code, _ = advance(planning, "execute", "plan")
        assert code == 0

    def test_rollback_is_audited(self, at_stage):
        _, planning = at_stage("evaluate")
        advance(planning, "evaluate", "plan")
        last = [e for e in read_run_log(planning) if e["event"] == "stage_advanced"][-1]
        assert (last["from"], last["to"]) == ("evaluate", "plan")

    def test_replan_then_forward_again(self, at_stage):
        """回退后能重新往前走完整一轮 —— 回退不是死路。"""
        _, planning = at_stage("evaluate")
        advance(planning, "evaluate", "plan")
        current = "plan"
        for stage in ("execute", "evaluate"):
            # 回退重做后需重新确认 —— 上一轮的放行不复用
            confirm(planning, current, note="replan 后复核")
            code, payload = state_cli(planning, "transition", "--to", stage)
            assert code == 0, payload
            current = stage
        assert read_state(planning)["active_stage"] == "evaluate"


# =============================================================================
# plan 阶段：会计算波次
# =============================================================================

class TestWaveScheduling:
    TASKS = [
        {"task_id": "task-a", "depends_on": []},
        {"task_id": "task-b", "depends_on": []},
        {"task_id": "task-c", "depends_on": ["task-a"]},
        {"task_id": "task-d", "depends_on": ["task-b", "task-c"]},
    ]

    def test_toposort_computes_waves(self, at_stage, write_task_record):
        _, planning = at_stage("plan")
        write_task_record(planning, self.TASKS)

        code, payload = run_script(
            TOPO_SORT, "schedule-waves", "--planning-dir", str(planning)
        )
        assert code == 0, payload

        waves = yaml.safe_load((planning / "waves.yaml").read_text(encoding="utf-8"))
        assert [w["count"] for w in waves["waves"]] == [2, 1, 1]

    def test_independent_tasks_share_first_wave(self, at_stage, write_task_record):
        _, planning = at_stage("plan")
        write_task_record(planning, self.TASKS)
        run_script(TOPO_SORT, "schedule-waves", "--planning-dir", str(planning))

        waves = yaml.safe_load((planning / "waves.yaml").read_text(encoding="utf-8"))
        first = {t["task_id"] for t in waves["waves"][0]["tasks"]}
        assert first == {"task-a", "task-b"}
        assert waves["waves"][0]["parallel"] is True

    def test_upstream_artifacts_are_derived(self, at_stage, write_task_record):
        _, planning = at_stage("plan")
        write_task_record(planning, self.TASKS)
        run_script(TOPO_SORT, "schedule-waves", "--planning-dir", str(planning))

        waves = yaml.safe_load((planning / "waves.yaml").read_text(encoding="utf-8"))
        task_d = waves["waves"][2]["tasks"][0]
        assert task_d["task_id"] == "task-d"
        assert len(task_d["upstream_artifacts"]) == 2

    def test_dependency_cycle_is_rejected(self, at_stage, write_task_record):
        """有环不能放过去 —— 否则调度会死等。"""
        _, planning = at_stage("plan")
        write_task_record(planning, [
            {"task_id": "x", "depends_on": ["y"]},
            {"task_id": "y", "depends_on": ["x"]},
        ])
        code, payload = run_script(
            TOPO_SORT, "schedule-waves", "--planning-dir", str(planning)
        )
        assert code == 1, "环必须被拒"


# =============================================================================
# HITL gate
# =============================================================================

class TestHumanGate:
    def test_plan_gate_declares_human_review(self, workspace):
        plan = next(p for p in load_workflow(workspace)["phases"] if p["stage"] == "plan")
        assert plan["gate"]["type"] == "human_review"

    def test_plan_gate_skips_on_auto_mode(self, workspace):
        plan = next(p for p in load_workflow(workspace)["phases"] if p["stage"] == "plan")
        assert "auto_mode" in plan["gate"]["skip_when"]

    def test_plan_gate_skips_on_trivial(self, workspace):
        plan = next(p for p in load_workflow(workspace)["phases"] if p["stage"] == "plan")
        assert any("trivial" in cond for cond in plan["gate"]["skip_when"])

    def test_pending_review_is_recordable(self, at_stage):
        """gate 待确认状态落在 state 里，续接时能看见。"""
        _, planning = at_stage("plan")
        code, _ = state_cli(planning, "update", "--set", "pending_plan_review=true")
        assert code == 0
        assert read_state(planning)["pending_plan_review"] is True


# =============================================================================
# pause / resume
# =============================================================================

class TestPauseResume:
    def test_pause_records_checkpoint(self, at_stage):
        _, planning = at_stage("plan")
        checkpoint = '{"at":"2026-07-27","active_stage":"plan"}'
        code, _ = state_cli(
            planning, "update", "--set", "paused=true",
            "--set-json", f"pause_checkpoint={checkpoint}",
        )
        assert code == 0
        state = read_state(planning)
        assert state["paused"] is True
        assert state["pause_checkpoint"]["active_stage"] == "plan"

    def test_pause_does_not_move_stage(self, at_stage):
        _, planning = at_stage("plan")
        state_cli(planning, "update", "--set", "paused=true")
        assert read_state(planning)["active_stage"] == "plan"

    def test_resume_clears_flag_and_keeps_stage(self, at_stage):
        _, planning = at_stage("execute")
        state_cli(planning, "update", "--set", "paused=true")
        state_cli(planning, "update", "--set", "paused=false")
        state = read_state(planning)
        assert state["paused"] is False
        assert state["active_stage"] == "execute"


# =============================================================================
# 岗位边界
# =============================================================================

class TestRoleBoundaries:
    def test_init_planning_does_not_write_state(self, workspace):
        """建骨架的脚本不碰 state —— 那是 state-machine 的职责。"""
        from tests.e2e.conftest import INIT_PLANNING

        run_script(INIT_PLANNING, "--work-dir", str(workspace))
        assert not (workspace / ".drive" / "plan-e2e" / "executeState.json").exists()

    def test_read_workflow_does_not_write_anything(self, started):
        """读声明是只读操作。"""
        planning = started / ".drive" / "plan-e2e"
        before = read_state(planning)["revision"]
        load_workflow(started)
        assert read_state(planning)["revision"] == before

    def test_state_writes_go_through_one_file(self, at_stage):
        """并发写入时 revision 唯一 —— 单点加锁的可观测证据。"""
        import subprocess

        _, planning = at_stage("plan")
        from tests.e2e.conftest import STATE_CLI

        procs = [
            subprocess.Popen(
                [sys.executable, str(STATE_CLI), "update",
                 "--planning-dir", str(planning), "--set", f"current_wave={i}"],
                stdout=subprocess.PIPE, text=True,
            )
            for i in range(5)
        ]
        revisions = []
        for p in procs:
            out, _ = p.communicate()
            import json as _json
            revisions.append(_json.loads(out)["data"]["revision"])
        assert len(set(revisions)) == len(revisions), f"revision 冲突: {revisions}"
