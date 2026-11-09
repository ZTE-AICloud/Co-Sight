"""gaps_detector 测试 —— Phase 2。

每个 gap 类型至少 1 个测试；额外测排序 + summary。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gaps_detector import (
    Gap,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    detect_gaps,
    summarize,
)
from record_reader import read_record


def _make_plan(plan_dir: Path, *, execute_state: dict | None = None,
               run_log_lines: list[str] | None = None,
               include_topo: bool = True,
               include_evaluation: bool = True,
               artifacts: dict[str, str] | None = None) -> None:
    """手工填充 plan_dir 核心文件（用于 gap detector 单测）。

    默认写入全部 9 个 CORE_FILES（包括 topo-state.json 与
    evaluation/verification-report.md）。executeState.json / run-log.jsonl 始终
    创建（即便无内容），便于"unlink 1 个文件触发单个 missing gap"的测试。
    """
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "run-meta.json").write_text(
        json.dumps({
            "schema_version": "drive.runtime.run_meta.v1",
            "plan_name": "t", "plan_dir": plan_dir.name,
            "git_head": "x", "git_branch": "main",
            "workflow_hash": "sha256:x",
            "started_at": "2026-08-18T09:30:00Z",
            "worktree": "/tmp",
        }),
        encoding="utf-8",
    )
    (plan_dir / "intent.md").write_text("# intent\n", encoding="utf-8")
    (plan_dir / "manifest.md").write_text("# manifest\n", encoding="utf-8")
    (plan_dir / "taskRecord.yaml").write_text(
        "plan_id: t\ntasks: []\n", encoding="utf-8"
    )
    (plan_dir / "waves.yaml").write_text(
        "plan_id: t\nwaves: []\n", encoding="utf-8"
    )
    if include_topo:
        (plan_dir / "topo-state.json").write_text(
            json.dumps({"plan_id": "t", "waves": []}), encoding="utf-8"
        )
    (plan_dir / "executeState.json").write_text(
        json.dumps(execute_state) if execute_state is not None else "{}",
        encoding="utf-8",
    )
    (plan_dir / "run-log.jsonl").write_text(
        ("\n".join(run_log_lines) + "\n") if run_log_lines else "",
        encoding="utf-8",
    )
    if include_evaluation:
        (plan_dir / "evaluation").mkdir(exist_ok=True)
        (plan_dir / "evaluation" / "verification-report.md").write_text(
            "# Verification\n## Verdict: pass\n", encoding="utf-8"
        )
    if artifacts:
        for tid, summary in artifacts.items():
            d = plan_dir / "artifacts" / tid
            d.mkdir(parents=True, exist_ok=True)
            (d / "SUMMARY.md").write_text(summary, encoding="utf-8")


class TestMissingFiles:
    def test_detects_missing_files_with_split_severity(self, missing_record_dir: Path):
        """空目录：6 个 Runtime SDK 文件全缺（HIGH）+ 3 个 LLM 契约文件全缺（LOW）。"""
        record = read_record(missing_record_dir)
        gaps = detect_gaps(record)
        missing_file_gaps = [g for g in gaps if g.type == "missing_file"]
        # 6 Runtime + 3 LLM = 9
        assert len(missing_file_gaps) == 9
        sevs = {g.severity for g in missing_file_gaps}
        assert SEVERITY_HIGH in sevs
        assert SEVERITY_LOW in sevs
        # Runtime SDK 缺失必须全部 HIGH
        runtime_high = [
            g for g in missing_file_gaps
            if g.severity == SEVERITY_HIGH
            and any(rt in g.location for rt in (
                "run-meta.json", "intent.md", "executeState.json",
                "run-log.jsonl", "waves.yaml", "topo-state.json",
            ))
        ]
        assert len(runtime_high) == 6
        # LLM 契约缺失必须全部 LOW
        llm_low = [
            g for g in missing_file_gaps
            if g.severity == SEVERITY_LOW
            and any(rt in g.location for rt in (
                "manifest.md", "taskRecord.yaml", "verification-report.md",
            ))
        ]
        assert len(llm_low) == 3

    def test_runtime_only_missing_is_high(self, tmp_path: Path):
        """缺 1 个 Runtime SDK 文件 → HIGH。"""
        p = tmp_path / "p"
        _make_plan(p)
        (p / "run-log.jsonl").unlink()
        record = read_record(p)
        gaps = detect_gaps(record)
        missing = [g for g in gaps if g.type == "missing_file"]
        assert len(missing) == 1
        assert missing[0].severity == SEVERITY_HIGH
        assert "run-log.jsonl" in missing[0].location

    def test_llm_only_missing_is_low(self, tmp_path: Path):
        """缺 1 个 LLM 契约文件 → LOW。"""
        p = tmp_path / "p"
        _make_plan(p)
        (p / "manifest.md").unlink()
        record = read_record(p)
        gaps = detect_gaps(record)
        missing = [g for g in gaps if g.type == "missing_file"]
        assert len(missing) == 1
        assert missing[0].severity == SEVERITY_LOW
        assert "manifest.md" in missing[0].location


class TestMissingEvents:
    def test_detects_missing_drive_startup(self, tmp_path: Path):
        p = tmp_path / "p"
        _make_plan(p, run_log_lines=[
            '{"ts": "2026-08-18T09:30:00+00:00", "event": "stage_advanced", "from": "start", "to": "analyze"}',
        ])
        record = read_record(p)
        gaps = detect_gaps(record)
        missing = [g for g in gaps if g.type == "missing_event"]
        assert any("drive_startup" in g.description for g in missing)

    def test_detects_fewer_stage_advanced(self, tmp_path: Path):
        p = tmp_path / "p"
        _make_plan(p, run_log_lines=[
            '{"ts": "2026-08-18T09:30:00+00:00", "event": "drive_startup"}',
            '{"ts": "2026-08-18T09:30:05+00:00", "event": "stage_advanced", "from": "start", "to": "analyze"}',
        ])
        record = read_record(p)
        gaps = detect_gaps(record)
        sa = [g for g in gaps if g.type == "missing_event" and "stage_advanced 次数" in g.description]
        assert len(sa) >= 1


class TestMissingSummary:
    def test_detects_missing_summary(self, tmp_path: Path):
        p = tmp_path / "p"
        _make_plan(p, execute_state={
            "schema_version": "drive.runtime.state.v1",
            "revision": 1,
            "active_stage": "execute",
            "task_results": {"t1": {"status": "completed"}},
        }, artifacts={})
        record = read_record(p)
        gaps = detect_gaps(record)
        ms = [g for g in gaps if g.type == "missing_summary"]
        assert len(ms) == 1
        assert ms[0].severity == SEVERITY_MEDIUM


class TestRevisionGap:
    def test_detects_revision_gap(self, tmp_path: Path):
        p = tmp_path / "p"
        _make_plan(p, execute_state={
            "schema_version": "drive.runtime.state.v1",
            "revision": 3,
            "active_stage": "execute",
        }, run_log_lines=[
            '{"ts": "2026-08-18T09:30:00+00:00", "event": "agent_spawned", '
            '"subagent_type": "executor", "state_revision_at_spawn": 5}',
        ])
        record = read_record(p)
        gaps = detect_gaps(record)
        rg = [g for g in gaps if g.type == "revision_gap"]
        assert len(rg) == 1
        assert rg[0].severity == SEVERITY_CRITICAL


class TestTimestampAnomaly:
    def test_detects_out_of_order(self, tmp_path: Path):
        p = tmp_path / "p"
        _make_plan(p, run_log_lines=[
            '{"ts": "2026-08-18T10:00:00+00:00", "event": "stage_advanced", "from": "start", "to": "analyze"}',
            '{"ts": "2026-08-18T09:00:00+00:00", "event": "stage_advanced", "from": "analyze", "to": "plan"}',
        ])
        record = read_record(p)
        gaps = detect_gaps(record)
        ts_g = [g for g in gaps if g.type == "timestamp_anomaly"]
        assert len(ts_g) == 1
        assert ts_g[0].severity == SEVERITY_MEDIUM


class TestPendingConfirmationStuck:
    def test_detects_stuck_when_old(self, tmp_path: Path):
        p = tmp_path / "p"
        _make_plan(p, execute_state={
            "schema_version": "drive.runtime.state.v1",
            "revision": 1,
            "active_stage": "plan",
            "pending_confirmation": "plan-review-gate",
            "updated_at": "2020-01-01T00:00:00+00:00",
        })
        record = read_record(p)
        gaps = detect_gaps(record)
        st = [g for g in gaps if g.type == "pending_confirmation_stuck"]
        assert len(st) == 1
        assert st[0].severity == SEVERITY_HIGH


class TestUnknownStateFields:
    def test_detects_unknown_field(self, tmp_path: Path):
        p = tmp_path / "p"
        _make_plan(p, execute_state={
            "schema_version": "drive.runtime.state.v1",
            "revision": 1,
            "active_stage": "execute",
            "weird_new_field": "???",
        })
        record = read_record(p)
        gaps = detect_gaps(record)
        uf = [g for g in gaps if g.type == "unmapped_state_field"]
        assert len(uf) == 1
        assert uf[0].severity == SEVERITY_LOW


class TestDetectGapsAggregate:
    def test_phase_completed_real_sample_no_critical(self, phase_completed_plan: Path):
        record = read_record(phase_completed_plan)
        gaps = detect_gaps(record)
        # workdir-demo 是手工填的；缺 topo-state.json 会出 missing_file HIGH，
        # 但不应有 CRITICAL revision gap（executeState.revision=12 ≥ run-log 的 6）
        critical = [g for g in gaps if g.severity == SEVERITY_CRITICAL]
        assert critical == []

    def test_gaps_sorted_by_severity(self, tmp_path: Path):
        p = tmp_path / "p"
        _make_plan(p,
            execute_state={
                "schema_version": "drive.runtime.state.v1",
                "revision": 3,
                "active_stage": "completed",
                "verdict": "pass",
                "task_results": {"t1": {"status": "completed"}},
                "weird_field": "x",
            },
            run_log_lines=[
                '{"ts": "2026-08-18T09:30:00+00:00", "event": "agent_spawned", '
                '"subagent_type": "e", "state_revision_at_spawn": 5}',
                '{"ts": "2026-08-18T10:00:00+00:00", "event": "stage_advanced", "from": "x", "to": "y"}',
                '{"ts": "2026-08-18T09:00:00+00:00", "event": "stage_advanced", "from": "y", "to": "z"}',
            ],
        )
        record = read_record(p)
        gaps = detect_gaps(record)
        sevs = [g.severity for g in gaps]
        order_map = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        indices = [order_map[s] for s in sevs]
        assert indices == sorted(indices)


class TestSummarize:
    def test_summarize_counts(self):
        gaps = (
            Gap("a", SEVERITY_CRITICAL, "x", "d", "f"),
            Gap("b", SEVERITY_HIGH, "x", "d", "f"),
            Gap("c", SEVERITY_HIGH, "x", "d", "f"),
            Gap("d", SEVERITY_LOW, "x", "d", "f"),
        )
        s = summarize(gaps)
        assert s == {
            "total": 4,
            "critical": 1,
            "high": 2,
            "medium": 0,
            "low": 1,
        }

    def test_summarize_empty(self):
        s = summarize(())
        assert s["total"] == 0


# =============================================================================
# stale_running_agent — agent_invocations 中 status=running 超 30min（PROP-20260820-001）
# =============================================================================


class TestStaleRunningAgent:
    def _stale_ts(self, minutes_ago: int = 45) -> str:
        """生成 N 分钟前的 ISO ts（UTC）。"""
        from datetime import datetime, timedelta, timezone
        return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()

    def _recent_ts(self) -> str:
        """生成 5 分钟前的 ISO ts。"""
        return self._stale_ts(5)

    def test_detects_stale_running_code_reviewer(self, tmp_path: Path):
        p = tmp_path / "p"
        _make_plan(p, execute_state={
            "schema_version": "drive.runtime.state.v1",
            "revision": 1,
            "active_stage": "execute",
            "agent_invocations": {
                "plan-T04": {
                    "code-reviewer": {
                        "status": "running",
                        "started_at": self._stale_ts(45),
                        "attempt": 1,
                    },
                },
            },
        })
        record = read_record(p)
        gaps = detect_gaps(record)
        stale = [g for g in gaps if g.type == "stale_running_agent"]
        assert len(stale) == 1
        g = stale[0]
        assert g.severity == SEVERITY_HIGH
        assert "code-reviewer" in g.description
        assert "plan-T04" in g.description
        assert "agent_invocations.plan-T04.code-reviewer" in g.location

    def test_no_gap_when_recent(self, tmp_path: Path):
        p = tmp_path / "p"
        _make_plan(p, execute_state={
            "schema_version": "drive.runtime.state.v1",
            "revision": 1,
            "active_stage": "execute",
            "agent_invocations": {
                "plan-T01": {
                    "code-reviewer": {
                        "status": "running",
                        "started_at": self._recent_ts(),
                        "attempt": 1,
                    },
                },
            },
        })
        record = read_record(p)
        gaps = detect_gaps(record)
        stale = [g for g in gaps if g.type == "stale_running_agent"]
        assert stale == []

    def test_no_gap_when_completed(self, tmp_path: Path):
        """status=completed 的 reviewer 不论 started_at 多早都非 stale。"""
        p = tmp_path / "p"
        _make_plan(p, execute_state={
            "schema_version": "drive.runtime.state.v1",
            "revision": 1,
            "active_stage": "execute",
            "agent_invocations": {
                "plan-T01": {
                    "code-reviewer": {
                        "status": "completed",
                        "started_at": self._stale_ts(120),
                        "finished_at": self._stale_ts(60),
                    },
                },
            },
        })
        record = read_record(p)
        gaps = detect_gaps(record)
        stale = [g for g in gaps if g.type == "stale_running_agent"]
        assert stale == []

    def test_no_gap_when_failed(self, tmp_path: Path):
        """status=failed 也算终结态。"""
        p = tmp_path / "p"
        _make_plan(p, execute_state={
            "schema_version": "drive.runtime.state.v1",
            "revision": 1,
            "active_stage": "execute",
            "agent_invocations": {
                "plan-T02": {
                    "security-reviewer": {
                        "status": "failed",
                        "started_at": self._stale_ts(90),
                    },
                },
            },
        })
        record = read_record(p)
        gaps = detect_gaps(record)
        stale = [g for g in gaps if g.type == "stale_running_agent"]
        assert stale == []

    def test_detects_multiple_stale_agents(self, tmp_path: Path):
        """两个 reviewer 都卡死 → 两条 gap。"""
        p = tmp_path / "p"
        _make_plan(p, execute_state={
            "schema_version": "drive.runtime.state.v1",
            "revision": 1,
            "active_stage": "execute",
            "agent_invocations": {
                "plan-T04": {
                    "code-reviewer": {
                        "status": "running",
                        "started_at": self._stale_ts(45),
                        "attempt": 1,
                    },
                    "security-reviewer": {
                        "status": "running",
                        "started_at": self._stale_ts(50),
                        "attempt": 1,
                    },
                },
            },
        })
        record = read_record(p)
        gaps = detect_gaps(record)
        stale = [g for g in gaps if g.type == "stale_running_agent"]
        assert len(stale) == 2
        reviewers = {g.description.split(" ")[0] for g in stale}
        assert reviewers == {"code-reviewer", "security-reviewer"}

    def test_no_gap_when_no_invocations_field(self, tmp_path: Path):
        """旧 state 文件不含 agent_invocations → 不应 crash，也不应误报。"""
        p = tmp_path / "p"
        _make_plan(p, execute_state={
            "schema_version": "drive.runtime.state.v1",
            "revision": 1,
            "active_stage": "execute",
        })
        record = read_record(p)
        gaps = detect_gaps(record)
        stale = [g for g in gaps if g.type == "stale_running_agent"]
        assert stale == []

    def test_no_gap_when_started_at_missing(self, tmp_path: Path):
        """status=running 但 started_at 缺 → 跳过（防御 malformed state）。"""
        p = tmp_path / "p"
        _make_plan(p, execute_state={
            "schema_version": "drive.runtime.state.v1",
            "revision": 1,
            "active_stage": "execute",
            "agent_invocations": {
                "plan-T01": {
                    "code-reviewer": {"status": "running", "attempt": 1},
                },
            },
        })
        record = read_record(p)
        gaps = detect_gaps(record)
        stale = [g for g in gaps if g.type == "stale_running_agent"]
        assert stale == []

    def test_skips_non_dict_invocation(self, tmp_path: Path):
        """malformed invocation（非 dict）→ skip 不 crash。"""
        p = tmp_path / "p"
        _make_plan(p, execute_state={
            "schema_version": "drive.runtime.state.v1",
            "revision": 1,
            "active_stage": "execute",
            "agent_invocations": {
                "plan-T01": {"code-reviewer": "bad"},
            },
        })
        record = read_record(p)
        gaps = detect_gaps(record)
        stale = [g for g in gaps if g.type == "stale_running_agent"]
        assert stale == []

    def test_fix_suggestion_mentions_user_decision(self, tmp_path: Path):
        """fix_suggestion 必须提到 HITL 决策路径（不是 auto fix）。"""
        p = tmp_path / "p"
        _make_plan(p, execute_state={
            "schema_version": "drive.runtime.state.v1",
            "revision": 1,
            "active_stage": "execute",
            "agent_invocations": {
                "plan-T04": {
                    "code-reviewer": {
                        "status": "running",
                        "started_at": self._stale_ts(45),
                    },
                },
            },
        })
        record = read_record(p)
        gaps = detect_gaps(record)
        stale = [g for g in gaps if g.type == "stale_running_agent"]
        assert len(stale) == 1
        suggestion = stale[0].fix_suggestion
        assert "用户决定" in suggestion or "用户" in suggestion
        # 显式声明不自动改
        assert "不自动" in suggestion or "保持 drive contract" in suggestion

    def test_threshold_30_minutes(self):
        """STALE_RUNNING_AGENT_SECONDS 必须是 30 分钟（设计契约）。"""
        from gaps_detector import STALE_RUNNING_AGENT_SECONDS
        assert STALE_RUNNING_AGENT_SECONDS == 30 * 60