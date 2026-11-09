"""
builtin/backup_skill_before_apply — ON_APPLY_PROPOSAL 阶段自动备份
================================================================

应用提案前把当前 SKILL.md 拷贝到 _debug/skill_backup_{ts}.md，
失败时返回 False 阻止应用（不覆盖当前文件）。
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any, Dict

from hooks.spec import HookSpec, HookTrigger


def _backup_skill(context: Dict[str, Any]) -> bool:
    skill_path = context.get("skill_path")
    if not skill_path:
        return True

    src = Path(skill_path)
    if not src.is_file():
        return True

    try:
        from hooks._debug import resolve_debug_log_path
        debug_dir = resolve_debug_log_path("hooks.log").parent
    except Exception:
        return True

    try:
        ts = int(time.time())
        round_num = context.get("round_num", 0)
        candidate_id = context.get("candidate_id", 0)
        target = debug_dir / f"skill_backup_r{round_num}_c{candidate_id}_{ts}.md"
        shutil.copy2(src, target)
        return True
    except Exception:
        # 注册器会自动记录失败, 这里不重复 log_hook_event
        return False


HOOK_SPECS = [
    HookSpec(
        name="backup_skill_before_apply",
        trigger=HookTrigger.ON_APPLY_PROPOSAL,
        fn=_backup_skill,
        timeout=5,
    ),
]
