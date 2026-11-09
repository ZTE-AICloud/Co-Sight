#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""seed 记录字段校验：data_id / input / timeout。"""

import pytest

import common
import config
from common import RunnerError


# ============================== case_id_of ==============================

def test_case_id_from_data_id():
    assert common.case_id_of({"data_id": "明文密码智能体_functional_001"}, 1) \
        == "明文密码智能体_functional_001"


def test_case_id_missing():
    with pytest.raises(RunnerError, match="缺少 data_id"):
        common.case_id_of({}, 3)


def test_case_id_blank():
    with pytest.raises(RunnerError, match="缺少 data_id"):
        common.case_id_of({"data_id": "   "}, 1)


@pytest.mark.parametrize("bad", [
    "a/b",              # 正斜杠 → 会建子目录
    "a\\b",             # 反斜杠
    "../escape",        # 路径跳转
    "..",
])
def test_case_id_rejects_path_traversal(bad):
    with pytest.raises(RunnerError, match="不能用作目录名"):
        common.case_id_of({"data_id": bad}, 1)


# ============================== input_of ==============================

def test_input_passes_through_verbatim():
    prompt = "请对 ./demo_code 目录做明文密码检查"
    assert common.input_of({"input": prompt}, 1) == prompt


def test_input_missing():
    with pytest.raises(RunnerError, match="缺少 input"):
        common.input_of({}, 2)


def test_input_blank_rejected():
    with pytest.raises(RunnerError, match="缺少 input"):
        common.input_of({"input": "  \n "}, 2)


def test_precondition_never_leaks_into_prompt():
    """precondition 里常含答案（明文凭据原文），必须留在记录里而非进 prompt。"""
    record = {
        "input": "检查 ./demo_code",
        "precondition": '文件内有一行 DB_PASSWORD = "Admin@123";',
    }
    prompt = common.input_of(record, 1)
    assert "Admin@123" not in prompt
    assert prompt == "检查 ./demo_code"


# ============================== timeout_of ==============================

def test_timeout_defaults_to_constant():
    assert common.timeout_of({}) == config.CASE_TIMEOUT_SECONDS


def test_timeout_from_record_overrides():
    assert common.timeout_of({"timeout": 900}) == 900


def test_timeout_string_coerced():
    assert common.timeout_of({"timeout": "120"}) == 120


@pytest.mark.parametrize("bad", [0, -5, "abc", {}])
def test_timeout_invalid_rejected(bad):
    with pytest.raises(RunnerError, match="timeout"):
        common.timeout_of({"timeout": bad})


def test_timeout_null_falls_back_to_default():
    """显式 null 视同未设置。"""
    assert common.timeout_of({"timeout": None}) == config.CASE_TIMEOUT_SECONDS


# ============================== JSONL IO ==============================

def test_read_jsonl_skips_blank_lines(tmp_path):
    path = tmp_path / "seed.jsonl"
    path.write_text('{"data_id":"a"}\n\n{"data_id":"b"}\n', encoding="utf-8")
    assert [r["data_id"] for r in common.read_jsonl(path)] == ["a", "b"]


def test_read_jsonl_missing_file_returns_empty(tmp_path):
    assert common.read_jsonl(tmp_path / "absent.jsonl") == []


def test_read_jsonl_bad_line_names_lineno(tmp_path):
    path = tmp_path / "seed.jsonl"
    path.write_text('{"data_id":"a"}\n{broken\n', encoding="utf-8")
    with pytest.raises(RunnerError, match="第 2 行非法"):
        common.read_jsonl(path)


def test_read_jsonl_rejects_non_object(tmp_path):
    path = tmp_path / "seed.jsonl"
    path.write_text('["not", "an", "object"]\n', encoding="utf-8")
    with pytest.raises(RunnerError, match="不是 JSON 对象"):
        common.read_jsonl(path)


def test_write_read_jsonl_roundtrip_keeps_cjk(tmp_path):
    path = tmp_path / "seed.jsonl"
    records = [{"data_id": "明文密码智能体_functional_001", "input": "检查密码"}]
    common.write_jsonl(path, records)
    assert common.read_jsonl(path) == records
    assert "明文密码智能体" in path.read_text(encoding="utf-8")


def test_write_jsonl_compact_one_line_per_record(tmp_path):
    path = tmp_path / "seed.jsonl"
    common.write_jsonl(path, [{"a": 1}, {"b": 2}])
    assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 2
