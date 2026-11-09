#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_tests.py — e2e-test-runner 的唯一入口。

读取 e2e-test-generator 落盘的 seed.jsonl，按 concurrency 并发调度 claude -p
执行每个用例，收集会话数据，并把执行结果回写到 seed.jsonl 的 run 子对象。

整个流程不需要 LLM 出力，因此没有生成器那样的断点续跑循环：本脚本跑完即交付。
（"续跑"是另一回事——已带 run 字段的用例会被跳过，见 SKILL.md。）

用法：
    python3 run_tests.py [--input <run目录|generated_datasets|seed.jsonl>]
                         [--output <run 目录>] [--agent <被测 agent 目录>]
                         [--concurrency N]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import config
from common import (
    RunnerError,
    case_id_of,
    copy_session_log,
    fail,
    input_of,
    locate_seed,
    read_json,
    read_jsonl,
    resolve_agent_root,
    run_dir_of,
    sha256_tree,
    timeout_of,
    write_json,
    write_jsonl,
    write_text,
)


# ============================== 单用例执行 ==============================

def _extract_partial_result(text: str) -> str:
    """从超时截断的半截 JSON 里抢救 "result" 字段。"""
    if not text or len(text) < 50:
        return ""
    marker = '"result":"'
    idx = text.find(marker)
    if idx < 0:
        return ""
    start = idx + len(marker)
    end = start
    while end < len(text):
        if text[end] == '"' and (end + 1 >= len(text) or text[end - 1] != "\\"):
            return text[start:end]
        end += 1
    return text[start:]


def _result_text_of(value) -> str:
    """把 result 字段归一为文本：字符串原样返回，其余结构做 JSON 序列化。

    preview 的契约是"恒为字符串"，而 claude 的 result 恒为字符串；非字符串只出现
    在异常输出里。序列化而非丢弃，是为了让下游裁判仍能看到原始证据。
    """
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False)


def _save_result_json(case_dir: Path, stdout_text: str) -> tuple:
    """把 claude 的 JSON 输出落盘，返回 (result 文本, CLI 自报的 session_id)。

    三种情形：
      - 合法 JSON         → 原样落盘，取 result 字段
      - 半截 JSON（超时） → 抢救 result 字段，落盘带 partial_result 标记
      - 无法解析          → 落盘带 parse_error 标记 + 完整原始 stdout
    各情形都保存完整文本，不设长度上限。
    stdout 为空时**不产生该文件**（写个空壳比缺席更误导）。

    只有第一种情形能拿到 session_id——后两种正是"会话日志已落盘、result 里却
    没有 id"的场合，这也是 id 必须由 runner 预生成的原因。
    """
    if not stdout_text:
        return "", ""
    try:
        payload = json.loads(stdout_text)
    except json.JSONDecodeError:
        partial = _extract_partial_result(stdout_text)
        if partial:
            write_json(case_dir / config.CASE_RESULT,
                       {"partial_result": True, "extracted_text": partial})
            return partial, ""
        write_json(case_dir / config.CASE_RESULT,
                   {"parse_error": True, "raw": stdout_text})
        return stdout_text, ""

    write_json(case_dir / config.CASE_RESULT, payload)
    if not isinstance(payload, dict):
        return "", ""
    return _result_text_of(payload.get("result")), str(payload.get("session_id") or "")


def collect_session_log(case_dir: Path, session_id: str,
                        reported_session_id: str = "", roots=None) -> dict:
    """把该会话的日志拷进 case_dir/sessions/，返回 run 子对象所需的会话三项。

    **日志缺失不算用例失败**：status 归被测 Agent（跑没跑成，由 exit_code 派生），
    session_error 归基建（日志录没录到）。因此这里只回写字段，绝不改 status，
    也绝不抛错打断整轮。找不到时只记原因、不写 session_dir——照着路径找不找得到，
    以 session_error 为准（与 workspace_dir 的既有约定一致）。

    契约：session_dir 与 session_error **互斥**，成功的标志是 session_dir 在、
    session_error 不在。调用方若往已有记录上合并（补拷就是），必须先清掉旧的
    session_error，否则记录会同时声称"已归档"和"缺失"。
    """
    session_dir = case_dir / config.SESSION_DIRNAME
    try:
        copied = copy_session_log(session_id, session_dir, roots)
    except OSError as exc:
        return {
            config.RUN_SESSION_ID: session_id,
            config.RUN_SESSION_ERROR: f"{config.SESSION_ERROR_COPY_FAILED}: {exc}",
        }

    if not copied:
        return {
            config.RUN_SESSION_ID: session_id,
            config.RUN_SESSION_ERROR: config.SESSION_ERROR_NOT_FOUND,
        }

    # id 是我们自己生成的，CLI 原样回显；对不上说明中间有环节不按约定来，
    # 以预生成的那个为准（日志文件名也是它），但要留痕。
    if reported_session_id and reported_session_id != session_id:
        print(f"WARN: {case_dir.name} 的 result.json 自报 session_id "
              f"{reported_session_id}，与实际使用的 {session_id} 不符；"
              f"以预生成值为准。", file=sys.stderr)

    return {
        config.RUN_SESSION_ID: session_id,
        config.RUN_SESSION_DIR: str(session_dir.resolve()),
    }


def prepare_workspace(case_dir: Path, agent_root: Path) -> Path:
    """为该用例铺一份 agent_root 副本，返回副本路径。

    旧副本先整目录删除再复制：用户重跑某条用例时会手工删掉 seed 记录里的 run 字段，
    但不一定记得删用例目录，此时残留副本会让"重跑"跑在脏环境上——擦除保证
    "重跑 = 干净起点"这个承诺真的成立。

    复制失败（源不存在、磁盘满、权限不足）由调用方按"单用例崩溃不带走整轮"处理。
    """
    workspace = case_dir / config.WORKSPACE_DIRNAME
    if workspace.resolve().is_relative_to(agent_root.resolve()):
        raise RunnerError(
            f"用例副本会落在 agent_root 内部，复制将无限递归：\n"
            f"  workspace : {workspace}\n"
            f"  agent_root: {agent_root}\n"
            f"  产物目录必须在被测目录之外。请把 --output 指到 agent_root 之外，"
            f"或换一个 --agent。"
        )
    if workspace.is_symlink() or workspace.exists():
        # 兼容手工遗留的符号链接：rmtree 对链接会报错，先解链
        if workspace.is_symlink():
            workspace.unlink()
        else:
            shutil.rmtree(workspace)
    shutil.copytree(agent_root, workspace)
    return workspace


def check_source_integrity(agent_root: Path, seed_path: Path) -> dict:
    """比对 agent_root 的实算树哈希与生成器 manifest 里记录的哈希，返回环境记录。

    不符即说明源目录在上次生成之后被写过（典型是上一轮评测留下的报告文件）。
    那种情况下这些残留会被原样复制进每一份副本——隔离了用例之间，却把污染固化成
    共同起点。**只告警、不阻断**：用户可能是有意改了 agent 再想重测，此时拦下来
    反而碍事；实算哈希落进 run-manifest.json，事后仍可追溯。

    生成器侧的 manifest 缺失（--agent 手工指定、旧测试集）时无从比对，记 null。
    """
    manifest = read_json(seed_path.parent / config.MANIFEST_FILENAME)
    expected = (manifest or {}).get("agent_sha256") or None
    observed = sha256_tree(agent_root)
    matches = None if expected is None else expected == observed

    if matches is False:
        print(f"WARN: agent_root 内容与生成时不一致，上一轮残留会被复制进全部副本：\n"
              f"      生成时: {expected}\n"
              f"      当前  : {observed}\n"
              f"      若要干净起点，先清理 {agent_root}（如报告文件、__pycache__）再跑。",
              file=sys.stderr)

    return {
        config.AGENT_ROOT_KEY: str(agent_root),
        "agent_sha256_expected": expected,
        "agent_sha256_observed": observed,
        "matches": matches,
        "isolation": "per-case-copy",
    }


def wipe_session_dir(case_dir: Path) -> None:
    """清空该用例的会话日志目录。

    与 prepare_workspace 同一时点、同一手法，兑现同一个承诺：**重跑 = 干净起点**。
    重跑会生成新的 session_id，不擦除的话新旧两份会话会并排躺在 sessions/ 里，
    而 run.session_dir 只指得到目录——光看目录分不出哪份属于本轮。
    """
    session_dir = case_dir / config.SESSION_DIRNAME
    if session_dir.is_symlink():
        session_dir.unlink()
    elif session_dir.exists():
        shutil.rmtree(session_dir)


def run_one_case(record: dict, index: int, artifact_dir: Path, agent_root: Path,
                 session_log_roots=None) -> dict:
    """执行单个用例，落盘 5 件产物，返回 run 子对象。

    用例跑在 case_dir/workspace/ 这份 agent_root 副本里，因此产物不写回源目录、
    也不被其他用例看见。

    session_log_roots 透传给日志搜索，缺省走 config.SESSION_LOG_GLOBS；测试用它
    把搜索根指到临时目录，避免每跑一条用例都去扫真实的 home。
    """
    case_id = case_id_of(record, index)
    prompt = input_of(record, index)
    timeout = timeout_of(record)

    case_dir = artifact_dir / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    workspace = prepare_workspace(case_dir, agent_root)
    wipe_session_dir(case_dir)

    # id 由我们生成而不是从 result 里读：超时被 kill、stdout 无法解析、CLI 缺失这
    # 三种场合拿不到 result，但会话日志照样已经增量落盘，只有手里的 id 能找到它。
    session_id = str(uuid.uuid4())

    t0 = time.time()
    timed_out = False
    exit_code = None
    stdout_text = ""
    stderr_text = ""

    try:
        proc = subprocess.Popen(
            [config.CLAUDE_CLI, *config.CLAUDE_ARGS,
             config.CLAUDE_SESSION_ID_FLAG, session_id],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(workspace),
            env={**os.environ, **config.CLAUDE_ENV_EXTRA},
        )
        try:
            stdout_text, stderr_text = proc.communicate(input=prompt, timeout=timeout)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            try:
                stdout_text, stderr_text = proc.communicate(timeout=config.KILL_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                proc.terminate()
                stdout_text, stderr_text = proc.communicate()
            stdout_text = stdout_text or ""
            stderr_text = stderr_text or ""
    except FileNotFoundError:
        stderr_text = f"{config.CLAUDE_CLI} CLI not found"
        exit_code = 127

    elapsed = round(time.time() - t0, 1)

    write_text(case_dir / config.CASE_STDOUT, stdout_text)
    write_text(case_dir / config.CASE_STDERR, stderr_text)
    write_json(case_dir / config.CASE_TIMING, {
        config.RUN_ELAPSED: elapsed,
        config.RUN_EXIT_CODE: exit_code,
        config.RUN_TIMED_OUT: timed_out,
    })

    result_text, reported_session_id = _save_result_json(case_dir, stdout_text)

    if timed_out:
        status = config.STATUS_TIMEOUT
    elif exit_code == 0:
        status = config.STATUS_PASSED
    else:
        status = config.STATUS_FAILED

    info = {
        config.RUN_STATUS: status,
        config.RUN_EXIT_CODE: exit_code,
        config.RUN_ELAPSED: elapsed,
        config.RUN_TIMED_OUT: timed_out,
        config.RUN_RESULT_PREVIEW: result_text,
        config.RUN_CASE_DIR: str(case_dir.resolve()),
        config.RUN_WORKSPACE_DIR: str(workspace.resolve()),
    }
    # 会话日志在 status 定下来之后再收：它只增补字段，不改 status。
    info.update(collect_session_log(case_dir, session_id, reported_session_id,
                                    session_log_roots))
    return info


# ============================== 用例集合装配 ==============================

def build_records(input_records: list, output_seed: Path) -> tuple:
    """装配工作记录集：续跑时用 output 侧已带 run 的记录覆盖 input 侧。

    返回 (records, skipped_count)。
    """
    prior = {}
    if output_seed.is_file():
        prior_records = read_jsonl(output_seed)
        prior = {str(r.get(config.DATA_ID_KEY)): r for r in prior_records}

        input_ids = [str(r.get(config.DATA_ID_KEY)) for r in input_records]
        prior_ids = [str(r.get(config.DATA_ID_KEY)) for r in prior_records]
        if input_ids != prior_ids:
            raise RunnerError(
                f"输入测试集与已有结果对不上：\n"
                f"  --input : {len(input_ids)} 条\n"
                f"  已有结果: {len(prior_ids)} 条\n"
                f"  位置    : {output_seed}\n"
                f"  续跑要求两次的用例集合完全一致。要换测试集请先删除：\n"
                f"    rm -rf {output_seed.parent}"
            )

    records = []
    skipped = 0
    for record in input_records:
        data_id = str(record.get(config.DATA_ID_KEY))
        merged = dict(record)
        if data_id in prior and config.RUN_KEY in prior[data_id]:
            merged[config.RUN_KEY] = prior[data_id][config.RUN_KEY]
            skipped += 1
        records.append(merged)
    return records, skipped


def backfill_sessions(records: list, artifact_dir: Path, session_log_roots=None) -> tuple:
    """给"已有 run 但缺 session_dir"的旧记录补拷会话日志，返回 (尝试数, 成功数)。

    续跑契约是"已带 run 的用例会被跳过"，于是拷贝失败的用例永远等不到第二次机会
    ——而重跑整条既花一次 API 费用、答案还可能不同、历史结果也没了，可你只是想要
    一份本就躺在磁盘上的日志。

    **只动会话三项**：status / exit_code / elapsed_seconds 是被测 Agent 的既成结果，
    不该因为事后补录日志而变化。

    0.1.0 留下的旧记录没有 session_id（那一版开了 --no-session-persistence，日志
    压根没落盘），这里按"拿不到钥匙"跳过，不会去猜。
    """
    attempted = 0
    recovered = 0
    for index, record in enumerate(records):
        run = record.get(config.RUN_KEY)
        if not isinstance(run, dict) or config.RUN_SESSION_DIR in run:
            continue
        session_id = str(run.get(config.RUN_SESSION_ID) or "").strip()
        if not session_id:
            continue

        attempted += 1
        try:
            case_id = case_id_of(record, index)
            case_dir = artifact_dir / case_id
            fields = collect_session_log(case_dir, session_id,
                                         roots=session_log_roots)
        except Exception as exc:  # 补拷失败不该带走整轮
            fields = {config.RUN_SESSION_ID: session_id,
                      config.RUN_SESSION_ERROR:
                          f"{config.SESSION_ERROR_COPY_FAILED}: {exc}"}

        # 先清旧的失败痕迹，再合并：session_dir 与 session_error 互斥，
        # 否则记录会同时声称"已归档"和"缺失"。
        run.pop(config.RUN_SESSION_ERROR, None)
        run.update(fields)
        if config.RUN_SESSION_DIR in run:
            recovered += 1
    return attempted, recovered


# ============================== 主流程 ==============================

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="E2E Test Runner — 按 seed.jsonl 并发调度 claude -p 并回写结果")
    parser.add_argument("--input", default=None,
                        help="seed.jsonl 来源。可指 run 目录 / generated_datasets 目录 / "
                             "seed.jsonl 文件；缺省取 outputs/ 下时间戳最新的 e2e-test* 目录")
    parser.add_argument("--output", default=None,
                        help="run 目录，产物落其下的 run_datasets/；"
                             "缺省用 --input 解析出的同一个 run 目录")
    parser.add_argument("--agent", default=None,
                        help="被测 agent 根目录（并发调度的共享 cwd）；"
                             "缺省读输入侧 manifest.json 的 agent_root")
    parser.add_argument("--concurrency", type=int, default=config.DEFAULT_CONCURRENCY,
                        help=f"并发数（默认 {config.DEFAULT_CONCURRENCY}，"
                             f"范围 {config.MIN_CONCURRENCY}~{config.MAX_CONCURRENCY}）")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    if not config.MIN_CONCURRENCY <= args.concurrency <= config.MAX_CONCURRENCY:
        fail(f"--concurrency 必须在 {config.MIN_CONCURRENCY}~{config.MAX_CONCURRENCY} 之间，"
             f"收到 {args.concurrency}")

    seed_path = locate_seed(args.input)

    run_dir = Path(args.output).expanduser().resolve() if args.output else run_dir_of(seed_path)
    artifact_dir = run_dir / config.OUTPUT_ARTIFACT_DIRNAME
    output_seed = artifact_dir / config.SEED_FILENAME

    # 输入侧的 seed 是我们唯一的只读事实来源，绝不能被自己的产物覆盖写回。
    # 这条校验先于 --agent 解析：它更根本，且不依赖 agent 能否解析出来。
    if seed_path == output_seed:
        fail(f"--output 指向的 run 目录会覆盖 --input 的 seed.jsonl：\n"
             f"  {seed_path}\n"
             f"  请换一个 --output，或换一份 --input。")

    agent_root = resolve_agent_root(args.agent, seed_path)

    # 副本一律落在 artifact_dir 之下，因此只要产物目录不在被测目录内，复制就安全。
    # 早失败：否则每条用例都会各自崩在复制上，N 条报错反而不如一条来得清楚。
    if artifact_dir.resolve().is_relative_to(agent_root.resolve()):
        fail(f"产物目录在被测目录内部，用例副本会递归复制自己：\n"
             f"  --output → {artifact_dir}\n"
             f"  --agent  → {agent_root}\n"
             f"  请把 --output 指到 agent_root 之外。")

    integrity = check_source_integrity(agent_root, seed_path)

    input_records = read_jsonl(seed_path)
    if not input_records:
        fail(f"测试集为空：{seed_path}")

    records, skipped = build_records(input_records, output_seed)

    print(f"E2E Test Runner {config.TOOL_VERSION}")
    print(f"Input:       {seed_path}")
    print(f"Output:      {artifact_dir}")
    print(f"Agent(src):  {agent_root}")
    print(f"Isolation:   每用例复制到 {config.WORKSPACE_DIRNAME}/ 后执行（源目录只读）")
    print(f"Cases:       {len(records)}" + (f"（跳过已完成 {skipped}，待跑 {len(records) - skipped}）"
                                            if skipped else ""))
    print(f"Concurrency: {args.concurrency}")
    print()

    artifact_dir.mkdir(parents=True, exist_ok=True)
    write_json(artifact_dir / config.RUN_MANIFEST_FILENAME, integrity)

    pending = [
        (idx, rec) for idx, rec in enumerate(records)
        if config.RUN_KEY not in rec
    ]

    lock = threading.Lock()

    def persist() -> None:
        """把当前全部记录写回 output 侧 seed.jsonl（保持原始顺序）。"""
        with lock:
            write_jsonl(output_seed, records)

    # 即使本轮无事可做也要落盘：续跑时 output 侧可能还不存在该文件
    persist()

    # 补拷排在调度之前：它只碰已跳过的记录，先做完再跑新用例，输出顺序更好读。
    backfilled, recovered = backfill_sessions(records, artifact_dir)
    if backfilled:
        print(f"Sessions:    补拷历史记录的会话日志 {recovered}/{backfilled} 条")
        print()
        persist()

    if pending:
        done = 0
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = {
                pool.submit(run_one_case, rec, idx, artifact_dir, agent_root): (idx, rec)
                for idx, rec in pending
            }
            for future in as_completed(futures):
                idx, rec = futures[future]
                case_id = str(rec.get(config.DATA_ID_KEY))
                done += 1
                try:
                    run_info = future.result()
                except Exception as exc:  # 单用例崩溃不应带走整轮
                    run_info = {
                        config.RUN_STATUS: config.STATUS_FAILED,
                        config.RUN_EXIT_CODE: None,
                        config.RUN_ELAPSED: 0.0,
                        config.RUN_TIMED_OUT: False,
                        config.RUN_RESULT_PREVIEW: "",
                        config.RUN_CASE_DIR: str((artifact_dir / case_id).resolve()),
                        # 崩在 prepare_workspace 时副本可能压根没建成；路径仍照常给出，
                        # 下游按"该路径可能不存在"处理（与 case_dir 同样只作定位线索）
                        config.RUN_WORKSPACE_DIR: str(
                            (artifact_dir / case_id / config.WORKSPACE_DIRNAME).resolve()
                        ),
                        config.RUN_ERROR: f"{type(exc).__name__}: {exc}",
                    }
                records[idx][config.RUN_KEY] = run_info
                persist()

                label = {"passed": "PASS", "timeout": "TIME", "failed": "FAIL"}.get(
                    run_info[config.RUN_STATUS], "????")
                print(f"[{done}/{len(pending)}] {case_id} {label} "
                      f"({run_info[config.RUN_ELAPSED]:.0f}s)", flush=True)

    persist()

    # 退出码口径是**整份 seed.jsonl 的最终结果**，而非本轮新跑的部分
    counts = {config.STATUS_PASSED: 0, config.STATUS_FAILED: 0, config.STATUS_TIMEOUT: 0}
    for rec in records:
        status = (rec.get(config.RUN_KEY) or {}).get(config.RUN_STATUS)
        if status in counts:
            counts[status] += 1

    # 会话日志单独计数：它缺失**不**影响退出码。status 归被测 Agent，日志归基建，
    # 把基建故障算进退出码等于让答对的 Agent 背锅（且会污染下游的通过率口径）。
    session_ok = sum(1 for rec in records
                     if config.RUN_SESSION_DIR in (rec.get(config.RUN_KEY) or {}))
    session_bad = sum(1 for rec in records
                      if config.RUN_SESSION_ERROR in (rec.get(config.RUN_KEY) or {}))

    bad = counts[config.STATUS_FAILED] + counts[config.STATUS_TIMEOUT]
    print()
    print("=" * 60)
    print("Run Summary")
    print("=" * 60)
    print(f"  Passed:   {counts[config.STATUS_PASSED]}")
    print(f"  Timeout:  {counts[config.STATUS_TIMEOUT]}")
    print(f"  Failed:   {counts[config.STATUS_FAILED]}")
    print(f"  Skipped:  {skipped}")
    print(f"  Sessions: {session_ok} 条已归档"
          + (f"，{session_bad} 条缺失（详见 run.session_error）" if session_bad else ""))
    print(f"  Datasets: {artifact_dir}")
    print(f"  Cases:    {artifact_dir}/<data_id>/")
    print(f"  Manifest: {output_seed}")

    if session_bad:
        print(f"WARN: {session_bad} 条用例没有拿到会话日志。用例本身的结果不受影响"
              f"（status 仍按 exit_code 判定），但缺少 trace 会让下游的轨迹评测"
              f"无从下手。逐条的 run.session_error 给出原因。", file=sys.stderr)

    return 1 if bad else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RunnerError as exc:
        fail(str(exc))
