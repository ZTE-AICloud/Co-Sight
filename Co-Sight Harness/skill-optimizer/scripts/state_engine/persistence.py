"""
Persistence Layer - 配置和产物持久化
======================================
ConfigStore: config.json 读写
ArtifactStore: 产物目录管理（按轮次组织，产物直接在 workspace 根级别）
ReportBuilder: 通用 Markdown 报告渲染器（避免到处 lines.append 拼字符串）
"""

import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import DEFAULT_TARGET_SCORE


class ReportBuilder:
    """
    通用 Markdown 报告构建器

    用法：
        rb = ReportBuilder("候选 0 生成失败")
        rb.meta("策略", "tier1")
        rb.meta("轮次", 0)
        rb.section("缺口摘要")
        for g in gaps:
            rb.bullet(f"[{g['severity']}] {g['section']}")
        rb.section("可能原因")
        rb.numbered("LLM API 超时", "子进程退出码非零", "...")
        rb.save(path)
    """

    def __init__(self, title: str):
        self._lines: List[str] = [f"# {title}", ""]

    def text(self, content: str):
        """追加原始 Markdown 文本"""
        self._lines.append(content)

    def meta(self, key: str, value: Any):
        """追加键值对：`**key**: value`"""
        self._lines.append(f"- **{key}**: {value}")

    def section(self, title: str, level: int = 2):
        """追加标题（默认 H2）"""
        prefix = "#" * level
        self._lines.extend(["", f"{prefix} {title}", ""])

    def bullet(self, text: str, indent: int = 0):
        """追加无序列表项"""
        pad = "  " * indent
        self._lines.append(f"{pad}- {text}")

    def numbered(self, *items: str, start: int = 1):
        """追加有序列表项"""
        for i, item in enumerate(items, start):
            self._lines.append(f"{i}. {item}")

    def table(self, headers: List[str], rows: List[List[Any]], align: str = ""):
        """
        追加表格

        Args:
            headers: 表头列名
            rows: 数据行列表
            align: 对齐方式（空=居中, :-=左对齐, -:>=右对齐）
        """
        if not headers:
            return
        self._lines.append(f"| {' | '.join(headers)} |")
        sep = []
        for h in headers:
            h_stripped = h.strip()
            if h_stripped.endswith(":"):
                sep.append(":---")
            elif h_stripped.startswith(":"):
                sep.append("---:")
            else:
                sep.append(":---:")
        self._lines.append(f"| {' | '.join(sep)} |")
        for row in rows:
            cells = [str(c) for c in row]
            # 补齐列数
            cells += [""] * (len(headers) - len(cells))
            self._lines.append(f"| {' | '.join(cells)} |")
        self._lines.append("")

    def code_block(self, content: str, lang: str = ""):
        """追加代码块"""
        self._lines.extend(["```" + lang, content, "```", ""])

    def blank(self, n: int = 1):
        """追加空行"""
        self._lines.extend([""] * n)

    def render(self) -> str:
        """渲染为 Markdown 字符串"""
        return "\n".join(self._lines)

    def save(self, path: str):
        """渲染并保存为文件"""
        atomic_write(path, self.render())


class RoundReportBuilder:
    """
    构建合并后的轮次报告 (report.md)，替代原有的 eval_summary.md、
    eval_summary_all.md、per_ran_summary.md、selection.md。

    数据来源:
    - score.json → gaps[], metadata.per_ran[], metadata.rule_scores
    - round_analysis.json → baseline/candidate scores, decision
    """

    _ROOT_CAUSE_KEYWORDS = {
        "terminology": ["术语", "terminology", "命名", "格式不一致", "名称不一致"],
        "missing": ["缺失", "missing", "未生成", "为空", "未产出", "没有生成"],
    }

    def __init__(self, round_num: int):
        self.round_num = round_num
        self.rb = ReportBuilder(f"Round {round_num} 评测报告")
        self.rb.meta("生成时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.rb.blank()

    # ── Section 1: 分数摘要 ──────────────────────────

    def add_score_summary(self, baseline_score, baseline_runs, baseline_std,
                          candidates, best_candidate=None):
        self.rb.section("分数摘要")
        headers = ["对象", "平均分", "标准差", "各次得分", "状态"]
        rows = [
            ["基线", f"{baseline_score:.2f}",
             f"{baseline_std:.2f}" if baseline_std > 0 else "—",
             ", ".join(f"{s:.2f}" for s in baseline_runs) if baseline_runs else "—",
             "基线"]
        ]
        for c in candidates:
            diff = c["score"] - baseline_score
            status = f"优于基线 (+{diff:.2f})" if diff > 0 else "低于基线"
            runs = ", ".join(f"{s:.2f}" for s in c.get("run_scores", []))
            rows.append([
                f"候选 c{c['id']} ({c.get('strategy', '?')})",
                f"{c['score']:.2f}",
                f"{c.get('stddev', 0):.2f}",
                runs if runs else "—",
                status,
            ])
        self.rb.table(headers, rows)
        self.rb.blank()

        if best_candidate and best_candidate.get("score", 0) > baseline_score:
            self.rb.bullet(
                f"**最佳候选**: c{best_candidate['id']} "
                f"({best_candidate.get('strategy', '?')}) = "
                f"{best_candidate['score']:.2f} "
                f"({best_candidate['score'] - baseline_score:+.2f} vs 基线)"
            )
        else:
            self.rb.bullet("**无候选优于基线，保留旧基线**")
        self.rb.blank()

    # ── Section 2: 缺口根因分析 ──────────────────────

    def add_gap_root_cause_analysis(self, score_data: Dict):
        gaps = score_data.get("gaps", [])
        per_ran = score_data.get("metadata", {}).get("per_ran", [])
        if not gaps:
            self.rb.bullet("无缺口")
            self.rb.blank()
            return

        # 2.1 概览表 — 按 ran_id 聚合
        self.rb.section("缺口根因分析")
        self.rb.section("缺口概览", level=3)

        ran_gap_map: Dict[str, list] = {}
        for g in gaps:
            rid = g.get("ran_id", "UNKNOWN")
            ran_gap_map.setdefault(rid, []).append(g)

        f1_map = {r.get("ran_id", "?"): r.get("f1", 0) for r in per_ran}
        sev_order = {"critical": 0, "high": 1, "medium": 2, "warning": 3, "low": 4, "info": 5}

        headers = ["RAN ID", "F1", "缺口数", "最严重等级", "主要问题类型"]
        rows = []
        for rid, rgaps in ran_gap_map.items():
            severities = [g.get("severity", "unknown") for g in rgaps]
            types = set(g.get("type", "") for g in rgaps)
            max_sev = min(severities, key=lambda s: sev_order.get(s, 99))
            rows.append([
                rid,
                f"{f1_map.get(rid, 0):.2f}",
                str(len(rgaps)),
                max_sev.upper(),
                ", ".join(sorted(types))[:40],
            ])
        self.rb.table(headers, rows)
        self.rb.blank()

        # 2.2 详细根因
        self.rb.section("详细根因", level=3)
        sorted_gaps = sorted(gaps, key=lambda g: (
            sev_order.get(g.get("severity", ""), 99),
            g.get("f1") or 999
        ))

        for g in sorted_gaps:
            if g.get("severity") == "info":
                continue
            self.rb.section(
                f"[{g.get('severity', '?').upper()}] {g.get('type', '?')} "
                f"@ {g.get('ran_id', '?')} — F1={g.get('f1', 0):.2f}",
                level=4
            )
            root_cause = g.get("root_cause", g.get("message", "未提供"))
            self.rb.bullet(f"**根因**: {root_cause}")
            self.rb.blank()

            # 差异详情
            details = g.get("details", [])
            if isinstance(details, list):
                for d in details:
                    if isinstance(d, dict):
                        self._print_diff_items(d)
            elif isinstance(details, dict):
                self._print_diff_items(details)
            self.rb.blank()

            fix = g.get("fix_suggestion", "无")
            self.rb.bullet(f"**改进建议**: {fix}")
            self.rb.blank()

        # 2.3-2.5 分类根因
        self._add_root_cause_categories(sorted_gaps)

    def _print_diff_items(self, detail: dict):
        """打印 r_only/c_only 差异项"""
        r_only = detail.get("r_only", [])
        c_only = detail.get("c_only", [])
        if r_only:
            items = [str(x) for x in r_only[:10]]
            suffix = f" ... (+{len(r_only) - 10})" if len(r_only) > 10 else ""
            self.rb.bullet(
                f"Gold 有但候选缺失 (r_only, {len(r_only)}项): "
                + ", ".join(items) + suffix
            )
        if c_only:
            items = [str(x) for x in c_only[:10]]
            suffix = f" ... (+{len(c_only) - 10})" if len(c_only) > 10 else ""
            self.rb.bullet(
                f"候选多余产出 (c_only, {len(c_only)}项): "
                + ", ".join(items) + suffix
            )
        diffs = detail.get("differences", "")
        if diffs:
            self.rb.bullet(f"字段差异: {str(diffs)[:200]}")

    def _add_root_cause_categories(self, gaps: list):
        """Section 2.3-2.5: 按关键词分类根因"""
        terminology = []
        missing_materials = []
        other = []
        for g in gaps:
            if g.get("severity") == "info":
                continue
            rc = (g.get("root_cause", "") + " " + g.get("message", "")).lower()
            if any(kw in rc for kw in self._ROOT_CAUSE_KEYWORDS["terminology"]):
                terminology.append(g)
            elif any(kw in rc for kw in self._ROOT_CAUSE_KEYWORDS["missing"]):
                missing_materials.append(g)
            else:
                other.append(g)

        if terminology:
            self.rb.section("术语差异导致的误判", level=3)
            for g in terminology:
                self.rb.bullet(
                    f"[{g.get('ran_id', '?')}] {g.get('type', '?')}: "
                    f"{g.get('root_cause', g.get('message', ''))[:150]}"
                )
            self.rb.blank()

        if missing_materials:
            self.rb.section("材料缺失导致的不完整输出", level=3)
            for g in missing_materials:
                self.rb.bullet(
                    f"[{g.get('ran_id', '?')}] {g.get('type', '?')}: "
                    f"{g.get('root_cause', g.get('message', ''))[:150]}"
                )
            self.rb.blank()

        if other:
            self.rb.section("其他根因", level=3)
            for g in other:
                self.rb.bullet(
                    f"[{g.get('severity', '?').upper()}] [{g.get('ran_id', '?')}] "
                    f"{g.get('type', '?')}: {g.get('root_cause', g.get('message', ''))[:150]}"
                )
            self.rb.blank()

    # ── Section 3: 日志与轨迹引用 ────────────────────

    def add_per_case_matrix(self, candidates):
        """
        追加 per-case 分数矩阵：每个候选 × 每个 CASE 在各 run 的分数
        数据来源：candidate_K_score.json 的 runs[].result_score_per_case
        """
        if not candidates:
            return
        # 收集所有 case_id
        case_ids = []
        for c in candidates:
            per_case_data = c.get("per_case") or {}
            for cid in per_case_data.keys():
                if cid not in case_ids:
                    case_ids.append(cid)
        if not case_ids:
            return
        self.rb.section("各 CASE 明细")
        headers = ["候选"] + case_ids
        rows = []
        for c in candidates:
            per_case_data = c.get("per_case") or {}
            row = [f"c{c.get('id', '?')} ({c.get('strategy', '?')}) avg={c.get('score', 0):.2f}"]
            for cid in case_ids:
                vals = per_case_data.get(cid, [])
                if not vals:
                    row.append("—")
                else:
                    row.append(" / ".join(f"{v:.1f}" for v in vals))
            rows.append(row)
        self.rb.table(headers, rows)
        self.rb.blank()

    def add_modifications_summary(self, modifications_summary: list):
        """
        追加本轮 modifications 摘要（baseline proposal → 各 Skill 的修改清单）。
        数据来源：history_entry.modifications_summary（来自 _parse_proposal_modifications_summary）
        """
        if not modifications_summary:
            return
        self.rb.section("本轮优化提案清单")
        for m in modifications_summary:
            idx = m.get("index", "?")
            action = m.get("action", "MODIFY")
            file = m.get("file", "?")
            section = m.get("section", "?")
            reason = m.get("reason", "")
            self.rb.bullet(
                f"**[{idx}] {action}** `{file}` → `{section}`"
            )
            if reason:
                self.rb.bullet(f"  理由: {reason}", indent=1)
        self.rb.blank()

    def add_log_references(self, round_num: int):
        self.rb.section("日志与轨迹引用")
        self.rb.table(
            ["数据", "路径"],
            [
                ["完整评分", f"round_{round_num}/score.json"],
                ["基线历史", "baseline/score_baseline.json"],
                ["结构化分析", f"round_{round_num}/round_analysis.json"],
                ["基线评测明细", "baseline/run_N/score.json"],
                ["候选评测明细", f"round_{round_num}/candidate_K/run_N/score.json"],
                ["执行轨迹", "data/**/trace.jsonl（由评测管道决定具体路径）"],
            ]
        )
        self.rb.blank()

    # ── Section 4: 选择决策 ──────────────────────────

    def add_selection_decision(self, baseline_score, best_candidate=None,
                               all_candidates=None,
                               current_best=None,
                               decision=None):
        """
        选择决策章节。

        Args:
            baseline_score: 原始基线分数（展示用）
            best_candidate: 最佳候选 dict
            all_candidates: 所有候选 list
            current_best: running max 基线（eng.best_score 本轮之前的快照）
            decision: 来自 history_entry.decision（"adopted" 或 "not_adopted"）
        """
        all_candidates = all_candidates or []
        self.rb.section("选择决策")

        # decision 是 running max 比较的最终结论（与 history_entry.decision 一致）
        adopted = decision == "adopted"
        compare_against = current_best if current_best is not None else baseline_score

        if adopted and best_candidate:
            self.rb.bullet(
                f"**选择结果**: 采用候选 c{best_candidate['id']} "
                f"({best_candidate.get('strategy', '?')})"
            )
            delta = best_candidate['score'] - compare_against
            target_label = "当前最佳" if current_best is not None else "基线"
            self.rb.bullet(
                f"**决策依据**: 平均分 {best_candidate['score']:.2f} "
                f"优于 {target_label} {compare_against:.2f} "
                f"({delta:+.2f})"
            )
        else:
            self.rb.bullet(f"**选择结果**: 保留当前最佳（{compare_against:.2f}）")
            if best_candidate:
                target_label = "当前最佳" if current_best is not None else "基线"
                self.rb.bullet(
                    f"**决策依据**: 最佳候选 c{best_candidate['id']} 分数 "
                    f"{best_candidate['score']:.2f} "
                    f"<= {target_label} {compare_against:.2f}"
                )
        self.rb.blank()

        if all_candidates:
            self.rb.table(
                ["候选", "分数", "vs 基线", "稳定性", "决策"],
                [
                    [
                        f"c{c['id']} ({c.get('strategy', '?')})",
                        f"{c['score']:.2f}",
                        f"{c['score'] - baseline_score:+.2f}",
                        f"σ={c.get('stddev', 0):.2f}",
                        "选中" if (adopted and best_candidate and c["id"] == best_candidate["id"])
                        else "未采用",
                    ]
                    for c in all_candidates
                ]
            )
            self.rb.blank()

    # ── Section 5: 改进建议汇总 ──────────────────────

    def add_improvement_summary(self, score_data: Dict):
        gaps = score_data.get("gaps", [])
        actionable = [g for g in gaps if g.get("severity") not in ("info",)]
        if not actionable:
            return

        self.rb.section("改进建议汇总")
        sev_priority = {
            "critical": "P0", "high": "P1", "warning": "P2",
            "medium": "P2", "low": "P3"
        }
        self.rb.table(
            ["优先级", "RAN ID", "问题类型", "修复建议"],
            [
                [
                    sev_priority.get(g.get("severity", ""), "P?"),
                    g.get("ran_id", "?"),
                    g.get("type", "?"),
                    g.get("fix_suggestion", g.get("message", ""))[:100],
                ]
                for g in actionable
            ]
        )
        self.rb.blank()

    # ── Save ─────────────────────────────────────────

    def render(self) -> str:
        """渲染为 Markdown 字符串"""
        return self.rb.render()

    def save(self, artifact_store, round_num: int) -> str:
        """写 round 报告到 round_N_report.md。

        artifact_store 兼容两种形态：
        - FileSystemArtifactStore（有 round_dir(round_num) 方法 + workspace 路径）
        - 任意带 .workspace: Path 属性的对象
        """
        if hasattr(artifact_store, "round_dir"):
            round_dir = artifact_store.round_dir(round_num)
        else:
            workspace = getattr(artifact_store, "workspace", None)
            if workspace is None:
                raise AttributeError("artifact_store 必须有 round_dir 方法或 workspace 属性")
            round_dir = Path(workspace) / f"round_{round_num}"
        ensure_dir(str(round_dir))
        out_path = round_dir / f"round_{round_num}_report.md"
        out_path.write_text(self.render(), encoding="utf-8")
        return str(out_path)


def ensure_dir(path: str) -> str:
    """确保目录存在"""
    os.makedirs(path, exist_ok=True)
    return path


def atomic_write(path: str, content: str, encoding: str = "utf-8"):
    """原子写入：tempfile + os.replace"""
    abs_path = os.path.abspath(path)
    parent = os.path.dirname(abs_path) or "."
    ensure_dir(parent)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, abs_path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def load_json(path: str) -> Dict[str, Any]:
    """加载 JSON 文件"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, obj: Dict[str, Any]):
    """保存 JSON 文件"""
    atomic_write(path, json.dumps(obj, ensure_ascii=False, indent=2))


def read_skill_directory(skill_path: str) -> dict:
    """
    读取完整 skill 目录结构，供优化器了解多文件 skill

    Args:
        skill_path: SKILL.md 文件路径

    Returns:
        {
            "skill_md": "SKILL.md 完整内容",
            "references": {"相对路径": "内容", ...},
            "scripts": {"相对路径": "内容（截断至200行）", ...},
            "prompts": {"相对路径": "内容", ...},
            "agents": {"相对路径": "内容", ...},
            "structure_summary": "可读的目录结构摘要",
            "file_list": ["SKILL.md", "references/foo.md", ...],
            "total_size_bytes": 12345,
        }
    """
    skill_dir = os.path.dirname(os.path.abspath(skill_path))
    result = {
        "skill_md": "",
        "references": {},
        "scripts": {},
        "prompts": {},
        "agents": {},
        "structure_summary": "",
        "file_list": [],
        "total_size_bytes": 0,
    }

    # 读取 SKILL.md
    with open(skill_path, "r", encoding="utf-8") as f:
        result["skill_md"] = f.read()

    # 遍历子目录
    for root, dirs, files in os.walk(skill_dir):
        rel_root = os.path.relpath(root, skill_dir)
        if rel_root == ".":
            continue
        for fname in files:
            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, skill_dir)
            result["file_list"].append(rel_path)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                content = "[二进制或不可读]"

            category = rel_root.split(os.sep)[0]
            # 脚本文件截断以控制 token 用量
            if fname.endswith((".py", ".sh")) or category == "scripts":
                lines = content.splitlines()
                if len(lines) > 200:
                    content = "\n".join(lines[:200]) + f"\n# ... 截断（共 {len(lines)} 行，省略 {len(lines) - 200} 行）"
            if category in result:
                result[category][rel_path] = content
            result["total_size_bytes"] += len(content.encode("utf-8"))

    # 构建可读的结构摘要
    result["structure_summary"] = _build_structure_summary(result)
    return result


def _build_structure_summary(dir_info: dict) -> str:
    """构建 skill 目录结构的可读摘要"""
    lines = [f"- SKILL.md: {len(dir_info['skill_md'])} 字符"]
    categories = [
        ("references/", "references"),
        ("scripts/", "scripts"),
        ("prompts/", "prompts"),
        ("agents/", "agents"),
    ]
    for label, key in categories:
        if dir_info[key]:
            lines.append(f"- {label}: {len(dir_info[key])} 个文件")
            for path, content in sorted(dir_info[key].items()):
                lines.append(f"  - {path} ({len(content)} 字符)")
    has_extra = any(dir_info[k] for _, k in categories)
    if not has_extra:
        lines.append("- (无子目录，仅 SKILL.md)")
    return "\n".join(lines)


class ConfigStore:
    """
    config.json 管理器

    数据结构：
    {
        "target_skills": [
            {"name": "...", "original_path": "...", "workspace_path": "..."}
        ],
        "max_rounds": 5,
        "project_root": "...",
        "created_at": "...",
        "current_round": 1,
        "current_score": 0.0,
        "status": "init_complete",
        "history": [
            {"round": 1, "score": 72.5, "rating": "FAIR", ...}
        ]
    }

    目标分数硬编码为 DEFAULT_TARGET_SCORE（100），不再写入 config.json。
    旧 config 中的 target_score 字段在读取时仍以 100 兜底，保持向后兼容。
    """

    # 终止状态列表
    TERMINAL_STATES = {"achieved", "max_rounds", "manual_stop"}

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.config_path = workspace / "config.json"
        self._config: Optional[Dict] = None

    def exists(self) -> bool:
        """检查 config.json 是否存在"""
        return self.config_path.exists()

    def load(self) -> Optional[Dict[str, Any]]:
        """加载配置，不存在返回 None"""
        if not self.exists():
            return None
        self._config = load_json(str(self.config_path))
        return self._config

    def save(self, config: Dict[str, Any]):
        """保存配置"""
        # 🆕 2026-08:expert_guidance 支持任务中编辑 —— 保留 config.json 文件里用户手动改的值。
        # 启动时 CLI 写入初始值;用户中途编辑 config.json 的 expert_guidance,下轮 ProposalAgent 读到新值引导方向。
        # 不覆盖文件里的 expert_guidance(用户编辑优先),避免 save 用内存旧值冲掉任务中修改。
        if self.config_path.exists():
            try:
                _existing = load_json(str(self.config_path))
                if isinstance(_existing, dict) and "expert_guidance" in _existing:
                    config["expert_guidance"] = _existing["expert_guidance"]
            except Exception:
                pass
        self._config = config
        save_json(str(self.config_path), config)

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值"""
        if self._config is None:
            self.load()
        return self._config.get(key, default) if self._config else default

    @property
    def config(self) -> Optional[Dict]:
        return self._config

    def is_terminal(self) -> bool:
        """检查是否处于终止状态"""
        status = self.get("status", "")
        return status in self.TERMINAL_STATES

    def get_current_round(self) -> int:
        """获取当前轮次"""
        return self.get("current_round", 1)

    def get_history(self) -> List[Dict]:
        """获取评测历史"""
        return self.get("history", [])

    def update_round(self, round_num: int, score: float, rating: str,
                      total_gaps: int, snapshot: str):
        """[已弃用] 更新轮次记录(已迁移到 PhaseTracker)

        实时分/状态/历史不再写入 config.json,统一由 PhaseTracker 管理(task_state.json)。
        此方法保留仅为兼容外部直接调用,实际写入已跳过。调用方应改用 StateEngine
        提供的 end_round / update_after_evaluation / record_current_progress API。
        """
        # 已弃用:不再写入 config.json,改走 task_state.json
        # 保留方法签名以便外部工具检测调用并发出弃用警告

    def update_status(self, status: str):
        """[已弃用] 更新状态(已迁移到 PhaseTracker)

        状态不再写入 config.json,统一由 PhaseTracker 管理(task_state.json)。
        此方法保留仅为兼容外部直接调用,实际写入已跳过。
        """
        # 已弃用:不再写入 config.json,改走 task_state.json


class ArtifactStore:
    """
    产物目录管理器（按轮次组织，产物直接在 workspace 根级别）

    目录结构：
    workspace/
    ├── baseline/
    │   ├── run_1/
    │   ├── run_2/
    │   └── score_baseline.json
    ├── round_1/
    │   ├── report.md
    │   ├── score.json
    │   ├── round_N_before_skill/  ← 优化前完整 skill 目录拷贝
    │   ├── proposal.md        ← 优化提案（merge 前原始内容）
    │   └── candidate_K/
    │       └── run_M/
    ├── round_2/ ...
    ├── score_history.md
    └── overview_report.md
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        ensure_dir(str(self.workspace))

    # ── 内部辅助 ──────────────────────────────────────

    def _round_dir(self, round_num: int) -> Path:
        """轮次目录路径"""
        return self.workspace / f"round_{round_num}"

    def _ensure_round_dir(self, round_num: int) -> Path:
        """确保轮次目录存在"""
        d = self._round_dir(round_num)
        ensure_dir(str(d))
        return d

    # ── 快照 ──────────────────────────────────────────

    def save_skill_snapshot(self, skill_dir: Path, round_num: int):
        """
        保存本轮起始基线 skill 目录快照到 round_N_before_skill/
        应在每轮评测开始前调用（before = round 起始时的 skill）。
        统一目录：round_N_before_skill/skill/{name}/
        """
        dest_dir = self._ensure_round_dir(round_num) / f"round_{round_num}_before_skill" / "skill"
        if dest_dir.exists():
            shutil.rmtree(str(dest_dir))
        dest_dir.parent.mkdir(parents=True, exist_ok=True)
        if skill_dir.exists():
            shutil.copytree(str(skill_dir), str(dest_dir))

    # ── 评分 ──────────────────────────────────────────

    def save_score(self, score_data: Dict, round_num: int):
        """保存评分 JSON"""
        path = self._ensure_round_dir(round_num) / "score.json"
        save_json(str(path), score_data)

    # ── 优化提案 ──────────────────────────────────────

    def save_proposal(self, content: str, round_num: int,
                       skill_name: Optional[str] = None,
                       candidate_id: Optional[int] = None):
        """
        保存 merge 前的优化提案原始内容

        Args:
            content: 提案文本（.proposed 原始内容）
            round_num: 轮次编号
            skill_name: Skill 名称（多 Skill 模式下传入，按 Skill 拆分）
            candidate_id: 候选 ID（agent 模式 + round 阶段传入，按候选拆分）

        路径优先级：
            1. round_N/candidate_{K}/proposal_{SkillName}.md
               （agent 模式 + round 阶段，每个候选每个 Skill 独立）
            2. round_N/proposal_{SkillName}.md
               （多 Skill 无候选场景）
            3. round_N/proposal.md
               （单 Skill 模式，向后兼容）
        """
        round_dir = self._ensure_round_dir(round_num)
        if candidate_id is not None and candidate_id >= 0 and skill_name:
            target_dir = round_dir / f"candidate_{candidate_id}"
            target_dir.mkdir(parents=True, exist_ok=True)
            path = target_dir / f"proposal_{skill_name}.md"
        elif skill_name:
            path = round_dir / f"proposal_{skill_name}.md"
        else:
            path = round_dir / "proposal.md"
        atomic_write(str(path), content)

    # ── 候选管理 ──────────────────────────────────────

    def _candidate_dir(self, candidate_id: int, round_num: int) -> Path:
        """候选目录: round_N/candidate_K/"""
        return self._ensure_round_dir(round_num) / f"candidate_{candidate_id}"

    def save_candidate_snapshot(self, candidate_id: int, skill_dir: Path, round_num: int):
        """
        保存候选 skill 快照到 round_N/candidate_K/skill/（统一目录结构）

        Args:
            candidate_id: 候选 ID
            skill_dir: skill 目录路径
            round_num: 轮次编号
        """
        dest = self._candidate_dir(candidate_id, round_num) / "skill"
        # 源和目标相同时跳过（避免 rmtree 后源丢失）
        if skill_dir.resolve() == dest.resolve():
            return
        if dest.exists():
            shutil.rmtree(str(dest))
        if skill_dir.exists():
            shutil.copytree(str(skill_dir), str(dest),
                           ignore=lambda d, f: [x for x in f if x.endswith(".proposed")])

    def save_candidate_score(self, candidate_id: int, score_data: Dict, round_num: int):
        """保存候选评测结果到 round_N/candidate_K/score_candidate.json"""
        path = self._candidate_dir(candidate_id, round_num) / "score_candidate.json"
        save_json(str(path), score_data)

    def save_candidates_manifest(self, manifest: List[Dict], round_num: int):
        """
        保存候选清单到 round_N/candidates_manifest.json

        Args:
            manifest: [{"id": 1, "strategy": "tier1", "score": 82.3, "stddev": 0.0,
                        "better_than_baseline": True, "based_on": "baseline|candidate_K", ...}, ...]
            round_num: 轮次编号
        """
        path = self._ensure_round_dir(round_num) / "candidates_manifest.json"
        save_json(str(path), manifest)

    def save_best_candidate_marker(self, candidate_id: int, score: float,
                                    strategy: str, better_than_baseline: bool,
                                    baseline_score: float, round_num: int):
        """
        保存最佳候选标记到 round_N/best_candidate.json

        作用：持久化记录本轮最佳候选，中断后可恢复，候选生成时可查询。
        """
        path = self._ensure_round_dir(round_num) / "best_candidate.json"
        save_json(str(path), {
            "candidate_id": candidate_id,
            "score": score,
            "strategy": strategy,
            "better_than_baseline": better_than_baseline,
            "baseline_score": baseline_score,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

    def save_baseline_score(self, score_data: Dict, round_num: int):
        """保存基线评测分数到 baseline/score_baseline.json（与round_N平级）"""
        base = self.workspace / "baseline"
        ensure_dir(str(base))
        path = base / "score_baseline.json"
        save_json(str(path), score_data)
        # 同时从最后一次 run 的 score.json 提取 per_ran 和 rule_scores 放入 score_baseline.json（供 overview 展示）
        last_run_path = base / f"run_{len(score_data.get('run_scores', [1]))}" / "score.json"
        if not last_run_path.exists():
            last_run_path = base / "run_1" / "score.json"
        if last_run_path.exists():
            try:
                last_run = load_json(str(last_run_path))
                per_ran = last_run.get("metadata", {}).get("per_ran", [])
                rule_scores = last_run.get("metadata", {}).get("rule_scores", [])
                if per_ran or rule_scores:
                    base_score = load_json(str(path))
                    if per_ran:
                        base_score.setdefault("metadata", {})["per_ran"] = per_ran
                    if rule_scores:
                        base_score.setdefault("metadata", {})["rule_scores"] = rule_scores
                    save_json(str(path), base_score)
            except Exception:
                pass

    def archive_eval_run_data(self, eval_run: int, round_num: int,
                              is_baseline: bool, candidate_id: Optional[int] = None):
        """
        确保评测产物 data/ 存在于正确的 run 目录下。
        不再写入 score.json 或 report.md。

        评测器（WorkflowPipelineExecutor._archive_inline_artifacts）已经将
        data/ 内容拷贝到此目录。此方法仅做目录验证。
        """
        if is_baseline:
            run_dir = self.workspace / "baseline" / f"run_{eval_run}"
        elif candidate_id is not None:
            run_dir = self._candidate_eval_run_dir(candidate_id, eval_run, round_num)
        else:
            run_dir = self._ensure_round_dir(round_num)
        ensure_dir(str(run_dir))
        # data/ 已由 evaluator 归档，无需额外操作

    def save_baseline_eval_run(self, eval_run: int, score_data: Dict, round_num: int):
        """已废弃：改为调用 archive_eval_run_data（仅归档数据，不写 score.json/report.md）。"""
        self.archive_eval_run_data(eval_run, round_num, is_baseline=True)

    def _candidate_eval_run_dir(self, candidate_id: int, eval_run: int, round_num: int) -> Path:
        """单次评测目录: round_N/candidate_K/run_L/"""
        cand_dir = self._candidate_dir(candidate_id, round_num)
        run_dir = cand_dir / f"run_{eval_run}"
        ensure_dir(str(run_dir))
        return run_dir

    def save_candidate_eval_run(self, candidate_id: int, eval_run: int,
                                score_data: Dict, round_num: int):
        """已废弃：改为调用 archive_eval_run_data（仅归档数据，不写 score.json/report.md）。"""
        self.archive_eval_run_data(eval_run, round_num, is_baseline=False, candidate_id=candidate_id)

    # ── 全局总览报告 ──────────────────────────────────

    def save_overview_report(self, workspace: Path):
        """
        生成全局总览报告 overview_report.md，包含分数趋势、误差根源 Top-N、各 RAN 表现。

        Args:
            workspace: 工作区根目录
        """

        config_path = workspace / "config.json"
        config = {}
        if config_path.exists():
            try:
                config = load_json(str(config_path))
            except Exception:
                pass

        history = config.get("history", [])
        target_score = config.get("target_score", DEFAULT_TARGET_SCORE)
        max_rounds = config.get("max_rounds", 5)
        status = config.get("status", "unknown")
        target_skills = config.get("target_skills", [])
        if target_skills:
            skill_names = "、".join(ts["name"] for ts in target_skills)
        else:
            skill_names = "unknown"

        rb = ReportBuilder("评测-优化循环 总览")
        rb.section("任务概览")
        rb.meta("目标 Skill", skill_names)
        rb.meta("目标分数", target_score)
        rb.meta("最大轮次", max_rounds)
        rb.meta("已完成轮次", len(history))
        rb.meta("当前状态", status)
        rb.blank()

        # 分数趋势
        rb.section("分数趋势")
        rb.table(
            ["轮次", "分数", "评级", "缺口数", "时间"],
            [
                [f"R{h['round']}",
                 f"{h['score']:.2f}",
                 h.get("rating", "—"),
                 str(h.get("total_gaps", "—")),
                 h.get("timestamp", "—")]
                for h in history
            ]
        )
        rb.blank()

        # 候选表现（从 candidate_pool 读取）
        candidate_pool = config.get("candidate_pool", {})
        if candidate_pool:
            rb.section("候选表现")
            for rk, cs in candidate_pool.items():
                rb.bullet(f"**Round {rk}**: {len(cs)} 个候选")
                headers = ["候选", "策略", "分数", "标准差", "各次得分"]
                rows = []
                for c in cs:
                    runs = ", ".join(f"{s:.2f}" for s in c.get("run_scores", []))
                    rows.append([
                        f"c{c['id']}",
                        c.get("strategy", "?"),
                        f"{c['score']:.2f}",
                        f"{c.get('stddev', 0):.2f}",
                        runs if runs else "—",
                    ])
                rb.table(headers, rows)
            rb.blank()

        # 误差根源 Top-5（从各轮 gaps 聚合，按 severity 排序）
        all_gaps = []
        for h in history:
            round_num = h["round"]
            score_path = workspace / f"round_{round_num}" / "score.json"
            if score_path.exists():
                try:
                    sd = load_json(str(score_path))
                    for g in sd.get("gaps", []):
                        sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
                        ran_id_val = g.get("ran_id")
                        all_gaps.append({
                            "round": round_num,
                            "ran_id": ran_id_val if ran_id_val else "N/A",
                            "severity": g.get("severity", "unknown"),
                            "type": g.get("type", "—"),
                            "f1": g.get("f1"),
                            "message": g.get("message", g.get("root_cause", ""))[:150],
                            "_sev": sev_order.get(g.get("severity", ""), 99),
                        })
                except Exception:
                    pass

        all_gaps.sort(key=lambda x: (x["_sev"], x.get("f1") or 999))
        top_gaps = all_gaps[:5]

        if top_gaps:
            rb.section("误差根源 Top-5")
            rb.table(
                ["排名", "轮次", "RAN ID", "类型", "F1", "根因摘要"],
                [
                    [i + 1,
                     f"R{g['round']}",
                     g["ran_id"],
                     g["type"],
                     f"{g['f1']:.2f}" if g["f1"] is not None else "—",
                     g["message"][:60]]
                    for i, g in enumerate(top_gaps)
                ]
            )
            rb.blank()

        # 各 RAN 最终表现（从**最佳轮次**的 score.json 取，而非最后一轮）
        best_round_num = config.get("best_round", None)
        if best_round_num is not None and history:
            best_score_path = workspace / f"round_{best_round_num}" / "score.json"
        elif history:
            last_round = history[-1]["round"]
            best_score_path = workspace / f"round_{last_round}" / "score.json"
        else:
            best_score_path = None

        if best_score_path and best_score_path.exists():
            try:
                last_sd = load_json(str(best_score_path))
                per_ran = last_sd.get("metadata", {}).get("per_ran", [])
                if per_ran:
                    rb.section("各 RAN 最终表现")
                    rb.table(
                        ["RAN ID", "F1", "召回率", "精确率", "趋势"],
                        [
                            [
                                r.get("ran_id", "?"),
                                f"{r['f1']:.2f}" if r.get("f1") is not None else "—",
                                f"{r['recall']:.2f}" if r.get("recall") is not None else "—",
                                f"{r['precision']:.2f}" if r.get("precision") is not None else "—",
                                "↑" if r.get("f1", 0) >= target_score * 0.6 else "↓",
                            ]
                            for r in per_ran
                        ]
                    )
                    rb.blank()
            except Exception:
                pass

        # 轮次产物索引
        rb.section("产物索引")
        rb.table(
            ["轮次", "评测报告", "评分数据", "优化提案", "结构化分析"],
            [
                [
                    f"R{h['round']}",
                    f"round_{h['round']}/round_{h['round']}_score_analysis.md",
                    f"round_{h['round']}/round_{h['round']}_score.json",
                    f"round_{h['round']}/proposal.md",
                    f"round_{h['round']}/round_analysis.json",
                ]
                for h in history
            ]
        )

        path = self.workspace / "overview_report.md"
        atomic_write(str(path), rb.render())

        # 生成 score_history.md（趋势图 + 详细数据表）
        self._save_score_history(workspace, config)

        return str(path)

    def _save_score_history(self, workspace: Path, config: Dict):
        """
        生成 score_history.md，包含完整分数明细（不包含 ASCII 趋势图,2026-06-18 起）。
        写入 workspace/score_history.md
        """
        history = config.get("history", [])
        if not history:
            return

        target_score = config.get("target_score", DEFAULT_TARGET_SCORE)
        candidate_pool = config.get("candidate_pool", {})

        rb = ReportBuilder("分数历史")
        rb.blank()

        # ── Section 1: ASCII 趋势图 ────────────────────
        rb.section("分数趋势")
        rb.blank()

        # 计算分数范围
        all_scores = [h["score"] for h in history] + [target_score]
        min_s = max(0, int(min(all_scores)) - 5)
        max_s = int(max(all_scores)) + 5
        chart_height = 10
        score_range = max_s - min_s or 1

        # 构建图表
        chart_lines = []
        chart_lines.append(f"  {max_s:>5.0f} |")
        for row in range(chart_height, 0, -1):
            threshold = min_s + (score_range * row / chart_height)
            line = f"  {threshold:>5.0f} |"
            for h in history:
                s = h["score"]
                if s >= threshold:
                    line += "  *"
                else:
                    line += "   "
            chart_lines.append(line)
        baseline_label = f"  {min_s:>5.0f} |"
        chart_lines.append(baseline_label)

        # 底部标签
        footer = "       +"
        for h in history:
            label = str(h["round"])[:6]
            footer += label.center(4)
        chart_lines.append(footer)

        # 标记线
        target_row = f"  {target_score:>5.0f} | ← 目标分数"
        chart_lines.insert(0, target_row)

        rb.code_block("\n".join(chart_lines), "text")
        rb.blank()

        # ── Section 2: 详细分数表 ─────────────────────
        rb.section("分数明细")

        # 判断是否有指标数据
        metrics_history = config.get("metrics_history", [])
        has_metrics = bool(metrics_history)

        if has_metrics:
            headers = ["轮次", "平均分", "复合分", "耗时(s)", "评级", "缺口数", "vs 基线"]
        else:
            headers = ["轮次", "平均分", "各次得分", "评级", "缺口数", "vs 基线"]

        bl_score = next((h["score"] for h in history if h.get("round") == "baseline"), None)
        rows = []
        for h in history:
            rn = h["round"]
            score = h["score"]
            rating = h.get("rating", "—")
            gaps = h.get("total_gaps", "—")
            if bl_score is not None and rn != "baseline":
                diff = score - bl_score
                vs_bl = f"+{diff:.2f}" if diff > 0 else f"{diff:.2f}"
            else:
                vs_bl = "—"

            if has_metrics:
                m = next((m for m in metrics_history if m.get("round") == rn), {})
                composite = m.get("composite_score", "—")
                composite_str = f"{composite:.2f}" if isinstance(composite, (int, float)) else "—"
                duration = m.get("total_duration_seconds", m.get("duration_seconds"))
                dur_str = f"{duration:.1f}" if duration is not None else "—"
                rows.append([rn, f"{score:.2f}", composite_str, dur_str, rating, str(gaps), vs_bl])
            else:
                runs = h.get("run_scores", [])
                runs_str = ", ".join(f"{s:.2f}" for s in runs) if runs else "—"
                rows.append([rn, f"{score:.2f}", runs_str, rating, str(gaps), vs_bl])

        rb.table(headers, rows)
        rb.blank()

        # ── Section 3: 候选明细 ──────────────────────
        if candidate_pool:
            rb.section("各轮候选详情")
            for rk, cs in candidate_pool.items():
                rb.section(f"Round {rk}", level=3)
                bl = next((h["score"] for h in history if h.get("round") == "baseline"), None)
                if rk != "baseline":
                    bl = bl or next((h["score"] for h in history
                                     if isinstance(h.get("round"), int) and h["round"] < int(rk)), None)
                headers2 = ["候选", "策略", "分数", "标准差", "各次得分", "vs 基线"]
                rows2 = []
                for c in cs:
                    runs = c.get("run_scores", [])
                    runs_str2 = ", ".join(f"{s:.2f}" for s in runs) if runs else "—"
                    if bl:
                        d = c["score"] - bl
                        vs = f"+{d:.2f}" if d > 0 else f"{d:.2f}"
                    else:
                        vs = "—"
                    rows2.append([
                        f"c{c['id']}",
                        c.get("strategy", "?"),
                        f"{c['score']:.2f}",
                        f"{c.get('stddev', 0):.2f}",
                        runs_str2,
                        vs,
                    ])
                rb.table(headers2, rows2)
                rb.blank()

        path = self.workspace / "score_history.md"
        atomic_write(str(path), rb.render())

    # ── 工作区目录 ────────────────────────────────────

    def ensure_dirs(self, workspace: Path):
        """确保工作区必要目录存在"""
        ensure_dir(str(workspace))

    @classmethod
    def migrate_from_flat(cls, workspace: Path):
        """
        迁移旧版平铺产物结构，清理冗余目录。

        旧版产物散落在 workspace 根目录（审查结果/、input/、r_result/），
        新版统一存放在 workspace 根目录下（baseline/、round_N/ 等）。
        """
        import shutil as _sh
        for name in ["审查结果", "input", "r_result"]:
            target = workspace / name
            if target.exists():
                try:
                    _sh.rmtree(str(target), ignore_errors=True)
                except Exception:
                    pass

    # ── Score Analyzer 产物保存 ───────────────────────

    def save_run_score(self, run_dir: Path, raw_metric: dict):
        """
        保存单个 run 的 Score Analyzer 产物 score.json。

        Args:
            run_dir: run_N 目录路径
            raw_metric: 包含 result_score 等
        """
        data = {
            "round_num": raw_metric.get("round_num", -1),
            "candidate_id": raw_metric.get("candidate_id", -1),
            "run_index": raw_metric.get("run_index", 1),
            "result_score": raw_metric.get("result_score"),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        save_json(str(run_dir / "score.json"), data)

    def save_candidate_score_analysis(self, candidate_id: int, round_num: int,
                                      score_data: Dict, analysis_text: str = ""):
        """
        保存候选评分分析文件。

        Args:
            candidate_id: 候选 ID
            round_num: 轮次号
            score_data: candidate_K_score.json 数据
            analysis_text: candidate_K_score_analysis.md 文本内容
        """
        cand_dir = self._candidate_dir(candidate_id, round_num)
        save_json(str(cand_dir / f"candidate_{candidate_id}_score.json"), score_data)
        if analysis_text:
            atomic_write(str(cand_dir / f"candidate_{candidate_id}_score_analysis.md"), analysis_text)

    def save_round_score(self, round_num: int, score_data: Dict, analysis_text: str = ""):
        """
        保存一轮的完整评分。

        Args:
            round_num: 轮次号
            score_data: round_N_score.json 数据
            analysis_text: round_N_score_analysis.md 文本内容
        """
        rd = self._ensure_round_dir(round_num)
        save_json(str(rd / f"round_{round_num}_score.json"), score_data)
        if analysis_text:
            atomic_write(str(rd / f"round_{round_num}_score_analysis.md"), analysis_text)

