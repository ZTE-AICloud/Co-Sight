"""
apply_agent_compat.py — apply_agent 的 compat 薄壳

取代原因:`scripts/orchestrators/apply_agent.py` 已删除(合并到 proposal-agent 单阶段流程)。
但 `eval_pipeline.py` / `breadth.py` / `reports.py` 仍引用 `invoke_apply_agent` /
`_parse_apply_agent_summary`(单 Skill / breadth 模式),本文件提供 compat 函数委托到新流程。

如确认单 Skill / breadth 模式不再使用,可删除本文件并清理 eval_pipeline / breadth。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from orchestrators.context_extractor import run_optimize_agent


def invoke_apply_agent_compat(
    state_engine,
    cand_skill_path: str,
    candidate_id: int,
    round_num: int,
    proposal_path: Optional[Path] = None,
    self_check_verdict: Optional[str] = None,
) -> None:
    """compat 入口:单 Skill 模式委托到 run_optimize_agent。

    原 invoke_apply_agent(state_engine, cand_skill_path, ...) 已删除,本函数
    用相同签名委托到新单阶段优化函数。
    """
    cand_skill_p = Path(cand_skill_path)
    candidate_skill_root = cand_skill_p.parent.parent
    skill_path_list = [cand_skill_path]

    run_optimize_agent(
        candidate_skill_root=candidate_skill_root,
        skill_path_list=skill_path_list,
        data_dir=candidate_skill_root.parent.parent.parent / "baseline" / "run_1" / "data",
        candidate_id=candidate_id,
        round_num=round_num,
        modification_budget=max(8 - round_num, 2),
        extra_inputs="",
        max_attempts=3,
    )