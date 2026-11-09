"""Optimizers — 优化器模块集合

当前包含:
  - static_optimizer: /skill_optimize 主循环（编排）
  - static_agents:    evaluator / optimizer LLM agent 调用
  - static_apply:     modifications 应用 + dim8 校验
  - static_llm:       ccr HTTP 客户端
  - static_prompts:   evaluator / optimizer prompt 模板
"""

from .static_apply import (PHASE_IDS, PHASE_NAMES, append_round_summary,
                           apply_modifications, collect_assets_snapshot,
                           finalize_progress_state, init_progress_state,
                           prepare_workspace_skill_copy, record_rework,
                           snapshot_skill, update_best_skill,
                           update_progress_phase, validate_assets,
                           write_skill_metadata)
from .static_llm import LLMConfig, call_llm_json
from .static_optimizer import (RoundResult, StaticConfig, invoke_evaluator,
                               invoke_optimizer, run_static_optimization)
from .static_prompts import build_evaluator_prompt, build_optimizer_prompt

__all__ = [
    "StaticConfig", "RoundResult", "run_static_optimization",
    "invoke_evaluator", "invoke_optimizer",
    "apply_modifications", "validate_assets",
    "collect_assets_snapshot",
    "prepare_workspace_skill_copy", "snapshot_skill",
    "update_best_skill", "write_skill_metadata",
    "init_progress_state", "update_progress_phase", "record_rework",
    "append_round_summary", "finalize_progress_state",
    "PHASE_IDS", "PHASE_NAMES",
    "LLMConfig", "call_llm_json",
    "build_evaluator_prompt", "build_optimizer_prompt",
]
