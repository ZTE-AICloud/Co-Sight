#!/usr/bin/env python3
"""planning_write_guard.py — PreToolUse 守卫。

拦截 LLM 对 `.drive/<plan_dir>/` 非白名单路径的直接 Write/Edit/MultiEdit。
状态文件 (executeState.json / run-log.jsonl) 强制走 SDK 通道
（Bash 调 state_cli.py）；叙事文档 / 输入 / worker 产物等白名单路径放行。

stdin JSON: {"tool_name": "...", "tool_input": {"file_path": "..."}}
exit: 0 放行 / 2 阻断（stderr 回显给 LLM）。

决策规则单一真相源: hooks/hooks_protocol.check_planning_write。
"""
from __future__ import annotations

import sys

import hook_io
from hooks_protocol import invoke_hook


def main() -> int:
    data = hook_io.read_hook_input()
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # PROP-20260817-001 P0-1：传 plan_dir 给 hook（跨 plan 写拦截需要）
    plan_dir = hook_io.find_current_plan_dir()

    result = invoke_hook("planning_write_guard", tool_name, tool_input, plan_dir=plan_dir)
    if result.is_denied:
        print(result.message or "BLOCKED", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
