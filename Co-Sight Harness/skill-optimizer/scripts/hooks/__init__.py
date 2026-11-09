"""
Hooks - 生命周期钩子系统
========================
支持 pre_round, post_evaluation, post_optimization, post_round, on_error 等生命周期钩子

用法：
    from hooks import HookRegistry, HookTrigger

    registry = HookRegistry()
    registry.load_builtin_hooks()

    # 触发 pre_round hooks
    results = registry.trigger(HookTrigger.PRE_ROUND, {
        "workspace": "/path/to/workspace",
        "skill_path": "/path/to/SKILL.md",
        "round_num": 1
    })
"""

from .spec import HookSpec, HookResult, HookTrigger, HookNames
from .registry import HookRegistry

__all__ = [
    "HookSpec",
    "HookResult",
    "HookTrigger",
    "HookNames",
    "HookRegistry",
]