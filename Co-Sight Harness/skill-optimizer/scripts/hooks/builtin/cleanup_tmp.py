"""
builtin/cleanup_tmp — PRE_ROUND 阶段清理 /tmp 残留文件
======================================================

删除 /tmp 下与 skillx/SDD-eval 相关的临时文件，避免跨轮次污染。
通用实现，不假设具体业务路径前缀。
"""

from __future__ import annotations

import glob
import os
import time
from typing import Any, Dict

from hooks.spec import HookSpec, HookTrigger


def _cleanup_tmp(context: Dict[str, Any]) -> bool:
    """删除 /tmp 下 24h 之前的 skillx* / sdd_eval* 临时文件。

    返回 True 表示清理完成（含无文件可清的情况）。
    """
    patterns = [
        "/tmp/skillx-*",
        "/tmp/sdd_eval_*",
        "/tmp/discovered_rids_*",
    ]
    cutoff = time.time() - 24 * 3600
    removed = 0
    for pattern in patterns:
        for path in glob.glob(pattern):
            try:
                if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                    os.unlink(path)
                    removed += 1
            except OSError:
                continue

    # 清理结果通过 context 透传给 registry, 由 registry 统一写日志
    context["removed_count"] = removed
    return True


HOOK_SPECS = [
    HookSpec(
        name="cleanup_tmp",
        trigger=HookTrigger.PRE_ROUND,
        fn=_cleanup_tmp,
        timeout=10,
    ),
]
