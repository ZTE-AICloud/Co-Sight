"""Skill 重构 diff HTML 报告生成器(极简版)。

复用 scripts/optimizers/static_html_history.py::_compute_file_diffs 产出 diff 数据,
复用 skill_optimize_report.html 的 gerrit 风格 CSS,server-side 渲染成自包含 HTML。

不引 ECharts,纯 HTML + 内联 CSS,offline 环境零依赖。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

# noqa: PLC0415 — 跨模块 import 模块内部函数(_compute_file_diffs)。
# 复用 static_html_history 已有的 diff 计算逻辑(基于 difflib.unified_diff),
# 避免重写 ~140 行 diff 算法。
from optimizers.static_html_history import _compute_file_diffs, _html_escape

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

REPORT_FILENAME = "refactor_diff_report.html"


# CSS 整段抄自 skill_optimize_report.html line 39-60,确保 gerrit 风格色板一致
_DIFF_CSS = """/* gerrit 风格文件 diff:绿=新增 / 红=删除 / 黑白=未改 */
.file-diff-block { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px;
                    padding: 16px; margin-bottom: 24px; }
.file-diff-block .diff-file { margin-top: 12px; }
.file-diff-block .diff-file h3 { font-size: 14px; font-weight: 600;
                               margin: 8px 0 4px; padding: 6px 10px;
                               background: #f3f4f6; border-radius: 4px; }
.file-diff-block .diff-file .file-meta { font-size: 11px; color: #6b7280;
                                        margin-left: 10px; }
.file-diff-block .diff-file pre { margin: 0; padding: 0;
                                  background: #fafafa; border: 1px solid #e5e7eb;
                                  border-radius: 4px; overflow-x: auto; font-size: 12px; }
.file-diff-block .diff-file .diff-line { padding: 2px 10px;
                                          font-family: 'SF Mono', 'Monaco', monospace;
                                          white-space: pre-wrap; word-break: break-all; }
.file-diff-block .diff-line.added { background: #d1fae5; color: #065f46;
                                    border-left: 3px solid #10b981; }
.file-diff-block .diff-line.removed { background: #fee2e2; color: #991b1b;
                                      border-left: 3px solid #ef4444; }
.file-diff-block .diff-line.context { color: #374151; }
.file-diff-block .diff-line .marker { display: inline-block; width: 18px;
                                       color: #6b7280; user-select: none; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       margin: 0; padding: 24px; background: #f9fafb; color: #111827; }
h1 { font-size: 22px; margin: 0 0 8px; color: #1f2937; }
.subtitle { font-size: 12px; color: #6b7280; margin-bottom: 24px; }
.subtitle strong { color: #111827; }"""


def _render_diff_block_static(file_diffs: list[dict]) -> str:
    """把 _compute_file_diffs 输出渲染为 HTML 字符串(server-side)。"""
    if not file_diffs:
        return (
            '<p style="color:#6b7280;">两目录无差异,或所有文件都在过滤列表中。</p>'
        )
    out: list[str] = [
        '<div style="font-size:12px;color:#6b7280;margin-bottom:12px;">'
        '绿=新增 / 红=删除 / 黑白=未改 / <code>+/-/space</code> 标记前缀</div>'
    ]
    for f in file_diffs:
        path = _html_escape(f["path"])
        added = f.get("added", 0)
        removed = f.get("removed", 0)
        total = f.get("lines", 0)
        out.append('<div class="diff-file">')
        out.append(
            f"<h3>{path} "
            f'<span class="file-meta">+{added} / -{removed} (总计 {total} 行)</span></h3>'
        )
        if total == 0 and added == 0 and removed == 0:
            out.append('<p style="color:#6b7280;padding:0 10px;">文件未变更</p>')
        else:
            # .diff-line 之间的 join 用 "" 避免 pre 内空行(块级元素 div 之间的 \n 被浏览器渲染成空行)
            out.append("<pre>")
            line_htmls: list[str] = []
            for line in f.get("diff", []):
                if line.get("added"):
                    cls = "added"
                    marker = "+"
                elif line.get("removed"):
                    cls = "removed"
                    marker = "-"
                else:
                    cls = "context"
                    marker = " "
                text = _html_escape(line.get("text", ""))
                line_htmls.append(
                    f'<div class="diff-line {cls}">'
                    f'<span class="marker">{marker}</span>{text}</div>'
                )
            out.append("".join(line_htmls))
            out.append("</pre>")
        out.append("</div>")
    return "\n".join(out)


def _build_summary(file_diffs: list[dict]) -> str:
    """统计摘要(总增删行、变更文件数),用一行摘要形式注入 subtitle。"""
    total_added = sum(f.get("added", 0) for f in file_diffs)
    total_removed = sum(f.get("removed", 0) for f in file_diffs)
    changed_files = sum(
        1 for f in file_diffs
        if (f.get("added", 0) + f.get("removed", 0)) > 0
        or f.get("lines", 0) > 0
    )
    return (
        f' · 共 <strong>{len(file_diffs)}</strong> 个文件,'
        f'<strong>{changed_files}</strong> 个有变更,'
        f'<strong style="color:#065f46;">+{total_added}</strong> / '
        f'<strong style="color:#991b1b;">-{total_removed}</strong>'
    )


def build_refactor_diff_html(skill_name: str, before_dir: Path, after_dir: Path) -> str:
    """构造完整 refactor_diff_report.html 字符串(不落盘)。"""
    file_diffs = _compute_file_diffs(before_dir, after_dir)
    summary = _build_summary(file_diffs)
    diff_block = _render_diff_block_static(file_diffs)
    timestamp = datetime.now(timezone.utc).isoformat()
    return (
        f'<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n'
        f'<meta charset="UTF-8">\n'
        f'<title>Skill Refactor Diff Report — {_html_escape(skill_name)}</title>\n'
        f'<style>\n{_DIFF_CSS}\n</style>\n</head>\n<body>\n'
        f'<h1>Skill Refactor Diff Report</h1>\n'
        f'<div class="subtitle">Skill: {_html_escape(skill_name)}'
        f'{summary}'
        f' · 生成于 {timestamp} · before_skill/ vs live source</div>\n'
        f'<div class="file-diff-block">\n'
        f'  <div class="chart-title">{_html_escape(skill_name)} '
        f'— before vs after 文件 diff(gerrit 风格)</div>\n'
        f'  {diff_block}\n'
        f'</div>\n</body>\n</html>\n'
    )


def generate_refactor_diff_report(
    workspace: Path,
    before_dir: Path,
    after_dir: Path,
    skill_name: str,
) -> Path:
    """生成 {workspace}/refactor_diff_report.html,返回路径。

    before_dir 与 after_dir 通常:
    - before_dir: workspace/before_skill/{skill_name}  (orchestrator 阶段 1 快照)
    - after_dir:  live skill_root                          (CC Edit 后的源)
    """
    if not before_dir.exists():
        raise FileNotFoundError(f"before_skill/ 快照不存在:{before_dir}")
    if not after_dir.exists():
        raise FileNotFoundError(f"after 目录不存在:{after_dir}")
    html = build_refactor_diff_html(skill_name, before_dir, after_dir)
    out = workspace / REPORT_FILENAME
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    logger.info("生成 refactor diff report:%s", out)
    return out
