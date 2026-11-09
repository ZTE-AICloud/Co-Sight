"""
评测编排模块
============

负责评测执行和编排：
- run_evaluation              : 评测执行（含 Hook 触发、gap 补齐、指标记录）
- run_optimization            : 优化执行（含指标记录）
- _run_eval_subprocess_inner  : 子进程评测
- _run_optimize_subprocess_inner : 子进程优化
- run_single_round            : 单轮评测+优化（深度优先模式）

所有优化统一通过 ApplyAgent 子 Agent（orchestrators.apply_agent.invoke_apply_agent）
读取 proposal.md 并修改 Skill 副本，不再使用 OptimizerGateway。
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from evaluators import EvaluatorFactory
from hooks import HookTrigger
from orchestrators.apply_agent_compat import \
    invoke_apply_agent_compat as invoke_apply_agent
from orchestrators.reports import (_generate_report_text,
                                   _save_round_analysis_json)
from orchestrators.skill_manager import (backup_skill_to_bak,
                                         restore_skill_from_bak)
# 跨模块导入（避免循环依赖：workspace/reports 不依赖本模块）
from orchestrators.workspace import _copy_back_whitelisted, _get_hook_registry
from state_engine.engine import StateEngine

logger = logging.getLogger(__name__)


def run_evaluation(state_engine: StateEngine, args, round_num: int, is_baseline: bool = False) -> dict:
    """
    执行评测

    流程：
    1. 触发 pre_round hooks
    2. 保存 SKILL 快照
    3. 调用 EvaluatorFactory 评测
    4. 触发 post_evaluation hooks
    5. 保存报告
    6. 记录指标（耗时、分数）

    is_baseline: True 时跳过 round_N 目录保存（baseline 使用独立的 baseline/ 目录）
    """
    metrics = getattr(args, 'metrics_collector', None)
    if metrics:
        metrics.start_phase(round_num, "evaluate")

    # ── Phase: evaluate ──
    # 关键修复:orchestrator 主循环直接调 run_evaluation(不走 _run_eval_subprocess_inner),
    # 此处必须显式打点,否则 task_state.json 的 evaluate phase 永远 pending。
    try:
        state_engine.record_phase_start(round_num, "evaluate")
    except Exception:
        pass

    skill_path = str(state_engine.skill_path)
    skill_name = state_engine.skill_name
    workspace = str(state_engine.workspace)

    # 🆕 评测前同步 workspace skill(优化后)到评测 agent 目录
    # 否则评测 agent 用初始 skill(skills/),优化不体现在分数(核心 bug)。
    try:
        from orchestrators.workspace import _sync_skill_to_eval_agents as _sync_skill
        _sync_skill(Path(state_engine.workspace))
    except Exception as _e_sync:
        print(f"  ⚠️ 评测前同步 skill 到评测 agent 失败(继续评测,可能测初始 skill): {_e_sync}")

    # 修复 baseline 归档路径误归到 round_0/data 的 bug
    # is_baseline=True 时,必须显式设置 args.eval_mode='baseline' 和 args.eval_run_index=1
    # 否则:
    # - args.eval_mode 默认 ""(argparse),工厂 getattr 不会用 'baseline' 默认值
    # - args.eval_run_index 默认 0(argparse),归档到 baseline/run_0
    if is_baseline:
        if not getattr(args, 'eval_mode', ''):
            args.eval_mode = 'baseline'
        if not getattr(args, 'eval_run_index', 0):
            args.eval_run_index = 1

    # 触发 pre_round hooks
    hooks = _get_hook_registry()
    hooks.trigger(HookTrigger.PRE_ROUND, {
        "workspace": workspace,
        "skill_path": skill_path,
        "skill_name": skill_name,
        "round_num": round_num,
    })

    # 将 round_num 注入 args（工厂函数需要）
    args.round_num = round_num

    # 从 state_engine.config["pipeline"] 注入 pipeline 派生配置（替代 yaml 路径）
    pipeline_section = (state_engine.config or {}).get("pipeline", {}) or {}
    if pipeline_section:
        args.pipeline_config_dict = dict(pipeline_section)

    # 调用评测器
    factory = EvaluatorFactory()
    evaluator_agent = getattr(args, 'evaluator_agent', None)
    try:
        evaluators = factory.create_pipeline(args)
        eval_result = factory.evaluate(skill_path, evaluators)
    except Exception as e:
        logger.error(f"评测失败: {e}")
        print(f"\n  ⚠️ workflow_pipeline 评测异常: {e}，标记为 BROKEN")
        # 触发 ON_ERROR hooks
        _get_hook_registry().trigger(HookTrigger.ON_ERROR, {
            "workspace": workspace,
            "skill_name": skill_name,
            "round_num": round_num,
            "stage": "evaluate",
            "error_type": type(e).__name__,
            "error_msg": str(e),
        })
        if evaluator_agent:
            print(f"  ❌ 评测 Agent '{evaluator_agent}' 执行失败，终止任务。")
            sys.exit(1)
        from evaluators.base import EvaluationResult
        eval_result = EvaluationResult(
            score=0.0,
            rating="BROKEN",
            gaps=[{"severity": "critical", "message": f"评测管道异常: {e}"}],
            improvements=["检查并修复评测脚本或数据配置"],
            evaluator_type="exception_fallback",
        )

    # 触发 post_evaluation hooks
    hooks.trigger(HookTrigger.POST_EVALUATION, {
        "workspace": workspace,
        "skill_name": skill_name,
        "round_num": round_num,
        "score": eval_result.score,
        "rating": eval_result.rating,
        "eval_result": eval_result.to_dict(),
    })

    # 保存报告
    score = eval_result.score
    rating = eval_result.rating
    total_gaps = eval_result.total_gaps

    icon_map = {"EXCELLENT": "🟢", "GOOD": "🟡", "FAIR": "🟠", "POOR": "🔴", "BROKEN": "💀"}
    icon = icon_map.get(rating, "⚪")
    print(f"  {icon} 评分: {score}/100 [{rating}] | 缺口: {total_gaps} 个")

    state_engine.record_current_progress("evaluated", f"Round {round_num} 评分 {score}/100 [{rating}]",
                    round_num=round_num, phase="eval")

    if eval_result.improvements:
        print("  改进建议（前3条）:")
        for imp in eval_result.improvements[:3]:
            print(f"    • {imp}")

    # 构造结果 dict
    result = {
        "score": score,
        "rating": rating,
        "total_gaps": total_gaps,
        "gaps": eval_result.gaps,
        "improvements": eval_result.improvements,
        "skill_snapshot": f"round_{round_num}_before_skill/",
        "report_text": _generate_report_text(eval_result, skill_name, round_num),
        "metadata": eval_result.metadata,
    }

    # 保存报告文件
    eval_run = getattr(args, 'eval_run_index', 1)
    eval_mode = getattr(args, 'eval_mode', None)
    cand_id = getattr(args, 'candidate_id', None)

    if is_baseline:
        # baseline 模式：仅归档 data/，不写 score.json/report.md（由 ScoreAnalyzerAgent 统一输出）
        state_engine.artifact_store.archive_eval_run_data(eval_run, round_num, is_baseline=True)
    elif eval_mode == "candidate" and cand_id is not None:
        # 候选模式：仅归档 data/，不写 score.json/report.md
        state_engine.artifact_store.archive_eval_run_data(eval_run, round_num,
            is_baseline=False, candidate_id=cand_id)
    else:
        # 深度模式：保存 score.json 到 round_N/ 目录
        state_engine.artifact_store.save_score(eval_result.to_dict(), round_num)

    # 指标记录
    if metrics:
        metrics.end_phase(round_num, "evaluate")
        metrics.record(round_num, "result_score", score)
        # 从 metadata 提取 token 等信息
        meta = eval_result.metadata or {}
        if "token_usage" in meta:
            for k, v in meta["token_usage"].items():
                metrics.record(round_num, k, v)

    # evaluate phase 完成（与 start 配对）
    try:
        state_engine.record_phase_complete(round_num, "evaluate")
    except Exception:
        pass

    return result

def run_optimization(state_engine: StateEngine, args, eval_result: dict, round_num: int,
                      candidate_id: int = -1,
                      skill_path_override: str = None):
    """
    执行优化

    流程：
    1. 定位 proposal.md（round_N/candidate_K/proposal.md，回退 baseline/proposal.md）
    2. 调 ApplyAgent 子 Agent 一次性应用 proposal 到 Skill
    3. ApplyAgent 不需要中间审批（一次性 propose+apply）

    Args:
        candidate_id: 候选 ID（agent 模式 + round 阶段传入，按候选拆分 proposal 文件）
        skill_path_override: 候选副本路径（agent 模式 + round 阶段传入，避免 5 候选优化互相覆盖 .proposed）
    """
    metrics = getattr(args, 'metrics_collector', None)
    if metrics:
        metrics.start_phase(round_num, "optimize")
    # 优先级：skill_path_override > sandbox_skill > state_engine.skill_path
    if skill_path_override:
        skill_path = skill_path_override
    elif os.environ.get("SKILLX_SANDBOX_SKILL", ""):
        sandbox_skill = os.environ.get("SKILLX_SANDBOX_SKILL", "")
        sandbox_skill_path = Path(sandbox_skill) / "SKILL.md"
        if sandbox_skill_path.exists():
            skill_path = str(sandbox_skill_path)
        else:
            skill_path = str(state_engine.skill_path)
    else:
        skill_path = str(state_engine.skill_path)

    skill_name = state_engine.skill_name
    gaps = eval_result.get("gaps", [])

    if not gaps:
        print("\n无缺口可优化，跳过优化阶段。")
        state_engine.record_phase_skip(round_num, "proposal", "无缺口")
        state_engine.record_phase_skip(round_num, "apply", "无缺口")
        return None

    print(f"\n{'='*60}")
    print(f"  Round {round_num}: 优化")
    print(f"{'='*60}")
    print(f"  缺口数: {len(gaps)}")

    state_engine.record_current_progress("optimizing", f"Round {round_num} 优化执行中", round_num=round_num, phase="proposal")

    # ── Phase: proposal ──
    state_engine.record_phase_start(round_num, "proposal")
    print("\n  [优化诊断] 缺口详情:")
    for g in gaps[:5]:
        sec = g.get("affected_section", "?")
        cause = g.get("root_cause", "?")
        fix = g.get("fix_suggestion", "")[:100]
        print(f"    ▸ [{g.get('severity', '?')}] {sec}: {cause}")
        if fix:
            print(f"      → {fix}")
    if len(gaps) > 5:
        print(f"    ... 还有 {len(gaps) - 5} 个缺口")

    # 定位 proposal.md：优先 round_N/candidate_K/proposal.md，回退 baseline/proposal.md
    workspace = str(state_engine.artifact_store.workspace)
    if round_num == 0 or candidate_id == -1:
        proposal_path = Path(workspace) / "baseline" / "proposal.md"
    else:
        candidate_proposal = Path(workspace) / f"round_{round_num}" / f"candidate_{candidate_id}" / "proposal.md"
        proposal_path = candidate_proposal if candidate_proposal.exists() else (Path(workspace) / "baseline" / "proposal.md")

    if not proposal_path.exists():
        print(f"  ⚠️ proposal.md 不存在 ({proposal_path})，跳过本轮优化")
        state_engine.record_phase_fail(round_num, "proposal", "proposal.md 缺失")
        if metrics:
            metrics.end_phase(round_num, "optimize")
        return None

    # 触发 POST_OPTIMIZATION hooks（proposal 已存在，ApplyAgent 直接消费）
    _get_hook_registry().trigger(HookTrigger.POST_OPTIMIZATION, {
        "workspace": str(state_engine.artifact_store.workspace),
        "skill_name": skill_name,
        "round_num": round_num,
        "candidate_id": candidate_id,
        "success": True,
        "proposal_path": str(proposal_path),
    })

    state_engine.record_phase_complete(round_num, "proposal")

    # 把 proposal.md 复制到 round 级 proposal 目录
    try:
        proposal_text = proposal_path.read_text(encoding="utf-8")
        state_engine.artifact_store.save_proposal(
            proposal_text, round_num,
            skill_name=skill_name,
            candidate_id=candidate_id,
        )
    except Exception:
        pass

    print(f"  📄 proposal 已就绪: {proposal_path}")

    # ── Phase: apply ──
    state_engine.record_phase_start(round_num, "apply")
    # 触发 ON_APPLY_PROPOSAL hooks
    _get_hook_registry().trigger(HookTrigger.ON_APPLY_PROPOSAL, {
        "workspace": str(state_engine.artifact_store.workspace),
        "skill_name": skill_name,
        "skill_path": skill_path,
        "round_num": round_num,
        "candidate_id": candidate_id,
    })

    # 读 Stage 4 verdict（fail-fast：REJECTED 时跳过 apply）
    # ⚠️ 临时禁用(2026-06-18):Stage 4 整体注释,verdict 强制 None,ApplyAgent 不再 skip。
    # 取消下面 try 块注释即可恢复 fail-fast。
    self_check_verdict = None
    # try:
    #     import json as _json_v
    #     _sc_path = (Path(state_engine.artifact_store.workspace) / "baseline"
    #                 / "_proposal" / "stage_4_self_check.json")
    #     if _sc_path.exists():
    #         self_check_verdict = _json_v.loads(
    #             _sc_path.read_text(encoding="utf-8")
    #         ).get("verdict")
    # except Exception:
    #     pass

    # 调 ApplyAgent 子 Agent 一次性应用 proposal 到 Skill
    try:
        invoke_apply_agent(
            state_engine,
            cand_skill_path=skill_path,
            candidate_id=candidate_id if candidate_id > 0 else 0,
            round_num=round_num,
            proposal_path=proposal_path,
            self_check_verdict=self_check_verdict,
        )
        state_engine.record_phase_complete(round_num, "apply")
    except Exception as e:
        print(f"  ❌ ApplyAgent 调用失败: {e}")
        state_engine.record_phase_fail(round_num, "apply", f"ApplyAgent 失败: {e}")
        if metrics:
            metrics.end_phase(round_num, "optimize")
        return None

    # 如果使用 sandbox skill，把沙箱中的 Skill 拷回 workspace
    sandbox_skill = os.environ.get("SKILLX_SANDBOX_SKILL", "")
    if sandbox_skill:
        _copy_sandbox_skill_back(sandbox_skill, state_engine.skill_dir)
        print("  🔒 优化后 Skill 已从沙箱拷回 workspace")

    # ── 同步优化后的 Skill 到原始 --skill-path 路径(严格替换)──
    # 目的:让原始路径始终是最新版本(后续手动 /sdd-eval / 下一轮 baseline 评测
    # 都能读到优化后的 skill)。先 rmtree 再 copytree 避免文件数差异导致 stale 残留。
    # 单 Skill 模式:从 workspace skill 同步到 state_engine.skill_path
    # 防御链:backup → 覆盖 → restore,保证任何异常退出都能恢复原路径
    try:
        _ws_skill_dir = state_engine.skill_dir
        _orig_skill_path = state_engine.skill_path
        if _ws_skill_dir and _ws_skill_dir.exists() and _orig_skill_path:
            _orig_skill_dir = Path(_orig_skill_path).resolve().parent
            if _orig_skill_dir.exists() and _orig_skill_dir != _ws_skill_dir.resolve():
                # 不同源:走 backup→覆盖→restore 防御链
                try:
                    backup_skill_to_bak([str(_orig_skill_path)], {}, force=False)
                    shutil.rmtree(str(_orig_skill_dir))
                    shutil.copytree(str(_ws_skill_dir), str(_orig_skill_dir))
                    print(f"  ✅ 同步 workspace skill → 原始路径: {_orig_skill_dir}")
                finally:
                    restore_skill_from_bak([str(_orig_skill_path)], {}, cleanup=False)
            else:
                print("  ℹ️ 原始路径与 workspace 同或不存在,跳过同步")
    except Exception as _e_sync:
        print(f"  ⚠️ 同步原始路径失败: {_e_sync}")

    if metrics:
        metrics.end_phase(round_num, "optimize")
    return {"applied": True, "skill_path": skill_path}

def _copy_sandbox_skill_back(sandbox_skill: str, skill_dir: Path):
    """将沙箱中的 Skill 拷回 workspace。"""
    import shutil
    sandbox_skill_path = Path(sandbox_skill) / "SKILL.md"
    if sandbox_skill_path.exists() and skill_dir.exists():
        target = skill_dir / "SKILL.md"
        shutil.copy2(str(sandbox_skill_path), str(target))

def _run_eval_subprocess_inner(state_engine: StateEngine, args, round_num: int) -> bool:
    """
    子进程内执行：测 + 评（inline 模式）

    直接在业务方评测目录执行命令，完成后拷贝产物到 workspace。
    """
    is_baseline = getattr(args, 'eval_mode', '') == 'baseline'

    # ── baseline 模式：跳过 round 目录创建，使用独立 baseline/ 目录 ──
    if is_baseline:
        from state_engine.persistence import ensure_dir as _bed
        _bed(str(state_engine.artifact_store.workspace / "baseline"))
        args.eval_run_index = 1
        try:
            eval_result = run_evaluation(state_engine, args, 1, is_baseline=True)
        except Exception:
            raise
        return True

    # ── 保存 before 快照 ──
    state_engine.artifact_store.save_skill_snapshot(state_engine.skill_dir, round_num)

    # ── Phase: evaluate ──
    state_engine.record_phase_start(round_num, "evaluate")
    try:
        eval_result = run_evaluation(state_engine, args, round_num)
    except BrokenPipeError as bpe:
        import traceback
        _trace = traceback.format_exc()
        print(f"\n  ❌ Broken pipe 错误: {bpe}")
        print(f"  📋 完整堆栈:\n{_trace}")
        try:
            state_engine.record_phase_fail(round_num, "evaluate", f"Broken pipe: {bpe}")
            state_engine.config_store.save(state_engine.config)
            state_engine.record_current_progress("broken_pipe", f"Round {round_num} 评测阶段 Broken pipe，已保存中间状态",
                            round_num=round_num, phase="evaluate")
        except Exception:
            pass
        raise
    except Exception as eval_e:
        import traceback
        _trace2 = traceback.format_exc()
        print(f"\n  ❌ 评测阶段异常: {eval_e}")
        print(f"  📋 完整堆栈:\n{_trace2}")
        raise

    state_engine.record_phase_complete(round_num, "evaluate")

    # ── Phase: score ──
    state_engine.record_phase_start(round_num, "score")
    state_engine.update_after_evaluation(eval_result, round_num)
    state_engine.record_phase_complete(round_num, "score")

    # ── 子进程内生成 round_analysis.json ──
    try:
        _sub_score = state_engine.config.get("current_score", 0) if state_engine.config else 0
        _save_round_analysis_json(state_engine, round_num, float(_sub_score), [float(_sub_score)], 0.0, [])
    except Exception as _e:
        print(f"  ⚠️ 子进程生成 round_analysis.json 失败: {_e}")

    return True

def _run_optimize_subprocess_inner(state_engine: StateEngine, args, round_num: int) -> bool:
    """
    子进程内执行：优化

    从文件读取 gaps（非内存传递），在 /tmp 副本上运行 ApplyAgent，
    完成后将结果拷回 workspace。子进程退出时 /tmp 上下文销毁。
    """
    import shutil
    import tempfile as _tempfile

    from orchestrators.apply_agent_compat import \
        invoke_apply_agent_compat as invoke_apply_agent

    # 修复路径不一致:orchestrator 写的是 round_{N}_score.json(带前缀),非 score.json
    # 旧代码读 score.json → 找不到 → gaps=[] → 永远走"无缺口,跳过优化"分支
    _round_dir = state_engine.artifact_store._ensure_round_dir(round_num)
    score_path = _round_dir / f"round_{round_num}_score.json"
    if not score_path.exists():
        # 兜底:试旧路径(纯 score.json),便于历史任务兼容
        score_path = _round_dir / "score.json"
    gaps = []
    eval_result = {}
    if score_path.exists():
        try:
            data = json.loads(score_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        gaps = data.get("gaps", [])
        eval_result = {
            "gaps": gaps,
            "total_gaps": len(gaps),
            "score": data.get("overall_score", 0),
        }

    if not gaps:
        print("  无缺口，跳过优化")
        state_engine.record_phase_skip(round_num, "proposal", "无缺口")
        state_engine.record_phase_skip(round_num, "apply", "无缺口")
        return True

    skill_name = state_engine.skill_name
    candidate_id = getattr(args, 'candidate_id', -1) or -1

    print(f"\n{'='*60}")
    print(f"  Round {round_num}: 优化")
    print(f"{'='*60}")
    print(f"  缺口数: {len(gaps)}")

    # 定位 proposal.md：优先 round_N/candidate_K/proposal.md，回退 baseline/proposal.md
    workspace = Path(str(state_engine.artifact_store.workspace))
    if round_num == 0 or candidate_id == -1:
        proposal_path = workspace / "baseline" / "proposal.md"
    else:
        candidate_proposal = workspace / f"round_{round_num}" / f"candidate_{candidate_id}" / "proposal.md"
        proposal_path = candidate_proposal if candidate_proposal.exists() else (workspace / "baseline" / "proposal.md")

    if not proposal_path.exists():
        print(f"  ⚠️ proposal.md 不存在 ({proposal_path})，跳过本轮优化")
        state_engine.record_phase_fail(round_num, "proposal", "proposal.md 缺失")
        return True

    state_engine.record_phase_start(round_num, "proposal")
    # 触发 POST_OPTIMIZATION hooks（proposal 已存在，ApplyAgent 直接消费）
    _get_hook_registry().trigger(HookTrigger.POST_OPTIMIZATION, {
        "workspace": str(workspace),
        "skill_name": skill_name,
        "round_num": round_num,
        "candidate_id": candidate_id,
        "success": True,
        "proposal_path": str(proposal_path),
    })
    state_engine.record_phase_complete(round_num, "proposal")

    # 把 proposal.md 复制到 round 级 proposal 目录
    try:
        proposal_text = proposal_path.read_text(encoding="utf-8")
        state_engine.artifact_store.save_proposal(
            proposal_text, round_num,
            skill_name=skill_name,
            candidate_id=candidate_id,
        )
    except Exception:
        pass

    print(f"  📄 proposal 已就绪: {proposal_path}")

    # 准备 /tmp 副本
    skill_dir = state_engine.skill_dir
    tmp_root = Path(_tempfile.mkdtemp(prefix="skillx-opt-"))
    tmp_skill_dir = tmp_root / skill_dir.name
    shutil.copytree(
        str(skill_dir), str(tmp_skill_dir),
        ignore=lambda d, f: [x for x in f if x.endswith(".proposed")]
    )
    tmp_skill_path = str(tmp_skill_dir / "SKILL.md")

    proposal_applied = False
    try:
        # ── Phase: apply ──
        state_engine.record_phase_start(round_num, "apply")
        # 触发 ON_APPLY_PROPOSAL hooks
        _get_hook_registry().trigger(HookTrigger.ON_APPLY_PROPOSAL, {
            "workspace": str(workspace),
            "skill_name": skill_name,
            "skill_path": tmp_skill_path,
            "round_num": round_num,
            "candidate_id": candidate_id,
        })

        # 调 ApplyAgent 子 Agent 一次性应用 proposal 到 Skill
        try:
            invoke_apply_agent(
                state_engine,
                cand_skill_path=tmp_skill_path,
                candidate_id=candidate_id if candidate_id > 0 else 0,
                round_num=round_num,
                proposal_path=proposal_path,
            )
            _copy_back_whitelisted(tmp_skill_dir, skill_dir, round_num)
            print("  🔒 优化后 Skill 已从 /tmp 拷回 workspace（白名单过滤）")
            proposal_applied = True
        except Exception as e:
            print(f"  ❌ ApplyAgent 调用失败: {e}")
            state_engine.record_phase_fail(round_num, "apply", f"ApplyAgent 失败: {e}")
            return True

        state_engine.record_phase_complete(round_num, "apply")
        return True

    finally:
        shutil.rmtree(str(tmp_root), ignore_errors=True)

def run_single_round(state_engine: StateEngine, args, round_num: int) -> bool:
    """
    执行单个轮次：评测 → 更新状态 → 优化（inline 模式）

    Returns:
        True 如果该轮正常完成（无论是否达标），False 需要停止
    """
    # ── 保存 before 快照 ──
    state_engine.artifact_store.save_skill_snapshot(state_engine.skill_dir, round_num)

    # ── Phase: evaluate ──
    state_engine.record_phase_start(round_num, "evaluate")
    eval_result = run_evaluation(state_engine, args, round_num)

    state_engine.record_phase_complete(round_num, "evaluate")

    # ── Phase: score ──
    state_engine.record_phase_start(round_num, "score")
    state_engine.update_after_evaluation(eval_result, round_num)
    state_engine.record_phase_complete(round_num, "score")

    if state_engine.status in state_engine.TERMINAL_STATES:
        _bl_score = state_engine.config.get("current_score", 0) if state_engine.config else 0
        try:
            _save_round_analysis_json(state_engine, round_num, float(_bl_score), [float(_bl_score)], 0.0, [])
        except Exception as _e2:
            print(f"  ⚠️ 生成 round_analysis.json 失败: {_e2}")
        return False

    run_optimization(state_engine, args, eval_result, round_num)

    _bl_score2 = state_engine.config.get("current_score", 0) if state_engine.config else 0
    try:
        _save_round_analysis_json(state_engine, round_num, float(_bl_score2), [float(_bl_score2)], 0.0, [])
    except Exception as _e3:
        print(f"  ⚠️ 生成 round_analysis.json 失败: {_e3}")

    return True
