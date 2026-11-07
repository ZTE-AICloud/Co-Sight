"""Knowledge-base schema and SQL-identifier guards.

Table names are assembled by callers (``data_`` + base name) and cannot be
parameterised, so every dynamic identifier goes through :func:`validate_identifier`.
This module is intentionally dependency-free so both ``infrastructure.db.ddl``
and the knowledge-base repositories can use it without a layering cycle.
"""
from __future__ import annotations

import re

SCHEMA = 'kb_index'

_IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def validate_identifier(name: str) -> str:
    """Whitelist a SQL identifier; all legitimate table names pass unchanged."""
    if not _IDENTIFIER.match(name or ''):
        raise ValueError(f'illegal SQL identifier: {name!r}')
    return name


#: 文档库动态表的角色后缀。``kb_kbase.table_name`` 存的是向量表名
#: （``doc_<kbase_id>_vector``），切片表由它派生（``doc_<kbase_id>_chunk``）。
DOC_VECTOR_SUFFIX = '_vector'


def doc_vector_table(kbase_id: str) -> str:
    """文档库向量表名：``doc_<kbase_id>_vector``。"""
    return f'doc_{kbase_id}{DOC_VECTOR_SUFFIX}'


def chunk_table_for(vector_or_base: str) -> str:
    """由 ``kb_kbase.table_name`` 派生切片表名。

    * 文档库传向量表名 ``doc_<id>_vector`` → ``doc_<id>_chunk``；
    * 图谱库传基名 ``graph_<id>`` → ``graph_<id>_chunk``。
    """
    if vector_or_base.endswith(DOC_VECTOR_SUFFIX):
        return vector_or_base[:-len(DOC_VECTOR_SUFFIX)] + '_chunk'
    return vector_or_base + '_chunk'
