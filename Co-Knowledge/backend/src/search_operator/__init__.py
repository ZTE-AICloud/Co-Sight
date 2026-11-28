"""NL2Search：把自然语言变成 Elasticsearch 查询 DSL 的 Query Operator。

知识对象来自索引 mapping（``INDEX`` + 每个 ``FIELD``），检索只用 BM25 一路——
mapping 是几十到几百个字段的小语料，够用且不引入额外索引。
"""

from knowledge_engine.operator import registry
from search_operator.operator import Nl2SearchOperator, get_operator

registry.register(get_operator())

__all__ = ['Nl2SearchOperator', 'get_operator']
