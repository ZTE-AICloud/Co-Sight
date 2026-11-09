"""
CompositeScoreCalculator — 加权复合分数计算
============================================
将多维度指标归一化后加权求和，得到 0-100 的综合分数。

公式：composite = sum(w_i * normalized(metric_i)) * 100

仅对 quantitative=True 且 weight>0 的指标参与计算。
"""

from typing import Any, Dict, List, Tuple

from .config import MetricDefinition, MetricsConfig


class CompositeScoreCalculator:
    """加权复合分数计算器。"""

    def __init__(self, config: MetricsConfig):
        self._config = config

    def normalize_value(
        self,
        value: float,
        metric: MetricDefinition,
        all_values: List[float],
    ) -> float:
        """
        归一化指标值到 [0, 1]。

        Args:
            value: 当前值
            metric: 指标定义
            all_values: 历史所有值（含当前），用于 min_max 归一化范围

        Returns:
            [0, 1] 范围内的归一化值
        """
        if metric.normalization == "none":
            # 假设已经是 0-100 尺度
            if value > 1:
                return value / 100.0
            return value

        if metric.normalization == "linear":
            return value / 100.0

        if metric.normalization == "min_max":
            valid = [v for v in all_values if v is not None]
            if not valid:
                return 0.0
            min_v = min(valid)
            max_v = max(valid)

            if max_v == min_v:
                # 所有值相同：lower_is_better 认为已最优 → 1.0
                return 1.0 if metric.direction == "lower_is_better" else 1.0

            norm = (value - min_v) / (max_v - min_v)

            # lower_is_better 需要反转
            if metric.direction == "lower_is_better":
                return 1.0 - norm
            return norm

        return 0.0

    def calculate(
        self,
        round_metrics: Dict[str, float],
        history: List[Dict[str, float]],
    ) -> Tuple[float, Dict[str, float]]:
        """
        计算复合分数。

        Args:
            round_metrics: 当前轮指标值 {name: value}
            history: 历史所有轮指标值 [{name: value}, ...]

        Returns:
            (composite_score 0-100, {metric_name: normalized_value})
        """
        quantitative = [
            m for m in self._config.metrics.values()
            if m.quantitative and m.weight > 0
        ]

        if not quantitative:
            # 无量化指标：回退到 result_score
            return round_metrics.get("result_score", 0.0), {}

        total_weight = sum(m.weight for m in quantitative)
        if total_weight == 0:
            return round_metrics.get("result_score", 0.0), {}

        normalized_scores: Dict[str, float] = {}
        weighted_sum = 0.0

        for metric in quantitative:
            value = round_metrics.get(metric.name)
            if value is None:
                continue

            # 收集历史值用于归一化
            all_values: List[float] = [value]
            for h in history:
                hv = h.get(metric.name)
                if hv is not None:
                    all_values.append(hv)

            norm = self.normalize_value(value, metric, all_values)
            normalized_scores[metric.name] = norm

            weight_ratio = metric.weight / total_weight
            # normalized 已经是 0-1（lower_is_better 已反转），越高越好
            weighted_sum += weight_ratio * norm

        return round(weighted_sum * 100, 1), normalized_scores
