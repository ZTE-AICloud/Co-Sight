"""
报告生成模块
============

负责生成各类评测报告：
- 审查报告（基于模板或回退）
- 单轮评测报告文本
- 结构化分析 JSON
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# 通用 case_id 模式:业务方 case_id 形如 RAN-12345 / CASE-9 / TC-001 / REQ-42,
# 任何"大写字母-数字"组合都视为 case_id 候选。不硬编码具体前缀。
_CASE_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*-\w+$")

from state_engine import DEFAULT_TARGET_SCORE
from state_engine.engine import StateEngine
from state_engine.persistence import atomic_write, ensure_dir


def _resolve_live_state(state_engine: StateEngine) -> Dict[str, Any]:
    """从 config 解析实时状态（task_state.json 极简版只存状态，不存结果数据）。

    集中读取 history / best_score / best_round / status / candidate_pool,
    避免每个 helper 函数重复读 config。

    Returns:
        dict 含 history, best_score, best_round, status, candidate_pool 五个键。
    """
    config = state_engine.config

    history = config.get("history", [])
    best_score = config.get("best_score", 0) or 0
    best_round = config.get("best_round", -1)
    if best_round is None:
        best_round = -1
    status = config.get("status", "unknown") or "unknown"
    candidate_pool = config.get("candidate_pool", {}) or {}

    return {
        "history": history,
        "best_score": best_score,
        "best_round": best_round,
        "status": status,
        "candidate_pool": candidate_pool,
    }


def _save_final_review_report(state_engine: StateEngine) -> None:
    """
    基于 round_report_template.md 模板生成最终审查报告。
    汇总整个优化循环的结果，包括分数、趋势、候选表现、缺口根因等。
    """
    workspace = state_engine.workspace
    config = state_engine.config

    live = _resolve_live_state(state_engine)
    history = live["history"]
    best_score = live["best_score"]
    best_round_num = live["best_round"]
    status = live["status"]
    candidate_pool = live["candidate_pool"]

    target_score = config.get("target_score", DEFAULT_TARGET_SCORE)
    max_rounds = config.get("max_rounds", 5)

    # ── 读取模板 ──
    _TEMPLATE_DIR = Path(__file__).parent.parent / "state_engine" / "templates"
    template_path = _TEMPLATE_DIR / "round_report_template.md"
    template_text = template_path.read_text(encoding="utf-8") if template_path.exists() else None

    # ── 收集数据 ──
    score_lines = _build_score_table_lines(history, candidate_pool)

    best_vs_baseline = _calc_best_vs_baseline(history, best_score, best_round_num)

    gap_overview_rows, gap_details_sections, terminology_issues, missing_materials = (
        _collect_gap_data(workspace, history)
    )

    selection_rows = _build_selection_rows(history, candidate_pool, best_score)
    improvements_rows = _collect_improvements(workspace, history)

    # ── 渲染模板 ──
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    num_rounds = len(history)

    if template_text:
        report = _render_template(
            template_text, history, best_score, best_round_num, target_score,
            max_rounds, status, num_rounds, generated_at, best_vs_baseline,
            score_lines, gap_overview_rows, gap_details_sections,
            terminology_issues, missing_materials, selection_rows,
            improvements_rows, config,
        )
    else:
        report = _generate_fallback_report(
            history, best_score, best_round_num, target_score, max_rounds,
            status, config, workspace, gap_overview_rows, gap_details_sections,
            selection_rows, improvements_rows, generated_at, best_vs_baseline,
            candidate_pool,
        )

    review_path = workspace / "审查报告.md"
    atomic_write(str(review_path), report)
    print(f"\n✅ 审查报告已生成（基于模板）: {review_path}")


# ---------------------------------------------------------------------------
# 数据收集辅助函数
# ---------------------------------------------------------------------------

def _build_score_table_lines(
    history: List[Dict], candidate_pool: Optional[Dict[str, Any]] = None,
) -> List[str]:
    if candidate_pool is None:
        candidate_pool = {}
    lines = []
    for h in history:
        round_label = h["round"]
        score = h["score"]
        run_scores = h.get("run_scores", [])
        runs_str = ", ".join(f"{s:.1f}" for s in run_scores) if run_scores else "—"
        if round_label == "baseline":
            lines.append(f"| 基线 | {score:.1f} | — | {runs_str} | 基线 |")
        else:
            lines.append(f"| Round {round_label} | {score:.1f} | — | {runs_str} | vs基线 |")
            # 展开该轮的候选详情
            round_cands = candidate_pool.get(str(round_label), [])
            for cs in round_cands:
                c_id = cs.get("id", "?")
                c_strategy = cs.get("strategy", "?")
                c_score = cs.get("score", 0)
                c_stddev = cs.get("stddev", 0)
                c_runs = cs.get("run_scores", [])
                c_runs_str = ", ".join(f"{s:.1f}" for s in c_runs) if c_runs else "—"
                c_stddev_str = f"{c_stddev:.1f}" if isinstance(c_stddev, (int, float)) else "—"
                c_diff = c_score - score
                c_diff_str = f"{'+' if c_diff >= 0 else ''}{c_diff:.1f}"
                if isinstance(c_stddev, (int, float)):
                    if c_stddev < 3 or c_score == 0:
                        c_stability = "稳定"
                    elif c_stddev < score * 0.5:
                        c_stability = "波动"
                    else:
                        c_stability = "不稳定"
                else:
                    c_stability = "—"
                c_decision = "采用" if c_score >= score else "保留"
                lines.append(f"| 候选 c{c_id} ({c_strategy}) | {c_score:.1f} | {c_stddev_str} | {c_runs_str} | vs基线 {c_diff_str} {c_stability} {c_decision} |")
    return lines


def _calc_best_vs_baseline(history: List[Dict], best_score: float, best_round_num: int) -> str:
    if best_round_num < 0 or not history:
        return "未改善"
    baseline_score = next((h["score"] for h in history if h["round"] == "baseline"), None)
    if baseline_score is None:
        return "未改善"
    diff = best_score - baseline_score
    if diff > 0:
        return f"+{diff:.1f} 提升"
    elif diff < 0:
        return f"{diff:.1f} 下降"
    return "持平"


def _collect_gap_data(workspace: Path, history: List[Dict]):
    """从最近一轮的 score.json 中提取缺口数据。"""
    overview_rows = []
    detail_sections = []
    terminology = []
    missing = []

    if not history:
        return overview_rows, detail_sections, terminology, missing

    last_round = history[-1]["round"]
    if isinstance(last_round, str) and last_round == "baseline":
        gap_score_path = workspace / "baseline" / "run_1" / "score.json"
    else:
        gap_score_path = workspace / f"round_{last_round}" / "score.json"

    if not gap_score_path.exists():
        return overview_rows, detail_sections, terminology, missing

    try:
        gap_sd = json.loads(gap_score_path.read_text(encoding="utf-8"))
        for i, g in enumerate(gap_sd.get("gaps", []), 1):
            sev = g.get("severity", "?")
            gap_type = g.get("type", "?")
            section = g.get("affected_section", "?")
            root_cause = g.get("root_cause", "")
            fix_suggestion = g.get("fix_suggestion", "")
            ran_id = g.get("ran_id", "?")
            overview_rows.append(f"| {i} | {ran_id} | {sev} | {gap_type} | {section} |")
            detail_sections.append(
                f"#### {i}. [{sev}] {gap_type} — {section}\n\n"
                f"**RAN**: {ran_id}\n"
                f"**根因**: {root_cause}\n"
                f"**建议**: {fix_suggestion}"
            )
            msg_lower = (root_cause + fix_suggestion).lower()
            if any(k in msg_lower for k in ["术语", "terminology", "命名", "格式不一致", "名称"]):
                terminology.append(f"- {ran_id}: {root_cause}")
            if any(k in msg_lower for k in ["缺失", "missing", "未生成", "为空", "未产出"]):
                missing.append(f"- {ran_id}: {root_cause}")
    except Exception:
        pass

    return overview_rows, detail_sections, terminology, missing


def _build_selection_rows(
    history: List[Dict],
    candidate_pool: Optional[Dict[str, Any]] = None,
    best_score: float = 0,
) -> List[str]:
    if candidate_pool is None:
        candidate_pool = {}
    rows = []
    baseline_score = next((h["score"] for h in history if h["round"] == "baseline"), None)

    for round_key, candidates in candidate_pool.items():
        for c in candidates:
            cid = f"c{c['id']}"
            score = c["score"]
            stddev = c.get("stddev", 0)
            vs_bl = "—"
            if baseline_score is not None:
                diff = score - baseline_score
                vs_bl = f"+{diff:.1f}" if diff > 0 else f"{diff:.1f}"
            stable = "稳定" if stddev < score * 0.5 else "不稳定"
            decision = "采用" if score == best_score else "保留"
            rows.append(f"| {cid} | {score:.1f} | {vs_bl} | {stable} | {decision} |")
    return rows


def _collect_improvements(workspace: Path, history: List[Dict]) -> List[str]:
    rows = []
    if not history:
        return rows

    last_round = history[-1]["round"]
    if isinstance(last_round, str) and last_round == "baseline":
        gap_score_path = workspace / "baseline" / "run_1" / "score.json"
    else:
        gap_score_path = workspace / f"round_{last_round}" / "score.json"

    if not gap_score_path.exists():
        return rows

    try:
        gap_sd = json.loads(gap_score_path.read_text(encoding="utf-8"))
        for g in gap_sd.get("gaps", []):
            sev = g.get("severity", "?")
            gap_type = g.get("type", "?")
            fix = g.get("fix_suggestion", "")
            ran_id = g.get("ran_id", "?")
            priority = "P0" if sev == "critical" else ("P1" if sev == "high" else "P2")
            rows.append(f"| {priority} | {ran_id} | {gap_type} | {fix} |")
    except Exception:
        pass

    return rows


# ---------------------------------------------------------------------------
# 模板渲染
# ---------------------------------------------------------------------------

def _render_template(
    template_text: str, history: List[Dict], best_score: float,
    best_round_num: int, target_score: float, max_rounds: int,
    status: str, num_rounds: int, generated_at: str,
    best_vs_baseline: str, score_lines: List[str],
    gap_overview_rows: List[str], gap_details_sections: List[str],
    terminology_issues: List[str], missing_materials: List[str],
    selection_rows: List[str], improvements_rows: List[str],
    config: Dict,
) -> str:
    report = template_text

    # 简单替换
    report = report.replace("{round_num}", str(best_round_num if best_round_num >= 0 else "N/A"))
    report = report.replace("{generated_at}", generated_at)

    # 分数摘要
    score_table = "| 对象 | 平均分 | 标准差 | 各次得分 | 状态 |\n|------|--------|--------|----------|------|\n"
    score_table += "\n".join(score_lines)
    score_table += f"\n\n**最佳候选/结论**: 最佳得分 {best_score:.1f}/{target_score:.0f}，vs基线 {best_vs_baseline}"
    report = report.replace(
        "## 1. 分数摘要\n\n| 对象 | 平均分 | 标准差 | 各次得分 | 状态 |\n|------|--------|--------|----------|------|\n| 基线 | ... | ... | ... | 基线 |\n| 候选 c0 (P1_intent) | ... | ... | ... | vs基线 |\n\n**最佳候选/结论**: ...",
        f"## 1. 分数摘要\n\n{score_table}"
    )

    # 缺口概览
    gap_table = "无缺口"
    if gap_overview_rows:
        gap_table = "| # | RAN ID | 严重程度 | 类型 | 章节 |\n|:---|:---|:---|:---|:---|\n" + "\n".join(gap_overview_rows)
    report = report.replace("（按 RAN 聚合的缺口数量、严重程度、问题类型表）", gap_table)

    # 详细根因
    if gap_details_sections:
        report = report.replace("（每个缺口的 root_cause + r_only/c_only 差异明细 + fix_suggestion）",
                                "\n".join(gap_details_sections))
    else:
        report = report.replace("（每个缺口的 root_cause + r_only/c_only 差异明细 + fix_suggestion）", "无")

    # 术语差异
    if terminology_issues:
        report = report.replace("（关键词：术语、terminology、命名、格式不一致、名称）",
                                "\n".join(terminology_issues))
    else:
        report = report.replace("（关键词：术语、terminology、命名、格式不一致、名称）", "无相关术语误判")

    # 材料缺失
    if missing_materials:
        report = report.replace("（关键词：缺失、missing、未生成、为空、未产出）",
                                "\n".join(missing_materials))
    else:
        report = report.replace("（关键词：缺失、missing、未生成、为空、未产出）", "无材料缺失问题")

    # 其他根因
    report = report.replace("（不属于上述分类的缺口）", "无")

    # 选择决策
    if selection_rows:
        sel_table = "| 候选 | 分数 | vs 基线 | 稳定性 | 决策 |\n|------|------|---------|--------|------|\n" + "\n".join(selection_rows)
    else:
        sel_table = "无候选"
    report = report.replace("| 候选 | 分数 | vs 基线 | 稳定性 | 决策 |\n|------|------|---------|--------|------|", sel_table)

    adopted = f"采用最佳候选（Round {best_round_num}，得分 {best_score:.1f}）" if best_round_num >= 0 else "保留基线"
    report = report.replace("**选择结果**: 采用候选 cX / 保留基线", f"**选择结果**: {adopted}")

    decision_basis = f"共执行 {num_rounds} 轮，目标分数 {target_score:.0f}，{'已达成' if best_score >= target_score else '未达成'}。"
    report = report.replace("**决策依据**: ...", decision_basis)

    # 改进建议
    if improvements_rows:
        imp_table = "| 优先级 | RAN ID | 问题类型 | 修复建议 |\n|:---|:---|:---|:---|\n" + "\n".join(improvements_rows)
    else:
        imp_table = "无改进建议"
    report = report.replace("| 优先级 | RAN ID | 问题类型 | 修复建议 |\n|------|------|--------|--------|", imp_table)

    return report


def _generate_fallback_report(
    history: List[Dict], best_score: float, best_round_num: int,
    target_score: float, max_rounds: int, status: str,
    config: Dict, workspace: Path, gap_rows: List[str],
    gap_details: List[str], sel_rows: List[str],
    imp_rows: List[str], generated_at: str, best_vs_baseline: str,
    candidate_pool: Optional[Dict[str, Any]] = None,
) -> str:
    """模板缺失时的回退报告生成。"""
    if candidate_pool is None:
        candidate_pool = {}
    lines = [
        "# 迭代优化审查报告",
        "",
        f"生成时间：{generated_at}",
        "",
        "## 总体结果",
        "",
        "| 指标 | 值 |",
        "|:---|:---|",
        f"| 最佳得分 | **{best_score:.1f} / {target_score:.0f}** |",
        f"| 目标达成 | {'✅ 已达成' if best_score >= target_score else '❌ 未达成'} |",
        f"| 完成轮次 | {len(history)} / {max_rounds} |",
        f"| 最佳轮次 | Round {best_round_num} |",
        f"| 最终状态 | {status} |",
        "",
    ]
    if history:
        lines.extend(["## 分数趋势", "", "| 轮次 | 分数 | 评级 | 缺口数 | 时间 |", "|:---|:---|:---|:---|:---|"])
        for h in history:
            lines.append(f"| R{h['round']} | {h['score']:.1f} | {h.get('rating', '—')} | {h.get('total_gaps', '—')} | {h.get('timestamp', '—')} |")
        lines.append("")
    strategy_history = config.get("strategy_history", {})
    if strategy_history:
        lines.extend(["## 策略表现", "", "| 策略 | 最佳分数 | 测试轮次 |", "|:---|:---|:---|"])
        for s, d in strategy_history.items():
            lines.append(f"| {s} | {d.get('best_score', 0):.1f} | {len(d.get('rounds_tested', []))} |")
        lines.append("")
    if candidate_pool:
        lines.append("## 候选详情")
        lines.append("")
        for rk, cs in candidate_pool.items():
            lines.append(f"### Round {rk}")
            lines.extend(["", "| 候选 ID | 策略 | 分数 | 标准差 |", "|:---|:---|:---|:---|"])
            for c in cs:
                lines.append(f"| c{c['id']} | {c['strategy']} | {c['score']:.1f} | {c.get('stddev', 0):.1f} |")
            lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 结构化分析 JSON
# ---------------------------------------------------------------------------

def _save_round_analysis_json(
    state_engine: StateEngine, round_num: int,
    baseline_score: float, baseline_runs: List[float], baseline_std: float,
    candidate_scores: List[Dict[str, Any]],
) -> None:
    """
    保存结构化评测分析文件（JSON）。

    包含每个对象（基线 + 各候选）的多轮评测分数、
    per-RAN 各维度分数、rule 分数明细、缺口信息及分析结论。
    """
    round_dir = state_engine.artifact_store._ensure_round_dir(round_num)

    def _read_eval_run_details(source_dir: Path) -> List[Dict]:
        details = []
        if not source_dir.exists():
            return details
        run_dirs = sorted(
            [d for d in source_dir.iterdir() if d.is_dir() and d.name.startswith("run_")],
            key=lambda d: int(d.name.split("_")[1]),
        )
        for run_dir in run_dirs:
            run_id = int(run_dir.name.split("_")[1])
            run_score_path = run_dir / "score.json"
            if not run_score_path.exists():
                continue
            try:
                data = json.loads(run_score_path.read_text(encoding="utf-8"))
                metadata = data.get("metadata", {})
                per_ran = metadata.get("per_ran", [])
                rule_scores = metadata.get("rule_scores", {})
                gaps = data.get("gaps", [])
                rating = data.get("rating", data.get("quality_rating", ""))
                score = data.get("score", data.get("overall_score", 0))
                details.append({
                    "run_id": run_id,
                    "score": score,
                    "rating": rating,
                    "per_ran": per_ran,
                    "rule_scores": rule_scores,
                    "gaps": [{"type": g.get("type"), "severity": g.get("severity"),
                              "ran_id": g.get("ran_id"), "f1": g.get("f1"),
                              "message": g.get("message", "")} for g in gaps],
                })
            except Exception:
                pass
        return details

    # ── 基线数据 ──
    baseline_detail = {
        "object_type": "baseline",
        "avg_score": baseline_score,
        "stddev": round(baseline_std, 2),
        "run_scores": [round(s, 2) for s in baseline_runs],
        "num_runs": len(baseline_runs),
        "eval_runs": [],
    }

    bs_path = state_engine.artifact_store.workspace / "baseline" / "score_baseline.json"
    if bs_path.exists():
        try:
            bs_data = json.loads(bs_path.read_text(encoding="utf-8"))
            bs_metadata = bs_data.get("metadata", {})
            baseline_detail["pipeline_steps"] = bs_metadata.get("pipeline_steps", {})
            baseline_detail["activities"] = bs_metadata.get("activities", [])
            run_details_list = bs_data.get("run_details", [])
            for idx, rd in enumerate(run_details_list):
                rd_meta = rd.get("metadata", {})
                baseline_detail["eval_runs"].append({
                    "run_id": idx,
                    "score": rd.get("score", rd.get("overall_score", 0)),
                    "rating": rd.get("rating", ""),
                    "per_ran": rd_meta.get("per_ran", []),
                    "rule_scores": rd_meta.get("rule_scores", {}),
                })
        except Exception:
            pass

    if not baseline_detail["eval_runs"]:
        # 优先从 baseline/run_N/score.json 读取完整评测数据（含 per_ran, rule_scores, gaps）
        bl_dir = state_engine.artifact_store.workspace / "baseline"
        baseline_detail["eval_runs"] = _read_eval_run_details(bl_dir)

    if not baseline_detail["eval_runs"]:
        # 兜底：从 round_N/score.json 读取
        score_path = round_dir / "score.json"
        if score_path.exists():
            try:
                sp_data = json.loads(score_path.read_text(encoding="utf-8"))
                sp_meta = sp_data.get("metadata", {})
                baseline_detail["eval_runs"].append({
                    "run_id": 0,
                    "score": sp_data.get("overall_score", 0),
                    "rating": sp_data.get("quality_rating", ""),
                    "per_ran": sp_meta.get("per_ran", []),
                    "rule_scores": sp_meta.get("rule_scores", {}),
                })
            except Exception:
                pass

    # ── 候选数据 ──
    candidates_detail = []
    for cs in candidate_scores:
        cand_id = cs["id"]
        cand_dir = state_engine.artifact_store._candidate_dir(cand_id, round_num)
        eval_runs = _read_eval_run_details(cand_dir)

        strategy = cs.get("strategy", "unknown")
        cand_score_path = cand_dir / "score_candidate.json"
        if cand_score_path.exists():
            try:
                cs_data = json.loads(cand_score_path.read_text(encoding="utf-8"))
                strategy = cs_data.get("strategy", strategy)
            except Exception:
                pass

        candidates_detail.append({
            "object_type": "candidate",
            "candidate_id": cand_id,
            "strategy": strategy,
            "avg_score": round(cs["score"], 2),
            "stddev": round(cs["stddev"], 2),
            "run_scores": [round(s, 2) for s in cs.get("run_scores", [])],
            "num_runs": len(cs.get("run_scores", [])),
            "eval_runs": eval_runs,
        })

    # ── 分析结论 ──
    best_candidate = None
    if candidate_scores:
        best = max(candidate_scores, key=lambda c: c["score"])
        best_candidate = {
            "candidate_id": best["id"],
            "strategy": best["strategy"],
            "avg_score": round(best["score"], 2),
            "better_than_baseline": best["score"] > baseline_score,
            "score_diff": round(best["score"] - baseline_score, 2),
        }

    stability_analysis = []
    for cs in candidate_scores:
        if cs["score"] > 0 and len(cs.get("run_scores", [])) > 1:
            cv = (cs["stddev"] / cs["score"]) * 100
            if cv < 3:
                label = "稳定"
            elif cv < 5:
                label = "波动较大"
            else:
                label = "不稳定"
            stability_analysis.append({
                "candidate_id": cs["id"],
                "stddev": round(cs["stddev"], 2),
                "cv_percent": round(cv, 2),
                "label": label,
            })

    decision = {"selected": None, "reason": ""}
    if best_candidate and best_candidate["better_than_baseline"]:
        decision["selected"] = f"candidate_{best_candidate['candidate_id']}"
        decision["reason"] = (
            f"候选 c{best_candidate['candidate_id']} ({best_candidate['strategy']}) "
            f"平均分 {best_candidate['avg_score']} 优于基线 {round(baseline_score, 2)} "
            f"（+{best_candidate['score_diff']}）"
        )
    elif candidate_scores:
        decision["selected"] = "baseline"
        decision["reason"] = (
            f"所有候选均未超过基线（最佳 {best_candidate['avg_score'] if best_candidate else 0} <= {round(baseline_score, 2)}），保留基线"
        )
    else:
        decision["selected"] = "baseline"
        decision["reason"] = "无有效候选，保留基线"

    # ── 组装 ──
    analysis = {
        "round_num": round_num,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "config": {
            "eval_runs_per_candidate": len(baseline_runs),
        },
        "baseline": baseline_detail,
        "candidates": candidates_detail,
        "analysis": {
            "best_candidate": best_candidate,
            "stability": stability_analysis,
            "decision": decision,
        },
    }

    analysis_path = round_dir / "round_analysis.json"
    ensure_dir(str(round_dir))
    with open(str(analysis_path), "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 单轮评测报告文本
# ---------------------------------------------------------------------------

def _generate_report_text(eval_result, skill_name: str, round_num: int) -> str:
    """生成评测报告文本。"""
    score = eval_result.score
    rating = eval_result.rating
    gaps = eval_result.gaps

    icon_map = {"EXCELLENT": "🟢", "GOOD": "🟡", "FAIR": "🟠", "POOR": "🔴", "BROKEN": "💀"}
    icon = icon_map.get(rating, "⚪")

    lines = [
        "=" * 60,
        f"  轨迹分析报告  |  {skill_name}  |  Round {round_num}",
        f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 60,
        "",
        f"  {icon} 综合评分: {score}/100  [{rating}]",
        f"  信号数量: {len(gaps)}  |  缺口数量: {len(gaps)}",
        "",
        f"  下一步: {'optimize' if gaps else 'skip'}",
    ]

    if gaps:
        lines.append("\n  --- 缺口详情 ---")
        for g in gaps:
            lines.append(f"  ▸ [{g.get('severity', '?')}] {g.get('type', 'unknown')} · 章节「{g.get('affected_section', '?')}」")
            lines.append(f"    根因: {g.get('root_cause', '?')}")
            lines.append(f"    建议: {g.get('fix_suggestion', '?')}")
        lines.append("")

    metadata = eval_result.metadata
    if metadata.get("rule_scores"):
        lines.append("\n  --- 量化评分 (规则匹配) ---")
        for leaf, scores in metadata["rule_scores"].items():
            lines.append(
                f"  ▸ {leaf}: "
                f"R={scores.get('recall', 0):.1f}% "
                f"P={scores.get('precision', 0):.1f}% "
                f"F1={scores.get('f1', 0):.1f}%"
            )

    if metadata.get("dimension_scores"):
        lines.append("\n  --- 维度评分 ---")
        for dim, s in metadata["dimension_scores"].items():
            lines.append(f"  ▸ {dim}: {s:.1f}")

    s_rule = metadata.get("s_rule")
    if s_rule is not None:
        s_llm = metadata.get("s_llm", 0)
        lmbda = metadata.get("rule_weight", 0.75)
        lines.append(f"\n  S_rule: {s_rule:.1f} | S_llm: {s_llm:.1f} | λ={lmbda}")

    if metadata.get("per_ran"):
        lines.append("\n  --- 各 RAN 得分 ---")
        for ran in metadata["per_ran"]:
            ran_id = ran.get("ran_id", "?")
            f1 = ran.get("f1")
            precision = ran.get("precision")
            recall = ran.get("recall")
            s_total = ran.get("s_total")
            if f1 is not None and precision is not None and recall is not None:
                lines.append(f"  ▸ {ran_id}: F1={f1:.1f}  召回率={recall:.1f}  精确率={precision:.1f}")
            elif f1 is not None:
                lines.append(f"  ▸ {ran_id}: F1={f1:.1f}")
            elif s_total is not None:
                lines.append(f"  ▸ {ran_id}: {s_total:.1f}")
            else:
                lines.append(f"  ▸ {ran_id}")

    if eval_result.improvements:
        lines.append("  --- 改进建议 ---")
        for imp in eval_result.improvements:
            lines.append(f"  ▸ {imp}")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent 级别报告生成（从 orchestrator.py 移入）
# ---------------------------------------------------------------------------



def _log_write(path, source: str, agent_dir=None) -> None:
    """
    统一的写文件日志（按用户要求：每次迭代任务写文件都要打印日志）。
    """
    p = Path(path)
    if agent_dir is not None:
        try:
            rel = p.relative_to(agent_dir)
        except ValueError:
            rel = p
    else:
        rel = p
    print(f"  ✓ 写产物: {rel} (来源: {source})", flush=True)


# 从 skill_manager 导入 diff 工具函数
from orchestrators.skill_manager import \
    extract_modified_sections as _extract_modified_sections
from orchestrators.skill_manager import skill_md_diff as _skill_md_diff


def _call_failure_analysis_agent(agent_dir: Path, target_score: float, best_score: float,
                                 bl_score: float, best_round, num_rounds: int) -> Optional[str]:
    """调 failure-analysis-agent 深度分析"进化未达到目标"的多维度原因。

    探查 agent_dir 下全部产物(score_history / score_analyzer_report / optimization_summary.failed /
    result_diff_report / phase3-eval / interface_data 等),从 6 个维度输出 markdown 章节:
    分数现状 / 数据口径(gold 与候选不匹配) / Skill 失分 / 优化循环(门禁降级+ProposalAgent 失败+分数波动) / 失败轮 / 结论杠杆。

    返回 markdown 章节正文(无 ## 标题,框架拼标题);调用失败或无输出返回 None,调用方回退代码版兜底。
    """
    try:
        from tools import Agent as _Agent
        _raw = _Agent(
            mode="auto",
            description="未达标原因深度分析",
            subagent_type="failure-analysis-agent",
            prompt=(
                "你是 failure-analysis-agent。\n"
                f"任务工作目录: `{agent_dir}`\n"
                f"目标分数: {target_score}, 最佳聚合分: {best_score}, 基线: {bl_score}, "
                f"最佳轮: {best_round}, 总轮数: {num_rounds}\n\n"
                "按 agents/failure-analysis-agent.md 契约 6 个维度探查产物,"
                "输出 markdown 章节正文(无 ## 标题,框架拼标题)。"
            ),
        )
        _out = str(_raw or "").strip()
        if len(_out) < 50:
            print("  ⚠️ failure-analysis-agent 输出过短,回退代码版")
            return None
        return _out
    except Exception as _e:
        print(f"  ⚠️ failure-analysis-agent 调用失败: {_e}")
        return None


def _generate_agent_report(agent_dir: Path, config: dict, skill_registry: dict, baselines: dict):
    """
    生成 Agent 级别 Skill 进化报告 + score_history.md。

    输出：
    - agent_dir/skill_进化报告.md（基于预制模板 scripts/templates/agent_evolution_report.md）
    - agent_dir/score_history.md（分数历史趋势图）

    task_state.json 极简版只存状态,所有实时分/状态/历史从 config 读。
    """
    from pathlib import Path as _P
    from string import Template

    from state_engine.persistence import atomic_write

    # 实时分/状态/历史统一从 config 读（task_state.json 极简版只存状态）
    history = config.get("history", [])
    bl_score = config.get("aggregate_baseline") or config.get("baseline_score", 0)
    best_score = config.get("best_score", 0)
    best_round = config.get("best_round", "—")
    if best_round == -1 or best_round is None:
        best_round = "—"

    final_score = history[-1].get("score", 0) if history else bl_score
    target_score = config.get("target_score", DEFAULT_TARGET_SCORE)
    achieved = best_score >= target_score
    evolution_direction = "上升" if best_score > bl_score else ("下降" if best_score < bl_score else "持平")
    summary = (
        f"本任务共执行 {len(history)} 轮迭代，聚合分从基线 {bl_score:.2f} 演化到最佳 {best_score:.2f}（{evolution_direction} {abs(best_score - bl_score):.2f}）。"
        if history else f"本任务未执行候选迭代，基线 {bl_score:.2f} 即为最终结果。"
    )

    # ── history_for_chart：注入 baseline 行 + 候选未跑规范化 ──
    history_for_chart = []
    has_baseline_row = any(h.get("round") == "baseline" for h in history)
    if bl_score and not has_baseline_row:
        history_for_chart.append({
            "round": "baseline",
            "score": bl_score,
            "gaps": 0,
            "skill_scores": {},
            "skills": {},
            "rating": "BASELINE",
            "timestamp": config.get("created_at", ""),
        })
    history_for_chart.extend(history)

    for h in history_for_chart:
        if h.get("round") == "baseline":
            h.setdefault("_display_score", h.get("score", 0))
            h.setdefault("_display_skill_scores", h.get("skill_scores") or {})
            h.setdefault("_display_note", "")
            continue
        is_skipped = bool(h.get("candidates_skipped"))
        if not is_skipped and h.get("candidates_evaluated", 0) == 0 and h.get("score", 0) < bl_score:
            skill_scores = h.get("skill_scores") or {}
            non_zero_cands = [v for v in skill_scores.values() if v and v > 0]
            if not non_zero_cands:
                is_skipped = True
        if is_skipped:
            h["_display_score"] = bl_score
            h["_display_skill_scores"] = {k: None for k in (h.get("skill_scores") or {})}
            h["_display_note"] = f"本轮候选未产出有效分数，已回退到基线 ({bl_score:.2f})"
        else:
            h["_display_score"] = h.get("score", 0)
            h["_display_skill_scores"] = h.get("skill_scores") or {}
            h["_display_note"] = ""

    # ── 构造模板变量 ──
    def _fmt_candidate_scores(skill_scores: dict) -> str:
        parts = []
        for k, v in (skill_scores or {}).items():
            if v is None:
                parts.append(f"{k}: —")
            else:
                parts.append(f"{k}: {v:.1f}")
        return "; ".join(parts) if parts else "—"

    # 分数趋势行（markdown 表格行；一分制 .2f）
    score_trend_rows = "\n".join([
        f"| {h.get('round', '?')} | {h['_display_score']:.2f} | "
        f"{'+' if h['_display_score'] > bl_score else ('-' if h['_display_score'] < bl_score else '=')}"
        f"{abs(h['_display_score'] - bl_score):.2f} | "
        f"{'首轮' if i == 0 and h.get('round') != 'baseline' else '—'} |"
        for i, h in enumerate(history_for_chart)
    ]) or "| baseline | 0.0000 | — | — |"

    # 各轮最佳候选行
    def _best_cand_label(h):
        if h.get("round") == "baseline":
            return "—"
        skill_scores = h.get("skill_scores", {}) or {}
        if not skill_scores:
            return "—"
        valid = {k: v for k, v in skill_scores.items() if v}
        if not valid:
            return "—"
        best_key = max(valid, key=lambda k: valid[k] or 0)
        return best_key
    round_best_rows = "\n".join([
        f"| {h.get('round', '?')} | {_best_cand_label(h)} | "
        f"{h['_display_score']:.2f} | "
        f"{h['_display_score']:.2f} | "
        f"{h.get('candidates_evaluated', 0)}/{h.get('candidates_total', 0)} |"
        for h in history_for_chart
    ]) or "| baseline | — | 0.0000 | 0.0000 | 0/0 |"

    # ── 从 candidate_K_score.json 读取实际 stddev / run_scores，补全候选详情 ──
    def _load_cand_score(round_num, cand_id):
        """读 round_N/candidate_K/candidate_K_score.json，返回 dict（含 avg、stddev、runs）。"""
        p = agent_dir / f"round_{round_num}" / f"candidate_{cand_id}" / f"candidate_{cand_id}_score.json"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _extract_run_scores(cand_score_data: dict) -> list:
        """从候选 JSON 中抽取 run_scores；如未保存则从 runs[].result_score 现算。"""
        if not cand_score_data:
            return []
        rs = cand_score_data.get("run_scores") or []
        if rs:
            return rs
        runs = cand_score_data.get("runs") or []
        return [r.get("result_score") for r in runs if r.get("result_score") is not None]

    def _compute_stddev(values: list) -> float:
        """样本标准差（n-1）。"""
        if not values or len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        return (sum((s - mean) ** 2 for s in values) / (len(values) - 1)) ** 0.5

    # 先扫一轮拿到所有 run_scores，确定最大 run 数和 round 的最佳候选
    candidate_rows_data = []
    max_runs = 0
    for h in history_for_chart:
        if h.get("round") == "baseline":
            continue
        rnd = h.get("round", "?")
        skill_scores = h.get("_display_skill_scores", {}) or {}
        for ck, cv in skill_scores.items():
            try:
                cand_id = int(str(ck).split("_")[1])
            except (IndexError, ValueError):
                cand_id = 0
            cand_score_data = _load_cand_score(rnd, cand_id)
            run_scores = _extract_run_scores(cand_score_data)
            if run_scores:
                max_runs = max(max_runs, len(run_scores))
            candidate_rows_data.append({
                "round": rnd,
                "cand_id": cand_id,
                "cand_key": ck,
                "score": cv,
                "run_scores": run_scores,
            })

    # 生成候选详情整张表（表头 + 分隔行 + 数据行；Run 列数 = max_runs）
    if not candidate_rows_data:
        candidate_table = "_无候选数据_"
    else:
        header_cells = ["候选", "策略", "平均分", "标准差"] + [f"Run {i + 1}" for i in range(max_runs)] + ["选中"]
        sep_cells = [":---", ":---:", ":---:", ":---:"] + [":---:"] * max_runs + [":---:"]
        lines = [
            "| " + " | ".join(header_cells) + " |",
            "| " + " | ".join(sep_cells) + " |",
        ]
        for d in candidate_rows_data:
            cand_score_data = _load_cand_score(d["round"], d["cand_id"])
            avg = d["score"]
            runs = d["run_scores"]
            if avg is None:
                avg_str = "—"
            else:
                avg_str = f"{avg:.2f}"
            if runs:
                _mean = sum(runs) / len(runs)
                _std = _compute_stddev(runs)
                stddev_str = f"{_std:.2f}"
                run_cells = [f"{r:.2f}" for r in runs]
                if len(run_cells) < max_runs:
                    run_cells += ["—"] * (max_runs - len(run_cells))
            else:
                stddev_str = "—"
                run_cells = ["—"] * max_runs
            # 选中判定：与原 candidate_rows 一致（同轮内 cv 最大者）
            skill_scores_h = next(
                (hh.get("_display_skill_scores", {}) for hh in history_for_chart if hh.get("round") == d["round"]),
                {}
            ) or {}
            is_best = (
                avg is not None
                and avg == max((v for v in skill_scores_h.values() if v is not None), default=None)
            )
            cells = [str(d["cand_id"]), d["cand_key"], avg_str, stddev_str] + run_cells + ["✅" if is_best else "—"]
            lines.append("| " + " | ".join(cells) + " |")
        candidate_table = "\n".join(lines)

    # 旧变量保留（兼容其他可能引用）
    candidate_rows = candidate_table

    # ── 候选稳定性（从 stddev 推导，无需 LLM） ──
    candidate_stability_parts = []
    cand_stability_data = []
    for h in history_for_chart:
        if h.get("round") == "baseline":
            continue
        rnd = h.get("round", "?")
        skill_scores = h.get("_display_skill_scores", {}) or {}
        for ck, cv in skill_scores.items():
            try:
                cand_id = int(str(ck).split("_")[1])
            except (IndexError, ValueError):
                continue
            data = _load_cand_score(rnd, cand_id)
            if not data:
                continue
            avg = data.get("avg_result_score", 0)
            # 优先用 JSON 中的 stddev；若没有则从 runs 现算（n-1）
            run_scores = _extract_run_scores(data)
            stddev = data.get("stddev", 0)
            if (not stddev or stddev == 0) and run_scores:
                stddev = _compute_stddev(run_scores)
            cv_pct = (stddev / avg * 100) if avg > 0 else 0
            cand_stability_data.append({
                "round": rnd,
                "cand": ck,
                "avg": avg,
                "stddev": stddev,
                "cv_pct": cv_pct,
            })
            if stddev == 0:
                stability = "完美稳定（σ=0）"
            elif cv_pct < 10:
                stability = f"高稳定（CV={cv_pct:.1f}%）"
            elif cv_pct < 30:
                stability = f"中等稳定（CV={cv_pct:.1f}%）"
            else:
                stability = f"低稳定（CV={cv_pct:.1f}%，需关注）"
            candidate_stability_parts.append(
                f"- **{ck}**（R{rnd}）: 平均分 {avg:.2f}, σ={stddev:.2f} → {stability}"
            )
    if not candidate_stability_parts:
        candidate_stability_analysis = "_无候选数据可分析_"
    else:
        # 排序：稳定性差的（CV 大）放前面
        cand_stability_data.sort(key=lambda x: -x["cv_pct"])
        worst = cand_stability_data[0]
        best_stable = min(cand_stability_data, key=lambda x: x["cv_pct"])
        candidate_stability_analysis = (
            "\n".join(candidate_stability_parts) +
            f"\n\n**结论**: 稳定性最差的候选是 **{worst['cand']}**（CV={worst['cv_pct']:.1f}%），"
            f"提示其修改可能引入随机性；最稳定的是 "
            f"**{best_stable['cand']}**（CV={best_stable['cv_pct']:.1f}%）。"
        )

    # ── Skill 间协同分析（基于实际数据） ──
    # 判定：若最佳聚合分 == 基线 → 无协同收益；若高于基线 → 列出对每个 Skill 的修改并标注是否同步提升
    skill_synergy_parts = []
    modified_skills_per_round = {}  # round -> set of skill names actually modified
    for h in history_for_chart:
        if h.get("round") == "baseline":
            continue
        rnd = h.get("round", "?")
        # 比对每个 candidate 的 skill 与 round_N/before/skill
        round_dir = agent_dir / f"round_{rnd}"
        before_dir = round_dir / f"round_{rnd}_before_skill" / "skill"
        for cand_id in range(1, 10):
            cand_skill_dir = round_dir / f"candidate_{cand_id}" / "skill"
            if not cand_skill_dir.exists():
                continue
            for sn in (skill_registry or {}).keys():
                before_md = before_dir / sn / "SKILL.md"
                after_md = cand_skill_dir / sn / "SKILL.md"
                if before_md.exists() and after_md.exists():
                    try:
                        if before_md.read_text(encoding="utf-8") != after_md.read_text(encoding="utf-8"):
                            modified_skills_per_round.setdefault(rnd, set()).add(sn)
                    except Exception:
                        pass
    if not modified_skills_per_round:
        skill_synergy_analysis = (
            "_本任务所有候选均未对 Skill 做实质修改（candidate_K/skill 与 round_N_before_skill/skill 内容一致）。_\n\n"
            "_建议检查：ApplyAgent 是否被正确调用、proposal 是否触达了 Skill 写入阶段。_"
        )
    else:
        for rnd in sorted(modified_skills_per_round.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
            skills = sorted(modified_skills_per_round[rnd])
            skill_synergy_parts.append(
                f"- **Round {rnd}**: 修改了 {len(skills)} 个 Skill → {', '.join(f'`{s}`' for s in skills)}"
            )
        # 评估对整体聚合分的影响
        if best_score > bl_score:
            verdict = "正向协同（聚合分提升）"
        elif best_score < bl_score:
            verdict = "负向冲突（聚合分下降，修改可能引入了退化）"
        else:
            verdict = "无明显协同（聚合分持平）"
        skill_synergy_analysis = (
            "**被修改的 Skill**（基于 candidate_K/skill 与 round_N_before_skill/skill 的文件 diff）：\n\n"
            + "\n".join(skill_synergy_parts)
            + f"\n\n**协同判定**: {verdict}"
        )

    # ── 关键修改（从文件 diff 提取，按行数 + unified diff 块） ──
    key_mod_parts = []
    for rnd in sorted(modified_skills_per_round.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
        for sn in sorted(modified_skills_per_round[rnd]):
            # 找该 Skill 的 diff（取第一个有修改的候选做样本）
            sample_cand_id = None
            for cid in range(1, 10):
                cand_skill_md = agent_dir / f"round_{rnd}" / f"candidate_{cid}" / "skill" / sn / "SKILL.md"
                before_md = agent_dir / f"round_{rnd}" / f"round_{rnd}_before_skill" / "skill" / sn / "SKILL.md"
                if cand_skill_md.exists() and before_md.exists():
                    try:
                        if cand_skill_md.read_text(encoding="utf-8") != before_md.read_text(encoding="utf-8"):
                            sample_cand_id = cid
                            break
                    except Exception:
                        pass
            if sample_cand_id is None:
                continue
            diff = _skill_md_diff(agent_dir, rnd, sample_cand_id, sn)
            if diff["changed_lines"] > 0:
                diff_block = diff.get("diff_text", "").rstrip()
                key_mod_parts.append(
                    f"#### Round {rnd} / {sn}（来自 candidate_{sample_cand_id}）\n\n"
                    f"- 新增行: {diff['added']}, 删除行: {diff['removed']}, 净增删: {diff['added'] - diff['removed']:+d} 行\n\n"
                    f"```diff\n{diff_block}\n```\n"
                )
    if not key_mod_parts:
        key_modifications = "_本任务所有候选均未对 Skill 做实质修改_"
    else:
        key_modifications = "**关键修改**（每轮每 Skill 的 unified diff，前后行已对齐上下文）：\n\n" + "\n".join(key_mod_parts)

    # ── 修改覆盖的 Skill 和章节 ──
    coverage_parts = []
    for rnd in sorted(modified_skills_per_round.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
        for sn in sorted(modified_skills_per_round[rnd]):
            sections = _extract_modified_sections(agent_dir, rnd, sn)
            if sections:
                coverage_parts.append(
                    f"- **{sn}**（R{rnd}）: 涉及 H2 章节 → {', '.join(f'`{s}`' for s in sections)}"
                )
            else:
                coverage_parts.append(
                    f"- **{sn}**（R{rnd}）: 涉及 H2 章节 → 仅内容微调（无 H2 章节变更）"
                )
    if not coverage_parts:
        modification_coverage = "_本任务所有候选均未对 Skill 做实质修改_"
    else:
        modification_coverage = "\n".join(coverage_parts)

    # ── 未达标原因分析（基于数据，不调 LLM） ──
    if achieved:
        failure_analysis = "**已达标**，无需分析。"
    else:
        # 🆕 调 failure-analysis-agent 深度分析(多维度:分数/数据口径/Skill失分/优化循环/失败轮)。
        # 子 Agent 失败则沿用下方代码版兜底。
        _fa_agent = _call_failure_analysis_agent(
            agent_dir, target_score, best_score, bl_score, best_round, len(history)
        )
        gap_to_target = target_score - best_score
        # 修正方向：best - baseline，正值表示提升，负值表示退化
        progress_vs_baseline = best_score - bl_score
        # 找最佳候选的分数明细(限定到 best_round,避免 R1 c2 误当 R2 c1)
        best_cand_runs = []
        best_round_num = best_round if isinstance(best_round, int) else None
        for h in history_for_chart:
            if h.get("round") == "baseline":
                continue
            rnd = h.get("round", "?")
            if best_round_num is not None and rnd != best_round_num:
                continue
            skill_scores = h.get("skill_scores", {}) or {}
            valid = {k: v for k, v in skill_scores.items() if v is not None}
            if not valid:
                continue
            best_ck = max(valid, key=lambda k: valid[k])
            try:
                best_cid = int(str(best_ck).split("_")[1])
            except (IndexError, ValueError):
                continue
            data = _load_cand_score(rnd, best_cid)
            if data:
                best_cand_runs = _extract_run_scores(data)
                break
        if progress_vs_baseline >= 0:
            progress_label = "略高"
        else:
            progress_label = "退化"
        failure_parts = [
            f"- 目标分数 **{target_score:.1f}** vs 最佳聚合分 **{best_score:.2f}**，差 **{gap_to_target:.1f}** 分",
            f"- 最佳聚合分 **{best_score:.2f}** vs 基线 **{bl_score:.2f}**，差 {progress_vs_baseline:+.2f} 分"
            f"（{progress_label}）",
        ]
        if best_cand_runs:
            spread = max(best_cand_runs) - min(best_cand_runs)
            run_strs = ", ".join(f"{r:.2f}" for r in best_cand_runs)
            failure_parts.append(
                f"- 最佳候选各 run 分数: [{run_strs}], 极差 {spread:.2f}（评测框架存在随机性）"
            )
        failure_parts.extend([
            f"- 共 {len(history)} 轮迭代, {sum(h.get('candidates_evaluated', 0) for h in history_for_chart if h.get('round') != 'baseline')} 个候选被评估",
            "- **可能原因**:",
            "  - 候选修改未真正修复系统性 gap（仅做表面调整）",
            "  - ApplyAgent 生成的修改引入了新的副作用",
            "  - 评测框架本身存在随机性（相同 Skill 多次 run 分数波动较大）",
            "  - 目标分数 100 在该 Skill 集下是上限附近的不可达值",
        ])
        if progress_vs_baseline < 0:
            failure_parts.extend([
                "- **建议**:",
                "  - 检查 baseline 提案的系统性 gap 列表，优先修复出现频次最高的 gap",
                "  - 增加 `--candidates` 和 `--runs` 提升搜索空间 + 统计稳定性",
                "  - 考虑加 `--max-rounds` 进入下一轮继续迭代",
            ])
        else:
            failure_parts.extend([
                "- **建议**:",
                "  - 维持当前优化方向",
                "  - 考虑加 `--max-rounds` 进入下一轮继续迭代",
            ])
        failure_analysis = "\n".join(failure_parts)
        if _fa_agent:
            failure_analysis = _fa_agent

    # ── 下一步建议（基于数据） ──
    if achieved:
        next_steps = (
            "### 8.1 工具使用建议\n"
            "1. **已达标**：无需进一步操作\n"
            "2. 保留 `score_history.md` 和 `skill_进化报告.md` 作为可追溯产物\n"
            "3. 关注 `best_skill/` 中的最佳 Skill 副本，可在生产环境部署"
        )
    else:
        suggestions = ["1. **未达标**：建议从以下方向继续优化："]
        if best_score <= bl_score:
            suggestions.append(
                "   - 检查 baseline 提案的系统性 gap 列表（`baseline/proposal*.md`），"
                "优先修复高 severity + 高频次的 gap"
            )
            suggestions.append(
                "   - 审视 ApplyAgent 生成的修改（`round_*/candidate_*/skill/`）是否破坏了原 Skill 的核心逻辑"
            )
        else:
            suggestions.append(
                "   - 当前轮次已观察到提升，可加 `--max-rounds` 进入下一轮继续叠加优化"
            )
        suggestions.extend([
            "2. **搜索空间**:",
            "   - 加大 `--candidates`（候选数）扩大搜索广度",
            "   - 加大 `--runs` 提升单候选分数的统计稳定性",
            "3. **可追溯产物**:",
            "   - `best_skill/`：整体最佳 Skill 副本（baseline + 候选中最高分）",
            "   - `skill_进化报告.md`：本报告",
            "   - `score_history.md`：分数趋势",
            "   - `round_*/proposal*.md`：每轮 / 每候选的优化提案",
        ])
        next_steps = "### 8.1 工具使用建议\n" + "\n".join(suggestions)

    # ── 8.2 业务方设计诊断（子 Agent 模式：让 LLM 自主读产物做 12 类诊断） ──
    try:
        from orchestrators.context_extractor import \
            _parse_apply_agent_summary as _parse_json
        from tools import Agent as _Agent
        _diag_input = {
            "agent_dir": str(agent_dir),
            "history_len": len([h for h in history if str(h.get("round")) != "baseline"]),
            "skill_names": list(skill_registry.keys()) if skill_registry else [],
        }
        _diag_raw = _Agent(
            mode="auto",
            description="业务方 Agent/Skill 设计诊断",
            subagent_type="evolution-report-agent",
            prompt=(
                "你是 evolution-report-agent。\n"
                f"任务工作目录: `{agent_dir}`\n"
                f"已完成轮次: {_diag_input['history_len']}\n"
                f"涉及 Skill: {', '.join(_diag_input['skill_names'])}\n\n"
                "按 agents/evolution-report-agent.md 契约 12 个方向探查,输出 JSON 到 stdout"
            ),
        )
        _diag_json = _parse_json(_diag_raw)
        if _diag_json and _diag_json.get("diagnoses"):
            diag_md_lines = ["### 8.2 业务方设计诊断\n"]
            for d in _diag_json["diagnoses"][:5]:
                diag_md_lines.append(f"- **{d.get('category', '?')} {d.get('title', '')}**")
                if d.get("evidence"):
                    diag_md_lines.append(f"  - 证据: {d['evidence']}")
                if d.get("action"):
                    diag_md_lines.append(f"  - 建议: {d['action']}")
            next_steps = next_steps + "\n" + "\n".join(diag_md_lines)
    except Exception as _e:
        print(f"  ⚠️ evolution-report-agent 调用失败: {_e}")

    # ── 产物索引（生成完整表，表头 + 数据行；候选列数 = 该轮候选数） ──
    artifact_index_parts = []
    # 先扫一遍所有轮次，统计最大候选数（用于确定表头列数）
    max_cand_count = 0
    rounds_with_data = []
    for h in history_for_chart:
        if h.get("round") == "baseline":
            continue
        rnd = h.get("round", "?")
        skill_scores = h.get("skill_scores", {}) or {}
        cand_ids = []
        for ck in skill_scores.keys():
            try:
                cid = int(str(ck).split("_")[1])
                cand_ids.append(cid)
            except (IndexError, ValueError):
                pass
        cand_ids = sorted(set(cand_ids))
        if not cand_ids:
            continue
        rounds_with_data.append((rnd, cand_ids))
        max_cand_count = max(max_cand_count, len(cand_ids))
    # 表头只写一次（用最大候选数列数）
    header_cells = ["轮次", "评分分析", "评分数据"] + [f"候选 {i+1}" for i in range(max_cand_count)]
    sep_cells = [":---", ":---", ":---"] + [":---:"] * max_cand_count
    artifact_index_parts.append("| " + " | ".join(header_cells) + " |")
    artifact_index_parts.append("| " + " | ".join(sep_cells) + " |")
    # 每轮数据行
    for rnd, cand_ids in rounds_with_data:
        row_cells = [
            f"R{rnd}",
            f"round_{rnd}/round_{rnd}_score_analysis.md",
            f"round_{rnd}/round_{rnd}_score.json",
        ] + [f"round_{rnd}/candidate_{cid}/" for cid in cand_ids]
        artifact_index_table_row = "| " + " | ".join(row_cells) + " |"
        artifact_index_parts.append(artifact_index_table_row)
    artifact_index_table = "\n".join(artifact_index_parts) if len(rounds_with_data) > 0 else "_无候选产物_"
    # 兼容旧变量名
    artifact_index_rows = artifact_index_table

    template_vars = {
        "agent_name": config.get("agent_name", "unknown"),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "workspace": str(agent_dir),
        "skill_list": ", ".join(skill_registry.keys()),
        "baseline_score": f"{bl_score:.2f}" if isinstance(bl_score, (int, float)) else "—",
        "best_score": f"{best_score:.2f}" if isinstance(best_score, (int, float)) else "—",
        "best_round": best_round,
        "final_score": f"{final_score:.2f}" if isinstance(final_score, (int, float)) else "—",
        "target_score": f"{target_score:.1f}",
        "achieved_status": "✅ 已达标" if achieved else "❌ 未达标",
        "evolution_direction": evolution_direction,
        "summary": summary,
        "score_trend_rows": score_trend_rows,
        "round_best_rows": round_best_rows,
        "skill_synergy_analysis": skill_synergy_analysis,
        "candidate_table": candidate_table,
        "candidate_rows": candidate_rows,
        "candidate_stability_analysis": candidate_stability_analysis,
        "key_modifications": key_modifications,
        "modification_coverage": modification_coverage,
        "failure_analysis": failure_analysis,
        "artifact_index_table": artifact_index_table,
        "artifact_index_rows": artifact_index_rows,
        "next_steps": next_steps,
    }

    # ── 读模板 + 替换占位符 + 写产物 ──
    # 关键修复:模板位于 scripts/templates/ 而非 scripts/orchestrators/templates/,
    # 旧路径找不到模板,fallback 到简单字符串报告。修正路径。
    template_path = _P(__file__).resolve().parent.parent / "templates" / "agent_evolution_report.md"
    report_path = agent_dir / "skill_进化报告.md"
    try:
        if template_path.exists():
            template_text = template_path.read_text(encoding="utf-8")
            # string.Template 用 $var 而非 {{var}}，先转换
            template_text = template_text.replace("{{", "${").replace("}}", "}")
            tpl = Template(template_text)
            rendered = tpl.safe_substitute(template_vars)
        else:
            # 模板缺失，fallback 到简单字符串
            rendered = f"# {template_vars['agent_name']} Skill 进化报告\n\n模板缺失：{template_path}\n"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(str(report_path), rendered)
        _log_write(report_path, "agent_evolution_report_render", agent_dir)
    except Exception as e:
        print(f"  ⚠️ 写 skill_进化报告.md 失败: {e}")

    # ── 增强版 score_history.md：汇总任务所有分数 ──
    try:
        _build_score_history_md(agent_dir, config, history_for_chart, skill_registry)
        _log_write(agent_dir / "score_history.md", "score_history_render", agent_dir)
    except Exception as e:
        print(f"  ⚠️ score_history.md 生成失败（非致命）: {e}")

    # ── 写入 best_skill/：任务整体最佳 Skill 副本（基线 + 候选中分数最高的） ──
    try:
        skill_names = config.get("skill_names") or list((config.get("skill_registry") or {}).keys())
        _save_best_skill(agent_dir, config, skill_names)
    except Exception as e:
        print(f"  ⚠️ best_skill 生成失败（非致命）: {e}")


def _save_best_skill(agent_dir: Path, config: dict, skill_names: list):
    """
    在任务根目录生成 best_skill/，存放整体最佳 Skill 副本。

    整体最佳 = baseline 分数 vs 所有候选平均分中的最大值。
    - 若 baseline 最高：源 = agent_dir/skill/{name}/
    - 若某候选最高：源 = agent_dir/round_{N}/candidate_{K}/skill/{name}/

    产物：
    - agent_dir/best_skill/{name}/SKILL.md 等
    - agent_dir/best_skill/best_skill_info.json（记录来源 + 分数）

    实时分/状态/历史从 task_state.json 读(权威源);config 仅用于配置项。
    """
    import datetime

    # 实时分/状态/历史统一从 config 读（task_state.json 极简版只存状态）
    bl_score = config.get("aggregate_baseline") or config.get("baseline_score", 0) or 0
    best_score = config.get("best_score", 0) or 0
    history = config.get("history", []) or []

    # ── 1. 判定最佳来源 ──
    source_round = None
    source_candidate = None
    if best_score > bl_score:
        for h in history:
            skill_scores = h.get("skill_scores") or {}
            if not skill_scores:
                continue
            best_cand_in_round = max(
                skill_scores.items(),
                key=lambda kv: (kv[1] if kv[1] is not None else 0),
            )
            cand_label, cand_score = best_cand_in_round
            if cand_score is None:
                continue
            if abs(cand_score - best_score) < 1e-6:
                try:
                    source_candidate = int(str(cand_label).split("_")[1])
                    source_round = h.get("round")
                except (IndexError, ValueError):
                    pass
                break

    # ── 2. 准备 best_skill 目录（先清空再重建） ──
    best_skill_dir = agent_dir / "best_skill"
    if best_skill_dir.exists():
        shutil.rmtree(best_skill_dir)
    best_skill_dir.mkdir(parents=True, exist_ok=True)

    # ── 3. 逐 Skill 拷贝 ──
    copied = []
    for name in (skill_names or []):
        if source_round is not None and source_candidate is not None:
            src = agent_dir / f"round_{source_round}" / f"candidate_{source_candidate}" / "skill" / name
        else:
            src = agent_dir / "skill" / name
        dst = best_skill_dir / name
        if not src.exists():
            print(f"  ⚠️ best_skill 源不存在: {src.relative_to(agent_dir) if src.is_absolute() else src}")
            continue
        shutil.copytree(src, dst)
        copied.append(name)
        _log_write(dst, "best_skill_copy", agent_dir)

    # ── 4. 写 best_skill_info.json（来源 + 分数 + 时间） ──
    if source_round is not None and source_candidate is not None:
        source_label = f"round_{source_round}/candidate_{source_candidate}"
    else:
        source_label = "baseline"

    info = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "best_score": best_score,
        "baseline_score": bl_score,
        "source": source_label,
        "source_round": source_round,
        "source_candidate": source_candidate,
        "skill_names": list(skill_names or []),
        "copied_skills": copied,
    }
    info_path = best_skill_dir / "best_skill_info.json"
    try:
        from state_engine.persistence import save_json
        save_json(str(info_path), info)
        _log_write(info_path, "best_skill_info", agent_dir)
    except Exception as e:
        print(f"  ⚠️ best_skill_info.json 写入失败: {e}")


def _copy_newest_skill_for_test(state_engine) -> None:
    """
    任务结束时把"最新 LLM 修改的 Skill"复制回 skill_registry 登记的原始路径(consume_lib 下)。

    🆕 2026-08-03 行为变更(用户要求):
    - **不再 cp best_skill/**(历史最高分,已知 67.63 测过无数遍)
    - **改 cp round_{current_round}/candidate_{best_candidate_id}/skill/**(最新 LLM 修改的版本,未测过)
    - **目的**:让业务方在 cosight-agent-sdd 仓库跑 /sdd-eval 时能测到"LLM 这次到底改了什么",而不是只能看 best_skill
    - **无条件 cp**(无开关):业务方"必须"能测到最新 SKILL,否则优化无意义
    - **保护用户源 SKILL.md**:任务开始时 _init_skill_bak 已自动备份到 {SkillName}.bak/ 目录

    与旧版 _restore_best_skill_to_original 的区别:
    - 旧版:cp best_skill/(R1 干净版 = 1.2.0)→ 业务方再跑一次已知 67.63,无新信息
    - 新版:cp 当前 round candidate skill(R12 1.2.0 删 R11 软提示 / R11 1.6.0 加软提示)= **未测版本**→ 业务方跑测试

    跳过条件(按顺序,任意命中即不复制):
    1. state_engine.config["skill_registry"] 为空(单 Skill 模式无 registry)
    2. 任务跑的最新 round candidate skill 目录不存在
    3. skill_registry 里的 SKILL 路径不存在

    写回语义:rmtree(dst) + copytree(src, dst) 完全替换。
    任何异常都打印 warning 而不抛出,避免阻塞后续总览报告/审查报告生成。
    

    跳过条件(按顺序,任意命中即不复制):
    1. args.no_restore_best 为 True(用户显式禁用)
    2. state_engine.config["skill_registry"] 为空(单 Skill 模式无 registry)
    3. workspace/best_skill/best_skill_info.json 不存在(优化未产出 best)
    4. best_skill/{name}/ 子目录不存在(对应 skill_name 副本缺失)

    写回语义(2026-06-19 修复):采用 rmtree(dst) + copytree(src, dst) 完全替换,
    保证目标目录状态严格等于源。复用 orchestrators.skill_manager.restore_skill_dir 原语。
    旧的 dirs_exist_ok=True 合并写法会保留目标目录里源没有的多余文件(如 .proposed、
    旧版本残留),违反"应用最佳 skill 到原位置"的语义。任何异常都打印 warning 而不抛出,
    避免阻塞后续总览报告/审查报告生成。
    """
    # 1. skill_registry 为空(单 Skill 模式无 registry)
    skill_registry = state_engine.config.get("skill_registry", {}) or {}
    if not skill_registry:
        print("  ℹ️ skill_registry 为空,跳过 copy_newest(单 Skill 模式?)")
        return

    # 2. 任务跑的最新 round candidate skill 目录不存在
    # 🆕 2026-08-03 改:不再读 best_skill_info.json,改用 current_round + best_candidate_id
    _cur_round = getattr(state_engine, "current_round", 0) or 0
    _cur_cand = getattr(state_engine, "best_candidate_id", -1) or -1
    if _cur_round <= 0 or _cur_cand <= 0:
        print(f"  ℹ️ 任务无有效 round/candidate(_cur_round={_cur_round}, _cur_cand={_cur_cand}),跳过 copy_newest")
        return

    # 3. 逐 Skill 复制(完全替换语义:rmtree(dst) + copytree(src, dst))
    restored = []
    from orchestrators.skill_manager import restore_skill_dir

    # 🆕 2026-08-03:写 _debug/copy_back_*.log 日志(用户要求"在源码加日志,可以在 _debug 定位到")
    # 日志位置:taskid_root/_debug/copy_back_YYYYMMDD_HHMMSS.log
    # 内容:cp 时间、源/目标路径、文件列表、byte diff、success flag
    _log_path = None
    try:
        from datetime import datetime as _dt_log
        _ts = _dt_log.now().strftime("%Y%m%d_%H%M%S")
        # taskid_root = workspace.parent(因为 workspace = taskid_root/round_N/)
        _taskid_root = state_engine.workspace.parent
        _debug_dir = _taskid_root / "_debug"
        _debug_dir.mkdir(parents=True, exist_ok=True)
        _log_path = _debug_dir / f"copy_back_{_ts}.log"
        _log_lines = [
            f"# Copy-Newest-Skill Log — round_{_cur_round}/candidate_{_cur_cand}",
            "",
            f"- **时间**: {_ts}",
            "- **触发**: 任务结束无条件 cp 最新 LLM 修改的 skill(让业务方跑 /sdd-eval 能测到)",
            f"- **源目录**: {state_engine.workspace / f'candidate_{_cur_cand}' / 'skill'}",
            "- **目标(skill_registry)** = 用户传 --skill-paths 时的原始路径(consume_lib 下)",
            f"- **当前 best_score**: {state_engine.best_score:.2f} (R{state_engine.best_round})",
            f"- **当前 round**: {_cur_round} (candidate {_cur_cand} = LLM 最新修改的版本)",
            "",
            "## 复制详情",
        ]
    except Exception as _e:
        print(f"  ⚠️ 写 copy_back log 头失败: {_e}")

    for name, skill_md_path in skill_registry.items():
        # 🆕 2026-08-03 改:从 best_skill 改 candidate_K/skill(最新 LLM 修改)
        # 注意:state_engine.workspace 本身已经是 taskid_root/round_N/,所以下一级直接是 candidate_K/skill/
        src_dir = state_engine.workspace / f"candidate_{_cur_cand}" / "skill" / name
        if not src_dir.exists():
            print(f"  ⚠️ candidate_{_cur_cand}/skill/{name} 不存在,跳过该 Skill 写回")
            if _log_path:
                _log_lines.append(f"- ❌ {name}: candidate_{_cur_cand}/skill/{name} 不存在,跳过")
            continue
        dst_dir = Path(skill_md_path).parent
        try:
            # 🆕 复制前:记录文件清单 + byte 大小
            if _log_path:
                _src_files = sorted([f.relative_to(src_dir) for f in src_dir.rglob("*") if f.is_file()])
                _src_total_size = sum((src_dir / f).stat().st_size for f in _src_files if (src_dir / f).is_file())
                _dst_files_before = sorted([f.relative_to(dst_dir) for f in dst_dir.rglob("*") if f.is_file()]) if dst_dir.exists() else []
                _log_lines.append("")
                _log_lines.append(f"### {name}")
                _log_lines.append(f"- 源: `{src_dir}` ({len(_src_files)} 文件, {_src_total_size} bytes)")
                _log_lines.append(f"- 目标: `{dst_dir}` (写回前 {len(_dst_files_before)} 文件)")

            # restore_skill_dir(backup=src, dest=dst) → rmtree(dst) + copytree(backup, dst)
            restore_skill_dir(src_dir, src_dir, dst_dir)
            restored.append(name)
            print(f"  ✅ 最新 LLM 修改的 skill 已写回原位置: {name} → {dst_dir} (来源: round_{_cur_round}/candidate_{_cur_cand})")

            # 🆕 复制后:验证 + 记录 diff
            if _log_path:
                _dst_files_after = sorted([f.relative_to(dst_dir) for f in dst_dir.rglob("*") if f.is_file()])
                _dst_total_size = sum((dst_dir / f).stat().st_size for f in _dst_files_after if (dst_dir / f).is_file())
                _log_lines.append(f"- 复制后: {len(_dst_files_after)} 文件, {_dst_total_size} bytes")
                _log_lines.append(f"- 新增文件: {[str(f) for f in _dst_files_after if f not in _dst_files_before]}")
                _log_lines.append(f"- 删除文件: {[str(f) for f in _dst_files_before if f not in _dst_files_after]}")
                _log_lines.append(f"- ✅ 成功:round_{_cur_round}/candidate_{_cur_cand}/skill/{name} → {dst_dir}")
        except Exception as e:
            print(f"  ⚠️ copy_newest 写回原位置失败: {name} → {dst_dir}: {e}")
            if _log_path:
                _log_lines.append(f"- ❌ 失败: {e}")

    if not restored:
        print("  ⚠️ 没有任何 Skill 成功 copy_newest(最新 LLM 修改版未触发)")
        if _log_path:
            _log_lines.append("")
            _log_lines.append("## 结果: ⚠️ 没有任何 Skill 成功 copy_newest")
    else:
        if _log_path:
            _log_lines.append("")
            _log_lines.append(f"## 结果: ✅ 成功 copy_newest {len(restored)} 个 Skill: {', '.join(restored)}")
        print(f"  📝 Copy-newest 日志: {_log_path}")

    # 🆕 落 _debug 日志
    if _log_path:
        try:
            _log_path.write_text("\n".join(_log_lines), encoding="utf-8")
        except Exception as _e:
            print(f"  ⚠️ 写 copy_newest log 失败: {_e}")


def write_back_best_skill_to_source(args, agent_dir: Path) -> dict:
    """任务结束后把 best_skill/ 写回用户源路径（覆盖式,所有文件）。

    .13+ 硬约束：此函数 **永远 disabled**。不论 args 是否有 write_back_to_source 属性、
    不论外部代码怎么调用，**绝不执行**任何覆盖用户源路径的操作。

    触发条件（已废弃）:--write-back-to-source 显式开启（默认 OFF,保护业务方源路径）。
    与 _restore_best_skill_to_original 的区别:
      - 后者写回 skill_registry 登记的 workspace 副本路径
      - 本函数写回 --skill-path(s) 传入的用户原始路径

    .13+ 删除原因:
      - 用户的源 SKILL.md 是受信任资产,优化器不应有覆盖权限
      - LLM judge 评分有噪声（46.4% 准确率），自动写回 = 把不可信结果回灌到可信源
      - 一旦覆盖,原始版本只能从 _user_source_backup/ 恢复（备份也可能失败/过期）

    Returns:
        永远返回 {"triggered": False, "reason": "HARD-DISABLED by .13+"}
        保留函数签名是为了不破坏旧调用方,实际不再执行任何写回逻辑。
    """
    # .13+ 硬禁用：永远 early-return,不执行任何 shutil.copytree / replace 等操作
    return {
        "triggered": False,
        "reason": "HARD-DISABLED by .13+ (详见 skills/skill-optimize/SKILL.md 硬约束段)",
    }

    skill_paths_str = getattr(args, "skill_paths", "") or getattr(args, "skill_path", "") or ""
    if not skill_paths_str:
        return {"triggered": True, "skipped": [], "failed": ["--skill-path(s) 为空,无法定位用户源路径"]}

    # 解析 skill_path 列表:支持逗号分隔
    if isinstance(skill_paths_str, (list, tuple)):
        skill_path_list = list(skill_paths_str)
    elif "," in skill_paths_str:
        skill_path_list = [p.strip() for p in skill_paths_str.split(",") if p.strip()]
    else:
        skill_path_list = [skill_paths_str]

    best_skill_root = agent_dir / "best_skill"
    if not best_skill_root.exists():
        return {"triggered": True, "skipped": [], "failed": ["best_skill/ 不存在,跳过写回"]}

    best_info_p = best_skill_root / "best_skill_info.json"
    if not best_info_p.exists():
        return {"triggered": True, "skipped": [], "failed": ["best_skill/best_skill_info.json 不存在"]}

    try:
        info = json.loads(best_info_p.read_text(encoding="utf-8"))
        best_source = info.get("source", "?")
    except Exception as e:
        return {"triggered": True, "skipped": [], "failed": [f"best_skill_info.json 解析失败: {e}"]}

    # 备份根目录
    backup_root = agent_dir / "_user_source_backup"
    backup_root.mkdir(parents=True, exist_ok=True)

    restored = []
    skipped = []
    failed = []
    backup_records = []

    for sp in skill_path_list:
        sp_p = Path(sp).resolve()
        if not sp_p.exists():
            failed.append(f"{sp}: 用户源路径不存在")
            continue
        name = sp_p.parent.name
        src_dir = sp_p.parent  # 用户源 skill 目录
        backup_dir = backup_root / name
        best_dir = best_skill_root / name

        # 备份用户源(完整目录,覆盖式更新)
        try:
            if backup_dir.exists():
                shutil.rmtree(str(backup_dir))
            shutil.copytree(str(src_dir), str(backup_dir))
            backup_records.append({"name": name, "backup": str(backup_dir), "src": str(src_dir)})
            print(f"  📦 已备份用户源 skill: {name} -> {backup_dir}")
        except Exception as e:
            failed.append(f"{name}: 备份失败: {e}")
            continue

        # best_skill/{name}/ 不存在 → 跳过该 Skill
        if not best_dir.exists():
            skipped.append(name)
            print(f"  ⚠️ best_skill/{name} 不存在,跳过该 Skill 写回")
            continue

        # 完全替换语义:rmtree(src_dir) + copytree(best_dir, src_dir)
        # 修复 Bug #6:旧 dirs_exist_ok=True 合并写法不删除源目录里没有的多余文件
        # (如 .proposed、上一轮残留),违反"应用最佳 skill 到原位置"的语义。
        # 复用 skill_manager.restore_skill_dir 原语保持一致。
        try:
            from orchestrators.skill_manager import restore_skill_dir
            restore_skill_dir(best_dir, best_dir, src_dir)
            restored.append({"name": name, "dst": str(src_dir), "source": best_source})
            print(f"  ✅ best_skill 已写回用户源: {name} -> {src_dir} (来源: {best_source})")
        except Exception as e:
            failed.append(f"{name}: 写回失败: {e}")

    status = {
        "triggered": True,
        "restored": restored,
        "skipped": skipped,
        "failed": failed,
        "backup_records": backup_records,
        "best_source": best_source,
    }
    (agent_dir / "writeback_status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  📝 写回状态已记录: {agent_dir / 'writeback_status.json'}")
    return status


def _recover_score_history_from_disk(agent_dir: Path, config: dict) -> List[Dict[str, Any]]:
    """从文件系统扫描 baseline/ 和 round_*/ 恢复 history_for_chart。

    适用场景：phase_tracker 不可用 / task_state.json 缺 summary 字段时，
    从磁盘 round_N_score.json / candidate_N_score.json / run_N/score.json 重建。

    返回：list[dict]，每个 dict 含 round / score / skill_scores / candidates_evaluated
    / timestamp / _disk_recovered=True，并附加 _cand_run_scores / _cand_case_scores
    供 _build_score_history_md 渲染使用。
    """
    out: List[Dict[str, Any]] = []
    skill_names = config.get("skill_names") or list((config.get("skill_registry") or {}).keys())

    # ── baseline ──
    baseline_p = agent_dir / "baseline" / "score_baseline.json"
    if baseline_p.exists():
        try:
            bl = json.loads(baseline_p.read_text(encoding="utf-8"))
            bl_data = bl.get("baseline_score", {}) or {}
            bl_runs = bl_data.get("runs", []) or []
            # 收集 baseline 每个 case 的分数（来自 baseline/run_1/score.json）
            bl_case_scores: Dict[str, List[float]] = {}
            br1_p = agent_dir / "baseline" / "run_1" / "score.json"
            if br1_p.exists():
                try:
                    r1d = json.loads(br1_p.read_text(encoding="utf-8"))
                    info = r1d.get("info", {}) or {}
                    per_case = info.get("result_score_per_case") or {}
                    for case_id, val in per_case.items():
                        if isinstance(val, list):
                            bl_case_scores[case_id] = [float(x) for x in val if isinstance(x, (int, float))]
                        elif isinstance(val, (int, float)):
                            bl_case_scores[case_id] = [float(val)]
                except Exception:
                    pass
            # baseline 主分：normalized.result_score > avg_result_score > config.baseline_score
            bl_score = (bl_data.get("normalized", {}) or {}).get("result_score") \
                or bl_data.get("avg_result_score") \
                or config.get("aggregate_baseline") \
                or config.get("baseline_score", 0) \
                or 0
            out.append({
                "round": "baseline",
                "score": float(bl_score) if bl_score else 0.0,
                "gaps": 0,
                "skill_scores": {},
                "skills": {},
                "rating": "BASELINE",
                "timestamp": bl.get("timestamp", ""),
                "_disk_recovered": True,
                "_baseline_runs": bl_runs,
                "_baseline_case_scores": bl_case_scores,
            })
        except Exception as e:
            print(f"  ⚠️ 自愈:baseline score 读取失败: {e}")

    # ── rounds ──
    def _round_sort_key(p: Path):
        parts = p.name.split("_")
        if len(parts) >= 2 and parts[1].isdigit():
            return int(parts[1])
        return 0

    for round_dir in sorted(agent_dir.glob("round_*"), key=_round_sort_key):
        try:
            rnd = int(round_dir.name.split("_")[1])
        except (IndexError, ValueError):
            continue
        round_score_p = round_dir / f"round_{rnd}_score.json"
        if not round_score_p.exists():
            continue
        try:
            rd = json.loads(round_score_p.read_text(encoding="utf-8"))
        except Exception:
            continue
        candidates = rd.get("candidates", []) or []
        # skill_scores: key=candidate_N, value=normalized.result_score
        skill_scores: Dict[str, Optional[float]] = {}
        for c in candidates:
            cid = c.get("candidate_id")
            if cid is None:
                continue
            key = f"candidate_{cid}"
            norm = c.get("normalized", {}) or {}
            v = norm.get("result_score")
            if v is None:
                v = c.get("avg_result_score")
            try:
                fv = float(v) if v is not None else 0.0
            except (TypeError, ValueError):
                fv = 0.0
            # 区分"未跑"与"0 分":非 None 但为 0 的,记 0.0
            skill_scores[key] = fv if fv > 0 else (fv if v is not None else None)
        # 候选的 runs + case 分数（从 candidate_N_score.json + run_N/score.json）
        cand_run_scores: Dict[int, List[float]] = {}
        cand_case_scores: Dict[int, Dict[str, List[float]]] = {}
        for c in candidates:
            cid = c.get("candidate_id")
            if cid is None:
                continue
            cand_score_p = round_dir / f"candidate_{cid}" / f"candidate_{cid}_score.json"
            if not cand_score_p.exists():
                continue
            try:
                cd = json.loads(cand_score_p.read_text(encoding="utf-8"))
            except Exception:
                continue
            # run_scores
            run_scores_list: List[float] = []
            for r in cd.get("runs", []) or []:
                rs = r.get("result_score")
                try:
                    run_scores_list.append(float(rs) if rs is not None else 0.0)
                except (TypeError, ValueError):
                    run_scores_list.append(0.0)
            if run_scores_list:
                cand_run_scores[cid] = run_scores_list
            # case_scores（跨 run 聚合）
            for r in cd.get("runs", []) or []:
                info = r.get("info", {}) or {}
                per_case = info.get("result_score_per_case") or {}
                for case_id, val in per_case.items():
                    if isinstance(val, list):
                        vs = [float(x) for x in val if isinstance(x, (int, float))]
                    elif isinstance(val, (int, float)):
                        vs = [float(val)]
                    else:
                        continue
                    if vs:
                        cand_case_scores.setdefault(cid, {}).setdefault(case_id, []).extend(vs)
        # 最佳分
        best_cid = rd.get("best_candidate_id")
        best_score = 0.0
        if best_cid and best_cid in cand_run_scores and cand_run_scores[best_cid]:
            best_score = cand_run_scores[best_cid][0]
        elif candidates:
            try:
                best_score = max(
                    (float((c.get("normalized", {}) or {}).get("result_score") or c.get("avg_result_score") or 0)
                     for c in candidates),
                    default=0.0,
                )
            except (TypeError, ValueError):
                best_score = 0.0
        out.append({
            "round": rnd,
            "score": float(best_score),
            "gaps": 0,
            "skill_scores": skill_scores,
            "skills": {sn: {"gaps": "—"} for sn in skill_names},
            "rating": "—",
            "timestamp": rd.get("timestamp", ""),
            "candidates_evaluated": len(candidates),
            "candidates_total": len(candidates),
            "_disk_recovered": True,
            "_cand_run_scores": cand_run_scores,
            "_cand_case_scores": cand_case_scores,
        })
    return out


def _build_score_history_md(agent_dir: Path, config: dict, history_for_chart: list, skill_registry: dict):
    """
    增强版 score_history.md：汇总任务所有分数（基线 + 每轮每候选每 run + CASE 分数）。

    输出结构：
    1. 任务总览
    2. Round 明细
    3. 候选详细分数（含 run 分数 + CASE 分数）
    4. 稳定性统计
    5. 产物路径索引

    注:不再输出"Skill 级别分数"表 — 端到端评测下各 Skill 共享同一聚合分,
    按 Skill 拆分会得到相同数值,与"各 Skill 优化效果"无信息增量(2026-06-18 起)。

    task_state.json 极简版只存状态;history_for_chart 由调用方构造。

    自愈:若 history_for_chart 缺 round 行,从磁盘 round_N_score.json 扫描重建。
    """
    import statistics

    from state_engine.persistence import atomic_write

    # ── 自愈:扫描文件系统补全缺失的 round 行 ──
    round_rows_in = [h for h in history_for_chart if h.get("round") != "baseline"]
    disk_round_dirs = list(agent_dir.glob("round_*"))
    if not round_rows_in and disk_round_dirs:
        disk_history = _recover_score_history_from_disk(agent_dir, config)
        if disk_history:
            existing_baseline = next((h for h in history_for_chart if h.get("round") == "baseline"), None)
            disk_round_rows = [h for h in disk_history if h.get("round") != "baseline"]
            if not disk_round_rows and disk_history:
                # 极端情况:磁盘只有 baseline 文件,保留入参 baseline + 追加磁盘行
                history_for_chart = ([existing_baseline] if existing_baseline else []) + disk_history
            else:
                history_for_chart = ([existing_baseline] if existing_baseline else []) + disk_round_rows

    # baseline_score / best_score: task_state.json 极简版只存状态,从 config 读
    bl_score = config.get("aggregate_baseline") or config.get("baseline_score", 0) or 0
    best_score = config.get("best_score", 0) or 0

    target_score = config.get("target_score", 100.0)
    achieved = best_score >= target_score
    evolution_direction = "上升" if best_score > bl_score else ("下降" if best_score < bl_score else "持平")
    agent_name = config.get("agent_name", "unknown")
    skill_names = list(skill_registry.keys()) if skill_registry else config.get("skill_names", [])
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    md_parts = []

    # ── 0. 标题 ──
    md_parts.append(f"# 分数历史 - {agent_name}")
    md_parts.append("")
    md_parts.append(f"> **生成时间**: {timestamp}")
    md_parts.append(f"> **工作空间**: {agent_dir}")
    md_parts.append("> **报告类型**: 任务全量分数汇总（基线 + 每轮每候选 + CASE 分数）")
    md_parts.append("")

    # ── 1. 任务总览 ──
    # 统计候选数、run 数
    total_candidates = 0
    total_runs = 0
    for h in history_for_chart:
        if h.get("round") == "baseline":
            continue
        skill_scores = h.get("skill_scores", {}) or {}
        total_candidates += len([k for k in skill_scores.keys() if k and k != "—"])
        for ck in skill_scores.keys():
            try:
                cand_id = int(str(ck).split("_")[1])
            except (IndexError, ValueError):
                continue
            cand_score_p = agent_dir / f"round_{h.get('round')}" / f"candidate_{cand_id}" / f"candidate_{cand_id}_score.json"
            if cand_score_p.exists():
                try:
                    data = json.loads(cand_score_p.read_text(encoding="utf-8"))
                    total_runs += data.get("num_runs", 0)
                except Exception:
                    pass

    md_parts.append("## 1. 任务总览")
    md_parts.append("")
    md_parts.append("| 指标 | 值 |")
    md_parts.append("|------|-----|")
    md_parts.append(f"| Agent 名称 | {agent_name} |")
    md_parts.append(f"| Skill 列表 | {', '.join(skill_names)} |")
    md_parts.append(f"| 总轮数 | {len([h for h in history_for_chart if h.get('round') != 'baseline'])} |")
    md_parts.append(f"| 总候选数 | {total_candidates} |")
    md_parts.append(f"| 总 Run 数 | {total_runs} |")
    md_parts.append(f"| 基线分数 | {bl_score:.1f} |")
    md_parts.append(f"| 最佳分数 | {best_score:.1f} |")
    md_parts.append(f"| 目标分数 | {target_score:.1f} |")
    md_parts.append(f"| 达标状态 | {'✅ 已达标' if achieved else '❌ 未达标'} |")
    md_parts.append(f"| 进化方向 | {evolution_direction} ({best_score - bl_score:+.1f}) |")
    md_parts.append("")

    # ── 2. Round 明细（含基线） ──
    # 取消 ASCII 分数趋势图：end-to-end 评测下分数波动小,图价值低(2026-06-18)。
    md_parts.append("## 2. Round 明细")
    md_parts.append("")
    # 基线先
    for h in history_for_chart:
        if h.get("round") == "baseline":
            md_parts.append("### 2.1 Baseline")
            md_parts.append("")
            baseline_score_p = agent_dir / "baseline" / "score_baseline.json"
            bl_runs = []
            if baseline_score_p.exists():
                try:
                    bl_data = json.loads(baseline_score_p.read_text(encoding="utf-8"))
                    bl_runs = bl_data.get("baseline_score", {}).get("runs", [])
                except Exception:
                    pass
            md_parts.append(f"- **平均分**: {bl_score:.1f}")
            md_parts.append(f"- **Run 数**: {len(bl_runs)}")
            if bl_runs:
                bl_run_strs = ", ".join(f"{r.get('result_score', 0):.1f}" for r in bl_runs)
                md_parts.append(f"- **Run 分数**: {bl_run_strs}")
                rs = [r.get("result_score", 0) for r in bl_runs]
                md_parts.append(f"- **Run 极差**: {max(rs) - min(rs):.1f}")
                stddev_str = f"{statistics.stdev(rs):.2f}" if len(rs) > 1 else "0.00"
                md_parts.append(f"- **Run 标准差**: {stddev_str}")
            # CASE 分数分布（从 baseline/run_1/score.json 取）
            baseline_run1_p = agent_dir / "baseline" / "run_1" / "score.json"
            if baseline_run1_p.exists():
                try:
                    run1_data = json.loads(baseline_run1_p.read_text(encoding="utf-8"))
                    info = run1_data.get("info", {}) or {}
                    case_scores = info.get("result_score_per_source") or info.get("result_score_per_case") or {}
                    if case_scores:
                        md_parts.append("- **CASE 分数分布**（来自 baseline/run_1/score.json）:")
                        md_parts.append("")
                        md_parts.append("| CASE | 分数 |")
                        md_parts.append("|:-----|:----:|")
                        for case_key, scores in sorted(case_scores.items()):
                            # 兼容两种 key:case_id 直接给(形如 XXX-NNN),或文件路径取末段
                            if isinstance(case_key, str) and _CASE_ID_PATTERN.match(case_key):
                                case_id = case_key
                            else:
                                case_id = Path(case_key).name if case_key else "—"
                            if isinstance(scores, list):
                                avg = sum(scores) / len(scores) if scores else 0
                            elif isinstance(scores, (int, float)):
                                avg = float(scores)
                            else:
                                continue
                            md_parts.append(f"| {case_id} | {avg:.1f} |")
                except Exception:
                    pass
            md_parts.append("")
            break

    # 每个 round
    round_subsection_idx = 2  # baseline 用了 2.1，Round 1 用 2.2，Round 2 用 2.3 ……
    for h in history_for_chart:
        if h.get("round") == "baseline":
            continue
        rnd = h.get("round", "?")
        md_parts.append(f"### 2.{round_subsection_idx} Round {rnd}")
        md_parts.append("")
        round_subsection_idx += 1
        # 找到该轮的 round_N/round_N_score.json
        round_score_p = agent_dir / f"round_{rnd}" / f"round_{rnd}_score.json"
        best_cand_id = None
        if round_score_p.exists():
            try:
                rd = json.loads(round_score_p.read_text(encoding="utf-8"))
                best_cand_id = rd.get("best_candidate_id")
            except Exception:
                pass
        # 候选分数表
        md_parts.append("| 候选 | 策略 | 平均分 | 标准差 | Run 1 | Run 2 | 选中 | vs 基线 |")
        md_parts.append("|:----:|:----:|:------:|:------:|:-----:|:-----:|:----:|:-------:|")
        skill_scores = h.get("skill_scores", {}) or {}
        for ck, cv in skill_scores.items():
            try:
                cand_id = int(str(ck).split("_")[1])
            except (IndexError, ValueError):
                continue
            cand_score_p = agent_dir / f"round_{rnd}" / f"candidate_{cand_id}" / f"candidate_{cand_id}_score.json"
            if not cand_score_p.exists():
                continue
            try:
                cd = json.loads(cand_score_p.read_text(encoding="utf-8"))
            except Exception:
                continue
            stddev = cd.get("stddev", 0) or 0
            # 兼容老格式:仅有 runs[].result_score 时,现抽 run_scores
            run_scores = cd.get("run_scores")
            if not run_scores:
                _runs_list = cd.get("runs") or []
                run_scores = [r.get("result_score") for r in _runs_list if r.get("result_score") is not None]
            # 兜底:stddev 缺失时从 runs 现算(n-1)
            if (not stddev or stddev == 0) and len(run_scores) >= 2:
                _m = sum(run_scores) / len(run_scores)
                stddev = (sum((s - _m) ** 2 for s in run_scores) / (len(run_scores) - 1)) ** 0.5
            r1 = f"{run_scores[0]:.1f}" if len(run_scores) >= 1 else "—"
            r2 = f"{run_scores[1]:.1f}" if len(run_scores) >= 2 else "—"
            diff = (cv or 0) - bl_score
            vs_bl = f"{diff:+.1f}"
            is_selected = (cand_id == best_cand_id) or cd.get("selected", False)
            mark = "✅" if is_selected else "—"
            # cv 可能为 None(history 中区分"未跑"和"0 分"),防御性格式化
            cv_str = f"{cv:.1f}" if cv is not None else "—"
            stddev_str = f"{stddev:.2f}" if stddev is not None else "—"
            md_parts.append(f"| {cand_id} | {ck} | {cv_str} | {stddev_str} | {r1} | {r2} | {mark} | {vs_bl} |")
        md_parts.append("")

    # ── 3. 候选详细分数（按 run + CASE） ──
    md_parts.append("## 3. 候选详细分数（Run + CASE 明细）")
    md_parts.append("")
    for h in history_for_chart:
        if h.get("round") == "baseline":
            continue
        rnd = h.get("round", "?")
        skill_scores = h.get("skill_scores", {}) or {}
        for ck in skill_scores.keys():
            try:
                cand_id = int(str(ck).split("_")[1])
            except (IndexError, ValueError):
                continue
            cand_dir = agent_dir / f"round_{rnd}" / f"candidate_{cand_id}"
            if not cand_dir.exists():
                continue
            md_parts.append(f"### 3.{rnd}.{cand_id} {ck}")
            md_parts.append("")
            # Run 明细
            md_parts.append("**Run 明细**：")
            md_parts.append("")
            md_parts.append("| Run | 分数 | vs 前一 Run | 路径 |")
            md_parts.append("|:---:|:----:|:-----------:|:-----|")
            prev_score = None
            for run_idx in range(1, 10):
                run_p = cand_dir / f"run_{run_idx}" / "score.json"
                if not run_p.exists():
                    break
                try:
                    rd = json.loads(run_p.read_text(encoding="utf-8"))
                except Exception:
                    break
                rs = rd.get("result_score", 0)
                delta = ""
                if prev_score is not None:
                    diff = rs - prev_score
                    delta = f"{diff:+.1f}"
                prev_score = rs
                rel = f"round_{rnd}/candidate_{cand_id}/run_{run_idx}/score.json"
                md_parts.append(f"| {run_idx} | {rs:.1f} | {delta} | `{rel}` |")
            md_parts.append("")

            # CASE 分数明细（按 RAN ID 聚合，跨 run 取均值）
            md_parts.append("**CASE 分数明细**（按 RAN ID 聚合，跨 run 取均值）：")
            md_parts.append("")
            md_parts.append("| CASE | Run 1 | Run 2 | 平均 | 极差 |")
            md_parts.append("|:----:|:-----:|:-----:|:----:|:----:|")
            # 收集所有 run 的 CASE 分数
            all_runs_case_scores = {}  # ran_id -> {run_idx: [scores]}
            for run_idx in range(1, 10):
                run_p = cand_dir / f"run_{run_idx}" / "score.json"
                if not run_p.exists():
                    break
                try:
                    rd = json.loads(run_p.read_text(encoding="utf-8"))
                except Exception:
                    continue
                per_source = rd.get("info", {}).get("result_score_per_source") or rd.get("info", {}).get("result_score_per_case") or {}
                for case_id_or_path, scores in per_source.items():
                    # 兼容两种 key 形态:case_id 直接(形如 XXX-NNN),或文件路径(从路径段中找)
                    if isinstance(case_id_or_path, str) and _CASE_ID_PATTERN.match(case_id_or_path):
                        case_id = case_id_or_path
                    else:
                        parts = Path(case_id_or_path).parts if case_id_or_path else ()
                        case_id = next((p for p in parts if _CASE_ID_PATTERN.match(p)), None)
                    if case_id is None:
                        continue
                    # scores 可能是 list 或 单值
                    if isinstance(scores, list):
                        avg_score = sum(scores) / len(scores) if scores else 0
                    elif isinstance(scores, (int, float)):
                        avg_score = float(scores)
                    else:
                        continue
                    all_runs_case_scores.setdefault(case_id, {})[run_idx] = avg_score
            if all_runs_case_scores:
                # 排序：按平均分降序
                sorted_cases = sorted(
                    all_runs_case_scores.items(),
                    key=lambda kv: -(sum(kv[1].values()) / len(kv[1]) if kv[1] else 0)
                )
                for ran_id, run_map in sorted_cases:
                    run_scores_strs = [f"R{ri}: {rs:.1f}" for ri, rs in sorted(run_map.items())]
                    r1 = f"{run_map[1]:.1f}" if 1 in run_map else "—"
                    r2 = f"{run_map[2]:.1f}" if 2 in run_map else "—"
                    avg = sum(run_map.values()) / len(run_map)
                    rng = max(run_map.values()) - min(run_map.values())
                    md_parts.append(f"| {ran_id} | {r1} | {r2} | {avg:.1f} | {rng:.1f} |")
            else:
                md_parts.append("| — | — | — | — | — |")
            md_parts.append("")

    # ── 4. 稳定性统计 ──
    md_parts.append("## 4. 稳定性统计")
    md_parts.append("")
    md_parts.append("| 候选 | 平均分 | σ | CV% | 评级 |")
    md_parts.append("|:----:|:------:|:-:|:---:|:-----|")
    for h in history_for_chart:
        if h.get("round") == "baseline":
            continue
        rnd = h.get("round", "?")
        skill_scores = h.get("skill_scores", {}) or {}
        for ck, cv in skill_scores.items():
            try:
                cand_id = int(str(ck).split("_")[1])
            except (IndexError, ValueError):
                continue
            cand_score_p = agent_dir / f"round_{rnd}" / f"candidate_{cand_id}" / f"candidate_{cand_id}_score.json"
            if not cand_score_p.exists():
                continue
            try:
                cd = json.loads(cand_score_p.read_text(encoding="utf-8"))
            except Exception:
                continue
            avg = cd.get("avg_result_score", 0)
            stddev = cd.get("stddev", 0)
            # 兜底:缺 stddev 时从 runs[].result_score 现算(n-1)
            if (not stddev or stddev == 0):
                runs = cd.get("runs") or []
                rs_list = [r.get("result_score") for r in runs if r.get("result_score") is not None]
                if len(rs_list) >= 2:
                    m = sum(rs_list) / len(rs_list)
                    stddev = (sum((s - m) ** 2 for s in rs_list) / (len(rs_list) - 1)) ** 0.5
            cv_pct = (stddev / avg * 100) if avg > 0 else 0
            if stddev == 0:
                rating = "完美稳定"
            elif cv_pct < 10:
                rating = "高稳定"
            elif cv_pct < 30:
                rating = "中等稳定"
            else:
                rating = "低稳定（需关注）"
            md_parts.append(f"| {ck} | {avg:.1f} | {stddev:.2f} | {cv_pct:.1f}% | {rating} |")
    md_parts.append("")

    # ── 5. 产物路径索引 ──
    md_parts.append("## 5. 产物路径索引")
    md_parts.append("")
    md_parts.append("| 类别 | 路径 |")
    md_parts.append("|:-----|:-----|")
    md_parts.append("| Agent 进化报告 | `skill_进化报告.md` |")
    md_parts.append("| 任务配置 | `config.json` |")
    md_parts.append("| 任务状态 | `task_state.json` |")
    md_parts.append("| 整体最佳 Skill | `best_skill/` |")
    md_parts.append("| 基线分数 | `baseline/score_baseline.json` |")
    md_parts.append("| 基线提案 | `baseline/proposal.md` |")
    for h in history_for_chart:
        if h.get("round") == "baseline":
            continue
        rnd = h.get("round", "?")
        md_parts.append(f"| Round {rnd} 分数汇总 | `round_{rnd}/round_{rnd}_score.json` |")
        md_parts.append(f"| Round {rnd} 分数分析 | `round_{rnd}/round_{rnd}_score_analysis.md` |")
        for ck in (h.get("skill_scores", {}) or {}).keys():
            try:
                cand_id = int(str(ck).split("_")[1])
            except (IndexError, ValueError):
                continue
            md_parts.append(f"| Round {rnd} {ck} | `round_{rnd}/candidate_{cand_id}/` |")
            md_parts.append(f"| Round {rnd} {ck} 分数 | `round_{rnd}/candidate_{cand_id}/candidate_{cand_id}_score.json` |")
    md_parts.append("")

    # ── 写文件 ──
    out_path = agent_dir / "score_history.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(str(out_path), "\n".join(md_parts))


# 缓存 pipeline 命令提取结果，避免重复解析 YAML
_extracted_pipeline_commands: Optional[list] = None


# 业务方命令中常见的"case ID 列表参数"形式
_CASE_ID_FLAGS = ("--req-id", "--req_id", "--reqid", "--request-id",
                  "--request_id", "--requestid", "--case-ids", "--case_ids")
