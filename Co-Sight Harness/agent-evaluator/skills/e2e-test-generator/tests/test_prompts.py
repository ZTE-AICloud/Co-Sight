#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_prompts.py — S3 提示词渲染：画像摘要、能力点约束、禁止重复素材。"""

import config
import prompts
from common import write_json


def make_profile(capabilities=None, engine=None, demo=None):
    return {
        "root": "/tmp/agent",
        "project_id": "a", "tier": config.TIER_A, "tier_reason": "含 GWT",
        "capabilities": capabilities if capabilities is not None else [
            {"id": "C01", "name": "命中", "desc": "命中并分级", "evidence": "e"},
            {"id": "C02", "name": "排除", "desc": "误报排除", "evidence": "e"},
        ],
        "tools": {"allow": ["Read", "Grep"], "deny": []},
        "constraints": {"scan_mode": "read-only"},
        "boundaries": {"positioning": "做一件事\n第二行",
                       "capability_boundary": "规则 R01~R06\n排除 X01~X06"},
        "engine": engine if engine is not None else {
            "cli_args": ["target", "-o"], "exit_codes": [0, 1, 2],
            "declarations": {}, "source_file": "e.py", "source_bytes": 10,
        },
        "demo_code": demo,
        "gwt_baseline": {"entries": [
            {"index": 1, "given": "存在 java 文件"},
            {"index": 2, "given": "存在配置文件"},
        ]},
        "warnings": [],
    }


def make_plan():
    return {
        "count": 6, "tier": config.TIER_A,
        "gwt_kept": [{"index": 1, "title": "命中", "given": "存在 java 文件",
                      "when": "执行检查", "then": "报告命中该行", "dimension": "functional"}],
        "gwt_dropped": [],
        "quota": {"functional": 2, "boundary": 1},
        "batch_size": config.BATCH_SIZE,
    }


# ============================== 画像摘要 ==============================

def test_summarize_profile_takes_first_positioning_line():
    summary = prompts.summarize_profile(make_profile())
    assert summary["positioning"] == "做一件事"


def test_summarize_profile_joins_tools():
    summary = prompts.summarize_profile(make_profile())
    assert summary["tools"] == "Read、Grep"


def test_summarize_profile_handles_missing_fields():
    profile = make_profile(capabilities=[])
    profile["boundaries"] = {}
    profile["engine"] = None
    profile["tools"] = {}
    summary = prompts.summarize_profile(profile)
    assert summary["positioning"] == "（未声明）"
    assert summary["cli"] == "（未识别）"
    assert "档 C" in summary["capabilities"]


def test_render_profile_brief_includes_capability_ids():
    brief = prompts.render_profile_brief(make_profile())
    assert "`C01`" in brief and "`C02`" in brief


# ============================== 能力点约束 ==============================

def test_capability_rule_lists_ids():
    rule = prompts.capability_rule(make_profile())
    assert "`C01`" in rule and "`C02`" in rule


def test_capability_rule_for_tier_c_forbids_field():
    rule = prompts.capability_rule(make_profile(capabilities=[]))
    assert "不要输出" in rule


def test_case_schema_includes_capability_field_when_caps_exist():
    schema = prompts.render_case_schema(make_profile())
    assert '"capability_ref"' in schema
    assert "<<" not in schema          # 占位符必须已被替换


def test_case_schema_omits_capability_field_for_tier_c():
    schema = prompts.render_case_schema(make_profile(capabilities=[]))
    assert "不要输出 capability_ref" in schema
    assert "<<" not in schema


def test_case_schema_excludes_gwt_index_by_default():
    assert "gwt_index" not in prompts.render_case_schema(make_profile())


def test_case_schema_includes_gwt_index_for_gwt_materialization():
    schema = prompts.render_case_schema(make_profile(), with_gwt_index=True)
    assert '"gwt_index"' in schema
    assert "<<" not in schema


# ============================== 禁止重复素材 ==============================

def test_exclusion_block_lists_gwt_givens():
    block = prompts.exclusion_block(make_profile(), [])
    assert "存在 java 文件" in block
    assert "验收基线" in block


def test_exclusion_block_includes_demo_code_head():
    demo = {"file_count": 1, "files": [{"file": "demo_code/a.py", "head": "pw = 1"}]}
    block = prompts.exclusion_block(make_profile(demo=demo), [])
    assert "demo_code/a.py" in block
    assert "pw = 1" in block


def test_exclusion_block_lists_existing_inputs():
    block = prompts.exclusion_block(make_profile(), ["已生成的一条 input"])
    assert "已生成的一条 input" in block


def test_exclusion_block_empty_when_nothing_to_compare():
    profile = make_profile(demo=None)
    profile["gwt_baseline"] = {"entries": []}
    assert prompts.exclusion_block(profile, []) == "（无可比对的素材）"


# ============================== 提示词产出 ==============================

def test_build_gwt_prompt_written_with_all_kept_entries(tmp_path):
    path = prompts.build_gwt_prompt(make_profile(), make_plan(), tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "#1" in text and "存在 java 文件" in text
    assert "验收基线物化" in text


def test_build_gwt_prompt_returns_none_without_kept_gwts(tmp_path):
    plan = make_plan()
    plan["gwt_kept"] = []
    assert prompts.build_gwt_prompt(make_profile(), plan, tmp_path) is None


def test_build_batch_prompts_one_per_dimension(tmp_path):
    paths = prompts.build_batch_prompts(make_profile(), make_plan(), tmp_path)
    names = sorted(p.name for p in paths)
    assert names == ["30-batch-boundary-1.prompt.md", "30-batch-functional-1.prompt.md"]


def test_build_batch_prompts_splits_by_batch_size(tmp_path):
    plan = make_plan()
    plan["quota"] = {"functional": config.BATCH_SIZE + 2}
    paths = prompts.build_batch_prompts(make_profile(), plan, tmp_path)
    assert len(paths) == 2
    assert paths[0].read_text(encoding="utf-8").count("生成 **5** 条") == 1
    assert paths[1].read_text(encoding="utf-8").count("生成 **2** 条") == 1


def test_build_batch_prompts_skips_zero_quota(tmp_path):
    plan = make_plan()
    plan["quota"] = {"functional": 0}
    assert prompts.build_batch_prompts(make_profile(), plan, tmp_path) == []


def test_batch_prompt_states_dimension_and_constraints(tmp_path):
    paths = prompts.build_batch_prompts(make_profile(), make_plan(), tmp_path)
    text = paths[0].read_text(encoding="utf-8")
    assert "functional" in text
    assert "自包含" in text          # 硬约束 #1
    assert "可判定要点" in text       # 硬约束 #2


# ============================== CLI ==============================

def test_main_requires_profile_and_plan(tmp_path, capsys):
    import pytest
    with pytest.raises(SystemExit) as exc:
        prompts.main(["--work", str(tmp_path)])
    assert exc.value.code == 1
    assert "freeze_profile.py" in capsys.readouterr().err


def test_main_writes_prompts(tmp_path):
    write_json(tmp_path / "12-agent-profile.json", make_profile())
    write_json(tmp_path / "20-plan.json", make_plan())
    assert prompts.main(["--work", str(tmp_path)]) == 0
    assert (tmp_path / "30-gwt.prompt.md").is_file()
    assert (tmp_path / "30-batch-functional-1.prompt.md").is_file()
