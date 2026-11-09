"""
同轮内归一化 + 加权复合分数计算
================================
对同轮内所有候选做 min-max 归一化，
仅对 quantitative=True 且 weight > 0 的指标参与计算，
lower_is_better 的指标反转 (1 - normalized)。
"""

from typing import List

from metrics.composite import CompositeScoreCalculator
from metrics.config import MetricsConfig

from .models import CandidateScore


class RoundNormalizer:
    """同轮内多候选归一化器。"""

    @staticmethod
    def normalize(candidates: List[CandidateScore],
                  metrics_config: MetricsConfig) -> List[CandidateScore]:
        """
        对同轮内所有候选做 min-max 归一化 + 加权 composite。
        """
        if not candidates:
            return candidates

        # 获取需要归一化的指标名（来自 metrics config 的字段名映射）
        # 当前只有 result_score 一个量化指标
        metric_field_map = {
            "result_score": "avg_result_score",
        }

        quantitative = metrics_config.quantitative_names()
        for metric_name in quantitative:
            field_name = metric_field_map.get(metric_name)
            if field_name is None:
                continue

            # 已量化指标（normalization='none'），跳过 min-max 归一化
            # 原值是百分制 0~100,normalized 字段语义仍为 0~1,需 /100 折算
            mdef = metrics_config.get_definition(metric_name)
            if mdef and mdef.normalization == "none":
                for c in candidates:
                    v = getattr(c, field_name, None)
                    if v is None:
                        c.normalized[metric_name] = 0.0
                    else:
                        c.normalized[metric_name] = round(float(v) / 100.0, 4)
                continue

            values = []
            for c in candidates:
                v = getattr(c, field_name, None)
                if v is not None:
                    values.append(v)

            if not values:
                continue

            lo, hi = min(values), max(values)
            span = hi - lo if hi != lo else 1.0

            lower_is_better = mdef and mdef.direction == "lower_is_better"

            for c in candidates:
                v = getattr(c, field_name, None)
                if v is None:
                    c.normalized[metric_name] = 0.0
                    continue
                raw_norm = (v - lo) / span
                if lower_is_better:
                    raw_norm = 1.0 - raw_norm
                c.normalized[metric_name] = raw_norm

        # 计算加权 composite
        calc = CompositeScoreCalculator(metrics_config)
        for c in candidates:
            # 用 normalized 值作为 round_metrics，history 仅含自身用于归一化
            composite, _ = calc.calculate(c.normalized, [c.normalized])
            c.composite = composite

        return candidates

    @staticmethod
    def format_analysis(candidates: List[CandidateScore],
                        metrics_config: MetricsConfig) -> str:
        """生成归一化过程的人类可读分析文本。"""
        lines = ["## 归一化分析过程", ""]
        quantitative = metrics_config.quantitative_names()

        if not quantitative:
            lines.append("- 仅 result_score 作为量化指标，其他指标仅参考")
            return "\n".join(lines)

        lines.append(f"- 量化指标: {', '.join(quantitative)}")
        lines.append("")

        for name in quantitative:
            values = {}
            for c in candidates:
                label = "基线" if c.candidate_id == -1 else f"Candidate {c.candidate_id}"
                values[label] = c.normalized.get(name, 0)
            lines.append(f"### {name} 归一化")
            for cid, v in values.items():
                lines.append(f"- {cid}: {v:.3f}")
            lines.append("")

        lines.append("### 加权综合分")
        for c in candidates:
            label = "基线" if c.candidate_id == -1 else f"Candidate {c.candidate_id}"
            lines.append(f"- {label}: composite = {c.composite:.1f}")

        return "\n".join(lines)
