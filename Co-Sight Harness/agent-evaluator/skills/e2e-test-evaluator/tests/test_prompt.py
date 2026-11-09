#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_prompt.py — 裁判 prompt 的渲染：证据链、字段裁剪、rubric 嵌入。

prompt 是裁判唯一的信息来源（它不碰文件系统），漏一个字段就会让某条判据失效，
所以字段的"给"与"不给"都要钉住。
"""

import json

import common
import config
import render
from conftest import seed_record


def build(record, index=1, answer_path="/tmp/answer.json"):
    return render.render_case_prompt(record, index, answer_path)


# ============================== rubric ==============================

def test_rubric_is_embedded_in_full():
    text = render.load_rubric()
    prompt = build(seed_record())
    assert text in prompt, "细则必须全文嵌入——裁判是独立会话，不给它就会自由发挥"


def test_rubric_weights_appear_in_prompt():
    prompt = build(seed_record())
    assert "40%" in prompt and "30%" in prompt


def test_rubric_reads_skill_local_copy():
    """固定读 skill 内那份：cwd 漂了、换台机器都不影响。"""
    assert render.RUBRIC_PATH.is_file()
    assert render.RUBRIC_PATH.parts[-2:] == config.RUBRIC_RELPATH


# ============================== 证据链 ==============================

def test_evidence_prefers_full_result_json(make_run, write_result_json):
    _, _, records = make_run([seed_record()])
    full = "完整报告正文" * 100
    write_result_json(records[0], {"result": full, "duration_ms": 1})

    evidence, source = common.load_evidence(records[0])
    assert evidence == full, "主证据必须是 result.json 的 result 全文，不是 400 字符的 preview"
    assert "result.json" in source


def test_evidence_falls_back_to_preview_as_full_text(make_run):
    _, _, records = make_run([seed_record()])
    evidence, source = common.load_evidence(records[0])
    assert evidence == "预检失败，流程终止。"
    assert "result_preview" in source
    assert "截断" not in source


def test_evidence_handles_partial_result(make_run, write_result_json):
    _, _, records = make_run([seed_record()])
    write_result_json(records[0], {"partial_result": True, "extracted_text": "半截输出"})
    evidence, source = common.load_evidence(records[0])
    assert evidence == "半截输出"
    assert "半截" in source or "超时" in source


def test_evidence_handles_parse_error(make_run, write_result_json):
    _, _, records = make_run([seed_record()])
    write_result_json(records[0], {"parse_error": True, "raw": "<html>不是 json</html>"})
    evidence, source = common.load_evidence(records[0])
    assert evidence == "<html>不是 json</html>"
    assert "raw" in source or "无法解析" in source


def test_evidence_empty_when_nothing_available(make_run):
    record = seed_record()
    record["run"]["result_preview"] = ""
    _, _, records = make_run([record])
    evidence, source = common.load_evidence(records[0])
    assert evidence == ""
    assert "无任何输出证据" in source


def test_evidence_falls_back_when_result_json_is_corrupt(make_run):
    from pathlib import Path
    _, _, records = make_run([seed_record()])
    case_dir = Path(records[0]["run"]["case_dir"])
    (case_dir / "result.json").write_text("{ 坏掉的 json", encoding="utf-8")

    evidence, source = common.load_evidence(records[0])
    assert evidence == "预检失败，流程终止。"


# ============================== 字段裁剪 ==============================

def test_precondition_is_given_to_judge():
    """与 runner 对被测 agent 的做法相反：对裁判它是判 run_valid 的硬依据。"""
    record = seed_record(precondition="目录 /workspace/pw-scan 存在且可读")
    assert "/workspace/pw-scan" in build(record)


def test_expected_output_items_are_all_listed():
    record = seed_record(expected_output=["AAA", "BBB", "CCC"])
    prompt = build(record)
    assert "共 3 项" in prompt
    for item in ("AAA", "BBB", "CCC"):
        assert item in prompt


def test_capability_and_source_fields_are_not_leaked():
    """这三个字段对判分无用，徒增噪声。"""
    record = seed_record(capability_ref="C99-MARKER", source="gwt-MARKER",
                         source_ref="pass-criteria.md#MARKER")
    prompt = build(record)
    assert "C99-MARKER" not in prompt
    assert "gwt-MARKER" not in prompt
    assert "#MARKER" not in prompt


def test_execution_meta_is_present_but_labeled_reference_only():
    record = seed_record()
    record["run"].update({"status": "timeout", "timed_out": True, "elapsed_seconds": 600.0})
    prompt = build(record)
    assert "timeout" in prompt
    assert "仅供参考" in prompt and "不得作为打分依据" in prompt


def test_none_metadata_keys_are_omitted():
    record = seed_record()
    record["run"]["exit_code"] = None
    prompt = build(record)
    assert "exit_code: None" not in prompt


def test_workspace_dir_is_given_as_reference(make_run):
    _, _, records = make_run([seed_record()])
    prompt = build(records[0])
    assert records[0]["run"]["workspace_dir"] in prompt
    assert "cwd" in prompt


def test_missing_workspace_dir_renders_placeholder():
    record = seed_record()
    record["run"]["workspace_dir"] = ""
    record["run"]["case_dir"] = ""
    assert "（未知）" in build(record)


# ============================== 输出契约 ==============================

def test_schema_items_match_expected_count():
    record = seed_record(expected_output=["A", "B", "C", "D"])
    prompt = build(record)
    block = prompt.split("```json")[-1].split("```")[0]
    payload = json.loads(block)
    assert len(payload["items"]) == 4, "模板必须按真实条目数占位，逼裁判逐项对齐"
    assert [item["text"] for item in payload["items"]] == ["A", "B", "C", "D"]


def test_schema_covers_every_required_key():
    """模板缺任何校验器要求的字段，裁判照写就必然不合格——白烧一整轮。

    这条正是漏掉 data_id 那次的回归守卫：当时 5 条裁判答案全部因此被判不合格。
    """
    import validate

    expected = ["A", "B"]
    record = seed_record(data_id="case-xyz", expected_output=expected)
    block = build(record).split("```json")[-1].split("```")[0]
    schema = json.loads(block)

    assert schema[config.DATA_ID_KEY] == "case-xyz"
    for key in (config.ANS_RUN_VALID, config.ANS_INVALID_REASON,
                config.ANS_ITEMS, config.ANS_REASONING, *config.DIMENSIONS):
        assert key in schema, f"输出模板漏了校验器要求的字段：{key}"


def test_filling_the_schema_verbatim_yields_a_valid_answer(tmp_path):
    """照着模板原样填值就必须能通过校验——模板与校验器不得有任何出入。"""
    import validate

    expected = ["A", "B", "C"]
    record = seed_record(data_id="case-abc", expected_output=expected)
    block = build(record).split("```json")[-1].split("```")[0]
    schema = json.loads(block)

    # 模拟裁判：把占位符换成真实值，其余结构原样保留
    schema[config.ANS_RUN_VALID] = False
    schema[config.ANS_INVALID_REASON] = "环境未就绪"
    for item in schema[config.ANS_ITEMS]:
        item["verdict"] = "miss"
        item["note"] = "无报告"
    for dim in config.DIMENSIONS:
        schema[dim] = 3

    answer_path = tmp_path / "case-abc.answer.json"
    answer_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")

    verdict = validate.validate_answer(answer_path, expected, "case-abc")
    assert verdict.ok, f"照模板填的答案竟不合法：{verdict.reason}"


def test_schema_forbids_judge_from_scoring():
    prompt = build(seed_record())
    assert "加权总分与是否通过由下游计算" in prompt


def test_answer_path_is_interpolated(make_run):
    _, _, records = make_run([seed_record()])
    answer_path = "/abs/path/.work/x.answer.json"
    prompt = build(records[0], answer_path=answer_path)
    assert answer_path in prompt
    assert render.ANSWER_PATH_PLACEHOLDER not in prompt


def test_landing_explanation_is_stated():
    """两处 rubric 降级解释必须在 prompt 里写明，否则裁判会因找不到字段而拒判。"""
    prompt = build(seed_record())
    assert "整体视为 required" in prompt
    assert "隐含" in prompt and "format_compliance" in prompt
