#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_validate.py — 裁判答案的校验。

校验是唯一的把关口：不合格的答案不进聚合、退回重派。所以每条失败都要有**能照做
的归因**，主 agent 要把这句话转给新裁判。这里逐条钉住。
"""

import json

import pytest

import config
import validate
from conftest import answer_payload

EXPECTED = ["期望项一", "期望项二", "期望项三"]
DATA_ID = "agent_functional_001"


def write(tmp_path, payload, name="x.answer.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def check(tmp_path, payload, expected=None, data_id=DATA_ID):
    return validate.validate_answer(write(tmp_path, payload),
                                    expected or EXPECTED, data_id)


# ============================== 通路 ==============================

def test_valid_answer_passes(tmp_path):
    verdict = check(tmp_path, answer_payload(DATA_ID, EXPECTED))
    assert verdict.ok, verdict.reason
    assert verdict.answer["data_id"] == DATA_ID


# ============================== 失败归因 ==============================

def test_missing_file_reports_not_readable(tmp_path):
    verdict = validate.validate_answer(tmp_path / "nope.json", EXPECTED, DATA_ID)
    assert not verdict.ok
    assert "不可读" in verdict.reason


def test_broken_json_reports_parse_failure(tmp_path):
    path = tmp_path / "x.answer.json"
    path.write_text("{ 不是 json", encoding="utf-8")
    verdict = validate.validate_answer(path, EXPECTED, DATA_ID)
    assert not verdict.ok
    assert "JSON 解析失败" in verdict.reason


def test_non_object_top_level_rejected(tmp_path):
    verdict = check(tmp_path, ["不是对象"])
    assert not verdict.ok and "JSON 对象" in verdict.reason


def test_data_id_mismatch_rejected(tmp_path):
    verdict = check(tmp_path, answer_payload("另一个_id", EXPECTED))
    assert not verdict.ok
    assert "data_id 不匹配" in verdict.reason
    assert "另一个_id" in verdict.reason


def test_item_count_mismatch_names_both_numbers(tmp_path):
    """归因必须点出两个数字，主 agent 才能把话转述清楚。"""
    payload = answer_payload(DATA_ID, EXPECTED[:2])
    verdict = check(tmp_path, payload)
    assert not verdict.ok
    assert "3" in verdict.reason and "2" in verdict.reason
    assert "等长同序" in verdict.reason


def test_item_not_object_rejected(tmp_path):
    payload = answer_payload(DATA_ID, EXPECTED)
    payload["items"][1] = "字符串不是对象"
    verdict = check(tmp_path, payload)
    assert not verdict.ok and "第 2 项" in verdict.reason


def test_illegal_verdict_names_allowed_values(tmp_path):
    payload = answer_payload(DATA_ID, EXPECTED, verdicts=["hit", "maybe", "hit"])
    verdict = check(tmp_path, payload)
    assert not verdict.ok
    assert "第 2 项" in verdict.reason
    assert "unverifiable" in verdict.reason


def test_missing_dimension_names_it(tmp_path):
    payload = answer_payload(DATA_ID, EXPECTED)
    del payload["actionability"]
    verdict = check(tmp_path, payload)
    assert not verdict.ok and "actionability" in verdict.reason


@pytest.mark.parametrize("bad", [0, 6, -1, "5", 3.5, None])
def test_out_of_range_score_rejected(tmp_path, bad):
    payload = answer_payload(DATA_ID, EXPECTED, scores={
        "correctness": bad, "completeness": 5,
        "format_compliance": 5, "actionability": 5})
    verdict = check(tmp_path, payload)
    assert not verdict.ok and "correctness" in verdict.reason


def test_boolean_score_rejected(tmp_path):
    """True 是 int 的子类，不显式排除就会被当成 1 分蒙混过关。"""
    payload = answer_payload(DATA_ID, EXPECTED, scores={
        "correctness": True, "completeness": 5,
        "format_compliance": 5, "actionability": 5})
    verdict = check(tmp_path, payload)
    assert not verdict.ok and "correctness" in verdict.reason


def test_non_boolean_run_valid_rejected(tmp_path):
    payload = answer_payload(DATA_ID, EXPECTED)
    payload["run_valid"] = "true"
    verdict = check(tmp_path, payload)
    assert not verdict.ok and "run_valid" in verdict.reason


def test_run_valid_false_requires_reason(tmp_path):
    payload = answer_payload(DATA_ID, EXPECTED, run_valid=False)
    payload["invalid_reason"] = "   "
    verdict = check(tmp_path, payload)
    assert not verdict.ok and "invalid_reason" in verdict.reason


def test_run_valid_false_with_reason_is_accepted(tmp_path):
    """run_valid=false 是合法结论（环境没搭起来），且四维分照常收下。"""
    payload = answer_payload(DATA_ID, EXPECTED, run_valid=False,
                             invalid_reason="目标路径不存在")
    verdict = check(tmp_path, payload)
    assert verdict.ok, verdict.reason


def test_boundary_scores_accepted(tmp_path):
    payload = answer_payload(DATA_ID, EXPECTED, scores={
        "correctness": config.SCORE_MIN, "completeness": config.SCORE_MAX,
        "format_compliance": config.SCORE_MIN, "actionability": config.SCORE_MAX})
    assert check(tmp_path, payload).ok


def test_verdict_unverifiable_is_accepted(tmp_path):
    payload = answer_payload(DATA_ID, EXPECTED,
                             verdicts=["hit", "unverifiable", "miss"])
    assert check(tmp_path, payload).ok
