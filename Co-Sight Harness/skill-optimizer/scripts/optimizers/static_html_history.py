"""static_html_history.py — /skill_optimize 的 HTML 可视化报告（ P1-7）。

对齐 agent-skills-eval 的"A/B 对比 + 可视化 HTML 报告"思想,但服务于多轮 hill-climb
场景。生成单个 skill_optimize_report.html,含:
- baseline + 每轮的 N 维 radar 图（echarts,N 由 framework_cfg.rubric 动态决定）
- 总分折线图
- 每轮 dim diff 表（before vs after）
- 触顶 break / HITL verdict 标注

设计原则：dim 数与名称**完全由 YAML 驱动**——
- dim 数量 = framework_cfg.rubric 中 dim 键的数量
- 维度名称 / 中文标签 = rubric[k].name
- 不在 Python 端硬编码 9/12 等任何数字
业务方启用多少个 auto 维度,HTML 标题与雷达图就显示多少维。

设计原则：
- 不引入前端构建链,Python 端只输出单文件 HTML
- 内嵌 echarts CDN（5.x），离线环境 fallback 到本地数据表格
- 读 static_history.json 作为唯一数据源（与 PNG 雷达图共用）
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("static_html_history")


@dataclass
class HtmlReportResult:
    """HTML 报告生成结果"""

    output_path: Optional[str] = None
    rounds_plotted: int = 0
    dims_plotted: int = 0
    skipped: bool = False
    reason: str = ""


# 内嵌 echarts 5.4.3 CDN（优先 jsdelivr — 实测国内可访问）
# 备选：bootcdn.net / cdnjs.cloudflare.com（境外可用）。HTML 加载失败时 fallback 到静态表格。
ECHARTS_CDN = "https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"


def _load_history(workspace: Path) -> list[dict]:
    """从 {workspace}/static_history.json 读 history。失败返回空 list。"""
    p = workspace / "static_history.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("读 static_history.json 失败: %s", e)
        return []


def _load_rubric_meta(framework_cfg: dict) -> dict[str, dict]:
    """.6:从 framework_cfg 提取 dim -> {name, weight} 映射。

    返回结构: {dim_key: {"name": str, "weight": float}}
    调用方根据需要读 name 和 weight,雷达图/HTML 同时显示中文名 + 权重。
    """
    rubric = framework_cfg.get("rubric", {}) or {}
    out: dict[str, dict] = {}
    for k, v in rubric.items():
        if not k.startswith("dim"):
            continue
        name = (v or {}).get("name") or k.split("_", 1)[-1] if "_" in k else k
        try:
            weight = float((v or {}).get("weight", 1.0))
        except (TypeError, ValueError):
            weight = 1.0
        out[k] = {"name": str(name), "weight": weight}
    return out


def _format_weight(w: float) -> str:
    """权重格式化:整数显示为 '1',浮点显示为 '1.5'。"""
    if w == int(w):
        return f"{int(w)}"
    return f"{w:.1f}"


def _compute_file_diffs(old_path: Path, new_path: Path) -> list[dict]:
    """递归对比 old_path 与 new_path 下的所有文件，生成 gerrit 风格 diff。

    过滤规则：
    - 只对比 SKILL.md 和 scripts/ 下的文件（用户关心的核心文件）
    - 排除 .eval_out/ 等评分过程产物
    - 排除 score.sub*.json 等评估分数文件

    Returns:
        list[dict]: [
            {
                "path": "relative/path",
                "lines": 总行数,
                "added": 新增行数,
                "removed": 删除行数,
                "diff": [{"text": "...", "added": bool, "removed": bool,
                           "old_ln": int|None, "new_ln": int|None}, ...]
            }
        ]
        无差异返回空 list。
    """
    if not old_path or not new_path:
        return []
    if not old_path.exists() or not new_path.exists():
        return []
    if not old_path.is_dir() or not new_path.is_dir():
        return []

    results: list[dict] = []
    # 只保留用户关心的文件扩展名
    text_exts = {".md", ".py", ".sh", ".json", ".yaml", ".yml", ".txt", ".toml"}
    old_files = {p.relative_to(old_path): p for p in old_path.rglob("*") if p.is_file() and p.suffix in text_exts}
    new_files = {p.relative_to(new_path): p for p in new_path.rglob("*") if p.is_file() and p.suffix in text_exts}

    # 过滤：跳过 .eval_out/ 和 score.sub*.json 等评估产物
    # .x 修复：用 regex 严格匹配 LLM 自救产物变体（backup_score_*.json / score_sub*.json / _score.json 等）
    # 严格按 basename 匹配，误删风险为零
    import re as _re_html_artifact
    _HTML_ARTIFACT_NAME_RE = _re_html_artifact.compile(
        r"^(score\.sub\d+(?:\.retry\d+)?\.json"
        r"|score_sub\d+(?:_retry\d+)?\.json"
        r"|backup_score[^/]*\.json"
        r"|_score\.json)$"
    )
    def _is_artifact(rel_path: str) -> bool:
        if rel_path.startswith(".eval_out") or rel_path.startswith(".skillx-bak"):
            return True
        if rel_path.startswith("round_"):
            return True
        # 只看 basename（防 path traversal / 嵌套目录）
        base = rel_path.rsplit("/", 1)[-1]
        if _HTML_ARTIFACT_NAME_RE.match(base):
            return True
        return False

    all_paths = sorted(set(old_files) | set(new_files))
    all_paths = [p for p in all_paths if not _is_artifact(str(p))]

    for rel in all_paths:
        old_f = old_files.get(rel)
        new_f = new_files.get(rel)
        if old_f is None:
            # 新增文件
            content = new_f.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
            diff = [
                {"text": line, "added": True, "removed": False,
                 "old_ln": None, "new_ln": i + 1}
                for i, line in enumerate(lines)
            ]
            results.append({
                "path": str(rel),
                "lines": len(lines),
                "added": len(lines),
                "removed": 0,
                "diff": diff,
            })
        elif new_f is None:
            # 删除文件
            content = old_f.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
            diff = [
                {"text": line, "added": False, "removed": True,
                 "old_ln": i + 1, "new_ln": None}
                for i, line in enumerate(lines)
            ]
            results.append({
                "path": str(rel),
                "lines": len(lines),
                "added": 0,
                "removed": len(lines),
                "diff": diff,
            })
        elif old_f.read_text(encoding="utf-8", errors="replace") == new_f.read_text(encoding="utf-8", errors="replace"):
            # 文件未变更，跳过
            continue
        else:
            # 修改的文件：使用 difflib 生成 unified diff，并追踪行号
            import difflib
            import re
            old_lines = old_f.read_text(encoding="utf-8", errors="replace").splitlines()
            new_lines = new_f.read_text(encoding="utf-8", errors="replace").splitlines()
            diff = difflib.unified_diff(old_lines, new_lines, lineterm="", n=3)

            parsed = []
            added = removed = 0
            old_ln = 0
            new_ln = 0
            for line in diff:
                if line.startswith("+++") or line.startswith("---"):
                    continue  # 跳过 diff 头
                if line.startswith("@@"):
                    # 解析 @@ -old_start,count +new_start,count @@
                    parsed.append({"text": line, "added": False, "removed": False,
                                   "old_ln": None, "new_ln": None})
                    m = re.match(r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
                    if m:
                        old_ln = int(m.group(1))
                        new_ln = int(m.group(2))
                    continue
                if line.startswith("-"):
                    parsed.append({"text": line[1:], "added": False, "removed": True,
                                   "old_ln": old_ln, "new_ln": None})
                    old_ln += 1
                    removed += 1
                elif line.startswith("+"):
                    parsed.append({"text": line[1:], "added": True, "removed": False,
                                   "old_ln": None, "new_ln": new_ln})
                    new_ln += 1
                    added += 1
                else:
                    # context 行
                    parsed.append({"text": line, "added": False, "removed": False,
                                   "old_ln": old_ln, "new_ln": new_ln})
                    old_ln += 1
                    new_ln += 1
            results.append({
                "path": str(rel),
                "lines": len(parsed),
                "added": added,
                "removed": removed,
                "diff": parsed,
            })
    return results


def _build_echarts_data(history: list[dict], rubric_meta: dict[str, dict], file_diffs: list[dict] | None = None) -> dict:
    """构造 echarts 数据结构（radar + line + diff table + file_diffs）。"""
    # 收集所有 dim_keys(从 history 里 union)
    dim_keys: list[str] = []
    seen: set[str] = set()
    for entry in history:
        for k in (entry.get("dim_scores") or {}).keys():
            if k not in seen:
                seen.add(k)
                dim_keys.append(k)
    if not dim_keys:
        return {"dim_keys": [], "rounds": []}

    # 排序:dim1~dimN 顺序,未知 dim 排后面
    def _sort_key(k: str) -> tuple[int, str]:
        if k.startswith("dim"):
            try:
                return (int(k[3:].split("_")[0]), k)
            except ValueError:
                return (999, k)
        return (998, k)

    dim_keys.sort(key=_sort_key)
    # .6:dim 标签同时显示中文名 + 权重,格式 "<name> x <weight>"
    dim_labels = []
    for k in dim_keys:
        meta = rubric_meta.get(k) or {"name": k, "weight": 1.0}
        name = meta.get("name", k)
        weight = meta.get("weight", 1.0)
        dim_labels.append(f"{name} x {_format_weight(weight)}")

    rounds: list[dict] = []
    for entry in history:
        # 兼容多种 key 命名：unified 路径写 'round'/'total'，旧 6 phase 路径写 'round_num'/'score'
        rn = entry.get("round_num", entry.get("round", 0))
        label = "baseline" if rn == 0 else f"R{rn}"
        ds = entry.get("dim_scores") or {}
        # .9: 从 _eval_runs.per_run_dim_scores 提取每次 evaluator 的 多维独立分数
        eval_runs = entry.get("_eval_runs", {}) or {}
        # score: 旧路径写 score,unified 路径写 total,两者都兼容
        entry_score = entry.get("score", entry.get("total", 0.0))
        rounds.append({
            "label": label,
            "round_num": rn,
            # .16 治本：score 字段与 static_history.json 一致（单次 LLM judge 分数）
            # 之前用 total_mean（per_run_totals 算术平均）导致 HTML 报告与原始数据不一致
            # 例如 123640 R0: entry.score=58.02, total_mean=58.62, 报告里写 58.62
            # 现在用 entry.score（原始 1 次评估的 dim 加权平均）,与 progress-state.yaml 同步
            # total_mean 保留到 _score 字段供回溯（CDN 明细表格仍可用 _score）
            "score": entry_score,
            "_score": (
                entry.get("_eval_runs", {}).get("total_mean")
                or entry_score
            ),
            "delta": entry.get("delta", 0.0),
            "verdict": entry.get("verdict", ""),
            "dim_scores": {k: float(ds.get(k, 0.0)) for k in dim_keys},
            "per_run_dim_scores": eval_runs.get("per_run_dim_scores", []),
            "per_run_totals": eval_runs.get("per_run_totals", []),
            "total_stdev": eval_runs.get("total_stdev", 0.0),
            # .10: requested/succeeded 让报告标注"几次请求几次成功几次失败"
            "n_requested": int(eval_runs.get("n_requested", len(eval_runs.get("per_run_totals", [])) or 1)),
            "n_succeeded": int(eval_runs.get("n_succeeded", len(eval_runs.get("per_run_totals", [])) or 1)),
            # .10: total_mean = per_run_totals 算术平均，与 Run 行语义对齐
            "total_mean": float(eval_runs.get("total_mean", entry_score)),
        })

    # .10: 收集 auto 维度（compute_mode=auto）传给前端,均值行追加 * 标记
    # 这些维度会被 _compute_coverage / 安全扫描 / token 统计等 system 端逻辑覆盖
    # 不是 LLM judge 直接给的分数,需与 per_run_dim_scores 区分
    auto_dims: list[str] = [
        k for k, v in rubric_meta.items()
        if k.startswith("dim") and (v or {}).get("compute_mode") == "auto"
    ]  # fmt: skip

    # .7: 采纳判定(分数相对上一采纳分数 > acceptance_gap_threshold 视为采纳)
    acceptance_gap = 0.5  # 默认 0.5 分（用户要求降低,允许小幅提升也被采纳）
    accepted_so_far: list[dict] = []
    accepted_score: float | None = None  # 已被采纳的最高分
    accepted_round: int | None = None
    for r in rounds:
        rn = r["round_num"]
        score = r["score"]
        verdict = r["verdict"]
        accepted = False
        note = ""
        if rn == 0:
            # baseline 不算"采纳",只是起点
            accepted = False
            note = "基线(起点,不参与采纳判定)"
            accepted_score = score
        else:
            # 采纳规则: 分数 > 上一采纳分数 + acceptance_gap
            # 如果 revert 路径,即使分数高也不采纳
            is_revert_path = verdict in {"reverted", "auto_revert", "human_review_rejected", "broken"}
            if not is_revert_path and accepted_score is not None and score > accepted_score + acceptance_gap:
                accepted = True
                prev = accepted_score
                accepted_score = score
                accepted_round = rn
                note = f"采纳(分数 {score:.2f} > 上一采纳 {prev:.2f} + {acceptance_gap})"
            else:
                # 不采纳:即使分数高但没超分差,或被回退
                if is_revert_path:
                    note = f"不采纳({verdict}, worktree 已回退)"
                elif accepted_score is not None and score > accepted_score:
                    note = f"未采纳:分数 {score:.2f} > 上一采纳 {accepted_score:.2f} 但 Δ={score - accepted_score:.2f} ≤ {acceptance_gap},未达分差门槛"
                else:
                    note = f"未采纳:分数 {score:.2f} ≤ 上一采纳 {accepted_score:.2f}"
        accepted_so_far.append({
            "accepted": accepted,
            "note": note,
            "accepted_score_so_far": accepted_score if accepted_score is not None else 0.0,
            "accepted_round": accepted_round,
        })

    return {
        "dim_keys": dim_keys,
        "dim_labels": dim_labels,
        "file_diffs": file_diffs or [],  # .10+: 文件 diff 章节数据
        "rounds": rounds,
        "auto_dims": auto_dims,                       # .10: 标 * 用的 auto 维度列表
        "acceptance_gap": acceptance_gap,             # .7
        "accepted_so_far": accepted_so_far,           # .7
        "accepted_round": accepted_round,             # .7(整局最佳采纳轮次)
    }


def _render_fallback_table_static(chart_data: dict) -> str:
    """.16 治本:静态渲染 fallback 表格到 HTML（不依赖 JS）。

    之前: fallback 表格只通过 JS (renderFallback) 渲染 → 用户直接看 HTML 源文件
          看到空容器 `<div id="fallback-table"></div>`, 看不到 58.02/70.55/81.34 等分数。
    现在: Python 端在 _build_html 时直接拼好表格 HTML 嵌入到 fallback-table div 内,
          JS 跑起来时 renderFallback() 会覆盖（不影响功能）。即使 CDN 墙了/JS 没跑,
          用户用 file:// 直接打开 HTML 也能看到所有分数。

    Args:
        chart_data: _build_echarts_data 输出的 dict（含 rounds / dim_keys / accepted_so_far）

    Returns:
        嵌入到 fallback-table div 内的 HTML 字符串（已含 <table>...</table>）
    """
    rounds = chart_data.get("rounds", []) or []
    if not rounds:
        return "<p style='color:#6b7280;'>暂无数据</p>"

    accepted_list = chart_data.get("accepted_so_far", []) or []
    accepted_round = chart_data.get("accepted_round")
    gap = chart_data.get("acceptance_gap", 2.0)
    dim_keys = chart_data.get("dim_keys", []) or []

    lines = ['<table class="fallback-table">']
    lines.append('<thead><tr>')
    lines.append('<th>轮次</th><th>分数</th><th>Δ</th><th>verdict</th><th>采纳?</th><th>采纳后分数</th>')
    for k in dim_keys:
        lines.append(f'<th>{_html_escape(k)}</th>')
    lines.append('</tr></thead><tbody>')

    for idx, r in enumerate(rounds):
        acc = accepted_list[idx] if idx < len(accepted_list) else {"accepted": False, "note": "", "accepted_score_so_far": 0}
        is_baseline = r.get("round_num", 0) == 0
        is_best = accepted_round is not None and r.get("round_num") == accepted_round
        row_class = "baseline-row" if is_baseline else ("accepted-row" if acc.get("accepted") else "")
        best_mark = " ★" if is_best else ""

        score = r.get("score") or 0.0
        delta = r.get("delta") or 0.0
        verdict = r.get("verdict") or ""

        lines.append(f'<tr class="{row_class}">')
        lines.append(f'<td>{_html_escape(r.get("label", ""))}{best_mark}</td>')
        lines.append(f'<td>{score:.2f}</td>')
        # Δ 加正负号
        delta_str = f'+{delta:.2f}' if delta >= 0 else f'{delta:.2f}'
        lines.append(f'<td>{delta_str}</td>')
        # verdict 加 CSS class
        verdict_class = f'verdict-{verdict.replace("_", "-")}' if verdict else ""
        lines.append(f'<td class="{verdict_class}">{_html_escape(verdict)}</td>')
        # 采纳?
        if is_baseline:
            lines.append('<td><span class="rejected-badge">起点</span></td>')
        elif acc.get("accepted"):
            lines.append('<td><span class="accepted-badge">✓ 采纳</span></td>')
        else:
            lines.append('<td><span class="rejected-badge">✗</span></td>')
        # 采纳后分数
        lines.append(f'<td>{(acc.get("accepted_score_so_far") or 0):.2f}</td>')
        # dim 列
        for k in dim_keys:
            v = (r.get("dim_scores") or {}).get(k)
            if v is None:
                lines.append('<td>-</td>')
            else:
                lines.append(f'<td>{v:.1f}</td>')
        lines.append('</tr>')

    lines.append('</tbody></table>')
    # 表格后注释（仅一句核心规则，避免噪音）
    lines.append(f'<p class="notes">采纳规则：分数相对上一采纳分数 ≥ {gap:.1f} 分才视为采纳（避免微改进触发反复采纳）。'
                 'revert 路径即使分数高也不采纳。</p>')
    return "\n".join(lines)


def _html_escape(s: str) -> str:
    """HTML 字符转义,防 XSS。"""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;"))


def _build_html(workspace_name: str, chart_data: dict, dims_plotted: int = 0) -> str:
    """构造完整的 HTML 单文件(内嵌 echarts + JSON data + 初始化脚本)。"""
    json_data = json.dumps(chart_data, ensure_ascii=False)

    # .16 治本:静态渲染 fallback 表格,不依赖 JS
    # 用户直接看 HTML 源文件也能看到分数（58.02/70.55/81.34 等）
    fallback_table_static = _render_fallback_table_static(chart_data)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<title>Skill Optimize History — {workspace_name}</title>
<script src="{ECHARTS_CDN}"></script>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
       "Microsoft YaHei", sans-serif; margin: 24px; color: #1a1a1a; background: #fafafa; }}
h1 {{ font-size: 22px; margin-bottom: 4px; }}
.subtitle {{ color: #666; font-size: 13px; margin-bottom: 24px; }}
.chart-block {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 6px;
                padding: 16px; margin-bottom: 16px; }}
.chart-title {{ font-size: 14px; font-weight: 600; margin-bottom: 10px; }}
.chart {{ width: 100%; height: 380px; }}
.charts-row {{ display: flex; gap: 16px; margin-bottom: 16px; }}
.charts-row .chart-block {{ flex: 1; min-width: 0; margin-bottom: 0; }}
.charts-row .chart {{ height: 340px; }}
.fallback-table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
.fallback-table th, .fallback-table td {{ border: 1px solid #e5e7eb; padding: 6px 10px;
                                           text-align: left; }}
.fallback-table th {{ background: #f3f4f6; }}
.fallback-table tr.accepted-row {{ background: #d1fae5; }}
.fallback-table tr.accepted-row td {{ font-weight: 600; }}
.fallback-table tr.baseline-row {{ background: #f9fafb; color: #6b7280; }}
.accepted-badge {{ color: #059669; font-weight: 700; }}
.rejected-badge {{ color: #dc2626; font-weight: 700; }}
.verdict-improved, .verdict-auto_pass {{ color: #059669; font-weight: 600; }}
.verdict-reverted, .verdict-auto_revert, .verdict-human_review_rejected, .verdict-broken {{ color: #dc2626; font-weight: 600; }}
.verdict-baseline, .verdict-human_review {{ color: #6b7280; }}
.notes {{ margin: 12px 0 0; color: #6b7280; font-size: 12px; }}
/* 文件 diff（gerrit 风格：绿=新增 红=删除） */
.file-diff-block .diff-file {{ margin-top: 12px; }}
.file-diff-block .diff-file h3 {{ font-size: 13px; font-weight: 600;
                               margin: 8px 0 4px; padding: 4px 8px;
                               background: #f3f4f6; }}
.file-diff-block .diff-file .file-meta {{ font-size: 11px; color: #6b7280;
                                        margin-left: 8px; font-weight: normal; }}
.file-diff-block .diff-file pre {{ margin: 0; padding: 0;
                                  background: #fafafa; border: 1px solid #e5e7eb;
                                  overflow-x: auto; font-size: 12px; }}
.file-diff-block .diff-file .diff-line {{ padding: 1px 10px;
                                          font-family: 'SF Mono', 'Monaco', monospace;
                                          white-space: pre-wrap; word-break: break-all; }}
.file-diff-block .diff-line.added {{ background: #d1fae5; color: #065f46;
                                    border-left: 3px solid #10b981; }}
.file-diff-block .diff-line.removed {{ background: #fee2e2; color: #991b1b;
                                      border-left: 3px solid #ef4444; }}
.file-diff-block .diff-line.context {{ color: #374151; }}
.file-diff-block .diff-line .marker {{ display: inline-block; width: 18px;
                                       color: #6b7280; user-select: none; }}
</style>
</head>
<body>
<h1>Skill Optimize History</h1>
<div class="subtitle">{workspace_name} · 共 {len(chart_data.get('rounds', []))} 轮 · {dims_plotted} 维</div>

<div class="charts-row">
  <div class="chart-block">
    <div class="chart-title">{dims_plotted} 维评分雷达图</div>
    <div id="radar-chart" class="chart"></div>
  </div>
  <div class="chart-block">
    <div class="chart-title">总分折线图</div>
    <div id="line-chart" class="chart"></div>
  </div>
</div>

<div class="chart-block">
  <div class="chart-title">每轮分数明细</div>
  <div id="fallback-table">{fallback_table_static}</div>
</div>

<div class="chart-block file-diff-block">
  <div class="chart-title">采纳轮次 SKILL 文件 diff</div>
  <div id="file-diff-table"></div>
</div>

<script>
const chartData = {json_data};
const dimLabels = chartData.dim_labels || [];
const rounds = chartData.rounds || [];

function tryRender() {{
  if (typeof echarts === 'undefined') {{
    document.getElementById('radar-chart').innerHTML = '<p class="notes">echarts 加载失败，请查看下方数据表</p>';
    document.getElementById('line-chart').innerHTML = '';
    renderFileDiff();
    return false;
  }}
  renderRadar();
  renderLine();
  renderFileDiff();
  return true;
}}

function renderFileDiff() {{
  const el = document.getElementById('file-diff-table');
  if (!el) return;
  const files = (chartData.file_diffs || []);
  if (files.length === 0) {{
    el.innerHTML = '<p class="notes">无文件 diff 数据</p>';
    return;
  }}
  let html = '';
  for (const f of files) {{
    html += '<div class="diff-file">';
    html += '<h3>' + f.path + ' ';
    html += '<span class="file-meta">+' + f.added + ' / -' + f.removed + '（' + f.lines + ' 行）</span>';
    html += '</h3>';
    if (f.added === 0 && f.removed === 0) {{
      html += '<p class="notes" style="padding: 0 10px;">文件未变更</p>';
    }} else {{
      html += '<pre>';
      for (const line of f.diff) {{
        let cls = 'context';
        let marker = ' ';
        if (line.added) {{ cls = 'added'; marker = '+'; }}
        else if (line.removed) {{ cls = 'removed'; marker = '-'; }}
        const safe = line.text
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;');
        html += '<div class="diff-line ' + cls + '">';
        html += '<span class="marker">' + marker + '</span>';
        html += safe;
        html += '</div>';
      }}
      html += '</pre>';
    }}
    html += '</div>';
  }}
  el.innerHTML = html;
}}

function renderRadar() {{
  const el = document.getElementById('radar-chart');
  const chart = echarts.init(el);
  const bestRound = chartData.accepted_round;
  // ★ .14 治标: legend.data 与 series.name 必须一致，否则 ECharts 隐藏图例
  const displayNameOf = (r) => (bestRound && r.round_num === bestRound) ? r.label + ' ★' : r.label;

  const legendData = rounds.map(r => {{
    const isBest = bestRound && r.round_num === bestRound;
    return isBest
      ? {{
          name: displayNameOf(r),    // "R3 ★"
          textStyle: {{ color: '#dc2626', fontWeight: 'bold', fontSize: 13 }}
        }}
      : {{ name: displayNameOf(r) }};  // "baseline" / "R1" / "R2"
  }});

  const series = rounds.map((r, idx) => {{
    const isBest = bestRound && r.round_num === bestRound;
    return {{
      name: displayNameOf(r),       // 与 legend.data[i].name 对齐
      type: 'radar',
      data: [{{
        value: dimLabels.map((_, i) => {{
          const k = chartData.dim_keys[i];
          return r.dim_scores[k] || 0;
        }}),
        name: displayNameOf(r)
      }}],
      areaStyle: {{ opacity: isBest ? 0.30 : (idx === 0 ? 0.25 : 0.12) }},
      lineStyle: {{ width: isBest ? 3.5 : (idx === 0 ? 2.5 : 1.8) }},
      itemStyle: isBest ? {{ color: '#ee6666' }} : {{}}
    }};
  }});
  chart.setOption({{
    tooltip: {{ trigger: 'item' }},
    legend: {{
      type: 'scroll',
      top: 0,
      itemWidth: 18, itemHeight: 18, itemGap: 14,
      data: legendData
    }},
    radar: {{
      indicator: dimLabels.map(name => ({{ name, max: 10 }})),
      radius: '65%',
      splitNumber: 5
    }},
    series: series
  }});
  if (bestRound) {{
    const best = rounds.find(r => r.round_num === bestRound);
    if (best) console.info('[skill_optimize_report] 最佳 skill:', best.label, '(分数 ' + best.score.toFixed(2) + ',R3 文字后追加 ★ + 橙色粗体)');
  }}
}}

function renderLine() {{
  // ★ .15 治标: 按用户反馈 — 折线图去掉所有针对"最高分"的特殊样式
  // 不再有：橙色虚线 / 黄底圆角标签 / 蓝色 pin / tooltip ★ 高亮
  // 折线图保持最朴素：1 条蓝色折线 + 4 个数据点 + 默认 tooltip
  const el = document.getElementById('line-chart');
  const chart = echarts.init(el);
  chart.setOption({{
    tooltip: {{ trigger: 'axis' }},
    legend: {{ top: 0 }},
    grid: {{ left: 60, right: 30, top: 60, bottom: 50 }},
    xAxis: {{ type: 'category', data: rounds.map(r => r.label), axisLabel: {{ rotate: 30 }} }},
    yAxis: {{ type: 'value', min: 0, max: 100, name: 'total (百分制)' }},
    series: [{{
      name: '总分',
      type: 'line',
      data: rounds.map(r => r.score),
      smooth: false,
      label: {{ show: true, formatter: '{{c}}' }},
      itemStyle: {{ color: '#3b82f6' }}
      // 不写 markPoint / markLine
    }}]
  }});
}}

function renderFallback() {{
  // 简化：JS 仅在 CDN 失败时重建表格，正常情况由 Python 端静态渲染
  const el = document.getElementById('fallback-table');
  if (!rounds.length) {{ el.innerHTML = '<p>暂无数据</p>'; }}
  // 静态表格已由 _render_fallback_table_static 嵌入，这里无需重复渲染
}}

// 启动渲染（echarts CDN 加载可能异步）
tryRender();
window.addEventListener('load', () => setTimeout(tryRender, 100));
</script>
</body>
</html>
"""


def generate_score_history_html(
    workspace: Path,
    framework_cfg: dict,
    workspace_name: str = "",
    *,
    output_filename: str = "skill_optimize_report.html",
    old_skill_path: Path | None = None,
    new_skill_path: Path | None = None,
) -> HtmlReportResult:
    """.6:生成 skill_optimize_report.html（单文件 echarts 可视化，含 dim 权重显示）。

    Args:
        workspace: 任务 workspace 路径（含 static_history.json）
        framework_cfg: framework YAML 加载结果，用于提取 dim 中文名 + 权重
        workspace_name: 显示名（标题用）
        output_filename: 输出文件名（默认 skill_optimize_report.html）

    Returns:
        HtmlReportResult
    """
    result = HtmlReportResult()
    history = _load_history(workspace)
    if not history:
        result.skipped = True
        result.reason = "static_history.json 不存在或为空"
        logger.warning("HTML 报告跳过：%s", result.reason)
        return result

    rubric_meta = _load_rubric_meta(framework_cfg or {})
    file_diffs = _compute_file_diffs(old_skill_path, new_skill_path) if old_skill_path and new_skill_path else []
    chart_data = _build_echarts_data(history, rubric_meta, file_diffs)
    if not chart_data.get("dim_keys"):
        result.skipped = True
        result.reason = "history 中无 dim_scores"
        return result

    name = workspace_name or workspace.name
    dims_plotted = len(chart_data["dim_keys"])
    html = _build_html(name, chart_data, dims_plotted=dims_plotted)

    output_path = workspace / output_filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")

    result.output_path = str(output_path)
    result.rounds_plotted = len(chart_data["rounds"])
    result.dims_plotted = len(chart_data["dim_keys"])
    logger.info(
        "HTML 报告已生成: %s (rounds=%d dims=%d)",
        output_path, result.rounds_plotted, result.dims_plotted,
    )
    return result