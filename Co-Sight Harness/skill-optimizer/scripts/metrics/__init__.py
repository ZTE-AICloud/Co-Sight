"""
Metrics 模块 — 多维度指标驱动优化
===================================
指标配置、收集、复合分数计算。

用法：
    from metrics import MetricsConfig, MetricsCollector, CompositeScoreCalculator
    config = MetricsConfig.default_single_metric()
    collector = MetricsCollector(config)
"""

from .config import MetricDefinition, MetricsConfig
from .collector import MetricsCollector
from .composite import CompositeScoreCalculator

__all__ = [
    "MetricDefinition",
    "MetricsConfig",
    "MetricsCollector",
    "CompositeScoreCalculator",
]
