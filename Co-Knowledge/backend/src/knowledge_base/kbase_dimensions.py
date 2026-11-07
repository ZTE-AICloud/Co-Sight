"""绑定基名 → 物理向量表维度（画布校验用）。

画布上存的是**检索基名**（``graph_<uuid>`` / ``doc_<uuid>``，可能带 ``|#|dev`` 一类的
scope 后缀），对应的物理向量表是 ``kb_index.<基名>_vector``（文档库与图谱库同一规则，
见 ``infrastructure/db/ddl`` 的建表模板）。

**为什么维度必须读物理列**：``kb_storage_registry.embedding_dim`` 是建库时的尽力而为
记录 —— 图谱导入走的 ``graph_import_api`` 不写这张表，旧行也可能是 NULL。
只有 ``vector(N)`` 这一列是事实。

读不到（表没建、名字非法、库抖动）一律**不出现在结果里**，调用方据此「无法判定」放行。
"""

from __future__ import annotations

from typing import Iterable

from infrastructure.db import ddl
from infrastructure.logging.logutil import log
from shared.kb_names import drop_scope_suffix

#: 物理向量表的后缀（``graph_<uuid>`` → ``graph_<uuid>_vector``）
VECTOR_TABLE_SUFFIX = '_vector'


def vector_table_name(base_name: str) -> str:
    """基名 → 物理向量表名（已经是 ``_vector`` 结尾的不重复追加）。"""
    if base_name.endswith(VECTOR_TABLE_SUFFIX):
        return base_name
    return base_name + VECTOR_TABLE_SUFFIX


def dimensions_for(names: Iterable[str]) -> dict[str, int]:
    """``{画布基名: 物理向量维度}``；读不到的基名**不出现在结果里**。

    键保留**画布上的原名**（含 scope 后缀），因为校验是拿画布里的字符串去匹配的；
    查表时才去掉后缀。
    """
    dimensions: dict[str, int] = {}
    for raw in names:
        if not isinstance(raw, str):
            continue
        name = raw.strip()
        if not name or name in dimensions:
            continue
        table = vector_table_name(drop_scope_suffix(name))
        dimension = ddl.vector_dimension(table)
        if dimension:
            dimensions[name] = dimension
        else:
            log.info('vector dimension unavailable for kbase %r (table %s)', name, table)
    return dimensions
