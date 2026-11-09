"""
orchestrators_history
=====================
轻量的 score_history.md 增量渲染入口,让 baseline 收尾、轮次收尾阶段能"看到什么写什么"。

设计动机:
    `_build_score_history_md` 内部假设了完整的 history_for_chart 上下文(基线行已注入 + 候选未跑规范化),
    由 `run_agent_loop` 收尾时统一调用。当 baseline 跑完、轮次跑完时,需要一种"立刻可调"的入口,
    不必把所有 build/normalize 逻辑再 copy 一遍。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional


def _build_history_for_chart(
    config: dict,
    history: list,
) -> list:
    """从 config + history 构造 history_for_chart(注入 baseline 行 + 候选未跑规范化)。

    与 run_agent_loop 里的内联构造保持一致(orchestrator.py:1584-1604):
    - 若 history 中无 baseline 行,用 config.baseline_score 注入一行
    - 每行补 _display_score / _display_skill_scores / _display_note 缺省

    task_state.json 极简版不存结果数据,所有历史/baseline 字段从 config 读。
    """
    bl_score = config.get("baseline_score", 0) or 0

    out: List[Dict[str, Any]] = []
    has_baseline_row = any(h.get("round") == "baseline" for h in history)
    if bl_score and not has_baseline_row:
        out.append({
            "round": "baseline",
            "score": bl_score,
            "gaps": 0,
            "skill_scores": {},
            "skills": {},
            "rating": "BASELINE",
            "timestamp": config.get("created_at", ""),
        })
    out.extend(history)

    for h in out:
        if h.get("round") == "baseline":
            h.setdefault("_display_score", h.get("score", 0))
            h.setdefault("_display_skill_scores", h.get("skill_scores") or {})
            h.setdefault("_display_note", "")
            continue
        score = h.get("score")
        if score is None or score == 0:
            skill_scores = h.get("skill_scores") or {}
            if skill_scores:
                avg = sum(skill_scores.values()) / len(skill_scores)
                h["_display_score"] = avg
            else:
                h["_display_score"] = 0
        else:
            h["_display_score"] = score
        h.setdefault("_display_skill_scores", h.get("skill_scores") or {})
        h.setdefault("_display_note", h.get("note", ""))
    return out


def render_score_history_incremental(
    agent_dir: Path,
    config: dict,
    history: list,
    skill_registry: Optional[dict] = None,
) -> Path:
    """增量渲染 score_history.md,基于当前 config + history 直接覆盖写。

    适用场景:
    - baseline 跑完但 run_agent_loop 还没到收尾阶段
    - 任意轮次结束后想立即刷新报告(不等整任务完成)

    入参:
        agent_dir: workspace 根目录(baseline/、round_*/ 都在其下)
        config:    state_engine.config(已含 baseline_score / best_score / target_score 等)
        history:   state_engine.history(可能没有 baseline 行 — 由本函数注入)
        skill_registry: 可选,若 config 里没 skill_names 字段则用此

    返回:
        写入的 score_history.md 绝对路径
    """
    from orchestrators.reports import _build_score_history_md

    history_for_chart = _build_history_for_chart(config, history)
    out_path = agent_dir / "score_history.md"
    _build_score_history_md(
        agent_dir=agent_dir,
        config=config,
        history_for_chart=history_for_chart,
        skill_registry=skill_registry or config.get("skill_registry", {}) or {},
    )
    return out_path
