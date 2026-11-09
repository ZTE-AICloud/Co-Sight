"""drive-record CLI 入口。

用法：
    python3 cli.py --plan-dir <path> [--cwd <cwd>] [--session <id>] [--worktree <path>]

输出 envelope（stdout）：
- 成功：{"ok": true, "data": {"report_md": <abs path>,
       "summary": {...}, "session_path": <abs path or null>}}
- 失败：{"ok": false, "reason": "...", "details": {...}}

退出码：0 = 成功；1 = 失败。

v1 不支持 --plan-dir 缺省（plan_dir 是必填）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 让脚本能从 skills/drive-record/scripts/ 直接 import 同目录模块
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_report import write_report  # noqa: E402
from env import REASON_INVALID_ARG, REASON_WRITE_FAILED, emit  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="drive-record",
        description="把 .drive/<plan_dir>/ 运行时记录汇编成 REPORT.md（gap 检测内嵌 §B）",
    )
    parser.add_argument(
        "--plan-dir",
        required=True,
        type=Path,
        help=".drive/<plan_dir>/ 路径",
    )
    parser.add_argument(
        "--cwd",
        default=None,
        help="当前 cwd（用于 cwd-hash 定位 session json）",
    )
    parser.add_argument(
        "--session",
        default=None,
        help="显式覆盖 session_id（v2 用）",
    )
    parser.add_argument(
        "--worktree",
        type=Path,
        default=None,
        help="git worktree 路径（用于 timeline 合并 commit）",
    )
    return parser.parse_args(argv if argv is not None else None)


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parse_args(argv if argv is not None else sys.argv[1:])
    except SystemExit:
        emit(
            ok=False,
            reason=REASON_INVALID_ARG,
            details={"hint": "检查 --plan-dir / --cwd / --worktree 是否正确"},
        )
        return 1

    plan_dir: Path = args.plan_dir
    if not plan_dir.is_dir():
        emit(
            ok=False,
            reason=REASON_INVALID_ARG,
            details={"plan_dir": str(plan_dir), "hint": "plan_dir 不是目录"},
        )
        return 1

    try:
        result = write_report(
            plan_dir,
            cwd=args.cwd,
            session_override=args.session,
            worktree=args.worktree,
        )
    except OSError as e:
        emit(
            ok=False,
            reason=REASON_WRITE_FAILED,
            details={"plan_dir": str(plan_dir), "error": str(e)},
        )
        return 1

    emit(
        ok=True,
        data={
            "plan_name": result["plan_name"],
            "mode": result["mode"],
            "completeness": result["completeness"],
            "report_md": str(plan_dir / "REPORT.md"),
            "summary": result["summary"],
            "session_path": str(result["session_path"]) if result["session_path"] else None,
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())