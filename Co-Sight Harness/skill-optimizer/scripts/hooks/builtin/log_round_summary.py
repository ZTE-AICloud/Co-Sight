"""
builtin/log_round_summary — POST_ROUND 阶段追加本轮摘要
======================================================

把每轮结果（score/rating/candidate_id/round_num）追加到
{SKILLX_CURRENT_TASK_DIR}/_debug/round_summary.jsonl，便于事后追溯。
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict

from hooks.spec import HookSpec, HookTrigger


def _log_round_summary(context: Dict[str, Any]) -> bool:
    """追加一行 JSON 摘要到 _debug/round_summary.jsonl。

    必填字段（缺失则跳过本次记录）：
      - round_num
      - score
      - rating
    """
    round_num = context.get("round_num")
    score = context.get("score")
    rating = context.get("rating")
    if round_num is None or score is None:
        return True  # 不是错误，仅是上下文不完整

    try:
        from hooks._debug import resolve_debug_log_path
        log_path = resolve_debug_log_path("round_summary.jsonl")
        if log_path is None:
            return True
    except Exception:
        return True

    record = {
        "ts": int(time.time()),
        "round_num": round_num,
        "score": float(score) if score is not None else None,
        "rating": rating,
        "candidate_id": context.get("candidate_id"),
        "skill_name": context.get("skill_name"),
        "workspace": context.get("workspace"),
    }

    try:
        with open(log_path, "a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return True


HOOK_SPECS = [
    HookSpec(
        name="log_round_summary",
        trigger=HookTrigger.POST_ROUND,
        fn=_log_round_summary,
        timeout=5,
    ),
]
