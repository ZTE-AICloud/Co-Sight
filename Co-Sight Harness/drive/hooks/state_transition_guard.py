#!/usr/bin/env python3
"""state_transition_guard.py — PreToolUse 守卫。

两职责:
  - Bash 调 transition：解析 (from, to)，用状态机流转表校验，非法流转
    (如 start → execute) 阻断。
  - Write/Edit/MultiEdit：当前阶段写入归属其它阶段的 baseline 产物
    (如 execute 阶段写 plan 产物) 阻断。

注册为 PreToolUse 而非 PostToolUse: 只有在工具执行前拒绝才能真正阻断
非法流转与跨阶段写入；PostToolUse 时副作用已发生。

stdin JSON: {"tool_name": "...", "tool_input": {...}}
exit: 0 放行 / 2 阻断（stderr 回显给 LLM）。

决策规则单一真相源: hooks/hooks_protocol.check_state_transition。

双轨 workflow 来源：项目根有 workflow.yaml 且 mode=phase 时，把解析出的
WorkflowPhases 注入 invoke_hook；否则走 builtin STAGES（行为零变化）。
"""
from __future__ import annotations

import sys
from pathlib import Path

# workflow_runtime 单副本位于 skills/state-machine/scripts/；
# hook 通过 sys.path 共享该模块。
# hook_io.py 仍保持纯 stdlib 不动；yaml 在函数体内 inline import。
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_SKILL_SCRIPTS = _PLUGIN_ROOT / "skills" / "state-machine" / "scripts"
if str(_SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SKILL_SCRIPTS))

import hook_io  # noqa: E402
from hooks_protocol import invoke_hook  # noqa: E402
from workflow_runtime import (  # noqa: E402
    SOURCE_BUILTIN,
    SOURCE_USER_YAML,
    WorkflowRuntimeError,
    parse_user_workflow_phases_from_dict,
)


def _resolve_user_workflow_phases(
    planning_dir: Path | None,
) -> tuple[object | None, str]:
    """解析项目根的 workflow.yaml，返回 (WorkflowPhases, "user_yaml") 或 (None, "builtin")。

    结局分类：
    - planning_dir 为空 / 无 workflow.yaml / 不是 phase mode / 解析失败 →
      (None, "builtin")。builtin 路径行为零变化。
    - phase mode + yaml 合法 + parse_user_workflow_phases_from_dict 成功 →
      (WorkflowPhases, "user_yaml")。

    yaml 与 workflow_runtime 的导入错误一律 soft-fallback 到 builtin：
    与 state_cli.py:170 read_phase_skip_git 同款模式 —— workflow.yaml 损坏
    不应硬卡合法流转，但 run-log 会记一条 audit 让用户察觉。state_cli
    那边也是 yaml parse 失败返 None，调用方按默认行为放行；这里把"放行"
    落实为"用 builtin STAGES 校验"，保证至少不静默越界。
    """
    if planning_dir is None:
        return None, SOURCE_BUILTIN
    # planning_dir = .drive/<plan_dir>/；workflow.yaml 在项目根 = planning_dir.parent.parent
    workflow_dir = Path(planning_dir).parent.parent
    for name in ("workflow.yaml", "workflow.yml"):
        path = workflow_dir / name
        if not path.is_file():
            continue
        try:
            import yaml
        except ImportError:
            return None, SOURCE_BUILTIN
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            return None, SOURCE_BUILTIN
        if not isinstance(doc, dict) or doc.get("mode") != "phase":
            return None, SOURCE_BUILTIN
        try:
            phases = parse_user_workflow_phases_from_dict(doc)
        except WorkflowRuntimeError:
            return None, SOURCE_BUILTIN
        return phases, SOURCE_USER_YAML
    return None, SOURCE_BUILTIN


def main() -> int:
    data = hook_io.read_hook_input()
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    planning_dir = hook_io.find_active_plan_dir()
    active_stage = hook_io.read_active_stage(planning_dir)
    # PROP-20260817-001 P0-1：传 plan_dir 给 hook（跨 plan 写拦截需要）
    plan_dir = planning_dir.name if planning_dir is not None else None
    workflow_phases, workflow_source = _resolve_user_workflow_phases(planning_dir)
    result = invoke_hook(
        "state_transition_guard",
        tool_name,
        tool_input,
        active_stage,
        plan_dir=plan_dir,
        workflow_phases=workflow_phases,
        workflow_source=workflow_source,
    )
    if result.is_denied:
        print(result.message or "BLOCKED", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())