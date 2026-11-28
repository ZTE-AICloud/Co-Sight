"""知识引擎：多个「自然语言 → 结构化查询」算子共用的最小内核。

只放**领域无关**的四件事：

* :mod:`knowledge_engine.object`   —— 知识对象的公共形状；
* :mod:`knowledge_engine.retrieval` —— 向量 + BM25 → RRF →（可选）重排；
* :mod:`knowledge_engine.operator`  —— Query Operator 契约与注册表；
* :mod:`knowledge_engine.policy`    —— 执行期的行/字节/超时策略。

领域数据（表、图谱 schema、OpenAPI 文档……）**不**放在这里：每个算子仍然拥有
自己的表与自己的投影逻辑，引擎只负责「按契约检索、按契约执行」。
"""

from knowledge_engine.object import KnowledgeObject
from knowledge_engine.operator import (OperatorRegistry, OperatorContext,
                                       QueryOperator, QueryPlan, ResultSet,
                                       ValidatedPlan)

__all__ = ['KnowledgeObject', 'OperatorRegistry', 'OperatorContext',
           'QueryOperator', 'QueryPlan', 'ResultSet', 'ValidatedPlan']
