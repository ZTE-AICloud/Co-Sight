"""NL2API：把自然语言变成 OpenAPI 里的一次调用。

知识对象来自 OpenAPI spec（``API`` + 每个 ``ENDPOINT``），执行时只允许调用
spec 里声明过的 method+path，且 URL 必须由 spec 的 server 前缀拼出——
这是与外部世界交互的算子，边界比 SQL 更硬。
"""

from knowledge_engine.operator import registry
from api_operator.operator import Nl2ApiOperator, get_operator

registry.register(get_operator())

__all__ = ['Nl2ApiOperator', 'get_operator']
