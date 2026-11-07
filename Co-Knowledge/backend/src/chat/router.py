"""编排路由的装配入口。

本模块把编排的 ``POST <prefix>/query`` 挂到宿主应用上；前缀由宿主决定
（当前是 ``shared.prefixes.RKB_PREFIX``）。``stream=true`` 时以 SSE 返回。

健康检查统一由 kb_api 的 ``GET <prefix>/health`` 提供。

**挂载顺序有硬要求**：RKB 必须在 `register_rkb_api(app)` **之前**调用本函数。
kb_api 接口层带一条兜底路由 ``@router.api_route('/{unknown_path:path}')``
（`http_api.py`），同一前缀下它会**吃掉**后面注册的 ``/query`` ——
症状是提问拿到 ``0005 + msg:null`` 信封而不是报错，极难排查。
"""

from __future__ import annotations

from fastapi import FastAPI

from shared.prefixes import RKB_PREFIX
from chat.app import router as query_router
from chat.trace_api import router as trace_router

#: 本服务的对外前缀（宿主的单点常量）。
#: 单测据此按**生产同形的路径**发请求 —— 不要打根路径，生产并没有根路径。
DEFAULT_PREFIX = RKB_PREFIX


def register_query_api(app: FastAPI, prefix: str) -> None:
    """把编排的 ``/query`` 与只读 ``/query-traces`` 挂到 ``app`` 上。"""
    app.include_router(query_router, prefix=prefix)
    app.include_router(trace_router, prefix=prefix)
