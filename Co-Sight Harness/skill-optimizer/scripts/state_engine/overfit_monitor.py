"""
过拟合监控模块
==============
跨轮次追踪 Skill 与 Gold 的相似度，检测"抄答案"信号。

检测指标：
1. Skill-Gold n-gram 重叠率
2. 分数跳变（单轮 >30 分提升）
3. 实体注入（Skill 中突然出现 Gold 独有的组件实例名）
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


@dataclass
class OverfitSignal:
    """过拟合信号"""
    signal_type: str        # "skill_gold_similarity" / "score_jump" / "entity_injection"
    confidence: str         # "高" / "中" / "低"
    evidence: str
    recommendation: str
    round_num: int = 0
    score: float = 0.0


class OverfitMonitor:
    """跨轮次过拟合检测器"""

    # Gold 中常见的组件实例名模式（大写_大写 或 大写缩写）
    ENTITY_PATTERN = re.compile(r'\b([A-Z]{2,}(?:_[A-Z]{2,})?(?:<[A-Z][a-z]+>)?)\b')

    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)
        self._gold_entities: Optional[Set[str]] = None

    def analyze(
        self, history: List[Dict], skill_paths: List[str], round_num: int
    ) -> List[OverfitSignal]:
        """
        对当前轮次执行过拟合检测

        Args:
            history: 评测历史 [{round, score, ...}, ...]
            skill_paths: 各轮 SKILL.md 路径（或内容），按轮次顺序
            round_num: 当前轮次

        Returns:
            过拟合信号列表
        """
        signals: List[OverfitSignal] = []

        # 1. 分数跳变检测
        signals.extend(self._check_score_jump(history, round_num))

        # 2. 实体注入检测
        if skill_paths and round_num >= 1:
            signals.extend(self._check_entity_injection(skill_paths, round_num))

        # 3. Skill-Gold 相似度（需要前轮 Skill 做对照）
        if len(skill_paths) >= 2:
            signals.extend(self._check_similarity_trend(skill_paths, round_num))

        return signals

    # ── 检测 1：分数跳变 ──────────────────────────

    def _check_score_jump(self, history: List[Dict], round_num: int) -> List[OverfitSignal]:
        if len(history) < 2:
            return []

        prev_score = history[-2].get("score", 0)
        curr_score = history[-1].get("score", 0)
        jump = curr_score - prev_score

        if jump > 30:
            return [OverfitSignal(
                signal_type="score_jump",
                confidence="中",
                evidence=(
                    f"分数从 {prev_score:.1f} 跳升至 {curr_score:.1f}"
                    f"（+{jump:.1f} 分），单轮提升超过 30 分。"
                    f"需排查是否因 Skill 内容向 Gold 标准靠拢而非真正改进"
                ),
                recommendation="人工审查本轮优化 diff，确认是否在 Skill 中直接写入了 Gold 独有的具体数据",
                round_num=round_num,
                score=30.0,
            )]
        return []

    # ── 检测 2：实体注入 ──────────────────────────

    def _check_entity_injection(
        self, skill_paths: List[str], round_num: int
    ) -> List[OverfitSignal]:
        """检测 SKILL.md 中是否突然出现 Gold 独有的组件实例名"""
        if len(skill_paths) < 2:
            return []

        entities_before = self._extract_entities(self._read_skill(skill_paths[-2]))
        entities_after = self._extract_entities(self._read_skill(skill_paths[-1]))
        gold_entities = self._load_gold_entities()

        # 新增的实体 ∩ Gold 独有实体
        new_entities = entities_after - entities_before
        leaked = new_entities & gold_entities

        if leaked:
            leaked_list = sorted(leaked)[:10]
            return [OverfitSignal(
                signal_type="entity_injection",
                confidence="高" if len(leaked) >= 3 else "中",
                evidence=(
                    f"SKILL.md 中新增了 {len(leaked)} 个疑似来自 Gold 的实体名: "
                    f"{', '.join(leaked_list)}。"
                    f"这些名称未出现在上一轮 Skill 中，可能通过优化器从 Gold 泄漏"
                ),
                recommendation="检查优化提案中是否直接引用了 Gold 的具体数据；建议重新生成优化提案并启用 gap 脱敏",
                round_num=round_num,
                score=35.0 if len(leaked) >= 3 else 20.0,
            )]
        return []

    # ── 检测 3：Skill-Gold 相似度趋势 ──────────────

    def _check_similarity_trend(
        self, skill_paths: List[str], round_num: int
    ) -> List[OverfitSignal]:
        """检测 Skill 与 Gold 的 n-gram 重叠率是否逐轮上升"""
        gold_text = self._load_gold_text()
        if not gold_text:
            return []

        similarities = []
        for sp in skill_paths:
            skill_text = self._read_skill(sp)
            sim = self._ngram_jaccard(skill_text, gold_text, n=4)
            similarities.append(sim)

        # 连续上升趋势
        if len(similarities) >= 3:
            if similarities[-1] > similarities[-2] > similarities[-3]:
                return [OverfitSignal(
                    signal_type="skill_gold_similarity",
                    confidence="低",
                    evidence=(
                        f"Skill-Gold 4-gram 相似度连续上升: "
                        f"{similarities[-3]:.3f} → {similarities[-2]:.3f} → {similarities[-1]:.3f}。"
                        f"可能正在向 Gold 内容收敛"
                    ),
                    recommendation="审查最近两轮优化提案，确认改进是否基于通用原则而非 Gold 具体数据",
                    round_num=round_num,
                    score=15.0,
                )]
        return []

    # ── 工具方法 ──────────────────────────────────

    def _load_gold_entities(self) -> Set[str]:
        """加载所有 Gold 文件中的实体名"""
        if self._gold_entities is not None:
            return self._gold_entities

        entities: Set[str] = set()
        # 扫描 Gold 目录（从 SKILLX_SANDBOX_GOLD 环境变量读取）
        gold_base = os.environ.get("SKILLX_SANDBOX_GOLD", "")
        if gold_base:
            gb = Path(gold_base)
            if gb.exists():
                for gold_file in gb.glob("*/gold.md"):
                    try:
                        text = gold_file.read_text(encoding="utf-8")
                        entities.update(self._extract_entities(text))
                    except Exception:
                        pass

        self._gold_entities = entities
        return entities

    def _load_gold_text(self) -> str:
        """加载所有 Gold 文本"""
        parts = []
        gold_base = os.environ.get("SKILLX_SANDBOX_GOLD", "")
        if gold_base:
            gb = Path(gold_base)
            for gold_file in sorted(gb.glob("*/gold.md"))[:5]:
                try:
                    parts.append(gold_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
        return "\n".join(parts)

    @staticmethod
    def _read_skill(path_or_content: str) -> str:
        """读取 Skill 内容（支持路径或内容字符串）"""
        p = Path(path_or_content)
        if p.exists():
            return p.read_text(encoding="utf-8")
        return path_or_content

    @staticmethod
    def _extract_entities(text: str) -> Set[str]:
        """提取文本中的实体名（大写缩写模式）"""
        entities = set()
        # 扫描 markdown 表格和普通文本
        for match in OverfitMonitor.ENTITY_PATTERN.finditer(text):
            entity = match.group(1)
            # 过滤常见非实体大写词
            skip_words = {
                "API", "CLI", "JSON", "HTTP", "URL", "LLM", "SDD", "RAN",
                "SKILL", "GOLD", "TODO", "FIXME", "NOTE", "IMPORTANT",
                "CRITICAL", "HIGH", "MEDIUM", "LOW", "EXCELLENT", "GOOD",
                "FAIR", "POOR", "BROKEN", "ID", "N", "R", "P", "F1", "C",
            }
            if entity not in skip_words and len(entity) >= 2:
                entities.add(entity)
        return entities

    @staticmethod
    def _ngram_jaccard(text1: str, text2: str, n: int = 4) -> float:
        """计算两个文本的 n-gram Jaccard 相似度"""
        def ngrams(s: str, n: int) -> Set[str]:
            chars = list(s)
            return {"".join(chars[i:i + n]) for i in range(len(chars) - n + 1)}

        ng1 = ngrams(text1, n)
        ng2 = ngrams(text2, n)

        if not ng1 or not ng2:
            return 0.0

        intersection = len(ng1 & ng2)
        union = len(ng1 | ng2)
        return intersection / union if union > 0 else 0.0
