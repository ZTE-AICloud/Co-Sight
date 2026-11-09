"""
orchestrators 包
================

orchestrator.py 解耦后的子模块：
- reports          : 报告生成（审查报告、总览、score_history）
- eval_pipeline    : 评测编排（单轮评测、pipeline 执行、分数聚合）
- breadth          : 广度优先（候选生成、候选评测、候选选择）
- subprocess_mgr   : 子进程管理（spawn、恢复、pipe 处理）
- workspace        : 工作空间管理（路径推断、沙箱、文件拷贝、清理）
"""

from orchestrators.breadth import (_clear_eval_artifacts,
                                   _enrich_gaps_with_trace, _evaluate_baseline,
                                   _evaluate_baseline_multi,
                                   _evaluate_candidate,
                                   _generate_candidate_detail,
                                   _generate_candidates,
                                   _generate_single_candidate,
                                   _load_gaps_for_round, _run_breadth_round)
from orchestrators.eval_pipeline import (_run_eval_subprocess_inner,
                                         _run_optimize_subprocess_inner,
                                         run_evaluation, run_optimization,
                                         run_single_round)
from orchestrators.reports import (_generate_fallback_report,
                                   _generate_report_text,
                                   _save_final_review_report,
                                   _save_round_analysis_json)
from orchestrators.subprocess_mgr import (_print_eval_summary,
                                          _print_optimize_summary,
                                          _spawn_phase_subprocess)
from orchestrators.workspace import (_build_ran_filter, _copy_back_whitelisted,
                                     _copy_sandbox_skill_back,
                                     _find_gold_base_dir, _get_hook_registry,
                                     _load_user_config, _revert_to_best_skill,
                                     clean_eval_data_sandbox)

__all__ = [
    # reports
    "_save_final_review_report",
    "_generate_fallback_report",
    "_save_round_analysis_json",
    "_generate_report_text",
    # eval_pipeline
    "run_evaluation",
    "run_optimization",
    "run_single_round",
    "_run_eval_subprocess_inner",
    "_run_optimize_subprocess_inner",
    # breadth
    "_evaluate_baseline",
    "_run_breadth_round",
    "_load_gaps_for_round",
    "_enrich_gaps_with_trace",
    "_generate_candidates",
    "_evaluate_baseline_multi",
    "_evaluate_candidate",
    "_generate_candidate_detail",
    "_generate_single_candidate",
    "_clear_eval_artifacts",
    # subprocess_mgr
    "_spawn_phase_subprocess",
    "_print_eval_summary",
    "_print_optimize_summary",
    # workspace
    "_revert_to_best_skill",
    "_find_gold_base_dir",
    "_build_ran_filter",
    "_copy_back_whitelisted",
    "_copy_sandbox_skill_back",
    "clean_eval_data_sandbox",
    "_load_user_config",
    "_get_hook_registry",
]
