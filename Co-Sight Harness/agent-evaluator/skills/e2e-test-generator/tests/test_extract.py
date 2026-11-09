#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_extract.py — S1 识别矩阵解析与引擎结构化抽取。"""


import pytest
import yaml
from conftest import SAMPLE_AGENT

import config
import engine_probe
import extract
from common import GoldevalError


# ============================== Markdown 解析 ==============================

def test_split_sections_handles_document_without_h1():
    """无一级标题时正文挂在 None 下；find_section 不得因此崩溃。"""
    _, sections, order = extract.split_sections("## 能力边界\n内容")
    assert find_safely(sections, "能力边界") == "内容"


def find_safely(sections, keyword):
    return extract.find_section(sections, keyword)


def test_parse_key_value_table_extracts_metadata():
    text = "| 变量 | 值 |\n|---|---|\n| project_id | abc |\n| version | v2 |"
    meta = extract.parse_key_value_table(text)
    assert meta["project_id"] == "abc"
    assert meta["version"] == "v2"
    assert "变量" not in meta


def test_parse_structure_index_keeps_path_rows():
    text = "| 路径 | 作用 |\n|---|---|\n| `engine.py` | 引擎 |\n| `docs/` | 文档 |"
    index = extract.parse_structure_index(text)
    assert index["engine.py"] == "引擎"


# ============================== 验收基线（YAML） ==============================

def test_parse_acceptance_criteria_indexes_from_one():
    payload = {"acceptance_criteria": [
        {"given": "含缺陷文件", "when": "要求审查", "then": "输出结构化报告"},
        {"given": "git 仓库", "when": "未指定范围", "then": "以 diff 为对象"},
    ]}
    entries, _, warnings = extract.parse_acceptance_criteria(payload)
    assert warnings == []
    assert [e["index"] for e in entries] == [1, 2]
    assert [e["title"] for e in entries] == ["AC1", "AC2"]
    assert entries[0]["given"] == "含缺陷文件"
    assert entries[1]["then"] == "以 diff 为对象"


def test_parse_acceptance_criteria_keeps_multiline_then():
    payload = {"acceptance_criteria": [
        {"given": "g", "when": "w", "then": "- 要点一\n- 要点二"},
    ]}
    entries, _, _ = extract.parse_acceptance_criteria(payload)
    assert entries[0]["then"] == "- 要点一\n- 要点二"


def test_parse_acceptance_criteria_skips_entries_missing_fields():
    payload = {"acceptance_criteria": [
        {"given": "g1", "when": "w1", "then": "t1"},
        {"given": "g2", "when": "w2"},                 # 缺 then
        {"when": "w3", "then": "t3"},                  # 缺 given
        "不是映射",
    ]}
    entries, _, warnings = extract.parse_acceptance_criteria(payload)
    assert [e["index"] for e in entries] == [1]
    assert any("第 2 条缺少 then" in w for w in warnings)
    assert any("第 3 条缺少 given" in w for w in warnings)
    assert any("第 4 条不是映射" in w for w in warnings)


def test_parse_acceptance_criteria_without_field_is_empty():
    entries, nonfunctional, warnings = extract.parse_acceptance_criteria({})
    assert entries == [] and nonfunctional == "" and warnings == []


def test_parse_acceptance_criteria_rejects_non_list():
    entries, _, warnings = extract.parse_acceptance_criteria(
        {"acceptance_criteria": {"given": "g"}}
    )
    assert entries == []
    assert any("不是数组" in w for w in warnings)


def test_build_nonfunctional_maps_quality_fields():
    text = extract.build_nonfunctional({
        "performance": "10 个文件内一次审完",
        "security": "只读",
        "availability": "无 git 也能跑",
    })
    assert "performance: 10 个文件内一次审完" in text
    assert "security: 只读" in text
    assert "availability: 无 git 也能跑" in text


def test_build_nonfunctional_tolerates_missing_quality():
    assert extract.build_nonfunctional(None) == ""
    assert extract.build_nonfunctional({"performance": ""}) == ""


def _write_requirements(scan_root, agent_name, entries, quality=None):
    path = (scan_root / ".agent-genesis" / "work" / agent_name
            / "agent-creation" / "clarified-agent-requirements.yaml")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"acceptance_criteria": entries}
    if quality is not None:
        payload["quality"] = quality
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    return path


def test_scan_pass_criteria_reads_yaml_baseline(tmp_path):
    agent = tmp_path / "my-agent"
    agent.mkdir()
    _write_requirements(agent, "my-agent", [
        {"given": "含缺陷文件", "when": "要求审查", "then": "结构化报告"},
    ])
    criteria, warnings = extract.scan_pass_criteria(agent, agent)
    assert warnings == []
    assert criteria["gwt_count"] == 1
    assert criteria["file"].endswith("clarified-agent-requirements.yaml")
    assert "my-agent" in criteria["file"]


def test_scan_pass_criteria_without_genesis_returns_none(tmp_path):
    criteria, warnings = extract.scan_pass_criteria(tmp_path, tmp_path)
    assert criteria is None
    assert any("未找到验收契约" in w for w in warnings)


def test_scan_pass_criteria_reports_empty_field(tmp_path):
    agent = tmp_path / "my-agent"
    agent.mkdir()
    _write_requirements(agent, "my-agent", [])
    criteria, warnings = extract.scan_pass_criteria(agent, agent)
    assert criteria["gwt_count"] == 0
    assert criteria["file"].endswith("clarified-agent-requirements.yaml")
    assert warnings == []


def test_scan_pass_criteria_reports_bad_yaml(tmp_path):
    agent = tmp_path / "my-agent"
    path = (agent / ".agent-genesis" / "work" / "my-agent" / "agent-creation"
            / "clarified-agent-requirements.yaml")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("acceptance_criteria: [\n", encoding="utf-8")
    criteria, warnings = extract.scan_pass_criteria(agent, agent)
    assert criteria is None
    assert any("解析失败" in w for w in warnings)


def test_find_requirements_matches_agent_name_when_multiple(tmp_path):
    agent = tmp_path / "b-agent"
    agent.mkdir()
    _write_requirements(tmp_path, "a-agent", [{"given": "a", "when": "a", "then": "a"}])
    wanted = _write_requirements(
        tmp_path, "b-agent", [{"given": "b", "when": "b", "then": "b"}]
    )
    path, _ = extract.find_requirements_file(tmp_path, agent)
    assert path == wanted


def test_find_requirements_ambiguous_without_match_raises(tmp_path):
    agent = tmp_path / "c-agent"
    agent.mkdir()
    _write_requirements(tmp_path, "a-agent", [{"given": "a", "when": "a", "then": "a"}])
    _write_requirements(tmp_path, "b-agent", [{"given": "b", "when": "b", "then": "b"}])
    with pytest.raises(GoldevalError, match="多份"):
        extract.find_requirements_file(tmp_path, agent)


def test_find_requirements_does_not_walk_up(tmp_path):
    """契约只在 --agent 之下找：搜外层祖先目录不算数。"""
    outer = tmp_path / "workspace"
    agent = outer / "output" / "agents" / "my-agent" / "v1"
    agent.mkdir(parents=True)
    _write_requirements(outer, "my-agent", [{"given": "g", "when": "w", "then": "t"}])
    path, _ = extract.find_requirements_file(agent, agent)
    assert path is None
    criteria, warnings = extract.scan_pass_criteria(agent, agent)
    assert criteria is None
    assert any("未找到验收契约" in w for w in warnings)


def test_parse_frontmatter_splits_yaml_and_body():
    text = '---\nname: x\ndescription: "d"\n---\n\n# 正文\n'
    front, body = extract.parse_frontmatter(text)
    assert front["name"] == "x"
    assert body.strip().startswith("# 正文")


def test_parse_frontmatter_without_delimiters_is_noop():
    front, body = extract.parse_frontmatter("# 正文")
    assert front == {} and body == "# 正文"


def test_parse_frontmatter_ignores_horizontal_rule():
    """`---` 也是 Markdown 水平分隔线，不能当成 frontmatter 把正文吞掉。"""
    text = "---\n\n# 标题\n\n## 能力边界\n\n内容\n"
    front, body = extract.parse_frontmatter(text)
    assert front == {}
    assert body == text


def test_parse_frontmatter_ignores_non_mapping_yaml():
    """块内不是映射（纯文本/列表）时同样不剥离。"""
    text = "---\n只是一段普通文字\n---\n\n# 标题\n"
    front, body = extract.parse_frontmatter(text)
    assert front == {}
    assert body == text


def test_parse_frontmatter_keeps_rest_of_document():
    """真 frontmatter 之后的正文，连同其后的 `---` 分隔线都要保留。"""
    text = "---\nproject_id: calc\n---\n\n# 标题\n\n---\n\n## 能力边界\n\n内容\n"
    front, body = extract.parse_frontmatter(text)
    assert front["project_id"] == "calc"
    assert body.lstrip().startswith("# 标题")
    assert "## 能力边界" in body


def test_merge_anchor_meta_reads_frontmatter():
    """CLAUDE.md 把元数据写在 YAML frontmatter 里，不能只认正文表格。"""
    meta = extract.merge_anchor_meta({}, {"project_id": "calculator",
                                          "version": "1.0.0"})
    assert meta["project_id"] == "calculator"
    assert meta["version"] == "1.0.0"


def test_merge_anchor_meta_frontmatter_wins_over_table():
    meta = extract.merge_anchor_meta({"project_id": "from-table"},
                                     {"project_id": "from-yaml"})
    assert meta["project_id"] == "from-yaml"


def test_merge_anchor_meta_skips_non_scalar_and_private_keys():
    """list/dict（tags、skills）不是元数据；下划线私有键一并跳过。"""
    meta = extract.merge_anchor_meta(
        {"keep": "t"},
        {"tags": ["a"], "skills": [{"n": 1}], "_raw": "x", "project_name": "计算器"},
    )
    assert meta == {"keep": "t", "project_name": "计算器"}


def test_merge_anchor_meta_degrades_to_table_only():
    assert extract.merge_anchor_meta({"project_id": "t"}, {}) == {"project_id": "t"}
    assert extract.merge_anchor_meta(None, None) == {}


def test_scan_manifest_reads_claude_frontmatter(tmp_path):
    """回归：CLAUDE.md 的 frontmatter 元数据必须进 meta，且不污染章节切分。"""
    (tmp_path / "CLAUDE.md").write_text(
        "---\nproject_id: calculator\nproject_name: 计算器智能体\n"
        "version: 1.0.0\ntags: [a, b]\n---\n\n# 计算器智能体\n\n## 能力边界\n\n只做四则运算。\n",
        encoding="utf-8",
    )
    manifest = extract.scan_manifest(tmp_path, config.flavor_of("claude"))
    assert manifest["meta"]["project_id"] == "calculator"
    assert manifest["meta"]["project_name"] == "计算器智能体"
    assert manifest["meta"]["version"] == "1.0.0"
    assert "tags" not in manifest["meta"]
    assert manifest["title"] == "计算器智能体"
    assert manifest["capability_boundary"] == "只做四则运算。"


def test_scan_manifest_keeps_table_metadata_without_frontmatter(tmp_path):
    """回归：COSIGHT 式正文表格元数据不受影响。"""
    (tmp_path / "COSIGHT.md").write_text(
        "# 标题\n\n| 变量 | 值 |\n|---|---|\n| project_id | plaintext-check |\n",
        encoding="utf-8",
    )
    manifest = extract.scan_manifest(tmp_path, config.flavor_of("cosight"))
    assert manifest["meta"]["project_id"] == "plaintext-check"
    assert "变量" not in manifest["meta"]


def test_scan_manifest_survives_leading_horizontal_rule(tmp_path):
    """回归：锚点以 `---` 分隔线开头时，标题与章节不得被吞掉。"""
    (tmp_path / "CLAUDE.md").write_text(
        "---\n\n# 计算器智能体\n\n## 能力边界\n\n只做四则运算。\n",
        encoding="utf-8",
    )
    manifest = extract.scan_manifest(tmp_path, config.flavor_of("claude"))
    assert manifest["title"] == "计算器智能体"
    assert manifest["capability_boundary"] == "只做四则运算。"
    assert manifest["meta"] == {}


# ============================== 引擎抽取（单测） ==============================

PY_ENGINE = '''
import re
import sys
import argparse

_RULE_SPECS = [
    ("R01", re.compile(r"pw\\\\s*="), 2, "P1", "英文键赋值"),
    ("R02", re.compile(r"pwd\\\\s*="), 2, "P0", "配置键赋值"),
]
RULES = [{"id": r, "regex": c, "base": s, "description": d}
         for (r, c, g, s, d) in _RULE_SPECS]

_X03_LITERALS = {"changeme", "your_password"}

SEVERITY_ORDER = {"P0": 0, "P1": 1}

def build_parser():
    p = argparse.ArgumentParser()
    p.add_argument("target")
    p.add_argument("-o", "--output")
    p.add_argument("--self-test", action="store_true")
    return p
'''


def test_probe_python_harvests_rule_descriptions(tmp_path):
    path = tmp_path / "engine.py"
    path.write_text(PY_ENGINE, encoding="utf-8")
    result = engine_probe.probe_python(path, path.read_text(encoding="utf-8"))

    assert "英文键赋值" in " ".join(result["declarations"]["RULES"])
    assert "配置键赋值" in " ".join(result["declarations"]["RULES"])


def test_probe_python_follows_comprehension_source(tmp_path):
    """RULES 由 _RULE_SPECS 推导而来，应能回溯到真正的数据表。"""
    path = tmp_path / "engine.py"
    path.write_text(PY_ENGINE, encoding="utf-8")
    result = engine_probe.probe_python(path, path.read_text(encoding="utf-8"))
    assert result["references"]["RULES"] == "_RULE_SPECS"


def test_probe_python_finds_private_prefixed_declarations(tmp_path):
    """_X03_LITERALS 这类下划线前缀的排除表也要抽到。"""
    path = tmp_path / "engine.py"
    path.write_text(PY_ENGINE, encoding="utf-8")
    result = engine_probe.probe_python(path, path.read_text(encoding="utf-8"))
    assert "_X03_LITERALS" in result["declarations"]


def test_probe_python_collects_cli_args_from_function_body(tmp_path):
    path = tmp_path / "engine.py"
    path.write_text(PY_ENGINE, encoding="utf-8")
    result = engine_probe.probe_python(path, path.read_text(encoding="utf-8"))
    assert set(result["cli_args"]) == {"target", "-o", "--output", "--self-test"}


def test_probe_python_parses_exit_code_contract_from_docstring(tmp_path):
    source = '"""\n退出码契约：\n    0 = 扫描完成；1 = 自检失败；2 = 参数错误。\n"""\nimport sys\n'
    path = tmp_path / "e.py"
    path.write_text(source, encoding="utf-8")
    result = engine_probe.probe_python(path, source)
    assert result["exit_codes"] == [0, 1, 2]
    assert "扫描完成" in result["exit_code_contract"]["0"]


def test_probe_python_ignores_local_variables(tmp_path):
    """函数内的局部变量同名不得被当成模块级常量表。"""
    source = "def f():\n    RULES = [1, 2, 3]\n    return RULES\n"
    path = tmp_path / "e.py"
    path.write_text(source, encoding="utf-8")
    result = engine_probe.probe_python(path, source)
    assert "RULES" not in result["declarations"]


def test_probe_python_returns_none_on_syntax_error(tmp_path):
    path = tmp_path / "bad.py"
    path.write_text("def broken(:\n", encoding="utf-8")
    assert engine_probe.probe_python(path, "def broken(:\n") is None


def test_harvest_strings_discards_regex_literals():
    import ast
    node = ast.parse('X = [("R01", re.compile(r"a\\\\s+b"), "描述文字足够长")]').body[0].value
    found = engine_probe._harvest_strings(node)
    assert any("描述文字足够长" == f for f in found)
    assert not any("\\\\s" in f for f in found)


def test_probe_generic_fallback_for_non_python():
    source = 'const RULES = [\n  {"id": "R1"}\n];\n'
    result = engine_probe.probe_generic(source)
    assert "RULES" in result["declarations"]


# ============================== 样本 Agent 集成 ==============================

pytestmark_sample = pytest.mark.skipif(
    not SAMPLE_AGENT.is_dir(), reason="样本 agent 不存在"
)


@pytestmark_sample
def test_sample_agent_hits_tier_a():
    profile_input = extract.build_profile_input(SAMPLE_AGENT, "cosight")
    assert profile_input["tier_hint"] == config.TIER_A
    assert profile_input["pass_criteria"]["gwt_count"] == 7


@pytestmark_sample
def test_sample_agent_skills_frontmatter_parsed():
    profile_input = extract.build_profile_input(SAMPLE_AGENT, "cosight")
    skill = profile_input["skills"][0]
    assert skill["frontmatter"]["name"] == "plaintext-password-check"
    assert "Use when" in skill["frontmatter"]["description"]


@pytestmark_sample
def test_sample_agent_hooks_excluded():
    profile_input = extract.build_profile_input(SAMPLE_AGENT, "cosight")
    excluded = {item["path"] for item in profile_input["excluded"]}
    assert ".cosight/hooks/hooks.json" in excluded


@pytestmark_sample
def test_sample_agent_engine_probe_populated():
    profile_input = extract.build_profile_input(SAMPLE_AGENT, "cosight")
    engine = profile_input["engine"]
    assert engine["source_file"] == "plaintext_password_checker.py"
    assert set(engine["exit_codes"]) == {0, 1, 2}
    assert "--self-test" in engine["cli_args"]
    assert "_X03_LITERALS" in engine["declarations"]


@pytestmark_sample
def test_sample_agent_cosight_metadata():
    profile_input = extract.build_profile_input(SAMPLE_AGENT, "cosight")
    cosight = profile_input["manifest"]
    assert cosight["title"].startswith("COSIGHT.md")
    assert cosight["meta"]["project_id"] == "plaintext-password-checker"
