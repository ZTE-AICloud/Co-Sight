"""NL2Graph：自然语言 → 图查询（复用 graph 域的查询运行时）。"""

from knowledge_engine.operator import registry
from graph_operator.operator import Nl2GraphOperator, get_operator

registry.register(get_operator())

__all__ = ['Nl2GraphOperator', 'get_operator']
