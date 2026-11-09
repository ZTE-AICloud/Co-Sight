"""
诊断分析模块
============
基于启发式规则自动分析低分根因，按四大维度归类并输出诊断结论。

纯规则驱动，不增加 LLM 调用。分析基于：
- 文件系统状态（知识库、输入数据是否齐备）
- 缺口模式统计（类型、严重度、占位符频率）
- 跨轮趋势（分数变化、缺口数变化）
- 评分结构（RAN 间方差、召回率/精确率不对称）

维度分类：
  CAT_INPUT_DATA     = "输入数据不足/知识库缺失"
  CAT_SKILL_DESIGN   = "Skill 设计问题"
  CAT_GOLD_STANDARD  = "Gold 标准问题"
  CAT_COLLABORATION  = "协作/流程问题"
  CAT_HARNESS        = "Skill 工程配置/Harness 合理性"
"""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── 维度常量 ──────────────────────────────────────────────

CAT_INPUT_DATA = "输入数据不足/知识库缺失"
CAT_SKILL_DESIGN = "Skill 设计问题"
CAT_GOLD_STANDARD = "Gold 标准问题"
CAT_COLLABORATION = "协作/流程问题"
CAT_HARNESS = "Skill 工程配置/Harness 合理性"
CAT_OVERFIT = "过拟合风险"

# ── 诊断数据结构 ──────────────────────────────────────────


@dataclass
class DiagnosticFinding:
    """单条诊断发现"""
    category: str
    confidence: str   # "高" / "中" / "低"
    evidence: str
    impact: str
    recommendation: str
    score: float = 0.0  # 影响分，用于排序


# ── 诊断分析器 ────────────────────────────────────────────


class DiagnosticAnalyzer:
    """根因诊断分析器，对评测结果进行多维度启发式分析"""

    # Skill 设计相关的缺口模式关键词
    SKILL_DESIGN_PATTERNS = [
        "映射规则", "识别逻辑", "扫描", "提取方法", "指令",
        "步骤遗漏", "流程断点", "格式不符", "路径错误", "规则",
    ]

    def __init__(
        self,
        workspace: Path,
        history: List[Dict],
        gaps_by_round: List[List[Dict]],
        metadata: Dict,
        target_score: float = 90.0,
    ):
        self.workspace = Path(workspace)
        self.history = history or []
        self.gaps_by_round = gaps_by_round or []
        self.metadata = metadata or {}
        self.target_score = target_score

        # 扁平化所有轮次的缺口
        self.all_gaps: List[Dict] = []
        for round_gaps in self.gaps_by_round:
            self.all_gaps.extend(round_gaps)

        # 如果 gaps_by_round 为空，尝试从磁盘恢复
        if not self.gaps_by_round and self.history:
            self.gaps_by_round = self._load_gaps_from_disk()
            self.all_gaps = []
            for round_gaps in self.gaps_by_round:
                self.all_gaps.extend(round_gaps)

    # ── 公共入口 ──────────────────────────────────────

    def analyze(self) -> List[DiagnosticFinding]:
        """执行全维度诊断，返回按影响分降序排列的诊断发现列表"""
        findings: List[DiagnosticFinding] = []

        findings.extend(self._check_input_data())
        findings.extend(self._check_skill_design())
        findings.extend(self._check_gold_standard())
        findings.extend(self._check_collaboration())
        findings.extend(self._check_harness())
        findings.extend(self._check_overfit())

        findings.sort(key=lambda f: f.score, reverse=True)
        return findings

    # ── 维度 1：输入数据 / 知识库检查 ─────────────────

    def _check_input_data(self) -> List[DiagnosticFinding]:
        findings = []

        # 1a. 扫描 case 子目录的 input/ 目录
        # 假设 workspace 下每个直接子目录都是一个 case 目录
        case_dirs = sorted([d for d in self.workspace.iterdir() if d.is_dir()])
        cases_with_input = []
        cases_without_input = []

        for case_dir in case_dirs:
            input_dir = case_dir / "input"
            if input_dir.is_dir() and any(input_dir.iterdir()):
                cases_with_input.append(case_dir.name)
            else:
                cases_without_input.append(case_dir.name)

        total_cases = len(cases_with_input) + len(cases_without_input)

        if cases_without_input:
            if len(cases_without_input) == total_cases:
                confidence = "高"
                evidence = (
                    f"全部 {total_cases} 个 case 的 input/ 目录为空或不存在"
                )
            else:
                confidence = "中"
                evidence = (
                    f"{total_cases} 个 case 中，{len(cases_without_input)} 个缺少输入数据。"
                    f"缺失输入数据的 case: {', '.join(cases_without_input[:5])}"
                    f"{'...' if len(cases_without_input) > 5 else ''}"
                )
            findings.append(DiagnosticFinding(
                category=CAT_INPUT_DATA,
                confidence=confidence,
                evidence=evidence,
                impact="缺乏输入数据导致候选产物生成质量下降，评测召回率偏低",
                recommendation="为每个 case 目录的 input/ 子目录补充完整的输入文档",
                score=40.0 if confidence == "高" else 25.0,
            ))

        # 1b. 检查知识库目录（通用：查找 case 下含 .md 的子目录）是否配置
        cases_with_kb = []
        cases_without_kb = []
        for case_dir in case_dirs:
            has_kb = False
            for child in case_dir.iterdir():
                if child.is_dir() and any(child.rglob("*.md")):
                    has_kb = True
                    break
            if has_kb:
                cases_with_kb.append(case_dir.name)
            else:
                cases_without_kb.append(case_dir.name)

        kb_total = len(cases_with_kb) + len(cases_without_kb)
        if kb_total > 0 and len(cases_without_kb) == kb_total:
            findings.append(DiagnosticFinding(
                category=CAT_INPUT_DATA,
                confidence="高",
                evidence=(
                    f"全部 {kb_total} 个 case 目录下都缺少含 .md 文件的知识库子目录"
                ),
                impact="缺少知识库文档，LLM 无法获取必要的上下文数据，导致候选产物质量下降",
                recommendation="为每个 case 目录补充知识库文档（.md 文件），确保 Skill 执行时能获取所需的上下文",
                score=40.0,
            ))

        # 1c. 统计 gaps 中 [待确认] 出现次数
        placeholder_count = 0
        for g in self.all_gaps:
            for field in ("root_cause", "fix_suggestion", "affected_section"):
                if "[待确认]" in str(g.get(field, "")):
                    placeholder_count += 1
                    break

        if placeholder_count >= 1:
            findings.append(DiagnosticFinding(
                category=CAT_INPUT_DATA,
                confidence="中",
                evidence=(
                    f"评测结果中 {placeholder_count} 个缺口涉及 [待确认] 标记，"
                    f"表明候选产物无法确定具体组件/子系统名称"
                ),
                impact="不确定信息导致候选产物与 Gold 标准的匹配率降低，精确率和召回率双低",
                recommendation="补充 RAN 输入数据中的具体组件实例名称（如 PPS_PROXY、PLS、UAC 等），而非仅提供抽象的子系统能力描述",
                score=20.0,
            ))

        return findings

    # ── 维度 2：Skill 设计检查 ────────────────────────

    def _check_skill_design(self) -> List[DiagnosticFinding]:
        findings = []

        # 2a. Skill 设计相关的缺口统计
        design_related_gaps = []
        for g in self.all_gaps:
            root_cause = str(g.get("root_cause", ""))
            fix = str(g.get("fix_suggestion", ""))
            combined = root_cause + fix
            if any(p in combined for p in self.SKILL_DESIGN_PATTERNS):
                design_related_gaps.append(g)

        if design_related_gaps:
            gap_types: Dict[str, int] = {}
            for g in design_related_gaps:
                t = g.get("type", "未知")
                gap_types[t] = gap_types.get(t, 0) + 1

            type_summary = "、".join(f"{k}×{v}" for k, v in sorted(gap_types.items(), key=lambda x: -x[1]))
            confidence = "高" if len(design_related_gaps) >= 3 else "中"

            findings.append(DiagnosticFinding(
                category=CAT_SKILL_DESIGN,
                confidence=confidence,
                evidence=(
                    f"共 {len(design_related_gaps)} 个缺口与 Skill 设计直接相关"
                    f"（{type_summary}）。"
                    f"典型根因: {design_related_gaps[0].get('root_cause', '?')[:100]}"
                ),
                impact="Skill 的执行指令或映射规则存在缺陷，导致 LLM 无法正确提取和匹配信息",
                recommendation="重新审视 Skill 的核心执行逻辑，特别是组件识别规则和映射表，考虑增加更具体的匹配步骤和错误处理",
                score=min(35.0, len(design_related_gaps) * 8.0),
            ))

        # 2b. 跨轮停滞检测
        if len(self.history) >= 2:
            scores = [h.get("score", 0) for h in self.history]
            score_range = max(scores) - min(scores)
            final_score = scores[-1]

            if score_range < 5.0 and final_score < self.target_score:
                findings.append(DiagnosticFinding(
                    category=CAT_SKILL_DESIGN,
                    confidence="高",
                    evidence=(
                        f"经过 {len(self.history)} 轮优化，分数变化仅 {score_range:.1f} 分"
                        f"（{scores}），优化基本无效"
                    ),
                    impact="当前优化策略未能有效解决 Skill 的根本性问题，继续增量修补无法突破瓶颈",
                    recommendation="建议重新审视 Skill 的整体设计，而非仅做增量修补。可能需要重新定义输出格式、执行流程或引入领域知识注入机制",
                    score=35.0,
                ))

        return findings

    # ── 维度 3：Gold 标准检查 ─────────────────────────

    def _check_gold_standard(self) -> List[DiagnosticFinding]:
        findings = []

        per_ran = self.metadata.get("per_ran", [])
        rule_scores = self.metadata.get("rule_scores", {})

        # 3a. 所有 RAN 分数极低
        ran_scores = []
        if per_ran:
            ran_scores = [r.get("s_total", 0) for r in per_ran if "s_total" in r]
            if ran_scores and all(s < 40 for s in ran_scores):
                ran_detail = ", ".join(
                    "{}={:.0f}".format(r.get("ran_id", "?"), r.get("s_total", 0))
                    for r in per_ran
                )
                findings.append(DiagnosticFinding(
                    category=CAT_GOLD_STANDARD,
                    confidence="低",
                    evidence=(
                        f"全部 {len(ran_scores)} 个 RAN 的分数均低于 40"
                        f"（{ran_detail}）"
                    ),
                    impact="所有 RAN 得分极低，可能原因包括：Gold 标准格式与候选产物不兼容、候选产物输出质量极差、知识库缺失",
                    recommendation="先确保输入数据和知识库齐备，然后选取一个分数最低的 RAN 单独排查 Gold 与候选产物的结构差异",
                    score=10.0,
                ))

        # 3b. RAN 间方差大
        if len(ran_scores) >= 2:
            mean_score = sum(ran_scores) / len(ran_scores)
            variance = sum((s - mean_score) ** 2 for s in ran_scores) / len(ran_scores)
            std_dev = variance ** 0.5

            if std_dev > 20:
                high_rans = [r for r in per_ran if r.get("s_total", 0) >= mean_score]
                low_rans = [r for r in per_ran if r.get("s_total", 0) < mean_score]
                findings.append(DiagnosticFinding(
                    category=CAT_GOLD_STANDARD,
                    confidence="中",
                    evidence=(
                        f"RAN 间得分标准差 {std_dev:.1f}，差异显著。"
                        f"高分 RAN: {', '.join(r.get('ran_id', '?') for r in high_rans)}，"
                        f"低分 RAN: {', '.join(r.get('ran_id', '?') for r in low_rans)}"
                    ),
                    impact="个别 RAN 的 Gold 标准可能包含候选产物难以获取的信息（如内部组件实例名），导致该 RAN 得分远低于其他",
                    recommendation=f"重点排查低分 RAN 的 Gold 标准与输入数据之间的信息差，确认 Gold 中要求的字段是否在输入数据中可获取",
                    score=15.0,
                ))

        # 3c. 召回率远低于精确率
        for leaf, scores in rule_scores.items():
            recall = scores.get("recall", 0)
            precision = scores.get("precision", 0)
            if recall < 50 and precision >= recall + 20:
                findings.append(DiagnosticFinding(
                    category=CAT_GOLD_STANDARD,
                    confidence="中",
                    evidence=(
                        f"规则项「{leaf}」召回率 {recall:.1f}% 远低于精确率 {precision:.1f}%，"
                        f"候选产物遗漏了大量 Gold 定义的内容"
                    ),
                    impact="可能 Gold 标准覆盖范围过广，或候选产物生成逻辑的覆盖范围有限",
                    recommendation=f"检查 Gold 标准「{leaf}」是否包含过多非核心条目；同时检查 Skill 输出模板是否完整覆盖所有必需的字段",
                    score=15.0,
                ))

        return findings

    # ── 维度 4：协作/流程检查 ─────────────────────────

    def _check_collaboration(self) -> List[DiagnosticFinding]:
        findings = []

        if len(self.history) < 2:
            return findings

        scores = [h.get("score", 0) for h in self.history]
        gap_counts = [h.get("total_gaps", 0) for h in self.history]

        # 4a. 分数震荡检测
        if len(scores) >= 3:
            directions = []
            for i in range(1, len(scores)):
                if scores[i] > scores[i - 1]:
                    directions.append(1)
                elif scores[i] < scores[i - 1]:
                    directions.append(-1)
                else:
                    directions.append(0)

            changes = sum(1 for i in range(1, len(directions))
                         if directions[i] != 0 and directions[i] != directions[i - 1])
            non_zero_dirs = [d for d in directions if d != 0]

            if len(non_zero_dirs) >= 3 and changes >= len(non_zero_dirs) - 1:
                findings.append(DiagnosticFinding(
                    category=CAT_COLLABORATION,
                    confidence="低",
                    evidence=(
                        f"分数呈现锯齿形波动（{scores}），优化方向可能不一致"
                    ),
                    impact="每轮优化方向不一致导致分数震荡，缺乏稳定的改进策略",
                    recommendation="建议分析各轮优化提案的差异，确定最有效的优化方向并坚持执行",
                    score=15.0,
                ))

        # 4b. 缺口数持续不降
        if len(gap_counts) >= 2:
            gap_range = max(gap_counts) - min(gap_counts)
            if gap_range <= 1 and gap_counts[-1] > 0:
                findings.append(DiagnosticFinding(
                    category=CAT_COLLABORATION,
                    confidence="高",
                    evidence=(
                        f"经过 {len(self.history)} 轮优化，缺口数量基本不变"
                        f"（{gap_counts}），优化未能有效减少缺口"
                    ),
                    impact="优化器可能未针对具体的缺口根因进行改进，或优化粒度不足以解决实际问题",
                    recommendation="检查各轮优化提案是否真正针对评测发现的缺口根因进行修改；考虑增加 LLM Judge 反馈到优化器的信息传递",
                    score=30.0,
                ))

        # 4c. 分数持续下降
        if len(scores) >= 3 and all(scores[i] <= scores[i - 1] for i in range(1, len(scores))):
            if scores[-1] < scores[0]:
                findings.append(DiagnosticFinding(
                    category=CAT_COLLABORATION,
                    confidence="高",
                    evidence=(
                        f"分数连续 {len(scores)} 轮下降"
                        f"（{scores[0]:.1f} → {scores[-1]:.1f}），优化方向可能有误"
                    ),
                    impact="持续下降表明优化策略与评测标准存在系统性冲突，每次修改反而降低质量",
                    recommendation="暂停自动优化，回退到最高分版本的 Skill，人工分析优化提案与评测标准之间的冲突点",
                    score=35.0,
                ))

        return findings

    # ── 维度 5：Skill 工程/Harness 合理性检查 ─────────

    def _check_harness(self) -> List[DiagnosticFinding]:
        """检查 Skill 的工程配置和依赖链是否合理"""
        findings = []

        # 假设 workspace 下每个直接子目录都是一个 case 目录
        case_dirs = sorted([d for d in self.workspace.iterdir() if d.is_dir()])
        if not case_dirs:
            return findings

        # 5a. 上游 Skill 产物缺失检测
        # 通过分析 gaps 中的 root_cause 识别可能的上下游依赖断裂
        upstream_terms = ["上游", "前置", "前序步骤", "输入文件缺失", "中间产物"]
        upstream_gaps = []
        for g in self.all_gaps:
            root_cause = str(g.get("root_cause", ""))
            if any(t in root_cause for t in upstream_terms):
                upstream_gaps.append(g)

        if upstream_gaps:
            findings.append(DiagnosticFinding(
                category=CAT_HARNESS,
                confidence="中",
                evidence=(
                    f"共 {len(upstream_gaps)} 个缺口涉及上游依赖产物问题。"
                    f"典型: {upstream_gaps[0].get('root_cause', '?')[:120]}"
                ),
                impact="上游 Skill 的输出质量直接影响下游 Skill 的分析基础，上游数据缺失或格式不符会导致下游完全无法正确执行",
                recommendation="检查上游 Skill 的输出格式是否与当前 Skill 的输入假设一致；确认 Skill 间的接口契约（文件路径、表格格式、字段命名）已对齐",
                score=25.0,
            ))

        # 5b. 中间产物目录结构检查
        # 检查每个 case 目录下是否有任何产出子目录（通用检查：存在子目录即认为有产物）
        cases_missing_intermediate = []
        for case_dir in case_dirs:
            # 通用检查：存在任何子目录即认为有产物
            has_products = any(child.is_dir() for child in case_dir.iterdir())
            if not has_products:
                cases_missing_intermediate.append(case_dir.name)

        if cases_missing_intermediate:
            findings.append(DiagnosticFinding(
                category=CAT_HARNESS,
                confidence="中",
                evidence=(
                    f"{len(cases_missing_intermediate)} 个 case 缺少评测产物目录。"
                    f"影响的 case: {', '.join(cases_missing_intermediate[:5])}"
                ),
                impact="缺少上游 Skill 的中间产物，当前 Skill 在执行时无法获取必要的上下文信息",
                recommendation="确保在运行当前 Skill 之前，所有前序 Skill 已在每个 case 下执行完毕并产生中间产物",
                score=25.0,
            ))

        # 5c. 知识库脚本可执行性检查（通用：查找任何 .sh 脚本）
        script_dirs = list(self.workspace.rglob("*.sh"))
        if not script_dirs:
            for case_dir in case_dirs:
                kb_scripts = list(case_dir.rglob("*.sh"))
                if kb_scripts:
                    break
            else:
                findings.append(DiagnosticFinding(
                    category=CAT_HARNESS,
                    confidence="低",
                    evidence=(
                        "未在 workspace 中找到任何可执行脚本（*.sh）。"
                        "Skill 可能需要调用外部脚本获取辅助数据"
                    ),
                    impact="外部脚本缺失导致 Skill 无法加载辅助数据，是候选产物质量下降的可能原因之一",
                    recommendation="检查工作目录结构是否完整，确认所需的可执行脚本已部署到对应位置",
                    score=20.0,
                ))

        # 5d. Skill 快照目录结构检查（是否有 references/、scripts/ 等辅助文件）
        snapshot_dirs = list(self.workspace.glob("round_*/snapshot"))
        has_aux_files = False
        for snap in snapshot_dirs:
            refs = snap / "references"
            scrs = snap / "scripts"
            if (refs.is_dir() and any(refs.iterdir())) or (scrs.is_dir() and any(scrs.iterdir())):
                has_aux_files = True
                break

        # 检查 SKILL.md 是否引用了外部文件
        skill_refs_to_nonexistent = []
        for snap in snapshot_dirs:
            skill_md = snap / "SKILL.md"
            if not skill_md.exists():
                continue
            content = skill_md.read_text(encoding="utf-8")
            # 检测常见的文件引用模式，排除模板变量（{...}）
            import re
            ref_patterns = re.findall(r'[`"]([^`"]+\.(?:md|sh|py|json))[`"]', content)
            for ref in ref_patterns:
                # 跳过模板变量占位符
                if "{" in ref or "}" in ref:
                    continue
                ref_path = snap / ref
                if not ref_path.exists():
                    skill_refs_to_nonexistent.append(ref)

        if skill_refs_to_nonexistent:
            unique_refs = list(set(skill_refs_to_nonexistent))[:5]
            findings.append(DiagnosticFinding(
                category=CAT_HARNESS,
                confidence="中",
                evidence=(
                    f"SKILL.md 引用了 {len(skill_refs_to_nonexistent)} 个不存在的文件，"
                    f"如: {', '.join(unique_refs)}"
                ),
                impact="Skill 引用了不存在的辅助文件，LLM 执行时文件读取失败可能导致步骤跳过或错误处理",
                recommendation="检查 Skill 目录结构，确保 SKILL.md 中引用的所有文件（references/、scripts/ 等）都已正确部署",
                score=20.0,
            ))

        return findings

    # ── 维度 6：过拟合风险检查 ─────────────────────

    def _check_overfit(self) -> List[DiagnosticFinding]:
        """检测 Skill 是否向 Gold 过拟合"""
        findings = []

        try:
            from .overfit_monitor import OverfitMonitor
        except ImportError:
            return findings

        # 收集各轮 Skill 快照路径
        skill_paths: List[str] = []
        for i in range(len(self.history)):
            snap_dir = self.workspace / f"round_{i}" / "snapshot"
            skill_md = snap_dir / "SKILL.md"
            if skill_md.exists():
                skill_paths.append(str(skill_md))

        if not skill_paths:
            return findings

        monitor = OverfitMonitor(self.workspace)
        current_round = len(self.history)
        signals = monitor.analyze(self.history, skill_paths, current_round)

        for sig in signals:
            findings.append(DiagnosticFinding(
                category=CAT_OVERFIT,
                confidence=sig.confidence,
                evidence=sig.evidence,
                impact="Skill 可能通过多轮优化间接\"学习\"了 Gold 标准的具体内容，而非真正提升了通用分析能力",
                recommendation=sig.recommendation,
                score=sig.score,
            ))

        return findings

    # ── 辅助方法 ──────────────────────────────────────

    def _load_gaps_from_disk(self) -> List[List[Dict]]:
        """从 round_N/score.json 恢复缺口数据"""
        gaps = []
        for i in range(len(self.history)):
            score_file = self.workspace / f"round_{i}" / "score.json"
            if score_file.exists():
                try:
                    with open(score_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    gaps.append(data.get("gaps", []))
                except (json.JSONDecodeError, OSError):
                    gaps.append([])
            else:
                gaps.append([])
        return gaps


# ── 报告生成 ──────────────────────────────────────────────

_CONFIDENCE_BAR = {"高": "████", "中": "██", "低": "█"}
_CATEGORY_EMOJI = {
    CAT_INPUT_DATA: "📥",
    CAT_SKILL_DESIGN: "🔧",
    CAT_GOLD_STANDARD: "📋",
    CAT_COLLABORATION: "🔄",
    CAT_HARNESS: "🏗️",
    CAT_OVERFIT: "🎯",
}


def generate_diagnosis_section(findings: List[DiagnosticFinding], top_n: int = 5, pattern_findings: Optional[List[Dict]] = None) -> str:
    """将诊断发现列表格式化为 markdown 报告章节"""
    lines = ["\n## 根因诊断\n"]

    if not findings:
        lines.append("✅ 未发现显著的诊断问题。\n")
        return "\n".join(lines)

    visible = findings[:top_n]

    lines.append(
        "> 以下基于评测历史、缺口模式和文件系统状态进行启发式诊断，"
        "帮助定位低分根因并指导改进方向。\n"
    )
    lines.append(f"共识别 {len(findings)} 个诊断信号，以下是 TOP {min(top_n, len(visible))}：\n")

    for i, f in enumerate(visible, 1):
        emoji = _CATEGORY_EMOJI.get(f.category, "❓")
        bar = _CONFIDENCE_BAR.get(f.confidence, "█")
        lines.append(f"### {i}. {emoji} {f.category}\n")
        lines.append("| 属性 | 内容 |")
        lines.append("|:---|:---|")
        lines.append(f"| **置信度** | {f.confidence} {bar} |")
        lines.append(f"| **证据** | {f.evidence} |")
        lines.append(f"| **影响** | {f.impact} |")
        lines.append(f"| **建议** | {f.recommendation} |")
        lines.append("")

    # ── 模式因果诊断 ─────────────────────
    if pattern_findings:
        lines.append(_render_pattern_section(pattern_findings))

    return "\n".join(lines)


def _render_pattern_section(pattern_findings: List[Dict]) -> str:
    """将模式诊断结果渲染为 markdown 章节"""
    lines = ["\n## 模式因果诊断\n"]
    lines.append("> 基于问题诊断知识库，识别设计模式级的失效模式。\n")
    for pf in pattern_findings:
        lines.append(f"### Gap {pf.get('gap_id', '?')}: {pf.get('pattern', '?')}")
        lines.append(f"- **维度**: {pf.get('dimension', '?')}")
        symptom = str(pf.get('symptom_match', ''))[:150]
        lines.append(f"- **匹配症状**: {symptom}")
        lines.append(f"- **Spec 检查点**: {pf.get('check_in_spec', '?')}")
        fix = str(pf.get('fix_approach', ''))[:150]
        lines.append(f"- **修复方向**: {fix}")
        lines.append("")
    return "\n".join(lines)


# ── 模式因果诊断 ──────────────────────────


class PatternBasedDiagnoser:
    """
    基于外部知识库 problem-diagnoser.yaml 的因果诊断。

    针对 skillx-alpha-agents的优化场景：
    - 优先匹配 skill_quality_delegation（failure/likely_cause/action 结构）
    - 其他维度为辅助（生成任务设计，优化场景区分度低）
    """
    DIAGNOSER_PATH = Path(__file__).parent / "knowledge" / "problem-diagnoser.yaml"

    # 优化场景核心维度
    SKILL_DIM = "skill_quality_delegation"
    # 其他维度按优先级排序
    OTHER_DIMS = [
        "data_flow_integrity", "workflow_integrity",
        "quality_control", "knowledge_integrity",
        "interaction_experience", "cross_dimension",
    ]

    def __init__(self):
        self.diagnoser = self._load_yaml(self.DIAGNOSER_PATH)

    def diagnose_gaps(self, gaps: List[Dict]) -> List[Dict]:
        if not self.diagnoser:
            return []

        results = []
        for gap in gaps:
            gap_id = gap.get("gap_id", gap.get("id", "?"))
            root_cause = str(gap.get("root_cause", ""))
            fix = str(gap.get("fix_suggestion", ""))
            combined = (root_cause + " " + fix).lower()

            # 1. 优先匹配 skill_quality_delegation
            match = self._match_skill_dim(gap_id, combined)
            if match:
                results.append(match)
                continue

            # 2. 辅助匹配其他维度
            match = self._match_other_dims(gap_id, combined)
            if match:
                results.append(match)

        return results

    def _match_skill_dim(self, gap_id: str, combined_text: str) -> Optional[Dict]:
        """匹配 skill_quality_delegation 维度（failure + likely_cause → action）"""
        dim = self.diagnoser.get(self.SKILL_DIM, {})
        for chain in dim.get("causal_chains", []):
            failure = chain.get("failure", "")
            cause = chain.get("likely_cause", "")
            action = chain.get("action", "")
            # 从连续中文段中提取所有2-4字词组
            keywords = set()
            for part in re.findall(r'[一-龥]+', failure + cause):
                for i in range(len(part) - 1):
                    for j in range(i + 2, min(i + 5, len(part) + 1)):
                        keywords.add(part[i:j])
            for w in re.findall(r'[A-Za-z]{2,}', failure + cause):
                keywords.add(w)
            stop = {"如果", "可能", "必须", "声明", "了", "相反"}
            keywords -= stop
            hit_count = sum(1 for kw in keywords if kw in combined_text)
            if hit_count >= 2:
                return {
                    "gap_id": gap_id,
                    "dimension": "Skill 质量委托",
                    "pattern": f"Skill 质量诊断: {failure}",
                    "symptom_match": f"失败模式: {failure}\n可能原因: {cause}",
                    "check_in_spec": "→ 委托 Skill-Builder 修复",
                    "fix_approach": action,
                }
        return None

    def _match_other_dims(self, gap_id: str, combined_text: str) -> Optional[Dict]:
        """辅助匹配其他维度（生成任务设计，优化场景区分度低）"""
        seen = set()
        for dim_key in self.OTHER_DIMS:
            dim = self.diagnoser.get(dim_key, {})
            for chain in dim.get("causal_chains", []):
                for rc in chain.get("root_causes", []):
                    symptoms = rc.get("failure_symptoms", "")
                    if not symptoms:
                        continue
                    if self._symptoms_match(combined_text, symptoms):
                        key = (gap_id, rc.get("pattern", ""))
                        if key in seen:
                            continue
                        seen.add(key)
                        return {
                            "gap_id": gap_id,
                            "dimension": dim.get("description", dim_key)[:60],
                            "pattern": rc.get("pattern", "?"),
                            "symptom_match": symptoms,
                            "check_in_spec": rc.get("check_in_spec", ""),
                            "fix_approach": rc.get("fix_approach", ""),
                        }
        return None

    @staticmethod
    def _symptoms_match(combined_text: str, symptoms: str) -> bool:
        """从症状描述中提取关键词，匹配 gap 文本。
        注：此为近似匹配，未来可升级为 LLM 语义匹配。"""
        keywords = set()
        for part in re.findall(r'[一-龥]+', symptoms):
            for i in range(len(part) - 1):
                for j in range(i + 2, min(i + 5, len(part) + 1)):
                    keywords.add(part[i:j])
        for w in re.findall(r'[A-Za-z]{2,}', symptoms):
            keywords.add(w)
        stop = {"如果", "可能", "必须", "声明", "了"}
        keywords -= stop
        return any(kw in combined_text for kw in list(keywords)[:8])

    @staticmethod
    def _load_yaml(path: Path) -> dict:
        import yaml
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
