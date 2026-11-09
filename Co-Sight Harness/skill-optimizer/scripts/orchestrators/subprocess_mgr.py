"""
子进程管理模块
==============

负责子进程启动和结果摘要打印：
- _spawn_phase_subprocess  : 启动子进程执行指定阶段（eval 或 optimize）
- _print_eval_summary      : 评测子进程返回后打印关键节点
- _print_optimize_summary  : 优化子进程返回后打印关键节点
"""

from __future__ import annotations

import os
import sys
from typing import List

from hooks import HookRegistry, HookTrigger

from state_engine import DEFAULT_TARGET_SCORE

# ──────────────────────────────────────────────────────────
# 关键节点打印辅助函数
# ──────────────────────────────────────────────────────────


def _print_eval_summary(round_num: int, current_score: float, best_score: float,
                        best_round: int, target_score: int) -> None:
    """在评测子进程返回后打印关键节点信息。"""
    rating = "N/A"
    total_gaps = "N/A"

    icon = "🔴" if current_score < target_score else "🟢"
    if best_score >= target_score:
        icon = "🟢"

    print(f"\n{'='*60}")
    print(f"  📊 Round {round_num} 评测结果")
    print(f"{'='*60}")
    print(f"  {icon} 本轮得分: {current_score:.1f} / {target_score}")
    print(f"  👑 最佳分数: {best_score:.1f} (Round {best_round})")
    if current_score > best_score - 0.01:
        print(f"  🆕 刷新最佳!")
    elif current_score < best_score:
        print(f"  ⚠️ 低于最佳，将回退")
    print(f"{'='*60}")


def _print_optimize_summary(round_num: int, history: list, best_score: float, best_round: int) -> None:
    """在优化子进程返回后打印关键节点信息。"""
    total_gaps = "N/A"
    rating = "N/A"
    for entry in reversed(history):
        record_rating = entry.get("rating")
        record_gaps = entry.get("total_gaps")
        if record_rating:
            rating = record_rating
        if record_gaps is not None:
            total_gaps = record_gaps

    print(f"\n  🔧 Round {round_num} 优化完成")
    print(f"     得分: {best_score:.1f} | 评级: {rating} | 剩余缺口: {total_gaps}")
    print(f"     将进入下一轮评测...")


# ═══════════════════════════════════════════════════════════════
#  分阶段子进程函数（eval / optimize 进程隔离）
# ═══════════════════════════════════════════════════════════════


def _spawn_phase_subprocess(args, round_num: int, phase: str) -> int:
    """启动子进程执行指定阶段（eval 或 optimize），返回退出码"""
    import subprocess
    from state_engine.phase_tracker import PhaseTracker

    _pt = PhaseTracker(args.workspace)

    cmd = [
        sys.executable, "-u", __file__,  # -u 强制无缓冲输出
        "--workspace", str(args.workspace),
        "--skill-path", str(args.skill_path),
        "--round", str(round_num),
        "--phase", phase,
        "--max-rounds", str(args.max_rounds),
    ]
    # 传递评测关键参数（子进程也需要这些信息）
    if getattr(args, 'evaluator_agent', ''):
        cmd.extend(["--evaluator-agent", args.evaluator_agent])
    # 默认启用 Skill 执行，仅在显式关闭时传递 --no-enable-skill-execution
    if not getattr(args, 'enable_skill_execution', True):
        cmd.append("--no-enable-skill-execution")
    if getattr(args, 'static_only', False):
        cmd.append("--static-only")
    if getattr(args, 'non_interactive', False):
        cmd.append("--non-interactive")
    if getattr(args, 'model_reasoning', ''):
        cmd.extend(["--model-reasoning", args.model_reasoning])
    # 模型参数已通过 user-config.yaml 统一配置，不再单独传递
    if getattr(args, 'api_base', ''):
        cmd.extend(["--api-base", args.api_base])
    if getattr(args, 'api_key', ''):
        cmd.extend(["--api-key", args.api_key])
    if getattr(args, 'no_fresh_session', False):
        cmd.append("--no-fresh-session")
    # 外部工作流参数
    if getattr(args, 'eval_config', ''):
        cmd.extend(["--eval-config", args.eval_config])
    if getattr(args, 'workflow_type', '') and getattr(args, 'workflow_type') != 'script':
        cmd.extend(["--workflow-type", args.workflow_type])
    if getattr(args, 'workflow_script', ''):
        cmd.extend(["--workflow-script", args.workflow_script])
    if getattr(args, 'result_path', ''):
        cmd.extend(["--result-path", args.result_path])
    if getattr(args, 'eval_mode', ''):
        cmd.extend(["--eval-mode", args.eval_mode])
    if getattr(args, 'eval_run_index', 0) != 0:
        cmd.extend(["--eval-run-index", str(args.eval_run_index)])
    # 业务方评测管道参数
    if getattr(args, 'skill_paths', ''):
        _sp = args.skill_paths
        if isinstance(_sp, (list, tuple)):
            _sp = ",".join(str(s) for s in _sp)
        cmd.extend(["--skill-paths", _sp])
    if getattr(args, 'optimization_mode', ''):
        cmd.extend(["--optimization-mode", args.optimization_mode])
    if getattr(args, 'agent_name', ''):
        cmd.extend(["--agent-name", args.agent_name])
    if getattr(args, 'pipeline_config', ''):
        cmd.extend(["--pipeline-config", args.pipeline_config])
    if getattr(args, 'pipeline_base_dir', ''):
        cmd.extend(["--pipeline-base-dir", args.pipeline_base_dir])
    # 广度优先参数
    if getattr(args, 'candidates_per_round', 5) != 5:
        cmd.extend(["--candidates-per-round", str(args.candidates_per_round)])
    if getattr(args, 'sub_rounds_per_candidate', 1) != 1:
        cmd.extend(["--sub-rounds-per-candidate", str(args.sub_rounds_per_candidate)])
    if getattr(args, 'eval_runs_per_candidate', 3) != 3:
        cmd.extend(["--eval-runs-per-candidate", str(args.eval_runs_per_candidate)])
    if getattr(args, 'enable_proposal_review', False):
        cmd.append("--enable-proposal-review")
    # ── LLM-as-Judge 通用评测参数 ──────────────────────
    llm_judge_params = [
        ('llm_judge', '--llm-judge', 'flag'),
        ('gold_dir', '--gold-dir', 'path'),
        ('rule_json', '--rule-json', 'path'),
        ('llm_judge_skill', '--llm-judge-skill', 'path'),
        ('candidate_pattern', '--candidate-pattern', 'str'),
        ('rule_path', '--rule-path', 'str'),
        ('rule_weight', '--rule-weight', 'str'),
        ('max_rans', '--max-rans', 'int'),
        ('ran_filter', '--ran-filter', 'str'),
    ]
    for attr, flag, kind in llm_judge_params:
        val = getattr(args, attr, None)
        if val is None or val == '' or val is False:
            continue
        if kind == 'flag':
            cmd.append(flag)
        elif kind == 'int':
            default = 0
            if val != default:
                cmd.extend([flag, str(val)])
        else:
            cmd.extend([flag, str(val)])

    label = "测+评" if phase == "eval" else "优化"
    print(f"\n{'='*60}")
    print(f"  🚀 启动新进程执行 Round {round_num} ({label})")
    print(f"  {'='*60}")

    _pt.update_current("subprocess_start", f"Round {round_num} {label} 子进程启动", round_num=round_num, phase=phase)

    # 显式转发父进程环境,确保 SKILLX_CURRENT_TASK_DIR 等子 Agent 落盘变量跨进程传递
    sub_env = os.environ.copy()

    result = subprocess.run(cmd, env=sub_env)

    status_label = "subprocess_done" if result.returncode == 0 else "subprocess_failed"
    detail_msg = f"Round {round_num} {label} 子进程退出(码={result.returncode})"
    _pt.update_current(status_label, detail_msg, round_num=round_num, phase=phase)

    return result.returncode
