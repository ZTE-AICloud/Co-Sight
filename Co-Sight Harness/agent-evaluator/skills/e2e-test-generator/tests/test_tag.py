#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_tag.py — S2 归类：提示词渲染与归类答案校验。"""

import pytest

import config
import tag
from common import GoldevalError, write_json


def make_gwts(count=7):
    return [
        {"index": i, "title": f"GWT{i}", "given": f"g{i}",
         "when": f"w{i}", "then": f"t{i}"}
        for i in range(1, count + 1)
    ]


def make_profile(count=2):
    return {
        "tier": config.TIER_A,
        "gwt_baseline": {"entries": make_gwts(count)},
    }


# ============================== 提示词渲染 ==============================

def test_build_tag_prompt_lists_all_dimensions():
    text = tag.build_tag_prompt(make_profile(), "")
    for dim in config.DIMENSIONS:
        assert f"`{dim['id']}`" in text


def test_build_tag_prompt_includes_every_gwt():
    text = tag.build_tag_prompt(make_profile(3), "")
    for gwt in make_gwts(3):
        assert f"#{gwt['index']}" in text
        assert gwt["given"] in text
        assert gwt["then"] in text


def test_build_tag_prompt_embeds_user_input():
    text = tag.build_tag_prompt(make_profile(), "重点覆盖失败路径")
    assert "重点覆盖失败路径" in text


def test_build_tag_prompt_without_user_input_states_so():
    text = tag.build_tag_prompt(make_profile(), "")
    assert "（用户未提供额外要求）" in text


def test_build_tag_prompt_schema_is_valid_json_when_rendered():
    """模板里的 JSON 花括号必须被正确转义，渲染后能解析。"""
    import json
    text = tag.build_tag_prompt(make_profile(1), "要求")
    block = text.split("```json")[1].split("```")[0]
    parsed = json.loads(block)
    assert "gwt_tags" in parsed and "focus" in parsed


# ============================== 归类答案校验 ==============================

def test_parse_tag_answer_rejects_unknown_dimension():
    answer = {"gwt_tags": [{"index": 1, "dimension": "nope"}]}
    with pytest.raises(GoldevalError, match="未知维度"):
        tag.parse_tag_answer(answer, make_gwts(), "")


def test_parse_tag_answer_requires_every_gwt_tagged():
    answer = {"gwt_tags": [{"index": 1, "dimension": "functional"}]}
    with pytest.raises(GoldevalError, match="未被归类"):
        tag.parse_tag_answer(answer, make_gwts(), "")


def test_parse_tag_answer_filters_invalid_focus():
    answer = {
        "gwt_tags": [{"index": i, "dimension": "functional"} for i in range(1, 8)],
        "focus": ["safety", "bogus"],
    }
    _, focus_ids, _ = tag.parse_tag_answer(answer, make_gwts(), "")
    assert focus_ids == ["safety"]


def test_parse_tag_answer_requires_gwt_tags_array():
    with pytest.raises(GoldevalError, match="gwt_tags"):
        tag.parse_tag_answer({"focus": []}, make_gwts(), "")


def test_parse_tag_answer_returns_reason():
    answer = {
        "gwt_tags": [{"index": i, "dimension": "functional"} for i in range(1, 8)],
        "focus": [],
        "focus_reason": "用户未提重点",
    }
    _, _, reason = tag.parse_tag_answer(answer, make_gwts(), "")
    assert reason == "用户未提重点"


def test_parse_tag_answer_tolerates_non_dict_entries():
    entries = ["bad"] + [{"index": i, "dimension": "functional"}
                         for i in range(1, 8)]
    tags, _, _ = tag.parse_tag_answer({"gwt_tags": entries}, make_gwts(), "")
    assert len(tags) == 7


def test_parse_tag_answer_tolerates_non_list_focus():
    answer = {
        "gwt_tags": [{"index": i, "dimension": "functional"} for i in range(1, 8)],
        "focus": "safety",
    }
    _, focus_ids, _ = tag.parse_tag_answer(answer, make_gwts(), "")
    assert focus_ids == []


def test_parse_tag_answer_coerces_string_index():
    answer = {"gwt_tags": [{"index": str(i), "dimension": "functional"}
                           for i in range(1, 8)]}
    tags, _, _ = tag.parse_tag_answer(answer, make_gwts(), "")
    assert set(tags) == set(range(1, 8))


# ============================== CLI ==============================

def test_main_requires_profile(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        tag.main(["--work", str(tmp_path)])
    assert exc.value.code == 1
    assert "freeze_profile.py" in capsys.readouterr().err


def test_main_skips_without_gwts(tmp_path, capsys):
    """无 GWT 时不该产出提示词，也不需要 LLM 出力。"""
    write_json(tmp_path / "12-agent-profile.json", make_profile(0))
    assert tag.main(["--work", str(tmp_path)]) == 0
    assert "跳过归类" in capsys.readouterr().out
    assert not (tmp_path / "20-tag.prompt.md").exists()


def test_main_writes_prompt(tmp_path):
    write_json(tmp_path / "12-agent-profile.json", make_profile(2))
    assert tag.main(["--work", str(tmp_path), "--input", "要求"]) == 0
    text = (tmp_path / "20-tag.prompt.md").read_text(encoding="utf-8")
    assert "要求" in text and "g1" in text
