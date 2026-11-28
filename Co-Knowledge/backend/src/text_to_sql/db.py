"""Text2SQL 领域共用的连接/事务小工具。"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Optional

import psycopg2
import psycopg2.extras


@contextmanager
def transaction():
    """一条连接 + 一个读写事务；异常回滚并抛出，正常提交。"""
    from infrastructure.db.pool import _db_pool

    conn = _db_pool.get_db_conn()
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row(value) -> Optional[dict[str, Any]]:
    return dict(value) if value else None
