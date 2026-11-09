"""
广度优先评测模块
=================

负责广度优先评测的候选生成、评测、选择：
- _evaluate_baseline       : 独立基线评测
- _run_breadth_round       : 广度优先单轮
- _load_gaps_for_round     : 缺口加载
- _enrich_gaps_with_trace  : 缺口轨迹增强
- _generate_candidates     : 候选生成（批量）
- _evaluate_baseline_multi : 基线多次评测
- _evaluate_candidate      : 候选评测
- _generate_candidate_detail : 候选详情报告
- _generate_single_candidate : 单候选生成（串行）
- _clear_eval_artifacts    : 评测产物清理

所有候选生成统一通过 ApplyAgent 子 Agent（orchestrators.apply_agent.invoke_apply_agent）
读取 baseline/proposal.md 并对候选 Skill 副本做精准修改，不再使用 OptimizerGateway
或任何 strategy / previous_best_candidate / AgentGenesis 路由。
"""

from __future__ import annotations

import json
import math
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from metrics.config import MetricsConfig
from orchestrators.eval_pipeline import run_evaluation
from orchestrators.reports import _save_round_analysis_json
from orchestrators.skill_manager import (replace_skill_with_optimized,
                                         restore_skill_from_bak)
# 跨模块导入（避免循环依赖：workspace/reports 不依赖本模块）
from orchestrators.workspace import clean_eval_data_sandbox
# Score Analyzer 子Agent（格式无关的评测产物扫描与评分）
from scorer import ScoreAnalyzerAgent
from state_engine import DEFAULT_TARGET_SCORE
from state_engine.engine import StateEngine
from state_engine.persistence import atomic_write, ensure_dir

_SKILL_DIR = "skill"


def _replace_skill_content(skill_dir: Path, source_dir: Path) -> None:
    """用 source_dir 的全部内容完全替换 skill_dir 的内容（完整目录替换）

    仅用于 workspace 副本内部替换(state_engine.skill_dir),不涉及 user source。
    user source 覆盖请用 skill_manager.replace_skill_with_optimized。
    """
    if not source_dir.exists():
        raise FileNotFoundError(f"候选 skill 目录不存在: {source_dir}")

    if skill_dir.exists():
        shutil.rmtree(str(skill_dir))
    shutil.copytree(str(source_dir), str(skill_dir))


def _restore_skill_to_round_start(state_engine, round_num: int) -> None:
    """未采纳轮后,把 workspace skill 恢复为本轮起点(before 快照)。

    背景:apply 阶段 eval_pipeline._copy_sandbox_skill_back 会把优化后的 SKILL.md 无条件
    拷回 workspace skill,即使候选未优于基线。恢复为本轮起点(before 快照,评测前已保存),
    保证下一轮从最佳起点继续(跨轮继承源 = best_round 而非 round_num-1)。
    """
    snap = state_engine.workspace / f"round_{round_num}" / f"round_{round_num}_before_skill" / "skill"
    if snap.exists():
        _replace_skill_content(state_engine.skill_dir, snap)


def _evaluate_baseline(state_engine: StateEngine, args) -> tuple:
    """
    独立 baseline 评测阶段（在主循环前执行，不属于任何 round）

    流程：
    1. 创建 baseline/ 目录
    2. 执行 l 次评测取平均
    3. 保存 baseline/score_baseline.json 和 baseline/run_N/score.json

    Returns:
        (baseline_score, baseline_runs, baseline_std) 或 (0, [], 0) 失败时
    """
    l = state_engine.eval_runs_per_candidate()
    print(f"\n{'='*60}")
    print("  Baseline 评测（独立前置阶段）")
    print(f"{'='*60}")
    print(f"  📊 基线多轮评测: {l} 次")

    # 创建 baseline 目录
    from state_engine.persistence import ensure_dir as _ensure_dir
    baseline_dir = state_engine.artifact_store.workspace / "baseline"
    _ensure_dir(str(baseline_dir))

    # 拷贝 skill 文件夹到 baseline 目录
    import shutil as _shutil
    _sdn = _SKILL_DIR
    skill_src = state_engine.workspace / _sdn
    skill_dst = baseline_dir / _sdn
    if skill_src.exists() and not skill_dst.exists():
        _shutil.copytree(str(skill_src), str(skill_dst))

    baseline_runs = []
    baseline_score = 0.0
    baseline_std = 0.0

    # 全内联执行：统一调用 _evaluate_baseline_multi()
    bl_avg, bl_runs, bl_std, bl_details = _evaluate_baseline_multi(
        state_engine, args, 1, l, start_run=1
    )
    baseline_score = bl_avg if bl_avg is not None else 0.0
    baseline_runs = bl_runs if bl_runs else [baseline_score]
    baseline_std = bl_std if bl_std is not None else 0.0

    # 更新 in-memory + task_state.json(实时分/状态权威源)
    state_engine.baseline_score = baseline_score
    state_engine.current_score = baseline_score
    if baseline_score > state_engine.best_score:
        state_engine.best_score = baseline_score
        state_engine.best_round = -1

    # 基线分数落盘由 _evaluate_baseline_multi 内的 analyze_baseline 统一负责
    # （写 score_baseline.json + score_baseline_analysis.md + 各 run 的 score.json/score_analysis.md）
    # 不再额外调用 save_baseline_score，避免两套来源不一致

    # 将 baseline 分数写入 config.history（使 overview_report 能正确显示）
    from datetime import datetime as _dt

    from state_engine.persistence import load_json as _load_json_bl
    rating = "UNKNOWN"
    total_gaps = 0
    # 从 baseline/run_N/score.json 聚合 gaps（而非 score_baseline.json，它不包含 gaps）
    _all_bl_gaps = []
    for _bi in range(1, l + 1):
        _br_path = baseline_dir / f"run_{_bi}" / "score.json"
        if _br_path.exists():
            try:
                _br_sd = _load_json_bl(str(_br_path))
                _br_gaps = _br_sd.get("gaps", [])
                if _br_gaps and not _all_bl_gaps:
                    _all_bl_gaps = _br_gaps
                # 从最后一次 run 的 per_ran 推导 rating
                _br_per_ran = _br_sd.get("metadata", {}).get("per_ran", [])
                if _br_per_ran:
                    avg_f1 = sum(r.get("f1", 0) for r in _br_per_ran) / len(_br_per_ran)
                    if avg_f1 >= 90:
                        rating = "EXCELLENT"
                    elif avg_f1 >= 70:
                        rating = "GOOD"
                    elif avg_f1 >= 40:
                        rating = "FAIR"
                    elif avg_f1 > 0:
                        rating = "POOR"
                    else:
                        rating = "BROKEN"
            except Exception:
                pass
    total_gaps = len(_all_bl_gaps)

    bl_record = {
        "round": "baseline",
        "score": baseline_score,
        "rating": rating,
        "total_gaps": total_gaps,
        "skill_snapshot": "baseline/",
        "timestamp": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        "run_scores": [float(s) for s in baseline_runs],
    }
    state_engine.history.append(bl_record)

    # 检查 baseline 是否达标
    if baseline_score >= state_engine.config.get("target_score", DEFAULT_TARGET_SCORE):
        print("\n  ✅ Baseline 已达目标分数！")
        state_engine.status = "achieved"

    # ── Baseline 收尾:同步 task_state + 增量 score_history ──
    # 之前 baseline 跑完只写 config,没回写 task_state.json 的 current 段,
    # 也没写 score_history.md,导致监控/外部脚本读到 score=0/phase=eval 的脏状态。
    try:
        # status 用动态值(achieved / evaluated),与 line 201-203 的 config 写保持一致
        state_engine.record_current_progress(
            state_engine.status,
            f"baseline 评测完成 ({l} run),平均分 {baseline_score:.2f}",
            round_num=0,
            phase="baseline_done",
        )
        print(f"  ✅ task_state.current 已更新: phase=baseline_done, score={baseline_score:.2f}, status={state_engine.status}")
    except Exception as e:
        print(f"  ⚠️ baseline 收尾(更新 task_state)失败: {e}")

    # Baseline 阶段只有 evaluate,无 apply/score/proposal 步骤,标记 Round 0 其余阶段为 skipped
    # 避免监控脚本误判 Round 0 处于 pending 状态
    for _skipped_phase in ("apply", "score", "proposal"):
        try:
            state_engine.record_phase_skip(0, _skipped_phase, reason="baseline 阶段无此步骤")
        except Exception:
            pass

    try:
        from orchestrators.history import render_score_history_incremental
        _agent_dir = state_engine.artifact_store.workspace
        render_score_history_incremental(
            agent_dir=_agent_dir,
            config=state_engine.config,
            history=state_engine.history,
            skill_registry=state_engine.config.get("skill_registry", {}),
        )
        print("  ✅ score_history.md 已增量更新(基线行已注入)")
    except Exception as e:
        print(f"  ⚠️ score_history.md 增量更新失败(非致命): {e}")

    print(f"  ✅ Baseline 评测完成，分数: {baseline_score:.1f}")
    return baseline_score, baseline_runs, baseline_std


def _run_breadth_round(state_engine: StateEngine, args, round_num: int,
                       baseline_score: float, baseline_runs: list, baseline_std: float) -> bool:
    """
    执行一轮广度优先优化

    流程：
    1. 评测基线 skill → baseline_score
    2. 生成 n 个候选（不同策略）
    3. 对每个候选执行优化+评测（m 子轮）
    4. 选择最佳候选，与基线对比
    5. 高于基线则替换，否则保留旧基线

    Returns:
        True 继续下一轮，False 终止
    """
    n = state_engine.candidates_per_round()
    m = state_engine.sub_rounds_per_candidate()

    print(f"\n{'='*60}")
    print(f"  Round {round_num}: 广度优先评测")
    print(f"  候选数: {n} | 子轮数: {m}")
    print(f"{'='*60}")
    print(f"  Baseline 分数: {baseline_score:.1f} (σ={baseline_std:.1f}, runs={baseline_runs})")

    # ── 保存 before 快照（本轮起始基线）──
    state_engine.artifact_store.save_skill_snapshot(state_engine.skill_dir, round_num)

    # ── 检查 baseline 是否达标（在 round 开始前判断）──
    if state_engine.status == "achieved":
        print("  ✅ Baseline 已达目标分数，跳过本轮优化。")
        from state_engine.persistence import RoundReportBuilder
        from state_engine.persistence import load_json as _load_json
        _ach_score_path = state_engine.artifact_store._ensure_round_dir(round_num) / "score.json"
        _ach_score_data = _load_json(str(_ach_score_path)) if _ach_score_path.exists() else {}
        _ach_rrb = RoundReportBuilder(round_num)
        _ach_rrb.add_score_summary(baseline_score, baseline_runs, baseline_std, [], None)
        _ach_rrb.add_gap_root_cause_analysis(_ach_score_data)
        _ach_rrb.add_log_references(round_num)
        _ach_rrb.add_selection_decision(baseline_score, None, [])
        _ach_rrb.add_improvement_summary(_ach_score_data)
        _ach_rrb.save(state_engine.artifact_store, round_num)
        _save_round_analysis_json(state_engine, round_num, baseline_score, baseline_runs, baseline_std, [])
        return False

    # ── 备份基线轨迹（候选评测前保存，代表优化前状态）──
    import shutil as _tsh
    _t_trace = state_engine.workspace / f"round_{round_num}" / "trace_analysis.json"
    if _t_trace.exists():
        _t_baseline = _t_trace.with_name("trace_analysis_baseline.json")
        _tsh.copy2(str(_t_trace), str(_t_baseline))
        print("  [轨迹] 基线轨迹已备份 (优化前)")

    # ── Solution C：round > 1 时基于上一轮 history 重生 baseline/proposal.md ──
    # 深度模式在 run_single_round 内已接线；广度模式此前缺失，导致没有
    # prev_failure_block（"禁止重复上轮 file+section"）约束，跨轮吸收只靠新基线重评。
    try:
        from metrics.config import MetricsConfig as _MetricsConfig
        from scorer import ScoreAnalyzerAgent as _ScoreAnalyzerAgent
        _solc_analyzer = _ScoreAnalyzerAgent(_MetricsConfig.load())
        from orchestrators.proposal import (
            regenerate_proposal_with_history as _regenerate_proposal_with_history,
        )
        _regenerate_proposal_with_history(
            state_engine, args, round_num, _solc_analyzer,
        )
    except Exception as _e_solc_b:
        print(f"  [Solution C] 广度模式调用异常(继续执行,不影响主流程): {_e_solc_b}")

    # ── 从基线 proposal.md 加载 gaps（候选生成需要）──
    gaps = []
    eval_result = {}
    # 尝试从 baseline/proposal.md 提取 problems
    baseline_dir = state_engine.artifact_store.workspace / "baseline"
    bl_proposal_path = baseline_dir / "proposal.md"
    if bl_proposal_path.exists():
        try:
            import re as _re_bl
            content = bl_proposal_path.read_text(encoding="utf-8")
            fence = _re_bl.search(r'```(?:json)?\s*\n(.*?)\n```', content, re.DOTALL)
            if fence:
                data = json.loads(fence.group(1))
                gaps = data.get("problems", [])
            else:
                brace = _re_bl.search(r'\{.*?"problems".*?\}', content, re.DOTALL)
                if brace:
                    data = json.loads(brace.group(0))
                    gaps = data.get("problems", [])
            if gaps:
                eval_result = {
                    "score": 0.0,
                    "rating": "UNKNOWN",
                    "total_gaps": len(gaps),
                    "gaps": gaps,
                }
        except Exception:
            pass
    # 回退：从 in-memory history 或 config.history 加载
    if not gaps:
        hist_iter = state_engine.history or state_engine.config.get("history", [])
        for entry in hist_iter:
            if entry.get("round") == "baseline":
                gaps = entry.get("gaps", [])
                eval_result = {
                    "score": entry.get("score", 0.0),
                    "rating": entry.get("rating", "UNKNOWN"),
                    "total_gaps": entry.get("total_gaps", 0),
                    "gaps": gaps,
                }
                break

    # ── Step 2 & 3: 串行生成和评测每个候选 ──
    # 所有候选统一通过 ApplyAgent 子 Agent 读取 baseline/proposal.md 并修改 Skill 副本。
    candidate_scores = []
    all_eval_results = {
        "baseline": {
            "avg_score": baseline_score,
            "run_scores": baseline_runs,
            "stddev": baseline_std,
        },
    }

    for i in range(1, n + 1):
        # ── 生成候选 i（ApplyAgent 子 Agent）──
        print(f"\n  === 生成候选 {i} ===")

        # 生成单个候选（直接调共享 invoke_apply_agent）
        cand_info = _generate_single_candidate(
            state_engine, round_num, i,
        )

        if not cand_info:
            print(f"  ⚠️ 候选 {i} 生成失败，跳过评测")
            continue

        # ── 评测候选 i ──
        cand_id = cand_info["id"]
        cand_skill_path = cand_info["skill_path"]

        print(f"\n  --- 评测候选 {cand_id} ---")

        l = state_engine.eval_runs_per_candidate()
        avg_score, run_scores, stddev, run_details = _evaluate_candidate(
            state_engine, args, cand_skill_path, cand_id, round_num, l,
            baseline_score=baseline_score,
        )

        if avg_score is not None:
            candidate_scores.append({
                "id": cand_id,
                "score": avg_score,
                "strategy": "apply_agent",
                "run_scores": run_scores,
                "stddev": stddev,
                "run_details": run_details,
            })
            all_eval_results[f"candidate_{cand_id}"] = {
                "avg_score": avg_score,
                "run_scores": run_scores,
                "stddev": stddev,
                "run_details": run_details,
            }
            state_engine.record_candidate(
                cand_id, avg_score, "apply_agent", "UNKNOWN", 0, round_num,
                run_scores=run_scores, stddev=stddev,
            )
            print(f"  候选 {cand_id} 得分: {avg_score:.1f} (runs: {run_scores})")
        else:
            print(f"  ❌ 候选 {cand_id} 评测失败")

    # 保存候选清单（所有候选生成完后），含完整分数和依赖信息
    if candidate_scores:
        state_engine.artifact_store.save_candidates_manifest([
            {
                "id": c["id"],
                "strategy": c["strategy"],
                "score": c["score"],
                "stddev": c.get("stddev", 0.0),
                "run_scores": c.get("run_scores", []),
                "better_than_baseline": c["score"] > baseline_score,
                "based_on": "baseline" if c["id"] == 1 else f"candidate_{c['id'] - 1}",
            }
            for c in candidate_scores
        ], round_num)

    # 跳过的旧批量评测代码已删除（现为串行流程）

    # ── 打印评测结果摘要 ──

    # ── Step 4: 全量评测结果汇总分析 ──
    print(f"\n{'='*60}")
    print("  全量评测结果汇总")
    print(f"{'='*60}")
    print(f"  评测轮次: {l} 次/对象")
    print(f"\n  {'对象':<30} {'平均分':>8} {'标准差':>8} {'各轮得分'}")
    print(f"  {'─'*30} {'─'*8} {'─'*8} {'─'*30}")

    # 基线
    bl_runs_str = ", ".join(f"{s:.1f}" for s in (baseline_runs if 'baseline_runs' in dir() else [baseline_score]))
    bl_std = baseline_std if 'baseline_std' in dir() else 0.0
    print(f"  {'基线 (baseline)':<30} {baseline_score:>8.1f} {bl_std:>8.1f} [{bl_runs_str}]")

    # 候选
    for cs in candidate_scores:
        run_str = ", ".join(f"{s:.1f}" for s in cs["run_scores"])
        print(f"  {'候选 ' + str(cs['id']) + ' (' + cs['strategy'] + ')':<30} {cs['score']:>8.1f} {cs['stddev']:>8.1f} [{run_str}]")

    # 为每个候选生成详细报告 detail.md（已保留，提供 per-candidate 深度分析）
    for cs in candidate_scores:
        try:
            cand_id = cs["id"]
            # 查找对应的 run_details（从 all_eval_results 中）
            key = f"candidate_{cand_id}"
            run_details = all_eval_results.get(key, {}).get("run_details", [])
            _generate_candidate_detail(
                state_engine, cand_id, round_num,
                cs["score"], cs["run_scores"], cs["stddev"],
                run_details, baseline_score,
            )
        except Exception as e:
            print(f"  ⚠️ 生成候选 {cs['id']} 详细报告失败: {e}")

    print(f"\n{'='*60}")

    # ── Step 5: 选择最佳候选 ──
    if not candidate_scores:
        print("\n  ⚠️ 所有候选评测失败，保留基线")
        return True

    # ── 调用 ScoreAnalyzerAgent 做同轮归一化 ──
    try:
        from metrics.config import MetricsConfig
        metrics_config = MetricsConfig.load()
        analyzer = ScoreAnalyzerAgent(metrics_config)

        round_dir = state_engine.artifact_store._ensure_round_dir(round_num)
        candidate_ids = [c["id"] for c in candidate_scores]
        strategy_map = {c["id"]: c["strategy"] for c in candidate_scores}

        round_score = analyzer.analyze_round(
            round_dir, round_num,
            candidate_ids=candidate_ids,
            strategy_map=strategy_map,
            case_ids=state_engine.config.get("case_ids") or None,
        )

        # 用 composite 分数更新候选排序
        for cs in round_score.candidates:
            for local_cs in candidate_scores:
                if local_cs["id"] == cs.candidate_id:
                    local_cs["composite"] = cs.composite
                    local_cs["normalized"] = cs.normalized
                    break

        # 按 composite 分数排序（而非原始 score）
        candidate_scores.sort(key=lambda c: c.get("composite", c["score"]), reverse=True)
        best = candidate_scores[0]
        print("  [ScoreAnalyzer] 归一化完成，按综合分排序")
        for cs in round_score.candidates:
            print(f"    Candidate {cs.candidate_id}: composite={cs.composite:.1f}")
    except Exception as e:
        import traceback as _tb
        print(f"  ⚠️ ScoreAnalyzer 归一化失败: {type(e).__name__}: {e}，回退到原始分数", flush=True)
        _tb.print_exc()
        candidate_scores.sort(key=lambda c: c["score"], reverse=True)
        best = candidate_scores[0]

    score_strs = [f"c{c['id']}({c['score']:.1f})" for c in candidate_scores]
    print(f"\n  候选排序: {' > '.join(score_strs)}")
    print(f"  最佳候选: c{best['id']} ({best['strategy']}) = {best['score']:.1f} 分")
    print(f"  基线分数: {baseline_score:.1f} 分")

    # ── 保存最佳候选标记 ──
    better = best["score"] > baseline_score
    state_engine.artifact_store.save_best_candidate_marker(
        best["id"], best["score"], best["strategy"],
        better, baseline_score, round_num,
    )

    # ── 达标终止：候选达到目标分后不再继续迭代 ──
    # 修复：此前只在 baseline 阶段检查 target_score，导致候选拿满分后仍跑满 max_rounds。
    _target_score = float(
        state_engine.config.get("target_score", DEFAULT_TARGET_SCORE)
        or DEFAULT_TARGET_SCORE
    )
    if _target_score > 0 and best.get("score", 0) >= _target_score:
        state_engine.status = "achieved"
        try:
            state_engine.record_current_progress(
                status="achieved",
                detail=(f"round {round_num} 候选 c{best['id']} 达到目标分 "
                        f"{best['score']:.1f}（目标 {_target_score:.0f}），终止迭代"),
                round_num=round_num,
                phase="finish",
            )
        except Exception:
            pass
        print(f"  ✅ 候选 c{best['id']} 达到目标分 {_target_score:.0f}，本轮结束后终止迭代")

    # ── Step 5: 保存最佳候选轨迹（候选评测可能覆盖基线轨迹，需在替换前保存）──
    import shutil as _tsh2
    _t_best = state_engine.workspace / f"round_{round_num}" / "trace_analysis.json"
    if _t_best.exists():
        try:
            _best_dest = _t_best.with_name("trace_analysis_best.json")
            _tsh2.copy2(str(_t_best), str(_best_dest))
            print("  [轨迹] 最佳候选轨迹已保存 (优化后)")
        except Exception:
            pass

    # ── Step 5.1: 与基线对比 ──
    if best["score"] > baseline_score:
        print(f"  ✅ 候选 c{best['id']} 优于基线 ({best['score']:.1f} > {baseline_score:.1f})，替换基线")
        # 用最佳候选的 Skill 副本覆盖 workspace skill
        cand_skill_dir = state_engine.artifact_store._candidate_dir(best["id"], round_num) / _SKILL_DIR
        _replace_skill_content(state_engine.skill_dir, cand_skill_dir)
        state_engine.skill_path = state_engine.skill_dir / "SKILL.md"
        print(f"  ✅ 基线已替换为候选 {best['id']}")
        # 更新 best_score(in-memory + task_state)
        state_engine.best_score = best["score"]
        state_engine.best_round = round_num
        # 记录本轮采纳的候选 id,供 _re_evaluate_as_new_baseline 重新端到端评测
        state_engine.config["current_best_candidate_id"] = best["id"]
    else:
        print(f"  ⚠️ 无候选优于基线 ({best['score']:.1f} <= {baseline_score:.1f})，保留旧基线")
        # 修复(2026-08-05):未采纳时恢复 workspace skill 到本轮起点(避免污染下一轮)
        _restore_skill_to_round_start(state_engine, round_num)

    state_engine.config_store.save(state_engine.config)
    # ── Bug 6 修复：广度模式也保存 round 级别 proposal.md ──
    # 将最佳候选的提案内容复制为 round 级别的 proposal.md
    if best["score"] > baseline_score:
        best_cand_dir = state_engine.artifact_store._candidate_dir(best["id"], round_num)
        best_proposal = best_cand_dir / "proposal.md"
        round_proposal = state_engine.artifact_store._ensure_round_dir(round_num) / "proposal.md"
        if best_proposal.exists():
            import shutil as _sh5
            _sh5.copy2(str(best_proposal), str(round_proposal))
        else:
            # 候选目录下没有 proposal.md 时，生成摘要版提案
            cand_skill_dir = state_engine.artifact_store._candidate_dir(best["id"], round_num) / _SKILL_DIR
            workspace_skill_dir = state_engine.skill_dir
            prop_lines = [
                f"# Round {round_num} 优化提案（候选 c{best['id']}）",
                "",
                f"策略：{best['strategy']}",
                f"分数：{best['score']:.1f}（基线 {baseline_score:.1f}）",
                "",
            ]
            # 对比 skill 差异
            try:
                import difflib as _dl
                ws_skill = workspace_skill_dir / "SKILL.md"
                c_skill = cand_skill_dir / "SKILL.md"
                if ws_skill.exists() and c_skill.exists():
                    ws_lines = ws_skill.read_text(encoding="utf-8").splitlines(keepends=True)
                    c_lines = c_skill.read_text(encoding="utf-8").splitlines(keepends=True)
                    diff = list(_dl.unified_diff(ws_lines, c_lines, fromfile="before", tofile="after"))
                    if diff:
                        prop_lines.append("```diff")
                        prop_lines.extend(diff[:100])  # 限制前 100 行
                        prop_lines.append("```")
            except Exception:
                pass
            from state_engine.persistence import atomic_write
            atomic_write(str(round_proposal), "\n".join(prop_lines))

    # ── Bug 7 修复：广度模式下 history 不会自动更新，需手动追加本轮最佳分数 ──
    # 选择最佳候选后，将结果追加到 history（与深度模式的 update_after_evaluation 一致）
    best_score = state_engine.best_score
    best_round_num = state_engine.best_round
    if best_round_num == round_num and best_score > 0:
        round_score_path = state_engine.artifact_store._ensure_round_dir(round_num) / "score.json"
        rating = "UNKNOWN"
        total_gaps = 0
        if round_score_path.exists():
            import json as _j3
            try:
                sd = _j3.loads(round_score_path.read_text(encoding="utf-8"))
                # 从 per_ran 聚合推导评级
                per_ran = sd.get("metadata", {}).get("per_ran", [])
                if per_ran:
                    avg_f1 = sum(r.get("f1", 0) for r in per_ran) / len(per_ran)
                    if avg_f1 >= 90:
                        rating = "EXCELLENT"
                    elif avg_f1 >= 70:
                        rating = "GOOD"
                    elif avg_f1 >= 40:
                        rating = "FAIR"
                    elif avg_f1 > 0:
                        rating = "POOR"
                    else:
                        rating = "BROKEN"
                total_gaps = len(sd.get("gaps", []))
            except Exception:
                pass

        from datetime import datetime
        record = {
            "round": round_num,
            "score": best_score,
            "rating": rating,
            "total_gaps": total_gaps,
            "skill_snapshot": f"candidate_{state_engine.config.get('current_best_candidate_id', -1)}/skill/",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "run_scores": [cs["score"] for cs in candidate_scores],
        }
        # Solution C 依赖：记录本轮 modifications 摘要 + 决策口径，
        # 供下一轮 regenerate_proposal_with_history 构造 prev_failure_block（避免重复试错方向）。
        _mods_summary = []
        try:
            from orchestrators.proposal import (
                parse_proposal_modifications_summary as _ppms,
            )
            _round_proposal = (
                state_engine.artifact_store._ensure_round_dir(round_num) / "proposal.md"
            )
            if _round_proposal.exists():
                _mods_summary = _ppms(_round_proposal) or []
        except Exception:
            _mods_summary = []
        record["modifications_summary"] = _mods_summary
        record["decision"] = "adopted"
        record["baseline_score"] = baseline_score
        record["vs_baseline_delta"] = round(best_score - baseline_score, 2)
        state_engine.history.append(record)

    # ── Bug 7 修复：同步 current_score = best_score，确保 overview_report 使用正确分数 ──
    state_engine.current_score = best_score

    # 生成合并后的轮次报告（分数 + 根因 + 选择决策）
    from state_engine.persistence import load_json as _load_json
    score_path = state_engine.artifact_store._ensure_round_dir(round_num) / "score.json"
    score_data = _load_json(str(score_path)) if score_path.exists() else {}

    best_cand = None
    if candidate_scores:
        top = max(candidate_scores, key=lambda c: c["score"])
        if top["score"] > baseline_score:
            best_cand = top

    from state_engine.persistence import RoundReportBuilder
    rrb = RoundReportBuilder(round_num)
    rrb.add_score_summary(baseline_score, baseline_runs, bl_std, candidate_scores, best_cand)
    rrb.add_gap_root_cause_analysis(score_data)
    rrb.add_log_references(round_num)
    rrb.add_selection_decision(baseline_score, best_cand, candidate_scores)
    rrb.add_improvement_summary(score_data)
    rrb.save(state_engine.artifact_store, round_num)

    # 生成结构化评测分析文件（JSON）
    _save_round_analysis_json(state_engine, round_num, baseline_score, baseline_runs, baseline_std, candidate_scores)

    # 广度模式：写入 round_N/score.json（最佳候选完整数据）
    _save_round_score_json(state_engine, round_num, baseline_score, candidate_scores)

    return True


# ═══════════════════════════════════════════════════════════════
#  广度优先辅助函数
# ═══════════════════════════════════════════════════════════════

# 候选生成策略列表（AgentGenesis 11 个优化模式）已删除：
# 单 Skill 模式与多 Skill 模式统一使用 ApplyAgent 子 Agent，
# 不再需要 strategy 路由、strategy_history、previous_best_candidate、AgentGenesis 模式目录


def _load_gaps_for_round(state_engine: StateEngine, round_num: int) -> list:
    """从 proposal.md 提取 problems 作为 gaps。"""
    round_dir = state_engine.artifact_store._ensure_round_dir(round_num)
    proposal_path = round_dir / f"round_{round_num}_proposal.md"
    if proposal_path.exists():
        try:
            content = proposal_path.read_text(encoding="utf-8")
            # 提取 JSON problems 数组
            fence = re.search(r'```(?:json)?\s*\n(.*?)\n```', content, re.DOTALL)
            if fence:
                data = json.loads(fence.group(1))
                return data.get("problems", [])
            brace = re.search(r'\{.*?"problems".*?\}', content, re.DOTALL)
            if brace:
                data = json.loads(brace.group(0))
                return data.get("problems", [])
        except Exception:
            pass
    return []


def _enrich_gaps_with_trace(gaps: list, round_num: int, workspace: Path):
    """
    从 baseline 评测的 trace_summary.json 提取执行层诊断，注入到 gaps 中。

    当 gap 只有 "F1=0" 这种抽象信息时，trace 诊断能补充：
    - Agent 执行过程中遇到的文件未找到错误
    - 输出路径偏差（写到了错误的目录）
    - 工具调用异常长间隔（Agent 卡住）
    - 输出文件是否存在
    """
    import json as _ej

    trace_dir = workspace / "baseline"
    if not trace_dir.exists():
        return

    errors_found = []
    output_issues = []

    # 通用：递归查找 baseline/run_*/data/**/*trace_summary*.json
    for run_dir in sorted(trace_dir.glob("run_*")):
        data_dir = run_dir / "data"
        if not data_dir.is_dir():
            continue
        for summary in data_dir.glob("**/*trace_summary*.json"):
            try:
                tdata = _ej.loads(summary.read_text(encoding="utf-8"))
                # 提取执行错误
                errs = tdata.get("errors", [])
                for e in errs:
                    err_msg = e.get("message", "") or e.get("error", "") or str(e)
                    if err_msg:
                        errors_found.append(err_msg[:200])
                # 提取输出文档状态
                content = tdata.get("content_indicators", {})
                if not content.get("output_document_exists", True):
                    output_issues.append("输出文件不存在")
                # 提取执行流异常
                flow = tdata.get("execution_flow", {})
                gap_seconds = flow.get("gaps_between_actions_seconds", 0)
                if gap_seconds > 30:
                    output_issues.append(f"执行流异常间隔: {gap_seconds}s")
            except Exception:
                pass

    # 去重
    errors_found = list(dict.fromkeys(errors_found))[:10]  # 最多 10 条
    output_issues = list(dict.fromkeys(output_issues))[:5]

    if errors_found or output_issues:
        exec_gap = {
            "type": "execution_error",
            "severity": "critical",
            "affected_section": "执行流程",
            "root_cause": "；".join(errors_found[:5]) if errors_found else "执行流程异常",
            "fix_suggestion": (
                f"Agent 执行时遇到 {len(errors_found)} 个错误: {'; '.join(errors_found[:3])}. "
                + (f"输出问题: {'; '.join(output_issues[:3])}. " if output_issues else "")
                + "请检查 SKILL.md 中的文件路径声明和输入输出目录配置是否正确"
            ),
            "message": f"执行诊断: {len(errors_found)} 个文件错误, {len(output_issues)} 个输出问题",
        }
        gaps.append(exec_gap)
        print(f"  [轨迹诊断] 追加 {len(errors_found)} 个执行错误 + {len(output_issues)} 个输出问题到 gaps")


def _generate_candidates(state_engine: StateEngine, args, round_num: int, n: int) -> tuple[List[dict], dict]:
    """
    生成 n 个优化候选（批量入口，未被当前串行流程调用，保留作为可复用函数）。

    所有候选统一通过 ApplyAgent 子 Agent（orchestrators.apply_agent.invoke_apply_agent）
    读取 baseline/proposal.md 并对候选 Skill 副本做精准修改。

    Returns:
        (candidates, strategy_reasoning)
        candidates = [{"id": 1, "strategy": "apply_agent", "skill_path": "..."}, ...]
        strategy_reasoning = {candidate_id: {"strategy": "apply_agent", ...}}
    """
    import json as _json
    import shutil as _shutil

    from orchestrators.apply_agent_compat import \
        invoke_apply_agent_compat as invoke_apply_agent

    skill_path = str(state_engine.skill_path)

    # 从 score.json 加载 gaps（仅用于轨迹增强，不传给 ApplyAgent）
    score_path = state_engine.artifact_store._ensure_round_dir(round_num) / "score.json"
    gaps = []
    if score_path.exists():
        try:
            data = _json.loads(score_path.read_text(encoding="utf-8"))
            gaps = data.get("gaps", [])
        except Exception:
            pass

    if not gaps:
        print("  无缺口，跳过候选生成")
        return [], {}

    # 缺口增强
    for g in gaps:
        if not g.get("root_cause"):
            g["root_cause"] = g.get("message", "")
        if not g.get("fix_suggestion"):
            g["fix_suggestion"] = g.get("message", "")

    # ── 轨迹诊断增强：从 trace_summary.json 提取执行层错误注入到 gaps ──
    _enrich_gaps_with_trace(gaps, round_num, state_engine.workspace)

    # ── 轨迹分析结果参考（如存在）──
    trace_path = state_engine.workspace / f"round_{round_num}" / "trace_analysis.json"
    if trace_path.exists():
        try:
            import json as _json2
            trace_data = _json2.loads(trace_path.read_text(encoding="utf-8"))
            t_sum = trace_data.get("summary", {})
            t_gaps = trace_data.get("gaps", [])
            print(f"  [轨迹分析] 分数={t_sum.get('overall_score', 0):.1f}, "
                  f"评级={t_sum.get('quality_rating', '?')}, "
                  f"信号={t_sum.get('total_signals', 0)}, "
                  f"缺口={t_sum.get('total_gaps', 0)}")
            for tg in t_gaps[:5]:
                print(f"    └─ {tg.get('severity', '?')} {tg.get('type', '?')} "
                      f"@ {tg.get('affected_section', '?')}: {tg.get('message', '')[:60]}")
            if len(t_gaps) > 5:
                print(f"    └─ ... 另有 {len(t_gaps)-5} 个缺口")
        except Exception:
            pass

    # 标注 trace 来源缺口
    trace_gap_count = sum(1 for g in gaps if g.get("source") == "trace_analysis")
    pipeline_gap_count = len(gaps) - trace_gap_count
    if trace_gap_count > 0:
        print(f"  缺口来源: {pipeline_gap_count} 评测 + {trace_gap_count} 轨迹分析")

    # ── 分配 n 个候选（全部走 ApplyAgent，strategy 字段统一为 "apply_agent"）──
    strategy_reasoning = {}
    for i in range(1, n + 1):
        strategy_reasoning[i] = {
            "strategy": "apply_agent",
            "candidate_id": i,
            "assign_reason": "ApplyAgent 子 Agent 统一处理，读取 baseline/proposal.md 改 Skill 副本",
            "matched_gaps": ["无关键词匹配"],
            "total_gaps": len(gaps),
            "ranked_patterns_count": 0,
            "has_pattern_match": False,
        }

    candidates = []

    for i in range(1, n + 1):
        print(f"\n  生成候选 {i} (apply_agent)...")

        # 为每个候选创建独立的 skill 副本
        cand_dir = state_engine.artifact_store._candidate_dir(i, round_num) / _SKILL_DIR
        if cand_dir.exists():
            _shutil.rmtree(str(cand_dir))
        # baseline-anchored 模式:从 round_1_before_skill 锚定 baseline 起点(与 orchestrator.py 行为一致)
        # ★ round_num > 1:R1 时还没写 before_skill,R1 用初始化 baseline;R2+ 严格读 R1 anchor
        # ★ 路径用 state_engine.workspace(StateEngine 无 agent_dir 属性)
        _inherit_src = state_engine.skill_dir
        if is_baseline_anchored() and round_num > 1:
            _anchor = state_engine.workspace / "round_1" / "round_1_before_skill" / "skill"
            if _anchor.exists():
                _inherit_src = _anchor
            else:
                raise FileNotFoundError(
                    f"baseline_anchored=true 但 {_anchor} 不存在;"
                    f"需先跑过 round_1 产生 before_skill 后再启用此开关"
                )
        _shutil.copytree(str(_inherit_src), str(cand_dir),
                        ignore=lambda d, f: [x for x in f if x.endswith(".proposed")])

        cand_skill_path = str(cand_dir / "SKILL.md")

        # 读 Stage 4 verdict（如存在），REJECTED 时跳过 apply
        # ⚠️ 临时禁用(2026-06-18):Stage 4 整体注释,verdict 强制 None,ApplyAgent 不再 skip。
        # 取消下面注释块即可恢复。
        _self_check_verdict = None
        # try:
        #     import json as _json_v
        #     _sc_path = (state_engine.artifact_store.workspace / "baseline"
        #                 / "_proposal" / "stage_4_self_check.json")
        #     if _sc_path.exists():
        #         _sc_data = _json_v.loads(_sc_path.read_text(encoding="utf-8"))
        #         _self_check_verdict = _sc_data.get("verdict")
        # except Exception:
        #     pass

        # 调用 ApplyAgent 子 Agent 修改候选 Skill 副本
        try:
            invoke_apply_agent(
                state_engine, cand_skill_path, i, round_num,
                self_check_verdict=_self_check_verdict,
            )
        except Exception as e:
            import traceback
            print(f"  ❌ 候选 {i} ApplyAgent 抛出异常: {e}")
            traceback.print_exc()
            continue

        # REJECTED 时 strategy 标记为 skipped,便于后续区分
        _strategy = "apply_agent"
        if _self_check_verdict == "REJECTED":
            _strategy = "skipped_stage_4_rejected"

        candidates.append({
            "id": i,
            "strategy": _strategy,
            "skill_path": cand_skill_path,
        })
        print(f"  ✅ 候选 {i} 已生成（strategy={_strategy}）")

    # 保存候选清单
    state_engine.artifact_store.save_candidates_manifest([
        {"id": c["id"], "strategy": c["strategy"]} for c in candidates
    ], round_num)

    print(f"\n  候选生成完成: {len(candidates)}/{n} 个成功")
    return candidates, strategy_reasoning


def _evaluate_baseline_multi(state_engine: StateEngine, args, round_num: int, l: int = 3, start_run: int = 1) -> tuple:
    """
    对基线 skill 执行 l 次独立评测，取平均分。

    Args:
        l: 独立评测次数
        start_run: 起始 run 索引（用于主进程接续子进程的 run），默认从 1 开始

    Returns:
        (avg_score, run_scores, stddev) 或 (None, [], None) 表示全部失败
    """

    baseline_skill_dir = state_engine.skill_dir
    workspace = Path(args.workspace).resolve()
    baseline_dir = state_engine.artifact_store.workspace / "baseline"

    # baseline 评测不覆盖原路径(读的就是原路径),无需 backup/restore。
    # .bak 已在 init 阶段由 backup_skill_to_bak 创建,跨 baseline+所有 candidate 复用。
    original_skill_dir = state_engine._original_skill_path.parent
    return _evaluate_baseline_multi_inner(state_engine, args, round_num, l, start_run, baseline_dir, baseline_skill_dir, Path(), original_skill_dir)


def _evaluate_baseline_multi_inner(state_engine: StateEngine, args, round_num: int, l: int, start_run: int, baseline_dir, baseline_skill_dir, backup_root, original_skill_dir) -> tuple:
    """基线多次评测内部逻辑（与备份/恢复解耦）"""
    run_scores = []
    run_details = []

    # 提前创建 analyzer：每次 run_evaluation 后立即调 analyze_run 写 score.json，
    # 否则 for 循环结束时才统一调 analyze_baseline，循环内读 score.json 时文件还不存在 → 拿到 0
    metrics_config = MetricsConfig.load()
    analyzer = ScoreAnalyzerAgent(metrics_config)

    for run_i in range(start_run, start_run + l):
        print(f"  基线评测 [{run_i}/{start_run + l - 1}]...", end=" ", flush=True)

        # 清除上次评测产物（含 CC 分数文件）
        workspace_path = getattr(args, 'workspace', None)
        _clear_eval_artifacts(round_num, run_i, workspace_path,
                              stage=f"baseline_round_{round_num}_run_{run_i}")

        # 设置 eval_run 索引和评测模式，确保每次评测使用独立的 CC 分数文件和归档目录
        args.eval_run_index = run_i
        args.eval_mode = "baseline"
        args.candidate_id = -1

        try:
            eval_result = run_evaluation(state_engine, args, round_num, is_baseline=True)

            # 修复 0 分 bug：run_evaluation 仅归档 data/，不写 score.json。
            # 必须在本次 run 后立即调 analyze_run 把 score.json 写出来，
            # 否则下方的"读 score.json"会拿到 0.0。
            run_dir_for_score = baseline_dir / f"run_{run_i}"
            if run_dir_for_score.exists():
                try:
                    _case_ids = state_engine.config.get("case_ids") or None
                    analyzer.analyze_run(
                        run_dir_for_score, -1, -1, run_i,
                        case_ids=_case_ids,
                    )
                except Exception as _e:
                    print(f"  ⚠️ analyze_run 失败 (run {run_i}): {_e}", flush=True)

            # 提取分数：优先读取 ScoreAnalyzerAgent 生成的 score.json（真实分数）
            # 不再从 eval_result.get("score") 取（该值固定为 0.0，仅表示执行状态）
            run_score = None
            run_data = {}
            eval_error = False
            if eval_result and isinstance(eval_result, dict):
                run_data["metadata"] = eval_result.get("metadata", {})
                run_data["gaps"] = eval_result.get("gaps", [])
                rating = eval_result.get("rating", "")
                if rating == "BROKEN":
                    eval_error = True
                for gap in run_data.get("gaps", []):
                    if "评测管道异常" in gap.get("message", "") or "评测异常" in gap.get("message", ""):
                        eval_error = True
                        break

            # 从 ScoreAnalyzerAgent 生成的 score.json 回读真实分数
            # ScoreAnalyzerAgent 在 run_evaluation 内已调用并写入 baseline/run_N/score.json
            from state_engine.persistence import load_json as _lj
            score_json_path = baseline_dir / f"run_{run_i}" / "score.json"
            if score_json_path.exists():
                try:
                    score_data = _lj(str(score_json_path))
                    rs = score_data.get("result_score")
                    if rs is not None:
                        run_score = float(rs)
                        # 从 score.json 的 info 中补充执行元数据
                        info = score_data.get("info", {})
                        if info and not run_data.get("metadata"):
                            run_data["metadata"] = info
                except Exception:
                    pass

            # 兜底：如果 score.json 未生成或提取失败，回退到 eval_result 或记为 0.0
            if run_score is None:
                run_score = 0.0
                if eval_error:
                    print("0.0 (评测执行错误)")
                else:
                    print("0.0 (评测失败)")
            else:
                label = ""
                if eval_error:
                    label = " (⚠️ 评测执行错误)"
                print(f"{run_score:.1f}{label}")

            if eval_error:
                run_data["_eval_error"] = True

            run_scores.append(run_score)
            run_details.append(run_data)

        except Exception as e:
            print(f"0.0 (异常: {e})")
            run_scores.append(0.0)
            run_details.append({"_eval_error": True, "error": str(e)})

    if not run_scores:
        return None, [], None, []

    avg_score = sum(run_scores) / len(run_scores)
    if len(run_scores) > 1:
        mean = avg_score
        variance = sum((s - mean) ** 2 for s in run_scores) / len(run_scores)
        stddev = math.sqrt(variance)
    else:
        stddev = 0.0

    # 指标记录（仅记录平均分，phase timing 由 run_evaluation 内完成）
    metrics = getattr(args, 'metrics_collector', None)
    if metrics:
        metrics.record(round_num, "result_score", avg_score)

    # 保留内存中的基线聚合数据供 run_details/error_runs 记录使用
    # 注：实际分数落盘由下文的 analyze_baseline 统一负责（score_baseline.json + score_baseline_analysis.md）
    baseline_multi_data = {
        "avg_score": avg_score,
        "run_scores": run_scores,
        "stddev": stddev,
        "num_runs": len(run_scores),
        "run_details": run_details,
    }

    error_runs = [i for i, s in enumerate(run_scores) if s == 0.0]
    if error_runs:
        baseline_multi_data["zero_score_runs"] = error_runs

    run_str = ", ".join(f"{s:.1f}" for s in run_scores)
    print(f"  基线平均: {avg_score:.1f} [({run_str}), σ={stddev:.1f}]")

    # ── ScoreAnalyzerAgent：扫描基线产物，提取多维度指标 ──
    # 复用函数顶部创建的 analyzer（line 1185-1186），避免重复实例化。
    # analyze_baseline 内部已统一写 score_baseline.json + score_baseline_analysis.md，
    # 不再调用 _write_baseline_score_analysis（避免重复写旧名 baseline_score.*）。
    try:
        baseline_dir_full = state_engine.artifact_store.workspace / "baseline"
        if baseline_dir_full.exists():
            bl_round_score = analyzer.analyze_baseline(
                baseline_dir_full, round_num,
                case_ids=state_engine.config.get("case_ids") or None,
            )
            bl_composite = bl_round_score.baseline_score.composite if bl_round_score.baseline_score else 0.0
            print(f"  [ScoreAnalyzer] 基线综合分: {bl_composite:.1f}")
    except Exception as e:
        print(f"  ⚠️ ScoreAnalyzer 基线分析失败: {e}")

    return avg_score, run_scores, stddev, run_details


def _re_evaluate_as_new_baseline(
    state_engine: StateEngine,
    args,
    prev_round_num: int,
) -> tuple:
    """
    把上一轮采纳的"最佳 Skill 组合"作为新基线,重新端到端跑 l 次 + 生成新 proposal。

    业务背景:广度模式下,每轮采纳优于基线的最佳候选后,下一轮仍会读
    baseline/proposal.md 来生成候选;但若不重跑新基线:
    - baseline/score_baseline.json 还停留在旧基线的分数,下一轮的"是否达标"判断会失真
    - baseline/proposal.md 还是旧基线跑出的 gaps,候选优化方向基于过期信息
    - 后续 round 比较时也是拿新候选 vs 旧基线分数,口径不一致

    本函数解决:把"上一轮最佳候选的 Skill 副本"当作新基线 skill,再调用
    `_evaluate_baseline_multi` 跑 l 次(默认 = eval_runs_per_candidate),
    ScoreAnalyzerAgent.analyze_baseline 内部会顺带触发 _generate_proposal_via_agent
    覆盖 baseline/proposal.md,这样下一轮看到的就是新基线的 gaps。

    Args:
        state_engine: 当前 StateEngine
        args: CLI 参数
        prev_round_num: 上一轮编号(被采纳的候选所在 round)

    Returns:
        (avg_score, run_scores, stddev) 成功
        (None, [], 0.0) 失败(候选副本缺失 / 评测异常)
    """
    best_cand_id = state_engine.config.get("current_best_candidate_id")
    if best_cand_id is None:
        print("  ⚠️ current_best_candidate_id 缺失,无法重跑新基线")
        return None, [], 0.0

    cand_skill_dir = state_engine.artifact_store._candidate_dir(best_cand_id, prev_round_num) / _SKILL_DIR
    if not cand_skill_dir.exists():
        print(f"  ⚠️ 最佳候选 skill 副本不存在: {cand_skill_dir},无法重跑新基线")
        return None, [], 0.0

    # 1. 把最佳候选 skill 副本覆盖到 workspace skill 目录(就是"新基线")
    print(f"  📋 切换基线:round {prev_round_num} 候选 c{best_cand_id} "
          f"→ 替换为新 baseline skill")
    try:
        _replace_skill_content(state_engine.skill_dir, cand_skill_dir)
        state_engine.skill_path = state_engine.skill_dir / "SKILL.md"
    except Exception as e:
        print(f"  ⚠️ 新基线 skill 替换失败: {e}")
        return None, [], 0.0

    # 2. 备份旧 baseline/ 目录(run_1/, run_2/, score_baseline.json, proposal.md)
    #    因为 evaluate_baseline_multi 会原地覆盖这些文件,保留旧值便于回溯
    workspace = state_engine.artifact_store.workspace
    old_baseline_dir = workspace / "baseline"
    archive_dir = workspace / f"round_{prev_round_num}_old_baseline"
    if old_baseline_dir.exists() and not archive_dir.exists():
        try:
            shutil.copytree(str(old_baseline_dir), str(archive_dir))
            print(f"  📦 旧基线产物已备份到 {archive_dir.relative_to(workspace)}/")
        except Exception as e:
            print(f"  ⚠️ 旧基线备份失败(非致命): {e}")

    # 3. 调用 _evaluate_baseline_multi 跑 l 次(默认 2 = eval_runs_per_candidate)
    l_runs = state_engine.eval_runs_per_candidate()
    print(f"  🔁 新基线重新评测: {l_runs} 次 run")
    try:
        avg, runs, std, _ = _evaluate_baseline_multi(
            state_engine, args, round_num=prev_round_num, l=l_runs,
        )
    except Exception as e:
        print(f"  ⚠️ 新基线重跑异常: {e}")
        return None, [], 0.0

    if avg is None:
        print("  ⚠️ 新基线重跑失败(无有效分数)")
        return None, [], 0.0

    # 4. 验证 baseline/proposal.md 已被刷新(analyze_baseline 内部触发 _generate_proposal_via_agent)
    new_proposal = old_baseline_dir / "proposal.md"
    if new_proposal.exists():
        mtime = datetime.fromtimestamp(new_proposal.stat().st_mtime).strftime("%H:%M:%S")
        print(f"  ✅ 新 baseline/proposal.md 已生成 (mtime={mtime})")
    else:
        print("  ⚠️ 新 baseline/proposal.md 未生成,下一轮候选可能基于过期 gaps")

    # 5. 同步把新 proposal 拷贝到新基线归档目录(留底,便于对比)
    if new_proposal.exists() and archive_dir.exists():
        try:
            shutil.copy2(str(new_proposal), str(archive_dir / "proposal.md"))
        except Exception:
            pass

    return avg, runs, std if std is not None else 0.0


def _evaluate_candidate(state_engine: StateEngine, args, cand_skill_path: str,
                        cand_id: int, round_num: int, l: int = 3,
                        baseline_score: float = 0.0,
                        strategy: str = "unknown") -> tuple:
    """
    对单个候选执行 l 次独立评测，取平均分。

    Args:
        l: 独立评测次数
        baseline_score: 基线分数（用于提前剪枝）

    Returns:
        (avg_score, run_scores, stddev, run_details) 或 (None, [], None, []) 表示全部失败
        如果被剪枝，返回 (first_run_score, [first] * l, 0.0, [first_data] * l) 并标记 _pruned

    注: sub_rounds_per_candidate (m) 参数已弃用，语义与 eval_runs_per_candidate 重叠。
    """

    cand_skill_dir = Path(cand_skill_path).parent
    workspace = Path(args.workspace).resolve()

    # .bak 已在 init 阶段由 backup_skill_to_bak 创建(跨多 candidate 复用)
    # 这里不再重复 backup,直接覆盖 + finally 恢复
    original_skill_dir = state_engine._original_skill_path.parent
    user_source_skill_path = original_skill_dir / "SKILL.md"
    skill_registry = {original_skill_dir.name: str(user_source_skill_path)}

    # ── eval 时拷贝：把候选 skill 覆盖到用户源,eval 读用户源 ──
    # cand_skill_dir = round_N/candidate_K/skill/SkillName/,
    # 其父目录 cand_skill_dir.parent = round_N/candidate_K/skill/ 即候选根
    candidate_skill_root = cand_skill_dir.parent
    if candidate_skill_root.exists():
        try:
            replace_skill_with_optimized(skill_registry, candidate_skill_root)
        except FileNotFoundError as e:
            # 前置校验失败(.bak 不存在),可能 init 没备份过——直接抛,让调用方排查
            raise RuntimeError(
                "覆盖原路径失败:.bak 不存在。请确认 init 阶段已调 backup_skill_to_bak。"
            ) from e

    try:
        # 切换 skill_path 到用户源,eval 实际读取用户源
        saved_skill_path = state_engine.skill_path
        saved_args_skill_path = getattr(args, 'skill_path', None)
        state_engine.skill_path = user_source_skill_path
        args.skill_path = user_source_skill_path

        return _evaluate_candidate_inner(state_engine, args, cand_skill_path, cand_id, round_num, l, baseline_score, strategy)
    finally:
        # 恢复 skill_path
        state_engine.skill_path = saved_skill_path
        if saved_args_skill_path is not None:
            args.skill_path = saved_args_skill_path
        # 恢复用户源(.bak 仍在,cleanup=False 表示不删)
        restore_skill_from_bak([str(user_source_skill_path)], {}, cleanup=False)


def _evaluate_candidate_inner(state_engine: StateEngine, args, cand_skill_path: str,
                               cand_id: int, round_num: int, l: int,
                               baseline_score: float,
                               strategy: str) -> tuple:
    """候选评测内部逻辑（与备份/恢复解耦）"""
    cand_skill_dir = Path(cand_skill_path).parent

    # 保存候选 skill 快照
    state_engine.artifact_store.save_candidate_snapshot(cand_id, cand_skill_dir, round_num)

    # 提前创建 analyzer：每次 run_evaluation 后立即调 analyze_run 写 score.json，
    # 否则 for 循环结束时才统一调 analyze_candidate，循环内读 score.json 时文件还不存在 → 拿到 0
    metrics_config = MetricsConfig.load()
    analyzer = ScoreAnalyzerAgent(metrics_config)

    run_scores = []
    run_details = []
    pruned = False

    metrics = getattr(args, 'metrics_collector', None)
    if metrics:
        metrics.start_phase(round_num, "evaluate")

    # 剪枝参数
    prune_threshold = getattr(args, 'prune_threshold', 20.0)
    prune_enabled = not getattr(args, 'no_prune', False)

    for run_i in range(1, l + 1):
        print(f"  评测 [{run_i}/{l}]...", end=" ", flush=True)

        # 清除上次评测产物（含 CC 分数文件），避免干扰
        workspace_path = getattr(args, 'workspace', None)
        _clear_eval_artifacts(round_num, run_i, workspace_path,
                              stage=f"candidate_{cand_id}_round_{round_num}_run_{run_i}")

        # 设置 eval_run 索引和评测模式，确保每次评测使用独立的 CC 分数文件和归档目录
        args.eval_run_index = run_i
        args.eval_mode = "candidate"
        args.candidate_id = cand_id

        # 防御性检查：确保候选 skill 目录存在
        if not cand_skill_dir.exists():
            print(f"\n  ⚠️ 候选 {cand_id} skill 目录丢失，从 workspace 恢复")
            dest = state_engine.artifact_store._candidate_dir(cand_id, round_num) / _SKILL_DIR
            if dest.exists():
                _shutil.rmtree(str(dest))
            _shutil.copytree(str(state_engine.skill_dir), str(dest),
                            ignore=lambda d, f: [x for x in f if x.endswith(".proposed")])
            cand_skill_path = str(dest / "SKILL.md")
            cand_skill_dir = dest
        args.skill_path = Path(cand_skill_path)

        try:
            eval_result = run_evaluation(state_engine, args, round_num)

            # 修复 0 分 bug：run_evaluation 仅归档 data/，不写 score.json。
            # 必须在本次 run 后立即调 analyze_run 把 score.json 写出来，
            # 否则下方的"读 score.json"会拿到 0.0。
            cand_run_dir = state_engine.artifact_store._candidate_dir(cand_id, round_num) / f"run_{run_i}"
            if cand_run_dir.exists():
                try:
                    _case_ids = state_engine.config.get("case_ids") or None
                    analyzer.analyze_run(
                        cand_run_dir, round_num, cand_id, run_i,
                        case_ids=_case_ids,
                    )
                except Exception as _e:
                    print(f"  ⚠️ analyze_run 失败 (cand {cand_id} run {run_i}): {_e}", flush=True)

            # 提取分数：优先读取 ScoreAnalyzerAgent 生成的 score.json（真实分数）
            run_data = {}
            run_score = None
            eval_error = False

            if eval_result and isinstance(eval_result, dict):
                rating = eval_result.get("rating", "")
                if rating == "BROKEN":
                    eval_error = True
                run_data["gaps"] = eval_result.get("gaps", [])
                for gap in run_data.get("gaps", []):
                    if "评测管道异常" in gap.get("message", "") or "评测异常" in gap.get("message", ""):
                        eval_error = True
                        break

            # 从 ScoreAnalyzerAgent 生成的 score.json 回读真实分数
            from state_engine.persistence import load_json as _lj
            cand_run_dir = state_engine.artifact_store._candidate_dir(cand_id, round_num) / f"run_{run_i}"
            score_json_path = cand_run_dir / "score.json"
            if score_json_path.exists():
                try:
                    score_data = _lj(str(score_json_path))
                    rs = score_data.get("result_score")
                    if rs is not None:
                        run_score = float(rs)
                        info = score_data.get("info", {})
                        if info and not run_data.get("metadata"):
                            run_data["metadata"] = info
                except Exception:
                    pass

            # 兜底：如果 score.json 未生成或提取失败
            if run_score is None:
                raw_score = eval_result.get("score") if eval_result else None
                run_score = float(raw_score) if raw_score is not None else 0.0

            # 构建 run_data（从 eval_result 提取完整信息）
            if eval_result and isinstance(eval_result, dict):
                run_data = {
                    "round": round_num,
                    "eval_mode": getattr(args, 'eval_mode', 'candidate'),
                    "candidate_id": cand_id,
                    "run_index": run_i,
                    "score": run_score,
                    "timestamp": datetime.now().isoformat(),
                    "gaps": eval_result.get("gaps", []),
                    "metadata": eval_result.get("metadata", {}),
                    "rating": eval_result.get("rating", ""),
                    "total_gaps": eval_result.get("total_gaps", 0),
                    "improvements": eval_result.get("improvements", []),
                }
                # 从 metadata 提取 per_ran / rule_scores 放入 run_data 根级
                meta = eval_result.get("metadata", {})
                if "per_ran" in meta:
                    run_data["per_ran"] = meta["per_ran"]
                if "rule_scores" in meta:
                    run_data["rule_scores"] = meta["rule_scores"]

            # 检测评测执行错误：BROKEN 评级或异常标记
            rating = run_data.get("rating", "")
            if rating == "BROKEN":
                eval_error = True
            rd_gaps = run_data.get("gaps", [])
            for gap in rd_gaps:
                if "评测管道异常" in gap.get("message", "") or "评测异常" in gap.get("message", ""):
                    eval_error = True
                    break

            if eval_error:
                print("0.0 (评测执行错误，非候选质量问题)")
            else:
                label = ""
                if eval_error:
                    label = " (⚠️ 评测执行错误)"
                print(f"{run_score:.1f}{label}")

            # 记录评测错误标记
            if eval_error:
                run_data["_eval_error"] = True

            run_scores.append(run_score)

            # ── 提前剪枝检查：已禁用（确保所有 run 都执行） ──
            # if prune_enabled and run_i == 0 and baseline_score > 0:
            #     prune_cutoff = baseline_score - prune_threshold
            #     if run_score < prune_cutoff:
            #         print(f"\n  ⚡ 首次评测 {run_score:.1f} 低于基线-阈值 ({baseline_score:.1f}-{prune_threshold:.1f}={prune_cutoff:.1f})，提前剪枝")
            #         pruned = True
            #         run_data["_pruned"] = True
            #         run_data["prune_reason"] = f"first_run {run_score:.1f} < baseline {baseline_score:.1f} - threshold {prune_threshold:.1f}"
            #         # 用首次分数填充剩余 runs 保持一致性
            #         for _ in range(l - 1):
            #             run_scores.append(run_score)
            #             run_details.append(dict(run_data))
            #         break

            # data/ 已由 workflow_pipeline 归档，score.json 由 ScoreAnalyzerAgent 统一生成
            if run_data:
                run_details.append(run_data)
            else:
                run_details.append({})

        except Exception as e:
            print(f"0.0 (异常: {e})")
            run_scores.append(0.0)
            run_details.append({"_eval_error": True, "error": str(e)})

    # 计算平均分和标准差
    if not run_scores:
        return None, [], None, []

    avg_score = sum(run_scores) / len(run_scores)
    if len(run_scores) > 1:
        mean = avg_score
        variance = sum((s - mean) ** 2 for s in run_scores) / len(run_scores)
        stddev = math.sqrt(variance)
    else:
        stddev = 0.0

    # 指标记录（仅记录平均分，phase timing 由 run_evaluation 内完成）
    metrics = getattr(args, 'metrics_collector', None)
    if metrics:
        metrics.record(round_num, "result_score", avg_score)

    # 保存聚合分数到 candidate score_candidate.json
    agg_data = {
        "candidate_id": cand_id,
        "strategy": strategy,
        "avg_score": avg_score,
        "run_scores": run_scores,
        "stddev": stddev,
        "num_runs": len(run_scores),
        "run_details": run_details,
    }
    if pruned:
        agg_data["_pruned"] = True
    # 候选分数落盘由 analyze_candidate 统一负责
    # （写各 run 的 score.json/score_analysis.md + candidate 级 score_candidate_X.json/analysis.md/proposal.md）
    try:
        cand_dir = state_engine.artifact_store._candidate_dir(cand_id, round_num)
        if cand_dir.exists():
            analyzer.analyze_candidate(
                cand_dir, round_num, cand_id, strategy,
                case_ids=state_engine.config.get("case_ids") or None,
            )
    except Exception as _e:
        print(f"  ⚠️ analyze_candidate 失败 (cand {cand_id}): {_e}", flush=True)

    # 如果有评测错误，额外记录
    error_runs = [i for i, s in enumerate(run_scores) if s == 0.0]
    if error_runs:
        agg_data["zero_score_runs"] = error_runs

    prune_label = " (⚡ 已剪枝)" if pruned else ""
    print(f"  候选 {cand_id} 平均分: {avg_score:.1f} (标准差: {stddev:.1f}){prune_label}")

    return avg_score, run_scores, stddev, run_details


def _generate_candidate_detail(state_engine: StateEngine, cand_id: int, round_num: int,
                               avg_score: float, run_scores: list, stddev: float,
                               run_details: list, baseline_score: float = None):
    """
    为候选生成事无巨细的详细报告 detail.md。

    包含：
    - 每次 eval_run 的完整 per-RAN 指标
    - 每次 run 的报告摘要
    - 与基线的逐 RAN 对比
    - 稳定性分析
    """
    import json as _json

    from state_engine.persistence import ReportBuilder

    cand_dir = state_engine.artifact_store._candidate_dir(cand_id, round_num)
    ensure_dir(str(cand_dir))

    rb = ReportBuilder(f"候选 {cand_id} 评测明细 (Round {round_num})")
    rb.meta("平均分", f"{avg_score:.1f}")
    rb.meta("标准差", f"{stddev:.1f}")
    rb.meta("评测次数", len(run_scores))
    rb.meta("各次得分", ", ".join(f"{s:.1f}" for s in run_scores))
    if baseline_score is not None:
        rb.meta("基线分数", f"{baseline_score:.1f}")
        rb.meta("vs 基线", f"{'+' if avg_score >= baseline_score else ''}{avg_score - baseline_score:.1f}")
    rb.blank()

    # 每次评测的 per-RAN 明细
    rb.section("逐次评测明细")
    for run_i, rd in enumerate(run_details):
        rb.bullet(f"--- Run {run_i} ---")
        rb.meta("得分", f"{run_scores[run_i]:.1f}" if run_i < len(run_scores) else "?")
        if rd.get("_eval_error"):
            rb.meta("状态", f"⚠️ 评测错误: {rd.get('error', 'unknown')}")
            rb.blank()
            continue

        per_ran = rd.get("metadata", {}).get("per_ran", [])
        if per_ran:
            rb.table(
                ["RAN ID", "F1", "召回率", "精确率", "缺口数"],
                [
                    [
                        r.get("ran_id", "?"),
                        f"{r['f1']:.1f}" if r.get("f1") is not None else "—",
                        f"{r['recall']:.1f}" if r.get("recall") is not None else "—",
                        f"{r['precision']:.1f}" if r.get("precision") is not None else "—",
                        str(sum(1 for g in rd.get("gaps", []) if g.get("ran_id") == r.get("ran_id"))),
                    ]
                    for r in per_ran
                ]
            )

        # 规则维度得分
        rule_scores = rd.get("metadata", {}).get("rule_scores", {})
        if rule_scores:
            rb.text("**规则得分:**")
            rb.table(
                ["规则路径", "F1", "召回率", "精确率"],
                [
                    [path,
                     f"{v.get('f1', 0):.1f}",
                     f"{v.get('recall', 0):.1f}",
                     f"{v.get('precision', 0):.1f}"]
                    for path, v in rule_scores.items()
                ]
            )

        # 缺口列表
        gaps = rd.get("gaps", [])
        if gaps:
            rb.text("**缺口:**")
            for g in gaps[:10]:
                rb.bullet(f"[{g.get('severity', '?').upper()}] {g.get('type', '')} @ "
                          f"{g.get('ran_id', '?')}: {g.get('message', '')[:100]}")

        # 评测报告摘要（取前 2000 字符）
        if rd.get("report_text"):
            rb.text("**评测报告摘要:**")
            rb.code_block(rd["report_text"][:2000], "")
            if len(rd["report_text"]) > 2000:
                rb.text(f"*(报告过长，已截断，完整内容见 run_{run_i}/report.md)*")

        rb.blank()

    # 与基线的逐 RAN 对比
    if baseline_score is not None:
        baseline_path = state_engine.artifact_store.workspace / "baseline" / "score_baseline.json"
        if baseline_path.exists():
            try:
                bl_data = _json.loads(baseline_path.read_text(encoding="utf-8"))
                bl_per_ran = bl_data.get("metadata", {}).get("per_ran", [])
                if bl_per_ran:
                    rb.section("与基线逐 RAN 对比")
                    rb.table(
                        ["RAN ID", "基线 F1", "候选 F1", "差距", "优势/劣势"],
                        [
                            [
                                bl.get("ran_id", "?"),
                                f"{bl['f1']:.1f}" if bl.get("f1") is not None else "—",
                                # 取最后一次 run 的 per-ran 分数
                                next((r.get("f1") for r in run_details[-1].get("metadata", {}).get("per_ran", [])
                                      if r.get("ran_id") == bl.get("ran_id")), None),
                                "",  # filled below
                                "",
                            ]
                            for bl in bl_per_ran
                        ]
                    )
                    # 补充差距列
                    rb.blank()
            except Exception:
                pass

    # 稳定性分析
    rb.section("稳定性分析")
    if len(run_scores) > 1:
        cv = (stddev / avg_score * 100) if avg_score > 0 else 0
        rb.meta("变异系数", f"{cv:.1f}%")
        rb.meta("评价", "✅ 稳定" if cv < 3 else ("⚠️ 波动" if cv < 5 else "❌ 不稳定"))
        rb.meta("最高分", f"{max(run_scores):.1f}")
        rb.meta("最低分", f"{min(run_scores):.1f}")
        rb.meta("极差", f"{max(run_scores) - min(run_scores):.1f}")
    else:
        rb.text("仅 1 次评测，无法评估稳定性")

    detail_path = str(cand_dir / "detail.md")
    atomic_write(detail_path, rb.render())
    return detail_path


def _generate_single_candidate(state_engine: StateEngine, round_num: int,
                               candidate_id: int) -> dict:
    """
    生成单个候选（串行流程，ApplyAgent 子 Agent 统一处理）。

    1. 为候选创建独立的 skill 副本（拷贝 workspace skill）
    2. 调 ApplyAgent 读取 baseline/proposal.md 并修改副本
    3. 返回候选信息 dict

    Returns:
        候选信息 dict（id/strategy/skill_path）
    """
    import shutil

    from orchestrators.apply_agent_compat import \
        invoke_apply_agent_compat as invoke_apply_agent

    # 为候选创建独立的 skill 副本
    cand_dir = state_engine.artifact_store._candidate_dir(candidate_id, round_num) / _SKILL_DIR
    if cand_dir.exists():
        shutil.rmtree(str(cand_dir))
    shutil.copytree(str(state_engine.skill_dir), str(cand_dir),
                    ignore=lambda d, f: [x for x in f if x.endswith(".proposed")])

    cand_skill_path = str(cand_dir / "SKILL.md")

    # 读 Stage 4 verdict（如存在），REJECTED 时跳过 apply
    # ⚠️ 临时禁用(2026-06-18):Stage 4 整体注释,verdict 强制 None,ApplyAgent 不再 skip。
    # 取消下面注释块即可恢复。
    _self_check_verdict = None
    # try:
    #     import json as _json_v2
    #     _sc_path = (state_engine.artifact_store.workspace / "baseline"
    #                 / "_proposal" / "stage_4_self_check.json")
    #     if _sc_path.exists():
    #         _sc_data = _json_v2.loads(_sc_path.read_text(encoding="utf-8"))
    #         _self_check_verdict = _sc_data.get("verdict")
    # except Exception:
    #     pass

    # 调用 ApplyAgent 子 Agent 修改候选 Skill 副本
    invoke_apply_agent(
        state_engine, cand_skill_path, candidate_id, round_num,
        self_check_verdict=_self_check_verdict,
    )

    _strategy = "apply_agent"
    if _self_check_verdict == "REJECTED":
        _strategy = "skipped_stage_4_rejected"
    print(f"  ✅ 候选 {candidate_id} 已生成 (strategy={_strategy})")

    return {
        "id": candidate_id,
        "strategy": _strategy,
        "skill_path": cand_skill_path,
    }


# _get_previous_candidates_info 与 _log_candidate_failure 已删除：
# 单 Skill 模式与多 Skill 模式统一使用 ApplyAgent 子 Agent，
# 不再需要 previous_best_candidate 串行参考机制与失败候选日志。


def _clear_eval_artifacts(round_num: int, eval_run: Optional[int] = None, workspace_path: Optional[str] = None,
                          stage: str = "unknown"):
    """统一清理入口：评测开始前清理 data/ 沙箱与 CC 分数文件。

    调用方（统一入口，必须从 baseline / candidate 两侧都调用）：
        - _evaluate_baseline_multi_inner（基线 run_i 评测前）
        - _evaluate_candidate（候选 cand_id 第 run_i 次评测前）

    参数:
        round_num: 轮次
        eval_run:  run 索引（None 表示仅清沙箱，不清 CC 分数文件）
        workspace_path: 工作空间路径（含 config.json）
        stage: 阶段标识（如 "baseline_run_1" / "candidate_3_run_2"），用于日志

    清理范围：
        1. workspace/cc_score_{input,output}_{round}_{run}.json
        2. workspace 解析出的 result_dir（业务方配置的 data 沙箱目录）下全部内容
           （统一通过 clean_eval_data_sandbox 实现，无任何保留目录）

    设计原则：
        - 不再持有"保留目录"概念，每次评测都从干净状态开始
        - 业务方评测管线自行重建其测试数据
    """
    import json as _json

    print(f"    [{stage}] 🧹 清理开始 (round={round_num} run={eval_run})", flush=True)

    # 0. 参数检查
    if not workspace_path:
        print(f"    [{stage}] ⚠️ workspace_path 为空，跳过沙箱清理", flush=True)
        return

    ws = Path(workspace_path)
    if not ws.exists():
        print(f"    [{stage}] ⚠️ workspace 目录不存在: {ws}，跳过清理", flush=True)
        return

    # 1. CC 分数文件清理（编排器侧关注，与沙箱 data/ 清理解耦）
    if eval_run is not None:
        cc_files = [
            f"cc_score_input_{round_num}_{eval_run}.json",
            f"cc_score_output_{round_num}_{eval_run}.json",
        ]
        for name in cc_files:
            p = ws / name
            if p.exists():
                try:
                    p.unlink()
                    print(f"    [{stage}] 🧹 CC 分数文件: 已删 {p.name}", flush=True)
                except Exception as e:
                    print(f"    [{stage}] ⚠️ CC 分数文件删除失败 {p.name}: {e}", flush=True)
    else:
        print(f"    [{stage}] ℹ️ eval_run=None，跳过 CC 分数文件清理", flush=True)

    # 2. 从 config.json 读取 result_dir
    config_path = ws / "config.json"
    if not config_path.exists():
        print(f"    [{stage}] ⚠️ config.json 不存在: {config_path}，跳过沙箱清理", flush=True)
        return

    try:
        config = _json.loads(config_path.read_text(encoding="utf-8"))
        result_dirs_raw = (
            config.get("pipeline", {})
            .get("result_extraction", {})
            .get("result_dirs")
        )
    except Exception as e:
        print(f"    [{stage}] ⚠️ config.json 解析失败: {e}，跳过沙箱清理", flush=True)
        return

    if not result_dirs_raw:
        print(f"    [{stage}] ⚠️ pipeline.result_extraction.result_dirs 未配置，跳过沙箱清理", flush=True)
        return

    result_dirs = [Path(p) for p in result_dirs_raw]
    # 主沙箱：取第一个清理目录（业务方 data/）
    sandbox_data = result_dirs[0]

    # 3. 清理前快照（用于日志追溯）
    if sandbox_data.exists():
        try:
            existing = sorted([c.name for c in sandbox_data.iterdir()])
        except Exception as e:
            print(f"    [{stage}] ⚠️ 列目录失败 {sandbox_data}: {e}", flush=True)
            existing = []
    else:
        existing = []
    print(f"    [{stage}] 清理前 data/ ({len(existing)} 项): {existing}", flush=True)

    # 4. 统一清理入口：全清所有 result_dirs 下的内容
    clean_eval_data_sandbox(sandbox_data, stage=stage, extra_clean_dirs=result_dirs[1:])

    # 5. 清理后快照
    try:
        after = sorted([c.name for c in sandbox_data.iterdir()])
    except Exception:
        after = []
    print(f"    [{stage}] 清理后 data/ ({len(after)} 项): {after}", flush=True)


# _apply_candidate_as_baseline 已删除：
# 选优后直接用 _replace_skill_content(state_engine.skill_dir, candidate_skill_dir) 替换基线。


def _save_round_score_json(state_engine, round_num, baseline_score, candidate_scores):
    """
    广度模式下写入 round_N/score.json 汇总文件。
    数据来源：最佳候选的 score_candidate.json（含 rich run_details）。
    这是 _collect_gap_data 的主要数据源，确保审查报告能获取缺口数据。
    """
    import json as _json

    from state_engine.persistence import ensure_dir as _ed
    from state_engine.persistence import save_json as _sj

    # 找最佳候选
    best = max(candidate_scores, key=lambda c: c["score"]) if candidate_scores else None

    if best:
        # 从 candidate score_candidate.json 读取完整数据
        cand_path = state_engine.artifact_store._candidate_dir(best["id"], round_num) / "score_candidate.json"
        if cand_path.exists():
            try:
                data = _json.loads(cand_path.read_text(encoding="utf-8"))
                # 合并关键信息
                round_score_data = {
                    "score": best["score"],
                    "candidate_id": best["id"],
                    "strategy": best.get("strategy", ""),
                    "run_scores": best.get("run_scores", []),
                    "stddev": best.get("stddev", 0),
                    "run_details": data.get("run_details", []),
                    "better_than_baseline": best["score"] > baseline_score,
                }
                # 确保 run_details 有 total_gaps 字段（供 _collect_gap_data 使用）
                # 并收集所有 gaps
                all_gaps = []
                for rd in round_score_data["run_details"]:
                    rd_gaps = rd.get("gaps", [])
                    if rd_gaps and not all_gaps:
                        all_gaps = rd_gaps
                    if "total_gaps" not in rd:
                        rd["total_gaps"] = len(rd_gaps)

                round_score_data["total_gaps"] = len(all_gaps)
                round_score_data["gaps"] = all_gaps

                round_dir = state_engine.artifact_store._ensure_round_dir(round_num)
                _ed(str(round_dir))
                _sj(str(round_dir / "score.json"), round_score_data)
                return
            except Exception:
                pass

    # 无有效候选时，从基线 run_1 读取
    baseline_path = state_engine.artifact_store.workspace / "baseline" / "run_1" / "score.json"
    if baseline_path.exists():
        try:
            bl_data = _json.loads(baseline_path.read_text(encoding="utf-8"))
            round_dir = state_engine.artifact_store._ensure_round_dir(round_num)
            _ed(str(round_dir))
            _sj(str(round_dir / "score.json"), {
                "score": baseline_score,
                "source": "baseline",
                "gaps": bl_data.get("gaps", []),
                "metadata": bl_data.get("metadata", {}),
                "total_gaps": bl_data.get("total_gaps", 0),
            })
        except Exception:
            pass


def _write_baseline_score_analysis(state_engine, round_score, run_scores, avg_score, stddev):
    """[已废弃] baseline 产物统一由 analyze_baseline 写 score_baseline.*。

    保留此函数仅作 import 兼容占位，主体已被上面调用方移除。
    """
    return None



