#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""evaluate.py — e2e-test-evaluator 的唯一入口。

两阶段同一条命令（不加 --work、不加 --stage）：每次启动都扫 `.work/` 找还缺哪些
裁判答案——缺就打印批次清单并退出（主 agent 据此派 Task），不缺就聚合落盘。状态全在
目录里，位置由 --output 唯一确定，于是没有第二个"阶段参数"要说谎的余地。

本脚本**不含任何 LLM 调用**：裁判是主 agent 派的 Task，不在这里。
"""

import argparse
import sys
from pathlib import Path

import aggregate
import common
import config
import render
import validate


# ============================== 参数 ==============================

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="E2E Test Evaluator — 按 runtime-rubric 评测 run_datasets 的执行结果")
    parser.add_argument(
        "--input", default=None,
        help="seed.jsonl 来源。可指 run 目录 / run_datasets 目录 / seed.jsonl 文件；"
             "缺省取 outputs/ 下目录名倒序第一个 e2e-test* 目录")
    parser.add_argument(
        "--output", default=None,
        help="run 目录，产物落其下的 eval_datasets/；缺省同样取 outputs/ 下"
             "倒序第一个 e2e-test* 目录")
    parser.add_argument(
        "--concurrency", type=int, default=config.DEFAULT_CONCURRENCY,
        help=f"裁判并发数（默认 {config.DEFAULT_CONCURRENCY}，"
             f"范围 {config.MIN_CONCURRENCY}~{config.MAX_CONCURRENCY}）")
    return parser.parse_args(argv)


# ============================== 产物路径 ==============================

def _attempts_path(work_dir: Path, data_id: str) -> Path:
    return work_dir / f"{data_id}{config.ATTEMPTS_SUFFIX}"


def _prompt_path(work_dir: Path, data_id: str) -> Path:
    return work_dir / f"{data_id}{config.PROMPT_SUFFIX}"


def _answer_path(work_dir: Path, data_id: str) -> Path:
    return work_dir / f"{data_id}{config.ANSWER_SUFFIX}"


def _read_attempts(work_dir: Path, data_id: str) -> int:
    try:
        return int(_attempts_path(work_dir, data_id).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def _write_attempts(work_dir: Path, data_id: str, count: int) -> None:
    common.write_text(_attempts_path(work_dir, data_id), f"{count}\n")


# ============================== 用例集合装配 ==============================

def build_records(input_records: list, output_seed: Path) -> list:
    """装配工作记录集：续跑时用 output 侧已带 eval 的记录覆盖 input 侧。

    用例集合（data_id 序列）必须与已有结果完全一致——避免把两份不同的测试集混进
    同一份结果里。
    """
    if not output_seed.is_file():
        return [dict(r) for r in input_records]

    prior_records = common.read_jsonl(output_seed)
    input_ids = [str(r.get(config.DATA_ID_KEY)) for r in input_records]
    prior_ids = [str(r.get(config.DATA_ID_KEY)) for r in prior_records]
    if input_ids != prior_ids:
        raise common.EvalError(
            f"输入测试集与已有结果对不上：\n"
            f"  --input : {len(input_ids)} 条\n"
            f"  已有结果: {len(prior_ids)} 条\n"
            f"  位置    : {output_seed}\n"
            f"  续跑要求两次的用例集合完全一致。要换测试集请先删除：\n"
            f"    rm -rf {output_seed.parent}"
        )

    prior = {str(r.get(config.DATA_ID_KEY)): r for r in prior_records}
    records = []
    for record in input_records:
        data_id = str(record.get(config.DATA_ID_KEY))
        merged = dict(record)
        if config.EVAL_KEY in prior[data_id]:
            merged[config.EVAL_KEY] = prior[data_id][config.EVAL_KEY]
        records.append(merged)
    return records


# ============================== 批次切分 ==============================

def make_batches(data_ids: list, concurrency: int) -> list:
    """按 concurrency 切成批次屏障（如 5 条 / 2 → [2, 2, 1]）。

    批内并发、批间串行：规则确定、可复现，主 agent 不必自己算。滑动窗口墙钟更优，
    但要求主 agent 依赖完成通知逐个补发，那个行为对 LLM 不是确定性的。
    """
    return [data_ids[i:i + concurrency] for i in range(0, len(data_ids), concurrency)]


# ============================== 阶段一：准备 ==============================

def prepare(records: list, work_dir: Path, concurrency: int) -> tuple:
    """给待评用例渲染 prompt，返回 (待派清单, 因尝试超限而放弃的清单)。

    已存在且校验通过的答案直接复用（续跑）；不存在或不合格的进待派清单。
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    pending, exhausted = [], []

    for index, record in enumerate(records, 1):
        data_id = common.case_id_of(record, index)
        if config.EVAL_KEY in record:
            continue  # 已有最终结论，跳过

        expected = common.expected_output_of(record, index)
        answer_path = _answer_path(work_dir, data_id)

        # 答案已在且合格 → 不必再派，交给聚合阶段直接用
        if answer_path.is_file():
            verdict = validate.validate_answer(answer_path, expected, data_id)
            if verdict.ok:
                continue

        attempts = _read_attempts(work_dir, data_id)
        if attempts >= config.MAX_JUDGE_ATTEMPTS:
            exhausted.append((data_id, _last_failure(work_dir, answer_path, expected, data_id)))
            continue

        prompt_path = _prompt_path(work_dir, data_id)
        common.write_text(prompt_path,
                          render.render_case_prompt(record, index, answer_path))
        _write_attempts(work_dir, data_id, attempts + 1)
        pending.append((data_id, prompt_path))

    return pending, exhausted


def _last_failure(work_dir: Path, answer_path: Path, expected: list, data_id: str) -> str:
    """取该条最后一次失败的原因，用于最终单列时的归因。"""
    if answer_path.is_file():
        return validate.validate_answer(answer_path, expected, data_id).reason
    return f"连续 {config.MAX_JUDGE_ATTEMPTS} 次未能产出裁判答案"


# ============================== 阶段二：聚合 ==============================

def collect(records: list, work_dir: Path, abandoned: dict) -> None:
    """把 `.work/` 里的裁判答案折成 eval 子对象，就地写回 records。"""
    for index, record in enumerate(records, 1):
        if config.EVAL_KEY in record:
            continue
        data_id = common.case_id_of(record, index)
        expected = common.expected_output_of(record, index)
        answer_path = _answer_path(work_dir, data_id)

        verdict = validate.validate_answer(answer_path, expected, data_id)
        if verdict.ok:
            record[config.EVAL_KEY] = aggregate.build_eval(verdict.answer, expected)
        else:
            reason = abandoned.get(data_id) or verdict.reason
            record[config.EVAL_KEY] = aggregate.build_parse_error(reason)
        record[config.EVAL_KEY][config.EVAL_ATTEMPTS] = _read_attempts(work_dir, data_id)


# ============================== 清单与横幅 ==============================

def print_banner(seed_path: Path, artifact_dir: Path, records: list,
                 concurrency: int, skipped: int) -> None:
    print(f"E2E Test Evaluator {config.TOOL_VERSION}")
    print(f"Input:       {seed_path}")
    print(f"Output:      {artifact_dir}")
    print(f"Rubric:      {render.RUBRIC_PATH}")
    print(f"Cases:       {len(records)}"
          + (f"（跳过已评测 {skipped}）" if skipped else ""))
    print(f"Concurrency: {concurrency}")
    print()


def print_batches(pending: list, concurrency: int, artifact_dir: Path) -> None:
    """打印主 agent 照做的批次清单。"""
    batches = make_batches([data_id for data_id, _ in pending], concurrency)
    prompt_of = {data_id: path for data_id, path in pending}

    print()
    print("=" * 72)
    print(f"需要你出力：{len(pending)} 条用例待裁判，分 {len(batches)} 批")
    print("=" * 72)
    print()
    print(f"请用 claude 类型 sub agent 并发评测。每批**同时**发出该批全部 Task，")
    print(f"等整批返回后再发下一批。每个 Task 的 prompt 只说：")
    print()
    print("  读取 <prompt 文件绝对路径> 并严格按其中指示执行，")
    print("  把最终 JSON 写到其中指定的 answer 文件。")
    print()
    print("**不要自己读 prompt 的内容，也不要自己打分。**")
    print()
    for number, batch in enumerate(batches, 1):
        print(f"第 {number} 批（并发 {len(batch)}）：")
        for data_id in batch:
            print(f"  - {data_id}")
            print(f"      {prompt_of[data_id]}")
        print()
    print("全部批次完成后，重跑同一条命令即可聚合落盘：")
    print()
    print(f"  python3 {Path(__file__).resolve()} "
          f"--input {artifact_dir.parent} --output {artifact_dir.parent} "
          f"--concurrency {concurrency}")
    print()


def print_summary(records: list, summary: dict, artifact_dir: Path) -> None:
    print()
    print("=" * 72)
    print("Eval Summary")
    print("=" * 72)
    print(f"  有效样本:   {len(summary['valid'])} / {summary['total']}")
    print(f"  通过:       {summary['passed_count']}（通过率 {summary['pass_rate']}）")
    print(f"  无效样本:   {len(summary['invalid'])}（run_valid=false，不计入均值）")
    print(f"  解析失败:   {len(summary['broken'])}")
    print(f"  加权平均分: {aggregate.fmt(summary['weighted_mean'])}")
    for dim in config.DIMENSIONS:
        print(f"    {dim:<18} {aggregate.fmt(summary['dimension_means'][dim])}")
    print(f"  Datasets:   {artifact_dir}")
    print(f"  Report:     {artifact_dir / config.REPORT_FILENAME}")


# ============================== 主流程 ==============================

def main(argv=None) -> int:
    args = parse_args(argv)

    if not config.MIN_CONCURRENCY <= args.concurrency <= config.MAX_CONCURRENCY:
        common.fail(f"--concurrency 必须在 {config.MIN_CONCURRENCY}~"
                    f"{config.MAX_CONCURRENCY} 之间，收到 {args.concurrency}")

    seed_path = common.locate_seed(args.input)
    run_dir = common.resolve_output_dir(args.output, seed_path)
    artifact_dir = (run_dir / config.OUTPUT_ARTIFACT_DIRNAME).resolve()
    output_seed = artifact_dir / config.SEED_FILENAME
    work_dir = artifact_dir / config.WORK_DIRNAME

    if not render.RUBRIC_PATH.is_file():
        common.fail(f"评分细则缺失：{render.RUBRIC_PATH}")

    common.guard_no_seed_overwrite(seed_path, output_seed)

    input_records = common.read_jsonl(seed_path)
    if not input_records:
        common.fail(f"测试集为空：{seed_path}")
    common.require_executed(input_records)

    # 防泄题守卫先于任何写入：.work/ 下的 prompt 含 expected_output（=答案），
    # 一旦落进被测 Agent 的工作副本，重跑就会被读到，且失真不可见。
    common.guard_no_answer_leak(artifact_dir, input_records, seed_path.parent)
    common.guard_no_agent_root_write(artifact_dir, seed_path.parent)

    records = build_records(input_records, output_seed)
    for index, record in enumerate(records, 1):
        common.expected_output_of(record, index)

    skipped = sum(1 for r in records if config.EVAL_KEY in r)
    print_banner(seed_path, artifact_dir, records, args.concurrency, skipped)

    artifact_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    pending, exhausted = prepare(records, work_dir, args.concurrency)

    if pending or exhausted:
        if pending:
            print_batches(pending, args.concurrency, artifact_dir)
        if exhausted:
            print()
            print(f"注意：{len(exhausted)} 条连续 {config.MAX_JUDGE_ATTEMPTS} 次未产出合格答案，"
                  f"本轮不再派发，将在报告中单列：")
            for data_id, reason in exhausted:
                print(f"  - {data_id}：{reason}")
            print()
        if pending:
            # 有活要派：先落盘当前进度（可能 0 条），让主 agent 派完再回来
            common.write_jsonl(output_seed, records)
            return 0

    abandoned = dict(exhausted)
    collect(records, work_dir, abandoned)
    common.write_jsonl(output_seed, records)

    summary = aggregate.summarize(records)
    manifest = load_manifest(artifact_dir, seed_path, args.concurrency)
    common.write_json(artifact_dir / config.EVAL_MANIFEST_FILENAME, manifest)
    common.write_text(
        artifact_dir / config.REPORT_FILENAME,
        aggregate.render_report(run_dir.name, summary, manifest))

    print()
    print("落盘完成")
    print_summary(records, summary, artifact_dir)

    # 退出码只表达"评测是否正常完成"，不表达 Agent 考得好不好：
    # 否则 set -e 的脚本会在 Agent 表现差时中断，而那恰恰是想看结果的时刻。
    return 0


# ============================== manifest ==============================

def load_manifest(artifact_dir: Path, seed_path: Path, concurrency: int) -> dict:
    """环境记录。裁判模型标识由主 agent 写在 judge.json 里——只有它知道自己的模型，
    脚本猜不准。文件缺席不报错，报告里显示"未登记"。
    """
    judge = common.read_json(artifact_dir / config.JUDGE_INFO_FILENAME) or {}
    return {
        "tool_version": config.TOOL_VERSION,
        "input_seed": str(seed_path),
        "rubric_path": str(render.RUBRIC_PATH),
        "rubric_sha256": common.sha256_file(render.RUBRIC_PATH),
        "concurrency": concurrency,
        "thresholds": {
            "weighted": config.THRESHOLD_WEIGHTED,
            "correctness": config.THRESHOLD_CORRECTNESS,
            "completeness": config.THRESHOLD_COMPLETENESS,
        },
        "dimension_weights": dict(config.DIMENSION_WEIGHTS),
        "judge": judge,
    }


if __name__ == "__main__":
    try:
        sys.exit(main())
    except common.EvalError as exc:
        common.fail(str(exc))
