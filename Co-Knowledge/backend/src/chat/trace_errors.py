"""查询追踪读接口的存储错误（与 engine 的 RagException 分开）。"""
from __future__ import annotations


class QueryTraceStoreUnavailable(RuntimeError):
    """`chat_query_trace` 不存在或数据库不可用；API 映射为 503 problem。"""
