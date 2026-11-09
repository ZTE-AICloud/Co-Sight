"""anchor.json 协议已删；worker 改为返回 summary + 留 resumption.log。"""
from __future__ import annotations

import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
WORKER_MD = PLUGIN_ROOT / "agents" / "executor.md"
# phase 3 之前这里指 skills/drive-execute/SKILL.md（orchestrator 的 execute-stage playbook）。
# 删 5 个 playbook 之后，orchestrator 的 execute 阶段约定合入 skills/drive/SKILL.md 主体。
ORCHESTRATOR_SKILL = PLUGIN_ROOT / "skills" / "drive" / "SKILL.md"
EVALUATOR_MD = PLUGIN_ROOT / "agents" / "evaluator.md"
HOOKS_PROTOCOL = PLUGIN_ROOT / "hooks" / "hooks_protocol.py"


class TestAnchorProtocolGone:
    def test_worker_does_not_instruct_writing_anchor(self):
        body = WORKER_MD.read_text(encoding="utf-8")
        # 唯一允许提 anchor 的地方是"禁止写 anchor"这条否定条款
        mentions = [ln for ln in body.splitlines() if "anchor" in ln]
        assert all("不写" in ln or "已废弃" in ln for ln in mentions), mentions

    def test_evaluator_reads_task_results_not_anchor(self):
        body = EVALUATOR_MD.read_text(encoding="utf-8")
        assert "anchor" not in body
        assert "task_results" in body

    def test_orchestrator_skill_has_no_anchor_protocol(self):
        """5 个 playbook 删除后, orchestrator SKILL.md 不应再提 anchor 协议。"""
        body = ORCHESTRATOR_SKILL.read_text(encoding="utf-8")
        mentions = [ln for ln in body.splitlines() if "anchor" in ln]
        assert all("不写" in ln or "已废弃" in ln for ln in mentions), mentions


class TestSummaryReturnContract:
    def test_worker_declares_summary_schema(self):
        body = WORKER_MD.read_text(encoding="utf-8")
        for field in ("task_id", "status", "duration_sec", "files_changed",
                      "fail_notes", "acceptance_criteria_met"):
            assert field in body, f"summary schema 缺字段: {field}"

    def test_worker_says_no_return_blocks_wave(self):
        body = WORKER_MD.read_text(encoding="utf-8")
        assert "不返回=wave 卡住" in body or "不返回" in body

    def test_all_four_statuses_documented(self):
        body = WORKER_MD.read_text(encoding="utf-8")
        for status in ("completed", "skipped", "partial", "failed"):
            assert status in body

    def test_orchestrator_requires_summary_from_worker(self):
        """orchestrator 应记录 worker 通过 summary JSON 回报, 并以 wave barrier 检查。

        phase 3 后写契约在 worker.body 里, 但 orchestrator 必须 own this
        coordination point: 它要么明文写 "summary"+"wave barrier",
        要么明文写 "aggregate.py" 强制 barrier 强约束 (由 worker 跑)。
        """
        body = ORCHESTRATOR_SKILL.read_text(encoding="utf-8")
        # barrier 协调机制必须显式提到 (aggregate.py 或 summary JSON 或 wave barrier 任一)
        assert (
            "summary JSON" in body
            or "aggregate.py" in body
        ), "orchestrator 必须明确写出 worker 回报/记账机制"
        assert "wave barrier" in body


class TestResumptionLog:
    def test_worker_documents_resumption_log(self):
        body = WORKER_MD.read_text(encoding="utf-8")
        assert "resumption.log" in body
        assert "append" in body.lower()

    def test_resumption_log_is_jsonl_append_only(self):
        body = WORKER_MD.read_text(encoding="utf-8")
        assert "append-only" in body
        # 覆写重定向会毁掉历史留痕：只允许 >>，不允许单 >
        assert not re.search(r'(?<!>)>\s*"?\$LOG', body)
        assert ">>" in body

    def test_log_path_under_task_artifacts(self):
        body = WORKER_MD.read_text(encoding="utf-8")
        assert ".drive/<plan_dir>/artifacts/" in body

    def test_whitelist_allows_artifacts_writes(self):
        """resumption.log / SUMMARY.md 落 artifacts/ 下，hook 必须放行。"""
        src = HOOKS_PROTOCOL.read_text(encoding="utf-8")
        assert r'r"^artifacts/.+"' in src


class TestWorkerJobBoundary:
    def test_worker_does_not_write_state(self):
        body = WORKER_MD.read_text(encoding="utf-8")
        assert "不改 taskRecord.yaml / waves.yaml / executeState.json" in body

    def test_worker_does_not_spawn(self):
        assert "不 spawn subagent" in WORKER_MD.read_text(encoding="utf-8")

    def test_orchestrator_documents_worker_self_bookkeeping(self):
        """execute 阶段 wave barrier 由 worker 调 aggregate.py 自记账,
        orchestrator SKILL.md 应记录这一机制。"""
        body = ORCHESTRATOR_SKILL.read_text(encoding="utf-8")
        assert "executor" in body
        # wave barrier 强制 mechanism 与 aggregate.py 都在
        assert "wave barrier" in body
        assert "aggregate.py" in body
