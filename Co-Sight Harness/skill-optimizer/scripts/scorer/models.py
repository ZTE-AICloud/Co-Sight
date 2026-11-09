"""
Score Analyzer 数据模型
=======================
定义评测评分的核心数据结构。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class RawMetric:
    """一个 run 的原始指标（单维度 result_score + info 原始值）。"""
    round_num: int
    candidate_id: int        # -1=baseline, >=1=candidate（从 1 开始）
    run_index: int
    # 单维度分数（百分制 0~100,2 位小数）
    result_score: Optional[float] = None       # 结果分数 百分制 0~100
    # 原始指标（info 嵌套字段,仅 result_score 相关）
    info: Optional[dict] = None                # {result_score_raw, result_score_source, ...}


@dataclass
class RunScore:
    """一个 run 的评分输出。"""
    raw: RawMetric
    reasoning: str = ""              # "发现 score=72.5 来自 results[0].scores.component_f1"
    analysis_path: Optional[str] = None  # score_analysis.md 路径


@dataclass
class CandidateScore:
    """一个候选在同轮中的聚合分数。"""
    round_num: int
    candidate_id: int
    strategy: str = ""               # 优化策略名
    runs: List[RunScore] = field(default_factory=list)  # 各 run 详情
    # 聚合值（跨 run 平均,百分制 0~100）
    avg_result_score: float = 0.0
    # 归一化值（同轮内 min-max 后落 0~1 区间,用于 composite 加权）
    normalized: Dict[str, float] = field(default_factory=dict)  # {metric_name: 0~1}
    composite: float = 0.0           # 加权综合分 (0-100)
    # 稳定性指标（跨 run,百分制 0~100）
    stddev: float = 0.0              # 标准差（百分制 0~100）
    cv: float = 0.0                  # 变异系数 = stddev/avg (0~1)
    # 跨 run CASE 分数矩阵（解决"6/6 CASE 跨 run 0↔非 0 波动"未被识别的问题）
    # {case_id: [run1_score, run2_score, run3_score, ...]}
    case_run_matrix: Dict[str, List[float]] = field(default_factory=dict)
    # per-case 稳定性（同一字段名，但 key 是 case_id）
    per_case_stddev: Dict[str, float] = field(default_factory=dict)
    per_case_cv: Dict[str, float] = field(default_factory=dict)
    # 资源消耗聚合(口径从 sum 改 per-case + mean,与 result_score 一致)
    # per-case 字典是 source of truth,mean 字段是聚合结果(框架算,不是 LLM 算)
    # 缺失 case(token=0/duration=0)自动从 mean 分母中隔离,避免 sum 口径被 0 拉低
    per_case_input_tokens: Dict[str, int] = field(default_factory=dict)        # {case_id: tokens}
    per_case_output_tokens: Dict[str, int] = field(default_factory=dict)       # {case_id: tokens}
    per_case_duration_ms: Dict[str, int] = field(default_factory=dict)         # {case_id: ms}
    valid_token_case_count: int = 0      # token>0 的 case 数(mean 分母)
    valid_duration_case_count: int = 0   # duration_ms>0 的 case 数
    mean_input_tokens: int = 0          # macro-mean over cases(token>0)
    mean_output_tokens: int = 0
    mean_duration_ms: int = 0           # macro-mean over cases(duration_ms>0)
    mean_duration_seconds: float = 0.0
    # 旧字段(deprecated,保留作向后兼容 1-2 版本;sum 口径,会被 0 拉低)
    total_input_tokens: int = 0          # 跨 run 输入 token 合计
    total_output_tokens: int = 0         # 跨 run 输出 token 合计
    total_duration_ms: int = 0           # 跨 run 耗时合计（ms）
    # 资源消耗稳定性(跨 run 波动,模式同 score 的 stddev/cv)
    # 单 run 时 stddev/cv=0(与 score 行为一致)。CV 基于 mean(与 result_score 一致)。
    stddev_input_tokens: int = 0         # 输入 token 标准差
    cv_input_tokens: float = 0.0         # 输入 token 变异系数 = stddev/mean
    stddev_output_tokens: int = 0        # 输出 token 标准差
    cv_output_tokens: float = 0.0        # 输出 token 变异系数
    stddev_duration_ms: int = 0          # 耗时标准差（ms）
    cv_duration_ms: float = 0.0          # 耗时变异系数
    # f1 跨 run 聚合（与 token/duration 模式一致；f1 不能 sum 只 mean）
    avg_f1: float = 0.0                  # 跨 run f1 平均（百分制 0~100，2 位小数）
    stddev_f1: float = 0.0               # 跨 run f1 标准差（保留 4 位小数，f1 是浮点不能用 int）
    cv_f1: float = 0.0                   # 跨 run f1 变异系数
    per_run_f1: list = field(default_factory=list)  # 每个 run 的 f1（按 run_index 顺序）


@dataclass
class RoundScore:
    """一轮的完整评分。"""
    round_num: int
    baseline_score: Optional[CandidateScore] = None
    candidates: List[CandidateScore] = field(default_factory=list)
    best_candidate_id: Optional[int] = None
    timestamp: str = ""
