"""evaluator L2 reviewer cross-reference contract tests。

evaluator.md 的 reviewer cross-ref 是 SKILL guidance（LLM 自己执行），
不是 code path。本文件测结构性契约：

- SKILL.md 必备段（L2 step 0 / heuristic / report 模板 / gotcha / checklist）
- agent_invocations schema 接受 reviewer verdict 值（approve / warning / block）
- 旧 state 缺 agent_invocations 仍通过校验（向后兼容）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
EVALUATOR_MD = PLUGIN_ROOT / "agents" / "evaluator.md"
STATE_MACHINE_DIR = PLUGIN_ROOT / "skills" / "state-machine" / "scripts"


# =============================================================================
# SKILL.md 结构契约
# =============================================================================


def test_evaluator_md_documents_l2_step_zero_for_reviewer():
    body = EVALUATOR_MD.read_text(encoding="utf-8")
    assert "0. **读 reviewer 产物**" in body
    assert "agent_invocations[<task_id>]" in body
    assert "code-reviewer" in body and "security-reviewer" in body


def test_evaluator_md_documents_keyword_heuristic():
    body = EVALUATOR_MD.read_text(encoding="utf-8")
    assert "≥3 字符英文 token 重叠" in body
    assert "findings.critical" in body
    assert "强制为 PARTIAL" in body


def test_evaluator_md_documents_block_verdict_cap():
    body = EVALUATOR_MD.read_text(encoding="utf-8")
    assert 'verdict == "block"' in body
    assert "整体 verdict 最高" in body
    assert "partial" in body


def test_evaluator_md_documents_backward_compat():
    body = EVALUATOR_MD.read_text(encoding="utf-8")
    assert "字段缺失" in body
    assert "向后兼容" in body
    assert "走原 L2 路径" in body


def test_evaluator_md_report_template_includes_reviewer_findings_section():
    body = EVALUATOR_MD.read_text(encoding="utf-8")
    assert "## Reviewer Findings (agent_invocations)" in body
    assert "| reviewer | verdict | critical | high | medium | low |" in body
    assert "AC 受 reviewer 影响" in body


def test_evaluator_md_unchanged_medium_low_does_not_demote_ac():
    body = EVALUATOR_MD.read_text(encoding="utf-8")
    assert "medium/low findings 写进 report 不影响 AC" in body


def test_evaluator_md_inputs_section_lists_agent_invocations():
    body = EVALUATOR_MD.read_text(encoding="utf-8")
    inputs_block = body.split("## 输入", 1)[1].split("## 三层验证", 1)[0]
    assert "agent_invocations[<task_id>]" in inputs_block
    assert "code-reviewer" in inputs_block
    assert "security-reviewer" in inputs_block


def test_evaluator_md_checklist_includes_reviewer_cross_ref():
    body = EVALUATOR_MD.read_text(encoding="utf-8")
    assert "reviewer cross-ref" in body
    assert "agent_invocations[<task_id>]" in body


# =============================================================================
# state_schema 接受 reviewer verdict 值
# =============================================================================


sys.path.insert(0, str(STATE_MACHINE_DIR))
try:
    from state_schema import validate_agent_invocations  # type: ignore[import-not-found]
finally:
    if str(STATE_MACHINE_DIR) in sys.path:
        sys.path.remove(str(STATE_MACHINE_DIR))


def _make_invocations(reviewer: str, *, verdict: str, critical: int = 0):
    return {
        "plan-20260928-001-T01": {
            reviewer: {
                "status": "completed",
                "started_at": "2026-09-28T10:00:00+00:00",
                "finished_at": "2026-09-28T10:05:00+00:00",
                "duration_sec": 300,
                "verdict": verdict,
                "findings": {
                    "critical": critical,
                    "high": 0,
                    "medium": 0,
                    "low": 0,
                },
                "attempt": 1,
            }
        }
    }


@pytest.mark.parametrize("verdict", ["approve", "warning", "block"])
def test_schema_accepts_reviewer_verdict_values(verdict):
    invocations = _make_invocations("code-reviewer", verdict=verdict)
    ok, reason = validate_agent_invocations(invocations)
    assert ok, reason


def test_schema_accepts_critical_findings_count():
    invocations = _make_invocations("code-reviewer", verdict="block", critical=3)
    ok, reason = validate_agent_invocations(invocations)
    assert ok, reason


def test_schema_accepts_multiple_reviewers():
    invocations = {
        "plan-20260928-001-T01": {
            "code-reviewer": {
                "status": "completed",
                "verdict": "warning",
                "findings": {"critical": 0, "high": 1, "medium": 2, "low": 0},
                "attempt": 1,
            },
            "security-reviewer": {
                "status": "completed",
                "verdict": "approve",
                "findings": {"critical": 0, "high": 0, "medium": 0, "low": 0},
                "attempt": 1,
            },
        }
    }
    ok, reason = validate_agent_invocations(invocations)
    assert ok, reason


def test_schema_rejects_invalid_verdict_value():
    invocations = _make_invocations("code-reviewer", verdict="approve-with-love")
    ok, reason = validate_agent_invocations(invocations)
    assert not ok
    assert "verdict" in reason


def test_schema_rejects_negative_findings_count():
    invocations = {
        "plan-20260928-001-T01": {
            "code-reviewer": {
                "status": "completed",
                "verdict": "warning",
                "findings": {"critical": -1, "high": 0, "medium": 0, "low": 0},
            }
        }
    }
    ok, reason = validate_agent_invocations(invocations)
    assert not ok
    assert "non-negative" in reason or "findings" in reason


# =============================================================================
# 顶层 state 校验向后兼容：缺 agent_invocations 仍通过
# =============================================================================


sys.path.insert(0, str(STATE_MACHINE_DIR))
try:
    from state_write import default_state  # noqa: E402
finally:
    if str(STATE_MACHINE_DIR) in sys.path:
        sys.path.remove(str(STATE_MACHINE_DIR))


def test_default_state_lacks_agent_invocations():
    state = default_state()
    assert "agent_invocations" not in state


sys.path.insert(0, str(STATE_MACHINE_DIR))
try:
    from state_schema import validate_execute_state  # type: ignore[import-not-found]
finally:
    if str(STATE_MACHINE_DIR) in sys.path:
        sys.path.remove(str(STATE_MACHINE_DIR))


def test_state_without_agent_invocations_validates_clean():
    state = default_state()
    state["active_stage"] = "evaluate"
    state["verdict"] = "pass"
    ok, reason = validate_execute_state(state)
    assert ok, reason


def test_state_with_agent_invocations_validates_clean():
    state = default_state()
    state["active_stage"] = "evaluate"
    state["verdict"] = "pass"
    state["agent_invocations"] = {
        "plan-20260928-001-T01": {
            "code-reviewer": {
                "status": "completed",
                "verdict": "approve",
                "findings": {"critical": 0, "high": 0, "medium": 0, "low": 0},
                "attempt": 1,
            }
        }
    }
    ok, reason = validate_execute_state(state)
    assert ok, reason


def test_state_with_malformed_agent_invocations_rejected():
    state = default_state()
    state["active_stage"] = "evaluate"
    state["verdict"] = "pass"
    state["agent_invocations"] = {
        "plan-20260928-001-T01": {
            "code-reviewer": {
                "status": "completed",
                "verdict": "approve-with-love",
                "findings": {"critical": 0, "high": 0, "medium": 0, "low": 0},
            }
        }
    }
    ok, reason = validate_execute_state(state)
    assert not ok
    assert "agent_invocations" in reason
