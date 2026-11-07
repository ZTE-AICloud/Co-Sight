"""访问业务库（``rag_studio``）的连接池封装。

库名只有一个来源：``RKB_DB_NAME``（默认 ``rag_studio``）。没有运行态/设计态/发布态
之分，也没有图谱专用的库名覆盖开关。

**延迟 import**：``psycopg2.pool`` 与连接参数模块只在 ``_get_pool()`` 内 import，
模块加载本身不建池、不连库。
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Any

ENV_DB_NAME = 'RKB_DB_NAME'
ENV_POOL_MIN = 'RKB_DB_POOL_MIN'
ENV_POOL_MAX = 'RKB_DB_POOL_MAX'
DEFAULT_DB_NAME = 'rag_studio'
DEFAULT_POOL_MIN = 1
DEFAULT_POOL_MAX = 10

_POOLS: dict[str, Any] = {}
_POOL_LOCK = threading.Lock()


def get_kbase_db_name() -> str:
    """业务库的库名。未设或留空时回落 ``rag_studio``。"""
    return os.environ.get(ENV_DB_NAME, '').strip() or DEFAULT_DB_NAME


def _pool_bounds() -> tuple[int, int]:
    def _int(name: str, default: int) -> int:
        try:
            return int(os.environ.get(name, '') or default)
        except (TypeError, ValueError):
            return default

    minconn = max(0, _int(ENV_POOL_MIN, DEFAULT_POOL_MIN))
    maxconn = max(1, _int(ENV_POOL_MAX, DEFAULT_POOL_MAX))
    return min(minconn, maxconn), maxconn


def _get_pool(dbname: str):
    """按库名懒建 ``ThreadedConnectionPool``。

    连接参数来自 :func:`infrastructure.db.connection_info.get_db_conn_info`，
    与图谱检索等路径同一份来源；只是从「每次裸连」改成复用。
    连接超时固定 2s：DB 不可达时让调用方（尤其是 trace 写线程）尽快失败，
    不要把线程池/请求拖到 OS TCP 超时。
    """
    pool = _POOLS.get(dbname)
    if pool is not None:
        return pool
    with _POOL_LOCK:
        pool = _POOLS.get(dbname)
        if pool is not None:
            return pool
        from psycopg2.pool import ThreadedConnectionPool
        from infrastructure.db.connection_info import get_db_conn_info

        info = get_db_conn_info()
        minconn, maxconn = _pool_bounds()
        pool = ThreadedConnectionPool(
            minconn, maxconn,
            user=info.get('user'),
            password=info.get('password'),
            host=info.get('host'),
            port=info.get('port'),
            database=dbname,
            connect_timeout=2,
        )
        _POOLS[dbname] = pool
        return pool


def close_pools() -> None:
    """关闭全部连接池（测试/进程退出用）。"""
    with _POOL_LOCK:
        for pool in list(_POOLS.values()):
            try:
                pool.closeall()
            except Exception:                                      # noqa: BLE001
                pass
        _POOLS.clear()


@contextmanager
def connection():
    """从连接池借一条连接，**带完整事务语义**。

    正常退出时 ``commit()``，出异常时 ``rollback()`` 后把异常抛出去；最后把连接
    还给池（连接已断时 ``putconn(close=True)``，不把坏连接放回池）。

    需要跨多条语句的原子性时，全放在**同一个** ``with`` 里；``with`` 结束即提交。
    """
    pool = _get_pool(get_kbase_db_name())
    conn = pool.getconn()
    returned = False
    try:
        yield conn
    except Exception:
        # 回滚本身失败（连接已被对端断开/关闭）不能顶掉原始异常，否则真正的错因会丢
        try:
            conn.rollback()
        except Exception:                                          # noqa: BLE001
            pass
        raise
    else:
        try:
            conn.commit()
        except Exception:
            # commit 失败时连接可能仍显示 open，但事务已不可用；直接销毁。
            pool.putconn(conn, close=True)
            returned = True
            raise
    finally:
        if not returned:
            pool.putconn(conn, close=bool(getattr(conn, 'closed', 0)))
