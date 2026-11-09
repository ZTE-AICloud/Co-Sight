#!/usr/bin/env python3
"""PreToolUse hook: block Write/Edit that targets the AgentGenesis plugin's protected files.

Override: .claude/DEV_MODE marker file under the plugin root. When it exists, all writes are allowed.
Toggle: /dev and /dev-off commands create/delete the marker file.
"""

import json
import os
import sys

# Plugin root: prefer official env var (set by Claude Code for plugin hooks).
# Fallback: this script lives at <plugin-root>/hooks/guard-self-modify.py → 2 levels up.
AG_CODE = os.path.abspath(
    os.environ.get("CLAUDE_PLUGIN_ROOT")
    or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
DEV_MARKER = os.path.join(AG_CODE, ".claude", "DEV_MODE")


def main():
    try:
        raw = sys.stdin.read().strip()
        tool_call = json.loads(raw)
    except (json.JSONDecodeError, IOError):
        print(raw)
        sys.exit(0)

    tool_name = tool_call.get("tool_name", "")
    if tool_name not in ("Write", "Edit"):
        print(raw)
        sys.exit(0)

    file_path = tool_call.get("tool_input", {}).get("file_path", "")
    if not file_path:
        print(raw)
        sys.exit(0)

    target = os.path.abspath(file_path)

    # Always allow writes to the DEV_MODE marker itself (toggle)
    if target == DEV_MARKER:
        print(raw)
        sys.exit(0)

    # If dev mode is active, allow everything
    if os.path.isfile(DEV_MARKER):
        print(raw)
        sys.exit(0)

    # Check if target is in the protected zone
    if not target.startswith(AG_CODE + os.sep) and target != AG_CODE:
        # Outside the plugin root — allow (e.g., output/, user projects)
        print(raw)
        sys.exit(0)

    rel = os.path.relpath(target, AG_CODE)
    if rel == "work" or rel.startswith("work" + os.sep):
        print(raw)
        sys.exit(0)

    # Protected zone — block
    sys.stderr.write(
        f"[guard] BLOCKED {tool_name} on {file_path}\n"
        f"[guard] 该路径位于 AgentGenesis 插件受保护区域内。\n"
        f"[guard] 使用 /dev 命令进入开发模式后可修改自身代码。\n"
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
