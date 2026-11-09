"""
builtin/validate_skill_format — PRE_ROUND 阶段校验 SKILL.md frontmatter
=====================================================================

校验目标 SKILL.md 至少包含 YAML frontmatter 块（`---\n...\n---`）。
不假设具体业务字段，仅做形态检查；通过则返回 True。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from hooks.spec import HookSpec, HookTrigger


def _validate_skill_format(context: Dict[str, Any]) -> bool:
    """检查 skill_path 指向的文件首部是否含 frontmatter 块。"""
    skill_path = context.get("skill_path")
    if not skill_path:
        return True

    path = Path(skill_path)
    if not path.is_file():
        # 路径无效不算错误（可能是子目录的 SKILL.md，不在此处校验）
        return True

    try:
        with open(path, "r", encoding="utf-8") as fp:
            head = fp.read(2048)  # 只读前 2KB
    except OSError:
        return True

    has_frontmatter = head.startswith("---\n") and "\n---" in head
    if not has_frontmatter:
        # 形态不合规：返回 False 让 orchestrator 决定是否中断
        # 日志由 registry.trigger() 统一写, 无需本函数重复落盘
        return False

    return True


HOOK_SPECS = [
    HookSpec(
        name="validate_skill_format",
        trigger=HookTrigger.PRE_ROUND,
        fn=_validate_skill_format,
        timeout=5,
    ),
]
