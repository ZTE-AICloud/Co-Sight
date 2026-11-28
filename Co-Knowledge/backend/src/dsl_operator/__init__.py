"""NL2DSL：自然语言 → 告警规则 DSL（类型化 AST + 编译器）。"""

from knowledge_engine.operator import registry
from dsl_operator.operator import Nl2DslOperator, get_operator

registry.register(get_operator())

__all__ = ['Nl2DslOperator', 'get_operator']
