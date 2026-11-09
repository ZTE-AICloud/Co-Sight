"""audit_events.py — PreToolUse 审计 hook。

记录 LLM/agent 的 agent spawn、Skill 调用、Bash 命令到
`.drive/<plan_dir>/run-log.jsonl`，供后续阶段完整性审计使用。

纯审计：永不阻断（始终 exit 0，输出空 JSON 放行）。安装不完整或找不到
`.drive/<plan_dir>/` 时静默放行，不影响正常工具调用。
"""
from __future__ import annotations

import json
import os
import sys

import hook_io


def _get_user_id() -> str:
    git_name = os.environ.get("GIT_AUTHOR_NAME", "")
    git_email = os.environ.get("GIT_AUTHOR_EMAIL", "")
    if git_name and git_email:
        return f"{git_name} <{git_email}>"
    if git_name:
        return git_name
    return os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"


_AGENT_SPAWN_TOOLS = {"Task", "Agent"}


def _classify_event(tool_name: str, tool_input: dict) -> dict:
    """把 tool 调用映射为一个审计事件的 details（不含 ts/event/公共字段）。"""
    if tool_name in _AGENT_SPAWN_TOOLS:
        prompt = tool_input.get("prompt", "")
        excerpt = prompt[:200] + "..." if len(prompt) > 200 else prompt
        return {
            "event": "agent_spawned",
            "subagent_type": tool_input.get("subagent_type", "unknown"),
            "description": tool_input.get("description", ""),
            "prompt_excerpt": excerpt,
            "needs_revision_baseline": True,
        }
    if tool_name == "Skill":
        skill_name = (
            tool_input.get("skill")
            or tool_input.get("skill_name")
            or tool_input.get("name")
            or tool_input.get("id")
            or "unknown"
        )
        return {
            "event": "skill_tool_called",
            "skill_name": skill_name,
            "description": tool_input.get("description", ""),
        }
    # Bash
    return {
        "event": "bash_called",
        "command": tool_input.get("command", ""),
    }


_AUDITED_TOOLS = _AGENT_SPAWN_TOOLS | {"Skill", "Bash"}


def main() -> int:
    hook_input = hook_io.read_hook_input()
    tool_name = hook_input.get("tool_name", "")

    if tool_name not in _AUDITED_TOOLS:
        print(json.dumps({}))
        return 0

    planning_dir = hook_io.find_active_plan_dir()
    if planning_dir is None:
        print(json.dumps({}))
        return 0

    tool_input = hook_input.get("tool_input", {})
    classified = _classify_event(tool_name, tool_input)
    event_name = classified.pop("event")

    # agent spawn 记下当时的 state revision，供 SubagentStop 判定该 agent 是否汇报过。
    if classified.pop("needs_revision_baseline", False):
        classified["state_revision_at_spawn"] = hook_io.read_state_revision(planning_dir)

    hook_io.append_run_log(
        planning_dir,
        event_name,
        active_stage=hook_io.read_active_stage(planning_dir) or "unknown",
        user=_get_user_id(),
        session_id=hook_input.get("session_id", "unknown"),
        # PROP-20260817-001 机制 E：每条事件自动注入 plan_dir / plan_name / pid
        plan_dir=planning_dir.name,
        plan_name=_plan_name_from_dir(planning_dir.name),
        pid=os.getpid(),
        **classified,
    )

    print(json.dumps({}))
    return 0


def _plan_name_from_dir(plan_dir: str) -> str | None:
    """从 `plan-<ts>-<name>/` 提取 <name> 部分。无前缀时返回 None。"""
    if not plan_dir.startswith("plan-"):
        return None
    # `plan-20260817-1530-add-user-auth` → 取最后一段（kebab-case 不含 `plan-`）
    parts = plan_dir.split("-", 3)
    return parts[3] if len(parts) >= 4 else None


if __name__ == "__main__":
    sys.exit(main())
