"""
MetricsCollector — 指标收集器
=============================
追踪每轮的耗时、result_score 等指标。

用法：
    collector = MetricsCollector(metrics_config)
    collector.start_phase(round_num, "evaluate")
    # ... 执行评测 ...
    collector.end_phase(round_num, "evaluate")
    collector.record(round_num, "result_score", 72.5)
    collector.save_to_config(config_dict)
"""

import time
from typing import Any, Dict, List, Optional

from .config import MetricsConfig


class MetricsCollector:
    """指标收集器。"""

    def __init__(self, config: MetricsConfig):
        self._config = config
        # {round_num: {metric_name: value, ...}, ...}
        self._round_data: Dict[int, Dict[str, float]] = {}
        # {(round_num, phase): monotonic_start, ...}
        self._timers: Dict[tuple, float] = {}
        # 归一化基线值 {metric_name: [values...]}
        self._value_history: Dict[str, List[float]] = {}

    # ── 耗时追踪 ──────────────────────────────────────────

    def start_phase(self, round_num: int, phase: str) -> None:
        """标记阶段开始。"""
        self._timers[(round_num, phase)] = time.monotonic()

    def end_phase(self, round_num: int, phase: str) -> float:
        """标记阶段完成，返回耗时（秒）。"""
        key = (round_num, phase)
        start = self._timers.pop(key, None)
        if start is None:
            return 0.0
        elapsed = time.monotonic() - start
        self.record(round_num, f"phase_{phase}_seconds", elapsed)
        return elapsed

    def get_total_round_duration(self, round_num: int) -> float:
        """某轮所有 phase 耗时总和。"""
        data = self._round_data.get(round_num, {})
        return sum(
            v for k, v in data.items()
            if k.startswith("phase_") and k.endswith("_seconds")
        )

    # ── 指标记录 ──────────────────────────────────────────

    def record(self, round_num: int, name: str, value: float) -> None:
        """记录一个指标值。"""
        if round_num not in self._round_data:
            self._round_data[round_num] = {}
        self._round_data[round_num][name] = float(value)

        # 维护值历史（供归一化使用）
        if name not in self._value_history:
            self._value_history[name] = []
        self._value_history[name].append(float(value))

    def get_round_metrics(self, round_num: int) -> Dict[str, float]:
        """获取某轮的指标。"""
        return dict(self._round_data.get(round_num, {}))

    def get_all_history(self) -> List[Dict[str, Any]]:
        """返回所有轮次的指标历史 [{round, metrics, composite_score}, ...]。"""
        from .composite import CompositeScoreCalculator

        result = []
        calc = CompositeScoreCalculator(self._config)

        for rn in sorted(self._round_data.keys()):
            data = dict(self._round_data[rn])
            composite, _ = calc.calculate(data, list(self._round_data.values()))
            entry = {"round": rn}
            entry.update(data)
            entry["composite_score"] = composite
            entry["total_duration_seconds"] = self.get_total_round_duration(rn)
            result.append(entry)

        return result

    def save_to_config(self, config: Dict[str, Any]) -> None:
        """将指标写入 config.json。"""
        history = self.get_all_history()
        config["metrics_history"] = history

        # 最新轮次的 composite_score
        if history:
            config["current_composite_score"] = history[-1].get("composite_score", 0)

        # 指标配置快照
        config["metrics_config"] = {
            "metrics": {
                name: {
                    "weight": m.weight,
                    "direction": m.direction,
                    "quantitative": m.quantitative,
                    "normalization": m.normalization,
                    "display_name": m.display_name,
                    "unit": m.unit,
                }
                for name, m in self._config.metrics.items()
            },
            "composite_formula": self._config.composite_formula,
        }

    # ── 诊断 ──────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """生成指标摘要。"""
        history = self.get_all_history()
        if not history:
            return {"total_rounds": 0}

        total_duration = sum(h.get("total_duration_seconds", 0) for h in history)
        avg_composite = sum(h.get("composite_score", 0) for h in history) / len(history)

        return {
            "total_rounds": len(history),
            "total_duration_seconds": round(total_duration, 1),
            "avg_composite_score": round(avg_composite, 1),
            "best_composite_score": round(max(h.get("composite_score", 0) for h in history), 1),
        }
