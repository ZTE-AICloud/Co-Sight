"""extract_verdict.py — 从 evaluator 报告里结构化抽取 verdict 并落 state。

evaluator 产出 `.drive/<plan_dir>/evaluation/verification-report.md`，
verdict 在报告的 `## Verdict: <pass|partial|fail>` 一行。

orchestrator 调本脚本，结构化解析该行后调 drive 本地 state_write 写进 state。
值合法性由本文件 ALLOWED_VERDICTS 守。

用法:
    python3 extract_verdict.py --planning-dir .planning --agent-id X
    python3 extract_verdict.py --planning-dir .planning --all-verdict-required '["a","b","c"]'
    python3 extract_verdict.py --planning-dir .planning --agent-id X --dry-run

`--all-verdict-required` 接受 JSON 数组，把同一 verdict 批量写入多个
verdict_required agent 的 state.verdicts[id]。

dry-run 模式只解析不写 state，便于调试。

退出码: 0 成功 / 1 失败。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from envelope import (  # noqa: E402
    Envelope,
    emit,
    REASON_FILE_MISSING,
    REASON_INVALID_ARG,
    REASON_SCHEMA_INVALID,
)
from state_write import read_state, update_fields

VERDICT_LINE_RE = re.compile(r"^##\s+Verdict:\s*(\S+)\s*$", re.MULTILINE)
ALLOWED_VERDICTS: frozenset[str] = frozenset({"pass", "partial", "fail"})

# evaluator.md line 94 写明路径
REPORT_PATH_TEMPLATE = "evaluation/verification-report.md"


def _report_path(planning_dir: Path) -> Path:
    return planning_dir / REPORT_PATH_TEMPLATE


def parse_verdict(report_text: str) -> str | None:
    """从报告正文里抽出 verdict。

    只匹配 `## Verdict: <value>` 整行（开头、单词边界、整词）。**不**做
    大小写归一化、不做语义改写、不容忍"verdict: pass"无标题层级的情况。
    evaluator 输出格式变 → 解析失败 → envelope.fail，比静默抽错更安全。
    """
    match = VERDICT_LINE_RE.search(report_text)
    if match is None:
        return None
    return match.group(1).strip().lower()


def extract(planning_dir: Path) -> Envelope:
    """读 report + 抽 verdict。结构化解析，全过程无 LLM 调用。"""
    report_path = _report_path(planning_dir)
    if not report_path.is_file():
        return Envelope.fail(
            REASON_FILE_MISSING,
            path=str(report_path),
            error="verifier report 不存在 —— evaluator 阶段没产出 verification-report.md",
        )
    try:
        text = report_path.read_text(encoding="utf-8")
    except OSError as exc:
        return Envelope.fail(
            REASON_FILE_MISSING, path=str(report_path), error=f"读 report 失败: {exc}"
        )

    verdict = parse_verdict(text)
    if verdict is None:
        return Envelope.fail(
            REASON_SCHEMA_INVALID,
            path=str(report_path),
            error="report 里没有匹配 `^## Verdict: <value>$` 的行",
            hint=(
                "evaluator 模板见 agents/evaluator.md line 96-99，"
                "## Verdict: pass | fail | partial 必填"
            ),
        )
    if verdict not in ALLOWED_VERDICTS:
        return Envelope.fail(
            REASON_SCHEMA_INVALID,
            path=str(report_path),
            verdict=verdict,
            error=f"verdict={verdict!r} 不在允许集 {sorted(ALLOWED_VERDICTS)}",
        )
    return Envelope.ok_envelope(verdict=verdict, source=str(report_path))


def write_verdict(planning_dir: Path, verdict: str, agent_id: str) -> Envelope:
    """写单个 verdict_required agent 的 verdict 到 state.verdicts[agent_id]。

    多次调用累积成 map（state.verdicts = {agent_id: verdict, ...}）。
    dag_runtime.check-terminal-verdict 对 map 做 AND。
    单 agent 模式（1 个 verdict_required agent）map 长度 = 1，与旧行为等价。
    """
    state_resp = read_state(planning_dir)
    if not state_resp.ok:
        return state_resp
    inner = state_resp.data.get("state", state_resp.data)
    verdicts = dict(inner.get("verdicts") or {})
    verdicts[agent_id] = verdict
    return update_fields(planning_dir, verdicts=verdicts)


def write_verdicts_batch(planning_dir: Path, verdict: str, agent_ids: list[str]) -> Envelope:
    """同一 verdict 批量写入多个 agent_id。"""
    state_resp = read_state(planning_dir)
    if not state_resp.ok:
        return state_resp
    inner = state_resp.data.get("state", state_resp.data)
    verdicts = dict(inner.get("verdicts") or {})
    for aid in agent_ids:
        verdicts[aid] = verdict
    return update_fields(planning_dir, verdicts=verdicts)


def _parse_agent_ids(raw: str) -> Envelope:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return Envelope.fail(REASON_INVALID_ARG, error=f"--all-verdict-required JSON 解析失败: {exc}")
    if not isinstance(parsed, list) or not all(isinstance(a, str) for a in parsed):
        return Envelope.fail(REASON_INVALID_ARG, error="--all-verdict-required 必须是字符串数组")
    return Envelope.ok_envelope(agent_ids=parsed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从 verifier report 抽 verdict 并写 state.verdicts[agent_id]")
    parser.add_argument("--planning-dir", required=True, type=Path)
    parser.add_argument(
        "--agent-id",
        help="verdict 所属 agent id（verdict_required=true 的那个 agent）；与 --all-verdict-required 互斥",
    )
    parser.add_argument(
        "--all-verdict-required",
        dest="all_verdict_required",
        help='verdict_required agent id JSON 数组，写入同一 verdict 到所有 agent',
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只解析不写 state，便于调试",
    )
    args = parser.parse_args(argv)

    if bool(args.agent_id) == bool(args.all_verdict_required):
        emit(Envelope.fail(
            REASON_INVALID_ARG,
            error="必须二选一传 --agent-id 或 --all-verdict-required",
        ))
        return 1

    planning_dir = args.planning_dir
    if not planning_dir.is_dir():
        emit(Envelope.fail(REASON_INVALID_ARG, error=f"--planning-dir 不是目录: {planning_dir}"))
        return 1

    extracted = extract(planning_dir)
    if not extracted.ok:
        emit(extracted)
        return 1

    verdict = extracted.data["verdict"]

    if args.all_verdict_required:
        parsed = _parse_agent_ids(args.all_verdict_required)
        if not parsed.ok:
            emit(parsed)
            return 1
        agent_ids = parsed.data["agent_ids"]
        if args.dry_run:
            emit(Envelope.ok_envelope(verdict=verdict, agent_ids=agent_ids, dry_run=True))
            return 0
        written = write_verdicts_batch(planning_dir, verdict, agent_ids)
        if not written.ok:
            emit(written)
            return 1
        emit(Envelope.ok_envelope(
            verdict=verdict,
            agent_ids=agent_ids,
            written=True,
            revision=written.data.get("revision"),
        ))
        return 0

    if args.dry_run:
        emit(Envelope.ok_envelope(verdict=verdict, agent_id=args.agent_id, dry_run=True))
        return 0
    written = write_verdict(planning_dir, verdict, args.agent_id)
    if not written.ok:
        emit(written)
        return 1
    emit(Envelope.ok_envelope(verdict=verdict, agent_id=args.agent_id, written=True, revision=written.data.get("revision")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
