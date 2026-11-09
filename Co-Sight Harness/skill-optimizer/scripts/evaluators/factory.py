"""
Evaluators 工厂
================
根据配置创建评测器管道
"""

import json as _json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import BaseEvaluator, EvaluationError, EvaluationResult


def _load_external_config(config_path: str) -> Dict[str, Any]:
    """加载外部评测配置（YAML/JSON）"""
    p = Path(config_path)
    if not p.exists():
        raise FileNotFoundError(f"评测配置文件不存在: {config_path}")

    text = p.read_text(encoding="utf-8")

    try:
        import yaml
        return yaml.safe_load(text) or {}
    except ImportError:
        pass

    return _json.loads(text)


class EvaluatorFactory:
    """
    评测器工厂

    根据配置创建评测器管道，支持链式 fallback
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def create_pipeline(self, args) -> List[BaseEvaluator]:
        """
        根据 args 创建评测器管道

        当前唯一支持的形态：WorkflowPipelineExecutor（业务方完整评测管道）
        pipeline_config_dict 由 orchestrator 从 state_engine.config["pipeline"] 注入
        """
        pipeline_config_dict = getattr(args, 'pipeline_config_dict', None)
        if pipeline_config_dict:
            from .workflow_pipeline import create_pipeline_executor
            _rn = getattr(args, 'round_num', None)
            round_num = _rn if _rn is not None else 1
            pipeline_eval_cmd = getattr(args, 'pipeline_eval_cmd', '') or ''
            pipeline_score_agg = getattr(args, 'pipeline_score_agg', 'mean') or 'mean'
            eval_run = getattr(args, 'eval_run_index', 1)
            # 修复:argparse 默认值为空字符串 "",getattr 的第二参数不会生效
            # 空字符串应视作 'baseline'(否则 baseline 阶段会走 round_0/data)
            eval_mode = getattr(args, 'eval_mode', '') or 'baseline'
            candidate_id = getattr(args, 'candidate_id', -1)

            executor = create_pipeline_executor(
                pipeline_config_dict=pipeline_config_dict,
                pipeline_eval_cmd=pipeline_eval_cmd,
                round_num=round_num,
                non_interactive=getattr(args, 'non_interactive', False),
                score_agg=pipeline_score_agg,
                workspace=str(getattr(args, 'workspace', '.')),
                args=args,
                eval_run=eval_run,
                eval_mode=eval_mode,
                candidate_id=candidate_id,
            )
            return [executor]

        return []

    def evaluate(self, skill_path: str, evaluators: List[BaseEvaluator]) -> EvaluationResult:
        """
        使用评测器管道执行评测
        按顺序尝试每个评测器，失败时 fallback 到下一个
        """
        last_error = None

        for evaluator in evaluators:
            try:
                result = evaluator.evaluate(skill_path)
                if result.is_valid():
                    return result
            except EvaluationError as e:
                last_error = e
                print(f"  ⚠️ {evaluator.evaluator_type} 评测失败: {e}，尝试下一个...")
                continue
            except Exception as e:
                last_error = e
                print(f"  ⚠️ {evaluator.evaluator_type} 评测异常: {e}，尝试下一个...")
                continue

        raise EvaluationError(f"所有评测器都失败，最后错误: {last_error}")
