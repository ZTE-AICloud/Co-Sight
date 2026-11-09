"""
Evaluators - 评测系统
====================
评测器基础类型、工厂函数、执行器。

用法：
    from evaluators import EvaluatorFactory, EvaluationResult

    factory = EvaluatorFactory()
    evaluators = factory.create_pipeline(args)
    result = factory.evaluate(skill_path, evaluators)
"""

from .base import BaseEvaluator, EvaluationResult, EvaluationError
from .factory import EvaluatorFactory
from .workflow_pipeline import WorkflowPipelineExecutor, create_pipeline_executor

__all__ = [
    "BaseEvaluator",
    "EvaluationResult",
    "EvaluationError",
    "EvaluatorFactory",
    "WorkflowPipelineExecutor",
    "create_pipeline_executor",
]
