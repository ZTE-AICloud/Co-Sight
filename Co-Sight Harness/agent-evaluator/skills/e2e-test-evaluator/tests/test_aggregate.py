#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_aggregate.py — 加权算术、阈值判定、无效样本隔离、report.md 渲染。

含一条**反向守卫**：解析 references/runtime-rubric.md，断言 config.py 里的权重与
阈值跟散文写的一致。改了 rubric 却忘了改 config，这里会红。
"""

import re
from pathlib import Path

import pytest

import aggregate
import config
from conftest import answer_payload, seed_record


def records_with(*specs):
    """specs: (data_id, run_valid, scores, verdicts, dimension) → 装配好的记录列表。"""
    records = []
    for spec in specs:
        data_id = spec["data_id"]
        record = seed_record(data_id=data_id, dimension=spec.get("dimension", "functional"),
                             expected_output=["a", "b", "c", "d", "e"])
        answer = answer_payload(data_id, ["a", "b", "c", "d", "e"],
                                run_valid=spec.get("run_valid", True),
                                scores=spec.get("scores"),
                                verdicts=spec.get("verdicts"))
        record[config.EVAL_KEY] = aggregate.build_eval(answer, ["a", "b", "c", "d", "e"])
        records.append(record)
    return records


SCORES = lambda c, co, f, a: {  # noqa: E731
    "correctness": c, "completeness": co, "format_compliance": f, "actionability": a}


# ============================== 反向守卫：rubric vs config ==============================

def test_rubric_copy_is_in_skill():
    import render
    assert render.RUBRIC_PATH == (Path(__file__).resolve().parent.parent
                                  / "references" / "runtime-rubric.md")


def test_rubric_weights_match_config():
    """rubric 是散文（"权重 40%"），config 是算术的唯一真相源——两者必须一致。"""
    text = (Path(__file__).resolve().parent.parent
            / "references" / "runtime-rubric.md").read_text(encoding="utf-8")

    parsed = {}
    for dimension, percent in re.findall(r"^## (\w+) — .*?\(权重 (\d+)%\)", text, re.M):
        parsed[dimension] = int(percent) / 100
    assert parsed, "没能从 rubric 里解析出权重——正则与文档格式已脱节"

    for dimension, weight in parsed.items():
        assert config.DIMENSION_WEIGHTS[dimension] == pytest.approx(weight), (
            f"{dimension} 的权重在 rubric 与 config 里不一致："
            f"rubric {weight}，config {config.DIMENSION_WEIGHTS[dimension]}")


def test_rubric_thresholds_match_config():
    text = (Path(__file__).resolve().parent.parent
            / "references" / "runtime-rubric.md").read_text(encoding="utf-8")
    body = text.split("## 通过阈值", 1)[1]

    assert f"| 加权总分 | ≥ {config.THRESHOLD_WEIGHTED} |" in body
    assert f"| correctness (单维度) | ≥ {config.THRESHOLD_CORRECTNESS} |" in body
    assert f"| completeness (单维度) | ≥ {config.THRESHOLD_COMPLETENESS} |" in body


def test_weights_sum_to_one():
    assert sum(config.DIMENSION_WEIGHTS.values()) == pytest.approx(1.0)


# ============================== 加权与阈值 ==============================

def test_weighted_score_formula():
    scores = SCORES(5, 5, 5, 5)
    assert aggregate.weighted_score(scores) == 5.0
    scores = SCORES(1, 1, 1, 1)
    assert aggregate.weighted_score(scores) == 1.0


def test_weighted_score_matches_rubric_example():
    """rubric 里写的 correctness×0.4 + completeness×0.3 + format×0.15 + action×0.15。"""
    assert aggregate.weighted_score(SCORES(4, 3, 5, 2)) == pytest.approx(
        4 * 0.40 + 3 * 0.30 + 5 * 0.15 + 2 * 0.15)


@pytest.mark.parametrize("scores,expected", [
    (SCORES(5, 5, 5, 5), True),
    (SCORES(4, 4, 3, 3), True),    # 加权 3.70
    (SCORES(5, 1, 5, 5), False),   # completeness 1 < 3.0
    (SCORES(1, 5, 5, 5), False),   # correctness 1 < 3.0
    (SCORES(3, 3, 5, 5), True),    # 两个单维度恰好卡在 3.0 = 达标，加权 3.60 也过线
])
def test_thresholds(scores, expected):
    weighted = aggregate.weighted_score(scores)
    assert aggregate.is_passed(scores, weighted) is expected


def test_score_of_three_three_is_boundary_pass():
    """correctness/completeness 恰好 3.0 是 ≥ 阈值，应判通过（加权 3.30 < 3.5 除外）。"""
    scores = SCORES(3, 3, 5, 5)
    weighted = aggregate.weighted_score(scores)   # 3*0.4+3*0.3+5*0.15+5*0.15 = 3.6
    assert weighted == pytest.approx(3.6)
    assert aggregate.is_passed(scores, weighted) is True


def test_weighted_just_below_threshold_fails():
    scores = SCORES(4, 4, 1, 1)
    weighted = aggregate.weighted_score(scores)   # 1.6+1.2+0.15+0.15 = 3.1
    assert weighted < config.THRESHOLD_WEIGHTED
    assert aggregate.is_passed(scores, weighted) is False


# ============================== completeness 档位与矛盾提示 ==============================

@pytest.mark.parametrize("ratio,band", [
    (1.0, 5), (0.8, 4), (0.6, 3), (0.3, 2), (0.0, 1),
])
def test_band_of(ratio, band):
    assert aggregate.band_of(ratio) == band


def test_unverifiable_excluded_from_ratio_denominator():
    items = [{"verdict": "hit"}, {"verdict": "unverifiable"}, {"verdict": "miss"}]
    assert aggregate.hit_ratio(items) == (1, 2)


def test_no_inconsistency_when_ratio_matches_score():
    items = [{"verdict": "hit"}] * 5
    assert aggregate.inconsistency_note(items, 5) == ""


def test_inconsistency_flagged_when_obviously_contradictory():
    items = [{"verdict": "miss"}] * 5
    note = aggregate.inconsistency_note(items, 5)
    assert note and "0/5" in note and "5" in note


def test_small_deviation_not_flagged():
    """"命中率档位"与自报分差 1 分内不算矛盾——rubric 还有定性判据。"""
    items = [{"verdict": "hit"}] * 4 + [{"verdict": "miss"}]
    assert aggregate.inconsistency_note(items, 5) == ""


def test_all_unverifiable_produces_no_note():
    items = [{"verdict": "unverifiable"}] * 5
    assert aggregate.inconsistency_note(items, 1) == ""


def test_inconsistency_is_recorded_not_applied():
    """只提示、不覆盖：裁判给的分原样保留。"""
    record = records_with({"data_id": "a", "verdicts": ["miss"] * 5,
                           "scores": SCORES(4, 5, 4, 4)})[0]
    assert record[config.EVAL_KEY]["completeness"] == 5
    assert config.EVAL_INCONSISTENT in record[config.EVAL_KEY]


# ============================== 无效样本隔离 ==============================

def test_invalid_samples_excluded_from_every_average():
    records = records_with(
        {"data_id": "good", "scores": SCORES(5, 5, 5, 5)},
        {"data_id": "bad-env", "run_valid": False, "scores": SCORES(1, 1, 1, 1)},
    )
    summary = aggregate.summarize(records)
    assert len(summary["valid"]) == 1
    assert len(summary["invalid"]) == 1
    assert summary["weighted_mean"] == 5.0, "无效样本不得污染加权平均分"
    assert summary["dimension_means"]["correctness"] == 5.0


def test_invalid_samples_still_carry_scores():
    """分数照常展示——它本身就是"这批为何无效"的证据。"""
    records = records_with({"data_id": "bad-env", "run_valid": False,
                            "scores": SCORES(2, 1, 3, 3)})
    summary = aggregate.summarize(records)
    ev = summary["invalid"][0][config.EVAL_KEY]
    assert ev["correctness"] == 2 and ev[config.EVAL_WEIGHTED] > 0


def test_all_invalid_gives_no_means():
    records = records_with(
        {"data_id": "a", "run_valid": False, "scores": SCORES(1, 1, 1, 1)},
        {"data_id": "b", "run_valid": False, "scores": SCORES(2, 2, 2, 2)},
    )
    summary = aggregate.summarize(records)
    assert summary["valid"] == []
    assert summary["weighted_mean"] is None
    assert summary["pass_rate"] == "—"
    assert summary["by_dimension"] == {}


def test_parse_error_samples_excluded():
    record = seed_record(data_id="broken")
    record[config.EVAL_KEY] = aggregate.build_parse_error("items 项数不匹配")
    summary = aggregate.summarize([record])
    assert len(summary["broken"]) == 1
    assert summary["valid"] == [] and summary["invalid"] == []


def test_weighted_mean_is_mean_of_per_case_weighted_scores():
    """加权平均分 = 逐条 weighted_score 的平均。"""
    records = records_with(
        {"data_id": "a", "scores": SCORES(5, 1, 5, 5)},   # 3.8
        {"data_id": "b", "scores": SCORES(1, 5, 1, 1)},   # 2.2
    )
    summary = aggregate.summarize(records)
    assert summary["weighted_mean"] == pytest.approx((3.8 + 2.2) / 2)


def test_per_case_then_average_equals_average_then_weight():
    """两种汇总口径**恒等**——weighted_score 是各维度的线性函数，均值和加权可交换。

    所以报告不必在两个数之间选一个：它们必然相同。维度均分仍单独列出，
    但那是为了看"哪一维拖后腿"，不是另一个"总分"。
    """
    specs = [
        {"data_id": "a", "scores": SCORES(5, 1, 5, 5)},
        {"data_id": "b", "scores": SCORES(1, 5, 1, 1)},
        {"data_id": "c", "scores": SCORES(3, 4, 2, 5)},
    ]
    summary = aggregate.summarize(records_with(*specs))

    per_case = sum(aggregate.weighted_score(s["scores"]) for s in specs) / len(specs)
    of_means = aggregate.weighted_score(summary["dimension_means"])

    assert summary["weighted_mean"] == pytest.approx(per_case)
    assert of_means == pytest.approx(per_case)


def test_by_dimension_groups_valid_only():
    records = records_with(
        {"data_id": "f1", "dimension": "functional", "scores": SCORES(5, 5, 5, 5)},
        {"data_id": "f2", "dimension": "functional", "scores": SCORES(1, 1, 1, 1)},
        {"data_id": "b1", "dimension": "boundary", "scores": SCORES(5, 5, 5, 5)},
        {"data_id": "x", "dimension": "boundary", "run_valid": False,
         "scores": SCORES(1, 1, 1, 1)},
    )
    summary = aggregate.summarize(records)
    assert summary["by_dimension"]["functional"]["有效样本"] == 2
    assert summary["by_dimension"]["boundary"]["有效样本"] == 1
    assert summary["by_dimension"]["boundary"]["通过率"] == "100%"


# ============================== report.md ==============================

def manifest_stub():
    return {"rubric_path": "/skill/references/runtime-rubric.md",
            "rubric_sha256": "abc123", "concurrency": 2,
            "input_seed": "/run/run_datasets/seed.jsonl",
            "judge": {"model": "claude-opus-5"}}


def test_report_flags_no_valid_conclusion():
    records = records_with({"data_id": "a", "run_valid": False,
                            "scores": SCORES(2, 1, 3, 3)})
    report = aggregate.render_report("e2e-test-x",
                                     aggregate.summarize(records), manifest_stub())
    assert "本轮无有效评测结论" in report
    assert "有效样本 | 0 / 1" in report


def test_report_shows_invalid_scores_but_marks_them_excluded():
    records = records_with({"data_id": "a", "run_valid": False,
                            "scores": SCORES(2, 1, 3, 3)})
    report = aggregate.render_report("e2e-test-x",
                                     aggregate.summarize(records), manifest_stub())
    assert "不计入上述任何指标" in report
    assert "2/1/3/3" in report


def test_report_has_all_sections_for_healthy_run():
    records = records_with(
        {"data_id": "a", "dimension": "functional", "scores": SCORES(5, 5, 5, 5)},
        {"data_id": "b", "dimension": "boundary", "run_valid": False,
         "scores": SCORES(2, 1, 3, 3)},
    )
    report = aggregate.render_report("e2e-test-x",
                                     aggregate.summarize(records), manifest_stub())
    for heading in ("## 一、结论", "## 二、无效样本", "## 三、逐条明细",
                    "## 四、按维度分布", "## 五、环境记录"):
        assert heading in report


def test_section_numbers_have_no_gaps():
    """省略的小节不得在编号上留窟窿（曾经出现过"二"之后直接"六"）。"""
    import re

    records = records_with({"data_id": "a", "scores": SCORES(5, 5, 5, 5)})
    report = aggregate.render_report("e2e-test-x",
                                     aggregate.summarize(records), manifest_stub())

    numerals = "一二三四五六七八九十"
    found = re.findall(r"^## (.)、(.+)$", report, re.M)
    assert found, "报告一个小节都没有"
    for position, (numeral, _) in enumerate(found):
        assert numeral == numerals[position], (
            f"第 {position + 1} 个小节的编号是 {numeral}，应连续为 {numerals[position]}")


def test_skipped_sections_are_absent_entirely():
    """只有有效样本时，无效样本 / 解析失败两节整段不出现（结论表里的计数行除外）。"""
    records = records_with({"data_id": "a", "scores": SCORES(5, 5, 5, 5)})
    report = aggregate.render_report("e2e-test-x",
                                     aggregate.summarize(records), manifest_stub())
    assert "## 二、无效样本" not in report
    assert "## 三、解析失败" not in report
    # 计数行仍然在结论表里——0 也要显示，缺席比 0 更误导
    assert "| 解析失败（未参与评测） | 0 |" in report


def test_report_lists_per_item_verdicts():
    records = records_with({"data_id": "a",
                            "verdicts": ["hit", "miss", "unverifiable", "hit", "hit"],
                            "scores": SCORES(4, 4, 4, 4)})
    report = aggregate.render_report("e2e-test-x",
                                     aggregate.summarize(records), manifest_stub())
    assert "命中" in report and "未命中" in report and "无法判定" in report


def test_report_escapes_pipes_in_input():
    record = seed_record(data_id="a", input="含有 | 竖线的输入",
                         expected_output=["a", "b", "c", "d", "e"])
    record[config.EVAL_KEY] = aggregate.build_eval(
        answer_payload("a", ["a", "b", "c", "d", "e"]), ["a", "b", "c", "d", "e"])
    report = aggregate.render_report("e2e-test-x",
                                     aggregate.summarize([record]), manifest_stub())
    assert "含有 \\| 竖线的输入" in report


def test_report_records_rubric_hash_and_model():
    report = aggregate.render_report(
        "e2e-test-x", aggregate.summarize([]), manifest_stub())
    assert "abc123" in report and "claude-opus-5" in report
