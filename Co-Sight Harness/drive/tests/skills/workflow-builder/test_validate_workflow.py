"""workflow-builder/scripts/validate_workflow.py 单测。

覆盖 _validate_agent_ref / validate / _validate_dag 的关键分支。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import validate_workflow as vw  # noqa: E402


# ---------- helpers ----------


def _write_wf(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "workflow.yaml"
    p.write_text(content, encoding="utf-8")
    return p


def _write_agents(agents_dir: Path, *names: str) -> None:
    agents_dir.mkdir(parents=True, exist_ok=True)
    for n in names:
        (agents_dir / f"{n}.md").write_text(
            f"---\nname: {n}\n---\n# {n}\n", encoding="utf-8"
        )


# ---------- _validate_agent_ref ----------


def test_validate_agent_ref_builtin_whitelisted():
    for a in ("general-purpose", "Explore", "Plan"):
        ok, err = vw._validate_agent_ref(a, set(), set(), set())
        assert ok and err is None


def test_validate_agent_ref_at_mention_passes():
    ok, err = vw._validate_agent_ref("@my-agent", set(), set(), set())
    assert ok and err is None
    # @ 后缺名字 → fail
    ok, err = vw._validate_agent_ref("@", set(), set(), set())
    assert not ok and "@" in err


def test_validate_agent_ref_drive_prefix():
    ok, err = vw._validate_agent_ref("drive:executor", set(), {"executor"}, set())
    assert ok and err is None
    # 没注册
    ok, err = vw._validate_agent_ref("drive:ghost", set(), {"executor"}, set())
    assert not ok and "ghost" in err
    # drive: 后空
    ok, err = vw._validate_agent_ref("drive:", set(), set(), set())
    assert not ok and "缺少" in err


def test_validate_agent_ref_bare_name_in_project_agents():
    ok, err = vw._validate_agent_ref("my-agent", {"my-agent"}, set(), set())
    assert ok and err is None
    # 不在 project_agents
    ok, err = vw._validate_agent_ref("ghost", {"my-agent"}, set(), set())
    assert not ok and "ghost" in err


def test_validate_agent_ref_empty_string():
    ok, err = vw._validate_agent_ref("", set(), set(), set())
    assert not ok and "空" in err


# ---------- validate: phase 模式 ----------


def test_validate_file_missing(tmp_path: Path):
    out = vw.validate(tmp_path / "no.yaml")
    assert not out["ok"]
    assert out["reason"] == "schema_invalid"


def test_validate_yaml_decode_error(tmp_path: Path):
    p = _write_wf(tmp_path, "phases: [unclosed")
    out = vw.validate(p)
    assert not out["ok"]
    assert out["reason"] == "yaml_decode_error"


def test_validate_top_level_not_mapping(tmp_path: Path):
    p = _write_wf(tmp_path, "- a\n- b\n")
    out = vw.validate(p)
    assert not out["ok"]
    assert "顶层" in out["details"]["message"]


def test_validate_unknown_mode(tmp_path: Path):
    p = _write_wf(tmp_path, "mode: weird\nphases: []\n")
    out = vw.validate(p)
    assert not out["ok"]
    assert "mode" in out["details"]["message"]


def test_validate_phase_mode_phases_empty(tmp_path: Path):
    p = _write_wf(tmp_path, "phases: []\n")
    out = vw.validate(p)
    assert not out["ok"]
    assert "phases" in out["details"]["message"]


def test_validate_phase_mode_phases_not_list(tmp_path: Path):
    p = _write_wf(tmp_path, "phases: not-a-list\n")
    out = vw.validate(p)
    assert not out["ok"]


def test_validate_phase_required_fields_missing(tmp_path: Path, tmp_path_factory=None):
    p = _write_wf(tmp_path, "phases:\n  - name: p1\n")
    out = vw.validate(p)
    assert not out["ok"]
    errs = out["details"]["errors"]
    assert any("缺少" in e for e in errs)


def test_validate_phase_reserved_stage_start(tmp_path: Path):
    p = _write_wf(tmp_path, "phases:\n  - name: p1\n    stage: start\n    agent: '@x'\n  - name: p2\n    stage: end\n    agent: '@x'\n    terminal_stage: true\n")
    out = vw.validate(p)
    assert not out["ok"]
    assert any("start" in e for e in out["details"]["errors"])


def test_validate_phase_duplicate_stage(tmp_path: Path):
    p = _write_wf(tmp_path, "phases:\n  - name: p1\n    stage: analyze\n    agent: '@x'\n  - name: p2\n    stage: analyze\n    agent: '@x'\n    terminal_stage: true\n")
    out = vw.validate(p)
    assert not out["ok"]
    assert any("重复" in e for e in out["details"]["errors"])


def test_validate_phase_gate_wrong_type(tmp_path: Path):
    p = _write_wf(tmp_path, "phases:\n  - name: p1\n    stage: analyze\n    agent: '@x'\n    gate: 'not a mapping'\n  - name: p2\n    stage: end\n    agent: '@x'\n    terminal_stage: true\n")
    out = vw.validate(p)
    assert not out["ok"]


def test_validate_phase_gate_unknown_type(tmp_path: Path):
    p = _write_wf(tmp_path, "phases:\n  - name: p1\n    stage: analyze\n    agent: '@x'\n    gate:\n      type: weird_gate\n      enforced_by: foo.py\n  - name: p2\n    stage: end\n    agent: '@x'\n    terminal_stage: true\n")
    out = vw.validate(p)
    assert not out["ok"]
    assert any("type 未知" in e for e in out["details"]["errors"])


def test_validate_phase_gate_missing_enforced_by(tmp_path: Path):
    p = _write_wf(tmp_path, "phases:\n  - name: p1\n    stage: analyze\n    agent: '@x'\n    gate:\n      type: human_review\n  - name: p2\n    stage: end\n    agent: '@x'\n    terminal_stage: true\n")
    out = vw.validate(p)
    assert not out["ok"]


def test_validate_phase_gate_enforced_by_not_exists(tmp_path: Path):
    p = _write_wf(tmp_path, "phases:\n  - name: p1\n    stage: analyze\n    agent: '@x'\n    gate:\n      type: human_review\n      enforced_by: hooks/no_such.py\n  - name: p2\n    stage: end\n    agent: '@x'\n    terminal_stage: true\n")
    # 传 plugin_root，hook 找不到应 fail
    out = vw.validate(p, plugin_root=tmp_path)
    assert not out["ok"]


def test_validate_phase_mode_unknown(tmp_path: Path):
    p = _write_wf(tmp_path, "phases:\n  - name: p1\n    stage: analyze\n    agent: '@x'\n    mode: weird\n  - name: p2\n    stage: end\n    agent: '@x'\n    terminal_stage: true\n")
    out = vw.validate(p)
    assert not out["ok"]


def test_validate_phase_terminal_not_last(tmp_path: Path):
    p = _write_wf(tmp_path, "phases:\n  - name: p1\n    stage: analyze\n    agent: '@x'\n    terminal_stage: true\n  - name: p2\n    stage: end\n    agent: '@x'\n")
    out = vw.validate(p)
    assert not out["ok"]
    assert any("terminal_stage" in e and "最后一个" in e for e in out["details"]["errors"])


def test_validate_phase_multiple_terminals(tmp_path: Path):
    p = _write_wf(tmp_path, "phases:\n  - name: p1\n    stage: analyze\n    agent: '@x'\n    terminal_stage: true\n  - name: p2\n    stage: end\n    agent: '@x'\n    terminal_stage: true\n")
    out = vw.validate(p)
    assert not out["ok"]


def test_validate_back_jumps_not_mapping(tmp_path: Path):
    p = _write_wf(tmp_path, "phases:\n  - name: p1\n    stage: a\n    agent: '@x'\n  - name: p2\n    stage: b\n    agent: '@x'\n    terminal_stage: true\nallowed_back_jumps: 'not a dict'\n")
    out = vw.validate(p)
    assert not out["ok"]


def test_validate_back_jumps_source_missing(tmp_path: Path):
    p = _write_wf(tmp_path, "phases:\n  - name: p1\n    stage: a\n    agent: '@x'\n  - name: p2\n    stage: b\n    agent: '@x'\n    terminal_stage: true\nallowed_back_jumps:\n  ghost: [a]\n")
    out = vw.validate(p)
    assert not out["ok"]
    assert any("源 stage" in e for e in out["details"]["errors"])


def test_validate_back_jumps_target_not_before(tmp_path: Path):
    p = _write_wf(tmp_path, "phases:\n  - name: p1\n    stage: a\n    agent: '@x'\n  - name: p2\n    stage: b\n    agent: '@x'\n    terminal_stage: true\nallowed_back_jumps:\n  b: [b]\n")
    out = vw.validate(p)
    assert not out["ok"]
    assert any("不在当前 stage 之前" in e for e in out["details"]["errors"])


def test_validate_back_jumps_targets_not_list(tmp_path: Path):
    p = _write_wf(tmp_path, "phases:\n  - name: p1\n    stage: a\n    agent: '@x'\n  - name: p2\n    stage: b\n    agent: '@x'\n    terminal_stage: true\nallowed_back_jumps:\n  b: 'not a list'\n")
    out = vw.validate(p)
    assert not out["ok"]


def test_validate_back_jumps_target_missing(tmp_path: Path):
    p = _write_wf(tmp_path, "phases:\n  - name: p1\n    stage: a\n    agent: '@x'\n  - name: p2\n    stage: b\n    agent: '@x'\n    terminal_stage: true\nallowed_back_jumps:\n  b: [ghost]\n")
    out = vw.validate(p)
    assert not out["ok"]


def test_validate_complexity_rules_not_mapping(tmp_path: Path):
    p = _write_wf(tmp_path, "phases:\n  - name: p1\n    stage: a\n    agent: '@x'\n  - name: p2\n    stage: b\n    agent: '@x'\n    terminal_stage: true\ncomplexity_rules: 'not a dict'\n")
    out = vw.validate(p)
    assert not out["ok"]


def test_validate_complexity_rules_unknown_tier(tmp_path: Path):
    p = _write_wf(tmp_path, "phases:\n  - name: p1\n    stage: a\n    agent: '@x'\n  - name: p2\n    stage: b\n    agent: '@x'\n    terminal_stage: true\ncomplexity_rules:\n  weird_tier:\n    skip_phases: []\n")
    out = vw.validate(p)
    assert not out["ok"]


def test_validate_complexity_rules_skip_phases_not_list(tmp_path: Path):
    p = _write_wf(tmp_path, "phases:\n  - name: p1\n    stage: a\n    agent: '@x'\n  - name: p2\n    stage: b\n    agent: '@x'\n    terminal_stage: true\ncomplexity_rules:\n  trivial:\n    skip_phases: 'oops'\n")
    out = vw.validate(p)
    assert not out["ok"]


def test_validate_complexity_rules_skip_phases_unknown(tmp_path: Path):
    p = _write_wf(tmp_path, "phases:\n  - name: p1\n    stage: a\n    agent: '@x'\n  - name: p2\n    stage: b\n    agent: '@x'\n    terminal_stage: true\ncomplexity_rules:\n  trivial:\n    skip_phases: [ghost]\n")
    out = vw.validate(p)
    assert not out["ok"]


def test_validate_complexity_rules_evaluate_levels_illegal(tmp_path: Path):
    p = _write_wf(tmp_path, "phases:\n  - name: p1\n    stage: a\n    agent: '@x'\n  - name: p2\n    stage: b\n    agent: '@x'\n    terminal_stage: true\ncomplexity_rules:\n  trivial:\n    evaluate_levels: [L3]\n")
    out = vw.validate(p)
    assert not out["ok"]


def test_validate_complexity_rules_unknown_field(tmp_path: Path):
    p = _write_wf(tmp_path, "phases:\n  - name: p1\n    stage: a\n    agent: '@x'\n  - name: p2\n    stage: b\n    agent: '@x'\n    terminal_stage: true\ncomplexity_rules:\n  trivial:\n    extra: 1\n")
    out = vw.validate(p)
    assert not out["ok"]


def test_validate_phase_happy_path(tmp_path: Path):
    p = _write_wf(tmp_path, "phases:\n  - name: p1\n    stage: a\n    agent: 'general-purpose'\n  - name: p2\n    stage: b\n    agent: 'general-purpose'\n    terminal_stage: true\n")
    out = vw.validate(p)
    assert out["ok"], out
    assert out["data"]["phases"]


# ---------- validate: dag 模式 ----------


def test_validate_dag_agents_empty(tmp_path: Path):
    p = _write_wf(tmp_path, "mode: dag\nagents: []\n")
    out = vw.validate(p)
    assert not out["ok"]


def test_validate_dag_agents_not_list(tmp_path: Path):
    p = _write_wf(tmp_path, "mode: dag\nagents: 'oops'\n")
    out = vw.validate(p)
    assert not out["ok"]


def test_validate_dag_required_fields(tmp_path: Path):
    p = _write_wf(tmp_path, "mode: dag\nagents:\n  - id: a\n")
    out = vw.validate(p)
    assert not out["ok"]


def test_validate_dag_duplicate_id(tmp_path: Path):
    p = _write_wf(tmp_path, "mode: dag\nagents:\n  - id: a\n    agent: '@x'\n  - id: a\n    agent: '@x'\n    terminal: true\n    verdict_required: true\n")
    out = vw.validate(p)
    assert not out["ok"]


def test_validate_dag_no_terminal(tmp_path: Path):
    p = _write_wf(tmp_path, "mode: dag\nagents:\n  - id: a\n    agent: '@x'\n")
    out = vw.validate(p)
    assert not out["ok"]
    assert any("terminal" in e for e in out["details"]["errors"])


def test_validate_dag_terminal_without_verdict(tmp_path: Path):
    p = _write_wf(tmp_path, "mode: dag\nagents:\n  - id: a\n    agent: '@x'\n    terminal: true\n")
    out = vw.validate(p)
    assert not out["ok"]


def test_validate_dag_verdict_without_terminal(tmp_path: Path):
    p = _write_wf(tmp_path, "mode: dag\nagents:\n  - id: a\n    agent: '@x'\n    verdict_required: true\n")
    out = vw.validate(p)
    assert not out["ok"]


def test_validate_dag_depends_on_unknown_id(tmp_path: Path):
    p = _write_wf(tmp_path, "mode: dag\nagents:\n  - id: a\n    agent: '@x'\n  - id: b\n    agent: '@x'\n    depends_on: [ghost]\n    terminal: true\n    verdict_required: true\n")
    out = vw.validate(p)
    assert not out["ok"]


def test_validate_dag_depends_on_not_list(tmp_path: Path):
    p = _write_wf(tmp_path, "mode: dag\nagents:\n  - id: a\n    agent: '@x'\n  - id: b\n    agent: '@x'\n    depends_on: 'oops'\n    terminal: true\n    verdict_required: true\n")
    out = vw.validate(p)
    assert not out["ok"]


def test_validate_dag_complexity_skip_agents_unknown(tmp_path: Path):
    p = _write_wf(tmp_path, "mode: dag\nagents:\n  - id: a\n    agent: '@x'\n    terminal: true\n    verdict_required: true\ncomplexity_rules:\n  trivial:\n    skip_agents: [ghost]\n")
    out = vw.validate(p)
    assert not out["ok"]


def test_validate_dag_complexity_skip_agents_not_list(tmp_path: Path):
    p = _write_wf(tmp_path, "mode: dag\nagents:\n  - id: a\n    agent: '@x'\n    terminal: true\n    verdict_required: true\ncomplexity_rules:\n  trivial:\n    skip_agents: 'oops'\n")
    out = vw.validate(p)
    assert not out["ok"]


def test_validate_dag_happy_path(tmp_path: Path):
    p = _write_wf(tmp_path, "mode: dag\nagents:\n  - id: a\n    agent: 'general-purpose'\n  - id: b\n    agent: 'general-purpose'\n    depends_on: [a]\n    terminal: true\n    verdict_required: true\n")
    out = vw.validate(p)
    assert out["ok"], out
    assert out["data"]["mode"] == "dag"
    assert out["data"]["terminal_count"] == 1
    assert out["data"]["verdict_required_count"] == 1


# ---------- _scan_agent_names ----------


def test_scan_agent_names_empty_dir(tmp_path: Path):
    assert vw._scan_agent_names(tmp_path) == set()


def test_scan_agent_names_picks_name_from_frontmatter(tmp_path: Path):
    _write_agents(tmp_path, "alpha", "beta")
    assert vw._scan_agent_names(tmp_path) == {"alpha", "beta"}


def test_scan_agent_names_skips_no_frontmatter(tmp_path: Path):
    (tmp_path / "x.md").write_text("# x\n", encoding="utf-8")
    assert vw._scan_agent_names(tmp_path) == set()


def test_scan_agent_names_skips_empty_name(tmp_path: Path):
    (tmp_path / "x.md").write_text("---\nname: '   '\n---\n# x\n", encoding="utf-8")
    assert vw._scan_agent_names(tmp_path) == set()


def test_scan_agent_names_skips_invalid_yaml(tmp_path: Path):
    (tmp_path / "x.md").write_text("---\nname: [broken\n---\n", encoding="utf-8")
    assert vw._scan_agent_names(tmp_path) == set()
