"""review_flow.py — execute 阶段 review 子流程的确定性判定。

两个子命令，都吃 worker summary 数组，都不调 LLM：

  select  哪些 task 需要 review。orchestrator 在派 reviewer 前调一次，在
          wave barrier 前自检"该有 REVIEW.md 却没有"时再调一次 —— 两处共用
          同一判定，不会出现"派的时候跳过、自检时又认为该有"的不一致。

  merge   按 task_id 去重，同 id 取最后一条。重派后 orchestrator 手里同一个
          task_id 有两版 summary，aggregate.py 对重复 task_id 直接判 fail，
          所以传进去之前必须先合流。

用法:
    python3 review_flow.py select --summaries-file /tmp/s.json
    python3 review_flow.py merge  --summaries-file /tmp/s.json
    echo '<json>' | python3 review_flow.py select --stdin

summaries 是 JSON 数组，每项是 executor 返回的 summary。

退出码: 0 成功 / 1 失败（Envelope.fail），与 state_cli / read_workflow 一致。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from envelope import (  # noqa: E402
    Envelope,
    REASON_INVALID_ARG,
    REASON_SCHEMA_INVALID,
    REASON_FILE_MISSING,
)


# ---- 触发条件 ----

# 只有 code 模式的产出有代码可审。analysis 模式产出 markdown / JSON 报告，
# 没有注入面也没有密钥面。
REVIEWABLE_MODE = "code"

# 纯文档改动无代码可审。按后缀判断，大小写不敏感。
DOC_SUFFIXES: frozenset[str] = frozenset({
    ".md", ".markdown", ".txt", ".rst", ".json", ".yaml", ".yml", ".toml", ".ini",
    ".csv", ".tsv", ".lock",
})

# simple 类 task 是"改一行配置 / 跑一条 shell"，两个 reviewer 的成本高于收益。
SKIP_CATEGORIES: frozenset[str] = frozenset({"simple"})

# 只对已完成的 task 做 review。failed / partial 的产出还要重做，审它是浪费。
REVIEWABLE_STATUS: frozenset[str] = frozenset({"completed"})


def _is_doc_only(files: list[str]) -> bool:
    """files 是否全为文档类文件。空列表视为无代码可审。"""
    if not files:
        return True
    return all(PurePosixPath(f).suffix.lower() in DOC_SUFFIXES for f in files)


def needs_review(summary: dict[str, Any]) -> tuple[bool, str]:
    """判定单条 summary 是否需要 review。

    Returns:
        (需要, 原因) —— 不需要时原因说明命中了哪条跳过规则
    """
    mode = str(summary.get("mode") or summary.get("execution_mode") or "").strip()
    if mode and mode != REVIEWABLE_MODE:
        return False, f"mode={mode!r} 非 code"

    status = str(summary.get("status") or "").strip()
    if status and status not in REVIEWABLE_STATUS:
        return False, f"status={status!r} 未完成"

    category = str(summary.get("task_category") or "").strip()
    if category in SKIP_CATEGORIES:
        return False, f"task_category={category!r} 无需 review"

    raw_files = summary.get("files_changed") or []
    files = [str(f) for f in raw_files if isinstance(f, str)]
    if _is_doc_only(files):
        return False, "files_changed 无代码文件"

    return True, ""


def select(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """把 summary 数组分成需 review 与跳过两组。"""
    selected: list[str] = []
    skipped: list[dict[str, str]] = []
    invalid = 0

    for item in summaries:
        if not isinstance(item, dict):
            invalid += 1
            continue
        task_id = str(item.get("task_id") or "").strip()
        if not task_id:
            invalid += 1
            continue
        ok, why = needs_review(item)
        if ok:
            selected.append(task_id)
        else:
            skipped.append({"task_id": task_id, "reason": why})

    return {
        "selected": selected,
        "skipped": skipped,
        "invalid_count": invalid,
        "selected_count": len(selected),
    }


def merge(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """按 task_id 去重，同 id 保留最后一条。

    重派产生的新 `files_changed` 覆盖旧值。顺序即优先级：数组里
    靠后的是更新的那次。
    """
    merged: dict[str, dict[str, Any]] = {}
    replaced: list[str] = []
    invalid = 0

    for item in summaries:
        if not isinstance(item, dict):
            invalid += 1
            continue
        task_id = str(item.get("task_id") or "").strip()
        if not task_id:
            invalid += 1
            continue
        if task_id in merged:
            replaced.append(task_id)
        merged[task_id] = item

    return {
        "summaries": list(merged.values()),
        "replaced": sorted(set(replaced)),
        "invalid_count": invalid,
        "count": len(merged),
    }


def load_summaries(args: argparse.Namespace) -> list[dict[str, Any]] | Envelope:
    """从 stdin / 文件 / 内联参数读 summary 数组。"""
    if args.stdin:
        raw = sys.stdin.read()
    elif args.summaries_file:
        path = args.summaries_file
        try:
            raw = open(path, encoding="utf-8").read()
        except OSError as exc:
            return Envelope.fail(
                REASON_FILE_MISSING, path=str(path), error=f"读 summaries 失败: {exc}"
            )
    elif args.summaries:
        raw = args.summaries
    else:
        return Envelope.fail(
            REASON_INVALID_ARG,
            error="需要 --stdin / --summaries-file / --summaries 之一",
        )

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return Envelope.fail(REASON_SCHEMA_INVALID, error=f"summaries 非合法 JSON: {exc}")

    if not isinstance(parsed, list):
        return Envelope.fail(REASON_SCHEMA_INVALID, error="summaries 必须是 JSON 数组")
    return parsed


def _add_input_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--summaries", default=None, help="内联 JSON 数组")
    parser.add_argument("--summaries-file", default=None, help="JSON 数组文件路径")
    parser.add_argument("--stdin", action="store_true", help="从 stdin 读 JSON 数组")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="execute 阶段 review 子流程判定")
    sub = parser.add_subparsers(dest="command", required=True)

    p_select = sub.add_parser("select", help="筛出需 review 的 task_id")
    _add_input_args(p_select)

    p_merge = sub.add_parser("merge", help="按 task_id 去重，同 id 取最后一条")
    _add_input_args(p_merge)

    args = parser.parse_args(argv)

    loaded = load_summaries(args)
    if isinstance(loaded, Envelope):
        print(loaded.to_json())
        return loaded.exit_code()

    handler = {"select": select, "merge": merge}[args.command]
    env = Envelope.ok_envelope(**handler(loaded))
    print(env.to_json())
    return env.exit_code()


if __name__ == "__main__":
    sys.exit(main())
