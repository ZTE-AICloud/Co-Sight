"""
Score Analyzer 模块 — 格式无关的评测产物扫描与评分
=================================================
扫描任意业务的评测产物（JSON、execution_log、trace），
提取原始指标，同轮内多候选横向比较做 min-max 归一化，
输出结构化 score.json + score_analysis.md。
"""

from .artifact_scanner import ArtifactScanner
from .score_analyzer import ScoreAnalyzerAgent
from .normalizer import RoundNormalizer
from .models import RawMetric, RunScore, CandidateScore, RoundScore

__all__ = [
    "ArtifactScanner",
    "ScoreAnalyzerAgent",
    "RoundNormalizer",
    "RawMetric",
    "RunScore",
    "CandidateScore",
    "RoundScore",
]
