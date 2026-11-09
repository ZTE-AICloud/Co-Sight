#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_record.py — evaluate.py 的主流程：两阶段循环、批次、续跑、回写、退出码。"""

import json

import pytest

import aggregate
import common
import config
import evaluate
from conftest import answer_payload, seed_record

EXPECTED = ["期望项一", "期望项二"]


def make_records(*data_ids, dimension="functional"):
    return [seed_record(data_id=d, expected_output=list(EXPECTED), dimension=dimension)
            for d in data_ids]


def run_main(run_dir, *extra):
    return evaluate.main(["--input", str(run_dir), "--output", str(run_dir), *extra])


def work_dir_of(run_dir):
    return run_dir / config.OUTPUT_ARTIFACT_DIRNAME / config.WORK_DIRNAME


def artifact_of(run_dir):
    return run_dir / config.OUTPUT_ARTIFACT_DIRNAME


def write_answer(run_dir, data_id, *, verdicts=None, scores=None, run_valid=True):
    payload = answer_payload(data_id, EXPECTED, verdicts=verdicts, scores=scores,
                             run_valid=run_valid)
    path = work_dir_of(run_dir) / f"{data_id}{config.ANSWER_SUFFIX}"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def read_out(run_dir):
    return common.read_jsonl(artifact_of(run_dir) / config.SEED_FILENAME)


def _rewrite_seed(run_dir, records):
    """fixture 建完目录后，把输入侧 seed 改成畸形形态以验证报错路径。

    fixture 需要 data_id 才能建用例目录，所以畸形记录只能事后覆写，不能在
    fixture 调用前构造。
    """
    seed_path = run_dir / config.INPUT_ARTIFACT_DIRNAME / config.SEED_FILENAME
    seed_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8")


# ============================== 批次切分 ==============================

def test_batches_are_barriers():
    assert evaluate.make_batches(["a", "b", "c", "d", "e"], 2) == [["a", "b"], ["c", "d"], ["e"]]
    assert evaluate.make_batches(["a", "b"], 5) == [["a", "b"]]
    assert evaluate.make_batches(["a"], 1) == [["a"]]


# ============================== 阶段一：派活 ==============================

def test_first_pass_prints_batches_and_exits_without_evaluating(make_run, capsys):
    run_dir, _, _ = make_run(make_records("a", "b", "c"))
    code = run_main(run_dir, "--concurrency", "2")

    out = capsys.readouterr().out
    assert code == 0
    assert "需要你出力：3 条用例待裁判，分 2 批" in out
    assert "第 1 批（并发 2）" in out and "第 2 批（并发 1）" in out

    # 三个 prompt 都渲染好了
    for data_id in ("a", "b", "c"):
        assert (work_dir_of(run_dir) / f"{data_id}{config.PROMPT_SUFFIX}").is_file()

    # 但还没有任何结论
    assert all(config.EVAL_KEY not in r for r in read_out(run_dir))


def test_batch_plan_tells_main_agent_not_to_read_or_score(make_run, capsys):
    run_dir, _, _ = make_run(make_records("a"))
    run_main(run_dir)
    out = capsys.readouterr().out
    assert "不要自己读 prompt 的内容，也不要自己打分" in out


def test_prompt_path_printed_is_absolute(make_run, capsys):
    run_dir, _, _ = make_run(make_records("a"))
    run_main(run_dir)
    out = capsys.readouterr().out
    assert str(work_dir_of(run_dir).resolve()) in out


# ============================== 阶段二：聚合 ==============================

def test_second_pass_aggregates_and_writes_report(make_run, capsys):
    run_dir, _, _ = make_run(make_records("a", "b"))
    run_main(run_dir)
    for data_id in ("a", "b"):
        write_answer(run_dir, data_id)

    code = run_main(run_dir)
    out = capsys.readouterr().out
    assert code == 0
    assert "落盘完成" in out

    records = read_out(run_dir)
    assert all(config.EVAL_KEY in r for r in records)
    assert records[0][config.EVAL_KEY][config.EVAL_STATUS] == config.EVAL_STATUS_OK
    assert records[0][config.EVAL_KEY][config.EVAL_WEIGHTED] == 5.0

    artifact = artifact_of(run_dir)
    assert (artifact / config.REPORT_FILENAME).is_file()
    assert (artifact / config.EVAL_MANIFEST_FILENAME).is_file()


def test_original_fields_are_untouched(make_run):
    run_dir, _, _ = make_run(make_records("a"))
    run_main(run_dir)
    write_answer(run_dir, "a")
    run_main(run_dir)

    record = read_out(run_dir)[0]
    original = seed_record(data_id="a", expected_output=list(EXPECTED))
    for key, value in original.items():
        if key == "run":
            continue
        assert record[key] == value, f"原字段被改动了：{key}"
    assert record[config.RUN_KEY]["status"] == "passed", "run 子对象必须原样保留"


def test_report_and_manifest_are_written_end_to_end(make_run):
    run_dir, _, _ = make_run([seed_record(data_id="a", expected_output=list(EXPECTED),
                                          dimension="functional"),
                              seed_record(data_id="b", expected_output=list(EXPECTED),
                                          dimension="boundary")])
    run_main(run_dir)
    write_answer(run_dir, "a", scores={"correctness": 5, "completeness": 5,
                                       "format_compliance": 5, "actionability": 5})
    write_answer(run_dir, "b", run_valid=False,
                 scores={"correctness": 2, "completeness": 1,
                         "format_compliance": 3, "actionability": 3})
    run_main(run_dir)

    report = (artifact_of(run_dir) / config.REPORT_FILENAME).read_text(encoding="utf-8")
    assert "有效样本 | 1 / 2" in report
    assert "无效样本" in report and "按维度分布" in report

    manifest = common.read_json(artifact_of(run_dir) / config.EVAL_MANIFEST_FILENAME)
    assert manifest["rubric_sha256"], "rubric 指纹必须落进 manifest 供追溯"
    assert manifest["concurrency"] == 1


# ============================== 无效样本 ==============================

def test_invalid_sample_is_isolated_in_output_and_report(make_run):
    run_dir, _, _ = make_run(make_records("a", "b"))
    run_main(run_dir)
    write_answer(run_dir, "a", scores={"correctness": 5, "completeness": 5,
                                       "format_compliance": 5, "actionability": 5})
    write_answer(run_dir, "b", run_valid=False,
                 scores={"correctness": 1, "completeness": 1,
                         "format_compliance": 1, "actionability": 1})
    run_main(run_dir)

    records = read_out(run_dir)
    assert records[0][config.EVAL_KEY][config.EVAL_RUN_VALID] is True
    assert records[1][config.EVAL_KEY][config.EVAL_RUN_VALID] is False
    assert records[1][config.EVAL_KEY][config.EVAL_INVALID_REASON]

    summary = aggregate.summarize(records)
    assert summary["weighted_mean"] == 5.0, "无效样本不得进均值"


def test_all_invalid_still_delivers_artifacts(make_run, capsys):
    """评测器把"Agent 表现为空"报成"评测器失败"会误导人去查评测器。"""
    run_dir, _, _ = make_run(make_records("a"))
    run_main(run_dir)
    write_answer(run_dir, "a", run_valid=False,
                 scores={"correctness": 1, "completeness": 1,
                         "format_compliance": 1, "actionability": 1})
    code = run_main(run_dir)

    assert code == 0
    assert (artifact_of(run_dir) / config.REPORT_FILENAME).is_file()
    assert "本轮无有效评测结论" in (
        artifact_of(run_dir) / config.REPORT_FILENAME).read_text(encoding="utf-8")


# ============================== 自愈与上限 ==============================

def test_bad_answer_is_reissued_not_fatal(make_run, capsys):
    run_dir, _, _ = make_run(make_records("a"))
    run_main(run_dir)

    # 裁判给了项数不对的答案
    (work_dir_of(run_dir) / f"a{config.ANSWER_SUFFIX}").write_text(
        json.dumps(answer_payload("a", EXPECTED[:1]), ensure_ascii=False),
        encoding="utf-8")

    run_main(run_dir)
    out = capsys.readouterr().out
    assert "需要你出力：1 条用例待裁判" in out, "不合格的答案必须进重派清单"

    # 修好后即可聚合
    write_answer(run_dir, "a")
    run_main(run_dir)
    assert read_out(run_dir)[0][config.EVAL_KEY][config.EVAL_STATUS] == config.EVAL_STATUS_OK


def test_repeated_failure_stops_after_max_attempts(make_run, capsys):
    """防死循环：反复给坏答案，最终单列而不再派发。"""
    run_dir, _, _ = make_run(make_records("a"))
    broken = json.dumps(answer_payload("a", EXPECTED[:1]), ensure_ascii=False)

    for _ in range(config.MAX_JUDGE_ATTEMPTS + 2):
        run_main(run_dir)
        (work_dir_of(run_dir) / f"a{config.ANSWER_SUFFIX}").write_text(
            broken, encoding="utf-8")

    out = capsys.readouterr().out
    assert "本轮不再派发" in out

    records = read_out(run_dir)
    ev = records[0][config.EVAL_KEY]
    assert ev[config.EVAL_STATUS] == config.EVAL_STATUS_PARSE_ERROR
    assert "项数不匹配" in ev[config.EVAL_ERROR]

    summary = aggregate.summarize(records)
    assert len(summary["broken"]) == 1
    assert summary["weighted_mean"] is None


def test_attempts_counter_is_recorded(make_run):
    run_dir, _, _ = make_run(make_records("a"))
    run_main(run_dir)
    write_answer(run_dir, "a")
    run_main(run_dir)
    assert read_out(run_dir)[0][config.EVAL_KEY][config.EVAL_ATTEMPTS] == 1


# ============================== 续跑 ==============================

def test_resume_skips_already_evaluated(make_run, capsys):
    run_dir, _, _ = make_run(make_records("a", "b"))
    run_main(run_dir)
    write_answer(run_dir, "a")
    write_answer(run_dir, "b")
    run_main(run_dir)

    capsys.readouterr()
    run_main(run_dir)
    out = capsys.readouterr().out
    assert "跳过已评测 2" in out
    assert "需要你出力" not in out


def test_resume_only_redispatches_the_missing_one(make_run, capsys):
    """续跑是增量的：已有合格答案的条目不再派裁判。"""
    run_dir, _, _ = make_run(make_records("a", "b", "c"))
    run_main(run_dir)
    write_answer(run_dir, "a")
    write_answer(run_dir, "c")
    capsys.readouterr()

    run_main(run_dir)
    out = capsys.readouterr().out
    assert "需要你出力：1 条用例待裁判，分 1 批" in out
    assert "  - b" in out
    assert "  - a" not in out and "  - c" not in out

    write_answer(run_dir, "b")
    run_main(run_dir)
    assert all(config.EVAL_KEY in r for r in read_out(run_dir))


def test_changed_case_set_is_rejected(make_run):
    run_dir, _, _ = make_run(make_records("a", "b"))
    run_main(run_dir)
    write_answer(run_dir, "a")
    write_answer(run_dir, "b")
    run_main(run_dir)

    # 换一份用例集指到同一个 run 目录
    other, _, _ = make_run(make_records("x", "y"), run_name="e2e-test-20260303-000000")
    with pytest.raises(common.EvalError, match="对不上"):
        evaluate.main(["--input", str(other), "--output", str(run_dir)])


# ============================== 报错而非静默避让 ==============================

def test_unexecuted_cases_are_rejected(make_run):
    """run 字段缺失 = 还没跑。硬评只会产出一堆假低分。"""
    run_dir, _, records = make_run(make_records("a"))
    del records[0][config.RUN_KEY]   # 必须在 fixture 建完目录之后再删
    _rewrite_seed(run_dir, records)

    with pytest.raises(common.EvalError, match="尚未执行"):
        run_main(run_dir)


def test_missing_expected_output_is_rejected(make_run):
    run_dir, _, records = make_run(make_records("a"))
    del records[0]["expected_output"]
    _rewrite_seed(run_dir, records)

    with pytest.raises(common.EvalError, match="expected_output"):
        run_main(run_dir)


def test_empty_expected_output_is_rejected(make_run):
    run_dir, _, records = make_run(make_records("a"))
    records[0]["expected_output"] = []
    _rewrite_seed(run_dir, records)

    with pytest.raises(common.EvalError, match="非空列表"):
        run_main(run_dir)


def test_missing_data_id_is_rejected(make_run):
    run_dir, _, records = make_run(make_records("a"))
    del records[0]["data_id"]
    _rewrite_seed(run_dir, records)

    with pytest.raises(common.EvalError, match="data_id"):
        run_main(run_dir)


@pytest.mark.parametrize("bad", [0, 33, -1])
def test_concurrency_out_of_range_errors(make_run, bad):
    run_dir, _, _ = make_run(make_records("a"))
    with pytest.raises(SystemExit) as excinfo:
        run_main(run_dir, "--concurrency", str(bad))
    assert excinfo.value.code == 1


def test_output_inside_workspace_is_rejected(make_run):
    """防泄题：prompt 里有 expected_output，放进去等于把答案塞给被测 Agent。"""
    run_dir, _, records = make_run(make_records("a"))
    workspace = records[0][config.RUN_KEY]["workspace_dir"]

    with pytest.raises(common.EvalError, match="工作副本内部"):
        evaluate.main(["--input", str(run_dir), "--output", workspace])


def test_output_overwriting_input_seed_is_rejected(make_run):
    """--output 指回 seed 所在的 run_datasets/ —— 会被"要的是 run 目录"这条先拦下。

    两条守卫都指向同一个前提：输入侧那份 seed 全程只读，产物必须落在别处。
    """
    run_dir, seed_path, _ = make_run(make_records("a"))
    with pytest.raises(common.EvalError, match="run 目录"):
        evaluate.main(["--input", str(seed_path), "--output", str(seed_path.parent)])


def test_guard_no_seed_overwrite_is_wired_in(make_run):
    """直接钉住那条守卫本身：同路径即拒绝。"""
    run_dir, seed_path, _ = make_run(make_records("a"))
    with pytest.raises(common.EvalError, match="覆盖"):
        common.guard_no_seed_overwrite(seed_path, seed_path)


def test_input_side_seed_is_never_modified(make_run):
    run_dir, seed_path, _ = make_run(make_records("a", "b"))
    before = seed_path.read_bytes()

    run_main(run_dir)
    write_answer(run_dir, "a")
    write_answer(run_dir, "b")
    run_main(run_dir)

    assert seed_path.read_bytes() == before, "runner 的交付物必须全程只读"


# ============================== manifest ==============================

def test_judge_info_from_main_agent_is_merged(make_run):
    """模型名只有主 agent 知道，脚本读它写的 judge.json。"""
    run_dir, _, _ = make_run(make_records("a"))
    run_main(run_dir)
    write_answer(run_dir, "a")
    (artifact_of(run_dir) / config.JUDGE_INFO_FILENAME).write_text(
        json.dumps({"model": "claude-opus-5", "main_agent_model": "dept6-ADC"},
                   ensure_ascii=False), encoding="utf-8")
    run_main(run_dir)

    manifest = common.read_json(artifact_of(run_dir) / config.EVAL_MANIFEST_FILENAME)
    assert manifest["judge"]["model"] == "claude-opus-5"

    report = (artifact_of(run_dir) / config.REPORT_FILENAME).read_text(encoding="utf-8")
    assert "claude-opus-5" in report


def test_manifest_without_judge_info_still_works(make_run):
    run_dir, _, _ = make_run(make_records("a"))
    run_main(run_dir)
    write_answer(run_dir, "a")
    run_main(run_dir)

    manifest = common.read_json(artifact_of(run_dir) / config.EVAL_MANIFEST_FILENAME)
    assert manifest["judge"] == {}
    report = (artifact_of(run_dir) / config.REPORT_FILENAME).read_text(encoding="utf-8")
    assert "未登记" in report
