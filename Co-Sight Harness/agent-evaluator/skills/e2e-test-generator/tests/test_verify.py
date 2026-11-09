#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_verify.py — S4 硬校验、去重矩阵、缺口计算。"""

import config
import verify
from common import containment, jaccard, normalize_text


# ============================== 硬校验 ==============================

def test_validate_case_accepts_wellformed():
    case = {"input": "对目录执行检查", "expected_output": ["报告命中该行并标记 P1"]}
    assert verify.validate_case(case) == []


def test_validate_case_rejects_short_input():
    errors = verify.validate_case({"input": "ab", "expected_output": ["够长的要点内容"]})
    assert any("input 短于" in e for e in errors)


def test_validate_case_rejects_empty_expected():
    errors = verify.validate_case({"input": "对目录执行检查", "expected_output": []})
    assert any("非空数组" in e for e in errors)


def test_validate_case_rejects_short_expected_item():
    errors = verify.validate_case({"input": "对目录执行检查", "expected_output": ["太短"]})
    assert any("短于" in e for e in errors)


def test_validate_case_rejects_non_string_expected_item():
    errors = verify.validate_case({"input": "对目录执行检查", "expected_output": [12345678]})
    assert any("为空" in e for e in errors)


# ============================== capability_ref 条件校验 ==============================

def test_capability_ref_must_be_known_when_present():
    profile = {"capabilities": [{"id": "C01", "name": "x", "desc": ""}]}
    collected = [{
        "case": {"input": "对目录执行检查", "expected_output": ["报告按预期产出可判定结果"],
                 "capability_ref": "C99"},
        "dimension": "functional", "source": "llm", "source_ref": "a.json",
    }]
    _, rejected = verify.validate_records(collected, profile)
    assert len(rejected) == 1
    assert "不在能力点集合内" in rejected[0]["errors"][0]


def test_capability_ref_absent_is_allowed_for_tier_c():
    """档 C 省略 capability_ref，不应被驳回。"""
    profile = {"capabilities": []}
    collected = [{
        "case": {"input": "对目录执行检查", "expected_output": ["报告按预期产出可判定结果"]},
        "dimension": "functional", "source": "llm", "source_ref": "a.json",
    }]
    passed, rejected = verify.validate_records(collected, profile)
    assert len(passed) == 1 and rejected == []


# ============================== GWT 归属 ==============================

def make_kept():
    return [
        {"index": 1, "dimension": "functional"},
        {"index": 2, "dimension": "functional"},
        {"index": 3, "dimension": "boundary"},
        {"index": 4, "dimension": "instruction"},
    ]


def test_gwt_index_attributes_each_case_to_its_own_gwt():
    """一条 GWT 拆成多条用例时，每条都应按编号落到自己的维度。"""
    kept = make_kept()
    index, dimension, source_ref, error = verify.resolve_gwt_attribution(
        {"gwt_index": 4}, 0, kept, []
    )
    assert (index, dimension, source_ref, error) == (
        4, "instruction", "clarified-agent-requirements.yaml#4", None
    )


def test_split_gwt_cases_share_index_but_keep_position_independent():
    """同一 GWT 的两条用例都填同一个 gwt_index，不按序位错配到下一个 GWT。"""
    kept = make_kept()
    first = verify.resolve_gwt_attribution({"gwt_index": 4}, 0, kept, [])
    second = verify.resolve_gwt_attribution({"gwt_index": 4}, 1, kept, [])
    assert first[1] == second[1] == "instruction"


def test_missing_gwt_index_falls_back_to_position():
    kept = make_kept()
    index, dimension, source_ref, error = verify.resolve_gwt_attribution({}, 2, kept, [])
    assert (index, dimension, source_ref, error) == (
        3, "boundary", "clarified-agent-requirements.yaml#3", None
    )


def test_position_beyond_kept_without_gwt_index_is_rejected():
    """旧版会静默归到第一个维度；现在必须报错，不得产生错误归因。"""
    kept = make_kept()
    index, dimension, source_ref, error = verify.resolve_gwt_attribution({}, 4, kept, [])
    assert dimension is None
    assert index is None
    assert source_ref == verify.UNATTRIBUTED_REF
    assert "无法确定归属" in error


def test_gwt_index_of_dropped_gwt_is_rejected():
    dropped = [{"index": 9, "dimension": "safety"}]
    index, dimension, _, error = verify.resolve_gwt_attribution(
        {"gwt_index": 9}, 0, make_kept(), dropped
    )
    assert index == 9 and dimension is None
    assert "已被计划截断丢弃" in error


def test_unknown_gwt_index_is_rejected():
    _, dimension, _, error = verify.resolve_gwt_attribution(
        {"gwt_index": 99}, 0, make_kept(), []
    )
    assert dimension is None
    assert "不在验收基线中" in error


def test_non_integer_gwt_index_is_rejected():
    _, dimension, _, error = verify.resolve_gwt_attribution(
        {"gwt_index": "C01"}, 0, make_kept(), []
    )
    assert dimension is None
    assert "不是整数" in error


def test_attribution_error_rejects_the_case():
    profile = {"capabilities": []}
    collected = [{
        "case": {"input": "对目录执行检查", "expected_output": ["报告按预期产出可判定结果"]},
        "dimension": None, "source": config.SOURCE_GWT,
        "source_ref": verify.UNATTRIBUTED_REF, "gwt_index": None,
        "attribution_error": "缺少 gwt_index，且答案序位超出保留的 GWT 条数，无法确定归属",
    }]
    passed, rejected = verify.validate_records(collected, profile)
    assert passed == []
    assert len(rejected) == 1
    assert "无法确定归属" in rejected[0]["errors"][0]


# ============================== 去重矩阵 ==============================

def make_profile():
    return {
        "capabilities": [{"id": "C01", "name": "x", "desc": ""}],
        "gwt_baseline": {"entries": [
            {"index": 3, "given": "代码中密码取值均为 ${DB_PASSWORD} 环境变量引用或 changeme 占位"}
        ]},
        "demo_code": {"files": [
            {"file": "demo_code/config.py", "head": 'password = "SuperSecret123"'}
        ]},
    }


def test_gwt_case_is_exempt_from_exclusion_corpus():
    """GWT 派生用例与其 Given 必然相似，必须豁免排除集。"""
    given = "代码中密码取值均为 ${DB_PASSWORD} 环境变量引用或 changeme 占位"
    collected = [{
        "case": {"input": f"对满足以下前置条件的目录执行检查：{given}",
                 "precondition": given,
                 "expected_output": ["报告无任何命中条目并说明排除规则"]},
        "dimension": "safety", "source": config.SOURCE_GWT, "source_ref": "gwt",
    }]
    kept, dropped = verify.dedup_cases(collected, make_profile())
    assert len(kept) == 1 and dropped == []


def test_llm_case_matching_gwt_given_is_dropped():
    given = "代码中密码取值均为 ${DB_PASSWORD} 环境变量引用或 changeme 占位"
    collected = [{
        "case": {"input": f"对满足以下前置条件的目录执行检查：{given}",
                 "precondition": given,
                 "expected_output": ["报告无任何命中条目并说明排除规则"]},
        "dimension": "safety", "source": config.SOURCE_LLM, "source_ref": "b.json",
    }]
    _, dropped = verify.dedup_cases(collected, make_profile())
    assert len(dropped) == 1
    assert "排除集" in dropped[0]["reason"]


def test_llm_case_matching_demo_code_is_dropped():
    collected = [{
        "case": {"input": 'password = "SuperSecret123"',
                 "expected_output": ["该行被标记为 P1 且证据脱敏"]},
        "dimension": "functional", "source": config.SOURCE_LLM, "source_ref": "b.json",
    }]
    _, dropped = verify.dedup_cases(collected, make_profile())
    assert len(dropped) == 1


def test_duplicate_cases_drop_the_second():
    case = {"input": "对 ./sample 目录执行明文密码检查",
            "expected_output": ["报告含概要统计与分级分布"]}
    collected = [
        {"case": dict(case), "dimension": "functional",
         "source": config.SOURCE_LLM, "source_ref": "a.json"},
        {"case": dict(case), "dimension": "functional",
         "source": config.SOURCE_LLM, "source_ref": "b.json"},
    ]
    kept, dropped = verify.dedup_cases(collected, {"capabilities": [],
                                                   "gwt_baseline": {"entries": []}})
    assert len(kept) == 1 and len(dropped) == 1


def test_distinct_cases_both_survive():
    collected = [
        {"case": {"input": "对 ./sample 目录执行明文密码检查",
                  "expected_output": ["报告含概要统计与分级分布"]},
         "dimension": "functional", "source": config.SOURCE_LLM, "source_ref": "a.json"},
        {"case": {"input": "对 /nonexistent 路径执行检查并观察退出码",
                  "expected_output": ["明确报错提示路径有误且不生成报告"]},
         "dimension": "failure", "source": config.SOURCE_LLM, "source_ref": "b.json"},
    ]
    kept, dropped = verify.dedup_cases(collected, {"capabilities": [],
                                                   "gwt_baseline": {"entries": []}})
    assert len(kept) == 2 and dropped == []


# ============================== 缺口计算 ==============================

def test_compute_gaps_counts_only_generated_cases():
    """quota 语义是"需生成条数"，GWT 派生记录不得填补生成缺口。"""
    plan = {"quota": {"failure": 1, "safety": 1}}
    records = [
        {"dimension": "failure", "source": config.SOURCE_GWT},
        {"dimension": "safety", "source": config.SOURCE_LLM},
    ]
    gaps, actual = verify.compute_gaps(records, plan)
    assert gaps == {"failure": 1}
    assert actual["failure"] == 1


def test_compute_gaps_empty_when_quota_met():
    plan = {"quota": {"safety": 1}}
    records = [{"dimension": "safety", "source": config.SOURCE_LLM}]
    gaps, _ = verify.compute_gaps(records, plan)
    assert gaps == {}


# ============================== 条数上限 ==============================

def _item(dimension, source, source_ref, gwt_index=None):
    return {
        "case": {"input": "x", "expected_output": ["y"]},
        "dimension": dimension, "source": source, "source_ref": source_ref,
        "gwt_index": gwt_index,
    }


def test_cap_records_noop_when_within_limit():
    kept = [_item("functional", config.SOURCE_GWT, "clarified-agent-requirements.yaml#1", 1)]
    capped, over = verify.cap_records(kept, {"count": 5})
    assert capped == kept and over == []


def test_cap_records_drops_split_duplicate_first():
    """拆分用例先于主用例和 LLM 用例被裁掉。"""
    kept = [
        _item("functional", config.SOURCE_GWT, "clarified-agent-requirements.yaml#1", 1),
        _item("boundary", config.SOURCE_GWT, "clarified-agent-requirements.yaml#2", 2),
        _item("boundary", config.SOURCE_GWT, "clarified-agent-requirements.yaml#2", 2),
        _item("safety", config.SOURCE_LLM, "30-batch-safety-1.answer.json"),
    ]
    capped, over = verify.cap_records(kept, {"count": 3})
    assert len(capped) == 3
    assert [i["source_ref"] for i in over] == ["clarified-agent-requirements.yaml#2"]
    assert over[0]["reason"] == "超出 --count 上限 3 条"


def test_cap_records_keeps_llm_before_split():
    """预算不足以同时容纳 LLM 用例与拆分用例时，先保 LLM。"""
    kept = [
        _item("functional", config.SOURCE_GWT, "clarified-agent-requirements.yaml#1", 1),
        _item("functional", config.SOURCE_GWT, "clarified-agent-requirements.yaml#1", 1),
        _item("safety", config.SOURCE_LLM, "30-batch-safety-1.answer.json"),
    ]
    capped, over = verify.cap_records(kept, {"count": 2})
    assert [i["source"] for i in capped] == [config.SOURCE_GWT, config.SOURCE_LLM]
    assert len(over) == 1


def test_cap_records_preserves_original_order():
    kept = [
        _item("functional", config.SOURCE_GWT, "clarified-agent-requirements.yaml#1", 1),
        _item("safety", config.SOURCE_LLM, "30-batch-safety-1.answer.json"),
        _item("boundary", config.SOURCE_GWT, "clarified-agent-requirements.yaml#2", 2),
    ]
    capped, _ = verify.cap_records(kept, {"count": 3})
    assert capped == kept


def test_cap_records_caps_llm_overshoot():
    kept = [_item("safety", config.SOURCE_LLM, f"r{i}") for i in range(5)]
    capped, over = verify.cap_records(kept, {"count": 2})
    assert len(capped) == 2 and len(over) == 3


# ============================== data_id 分配 ==============================

def test_assign_ids_sequences_per_dimension():
    kept = [
        {"case": {"input": "a", "expected_output": ["x"]},
         "dimension": "functional", "source": "gwt", "source_ref": "r1"},
        {"case": {"input": "b", "expected_output": ["y"]},
         "dimension": "functional", "source": "llm", "source_ref": "r2"},
        {"case": {"input": "c", "expected_output": ["z"]},
         "dimension": "safety", "source": "llm", "source_ref": "r3"},
    ]
    records = verify.assign_ids(kept, "my-agent")
    assert [r["data_id"] for r in records] == [
        "my-agent_functional_001", "my-agent_functional_002", "my-agent_safety_001",
    ]


def test_assign_ids_omits_capability_ref_when_absent():
    kept = [{"case": {"input": "a", "expected_output": ["x"]},
             "dimension": "functional", "source": "llm", "source_ref": "r"}]
    record = verify.assign_ids(kept, "s")[0]
    assert "capability_ref" not in record
    assert record["kind"] == config.KIND_SEED


def test_assign_ids_keeps_capability_ref_when_present():
    kept = [{"case": {"input": "a", "expected_output": ["x"], "capability_ref": "C01"},
             "dimension": "functional", "source": "llm", "source_ref": "r"}]
    assert verify.assign_ids(kept, "s")[0]["capability_ref"] == "C01"


# ============================== 相似度工具 ==============================

def test_jaccard_identical_texts_is_one():
    assert jaccard("对目录执行明文密码检查", "对目录执行明文密码检查") == 1.0


def test_jaccard_unrelated_texts_is_low():
    assert jaccard("对目录执行明文密码检查", "报告含概要统计与分级分布") < 0.3


def test_jaccard_empty_text_is_zero():
    assert jaccard("", "任意内容") == 0.0


def test_normalize_collapses_punctuation_and_case():
    assert normalize_text("Hello, World!") == normalize_text("hello   world")


# ============================== 包含度（排除集判定） ==============================

def test_containment_is_high_when_case_embeds_source():
    """用例完整嵌入素材时，包含度必须接近 1（Jaccard 会漏判到 0.51）。"""
    given = "代码中密码取值均为 ${DB_PASSWORD} 环境变量引用或 changeme 占位"
    case = (f"对满足以下前置条件的目录执行检查：{given}\n{given}\n"
            "报告无任何命中条目并说明排除规则")
    assert containment(case, given) > 0.85
    assert jaccard(case, given) < 0.85   # 对照：Jaccard 会漏判


def test_containment_low_for_unrelated_text():
    assert containment("对目录执行明文密码检查", "报告含概要统计与分级分布") < 0.3


def test_containment_empty_text_is_zero():
    assert containment("", "任意内容") == 0.0
