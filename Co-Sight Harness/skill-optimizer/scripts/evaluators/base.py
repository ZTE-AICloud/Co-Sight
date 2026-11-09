"""
评测器基类定义
==============
定义 Evaluator 接口和 EvaluationResult 数据类
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EvaluationResult:
    """
    评测结果

    Attributes:
        score: 综合评分 (0-100)
        rating: 质量评级 (EXCELLENT/GOOD/FAIR/POOR/BROKEN)
        gaps: 缺口列表
        improvements: 改进建议
        evaluator_type: 评测器类型
        metadata: 额外元数据
    """
    score: float
    rating: str
    gaps: List[Dict[str, Any]] = field(default_factory=list)
    improvements: List[str] = field(default_factory=list)
    regression_tests: List[str] = field(default_factory=list)
    evaluator_type: str = "base"
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def total_gaps(self) -> int:
        """缺口总数"""
        return len(self.gaps)

    def is_valid(self) -> bool:
        """是否有效"""
        return 0 <= self.score <= 100

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_score": self.score,
            "quality_rating": self.rating,
            "total_gaps": self.total_gaps,
            "gaps": self.gaps,
            "improvements": self.improvements,
            "regression_tests": self.regression_tests,
            "evaluator_type": self.evaluator_type,
            "metadata": self.metadata,
        }


class BaseEvaluator(ABC):
    """
    评测器抽象基类

    所有评测器必须实现 evaluate() 方法
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    @abstractmethod
    def evaluate(self, skill_path: str) -> EvaluationResult:
        """
        执行评测

        Args:
            skill_path: Skill 文件路径

        Returns:
            评测结果

        Raises:
            EvaluationError: 评测失败时抛出
        """
        pass

    @property
    @abstractmethod
    def evaluator_type(self) -> str:
        """评测器类型标识"""
        pass

    def validate_skill_path(self, skill_path: str) -> bool:
        """验证 skill 路径"""
        import os
        return os.path.isfile(skill_path)


class EvaluationError(Exception):
    """评测异常"""
    pass