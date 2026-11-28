"""Text2SQL 配置、语义目录与查询工作台接口。

对外前缀：``{RKB_PREFIX}/text2sql``。路由必须在 ``register_rkb_api`` **之前**
注册 —— 那个路由末尾的 ``/{unknown_path:path}`` 兜底会把晚注册的端点整批吃掉。
"""

from __future__ import annotations

from knowledge_engine.operator import registry
from shared.prefixes import RKB_PREFIX
from text_to_sql.api import build_router
from text_to_sql.operator import get_operator
from text_to_sql.service import Text2SqlService, get_service

TEXT2SQL_PREFIX = f'{RKB_PREFIX}/text2sql'

#: Text2SQL 是知识引擎的第一个 Query Operator；注册只发生一次（幂等）。
registry.register(get_operator())


def register_text_to_sql_api(app, service: Text2SqlService | None = None) -> None:
    app.include_router(build_router(service or get_service()),
                       prefix=TEXT2SQL_PREFIX)
