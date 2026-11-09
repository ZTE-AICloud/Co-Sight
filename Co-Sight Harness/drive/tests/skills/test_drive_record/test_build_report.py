"""build_report + cli 端到端测试 —— Phase 4。

4 fixture × 端到端：
1. phase_completed → §0~§5 + §B 都在 + REPORT.md 落盘
2. phase_executing → §4 显示 executing + 可能 §B 有 missing_summary
3. dag_plan → §0.1 显示 mode=dag + §2 含 wave_summaries
4. residual_plan → §B 含 missing_summary gap
5. cli.py → envelope 输出
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from build_report import build_report, write_report
from record_reader import read_record


# ---------- build_report 端到端 ----------


class TestBuildReportPhaseCompleted:
    def test_all_sections_present(self, phase_completed_plan: Path):
        result = build_report(phase_completed_plan)
        for sec in ["§0", "§0.1", "§1", "§2", "§3", "§4", "§5", "§B"]:
            assert sec in result["report_md"], f"section {sec} missing"

    def test_meta_has_run_meta(self, phase_completed_plan: Path):
        result = build_report(phase_completed_plan)
        assert "plan_name" in result["report_md"]
        assert "started_at" in result["report_md"]

    def test_timeline_in_code_block(self, phase_completed_plan: Path):
        result = build_report(phase_completed_plan)
        assert "```" in result["report_md"]
        assert "[startup]" in result["report_md"]
        assert "[stage]" in result["report_md"]

    def test_summary_present(self, phase_completed_plan: Path):
        result = build_report(phase_completed_plan)
        assert "summary" in result
        for k in ("total", "critical", "high", "medium", "low"):
            assert k in result["summary"]


class TestBuildReportPhaseExecuting:
    def test_active_stage_shows_executing(self, phase_executing_plan: Path):
        result = build_report(phase_executing_plan)
        assert "## §4 当前状态" in result["report_md"]
        assert "execute" in result["report_md"]

    def test_session_section_handles_missing_silently(
        self, phase_executing_plan: Path
    ):
        result = build_report(phase_executing_plan, cwd="/nonexistent")
        # 不报错；§5 显示 silently skipped
        assert "## §5 session 路径" in result["report_md"]
        assert result["session_path"] is None


class TestBuildReportDag:
    def test_dag_mode_in_meta(self, dag_plan_dir: Path):
        result = build_report(dag_plan_dir)
        assert "mode=dag" in result["report_md"] or "`dag`" in result["report_md"]

    def test_wave_summaries_in_section(self, dag_plan_dir: Path):
        result = build_report(dag_plan_dir)
        assert "## §2 阶段产物摘要" in result["report_md"]
        # dag fixture 含 confirmed_stages；§2 应展示阶段流转
        assert "已确认阶段" in result["report_md"]
        assert "start" in result["report_md"]
        assert "analyze" in result["report_md"]
        assert "plan" in result["report_md"]


class TestBuildReportResidual:
    def test_missing_summary_gap_detected(self, residual_plan: Path):
        result = build_report(residual_plan)
        assert "missing_summary" in result["report_md"]

    def test_section_b_lists_gaps(self, residual_plan: Path):
        result = build_report(residual_plan)
        assert "missing_summary" in result["report_md"]
        assert "## §B" in result["report_md"]


# ---------- write_report 落盘 ----------


class TestWriteReport:
    def test_writes_report_md(self, phase_completed_plan: Path):
        result = write_report(phase_completed_plan)
        assert (phase_completed_plan / "REPORT.md").is_file()


# ---------- cli.py 端到端 ----------


class TestCli:
    def test_cli_emits_envelope(self, phase_completed_plan: Path):
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[3]
                    / "skills" / "drive-record" / "scripts" / "cli.py"),
                "--plan-dir", str(phase_completed_plan),
            ],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        envelope = json.loads(result.stdout)
        assert envelope["ok"] is True
        assert "data" in envelope
        assert "report_md" in envelope["data"]
        assert "summary" in envelope["data"]

    def test_cli_invalid_plan_dir(self, tmp_path: Path):
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[3]
                    / "skills" / "drive-record" / "scripts" / "cli.py"),
                "--plan-dir", str(tmp_path / "does-not-exist"),
            ],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 1
        envelope = json.loads(result.stdout)
        assert envelope["ok"] is False
        assert "reason" in envelope


# ---------- envelope 新字段（plan_name / mode / completeness）----------


class TestEnvelopeFields:
    def test_plan_name_from_run_meta(self, phase_completed_plan: Path):
        result = build_report(phase_completed_plan)
        assert "plan_name" in result
        # 从 fixture 实际 run-meta.json 读 plan_name 应原样回填
        record = read_record(phase_completed_plan)
        expected = (
            record.run_meta.plan_name if record.run_meta and record.run_meta.plan_name
            else phase_completed_plan.name
        )
        assert result["plan_name"] == expected

    def test_plan_name_fallback_to_dirname(self, tmp_path: Path):
        """run-meta 缺失时 fallback 到 plan_dir 目录名。"""
        p = tmp_path / "plan-20260820-fallback"
        p.mkdir(parents=True)
        # 不写 run-meta.json → run_meta 为 None → fallback 到 dirname
        (p / "executeState.json").write_text("{}")
        (p / "run-log.jsonl").write_text("")
        result = build_report(p)
        assert result["plan_name"] == "plan-20260820-fallback"

    def test_mode_phase_default(self, phase_completed_plan: Path):
        result = build_report(phase_completed_plan)
        assert result["mode"] == "phase"

    def test_mode_dag(self, dag_plan_dir: Path):
        result = build_report(dag_plan_dir)
        assert result["mode"] == "dag"

    def test_completeness_shape(self, phase_completed_plan: Path):
        result = build_report(phase_completed_plan)
        c = result["completeness"]
        assert set(c.keys()) == {"runtime_present", "runtime_total", "llm_present", "llm_total"}
        assert c["runtime_present"] + c["llm_present"] <= c["runtime_total"] + c["llm_total"]
        assert c["runtime_total"] == 6
        assert c["llm_total"] == 3

    def test_cli_envelope_has_new_fields(self, phase_completed_plan: Path):
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[3]
                    / "skills" / "drive-record" / "scripts" / "cli.py"),
                "--plan-dir", str(phase_completed_plan),
            ],
            capture_output=True, text=True, timeout=30,
        )
        envelope = json.loads(result.stdout)
        data = envelope["data"]
        assert "plan_name" in data
        assert "mode" in data
        assert "completeness" in data
        # 与 build_report 返回一致
        record = read_record(phase_completed_plan)
        expected_name = (
            record.run_meta.plan_name if record.run_meta and record.run_meta.plan_name
            else phase_completed_plan.name
        )
        assert data["plan_name"] == expected_name
        assert data["mode"] == "phase"
        assert data["completeness"]["runtime_total"] == 6