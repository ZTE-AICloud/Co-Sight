"""``public.agent_api_key`` 的 PostgreSQL 读写。

连接走 ``infrastructure.db.kb.connection()``（P1 起统一用 ``ThreadedConnectionPool``，
库名由 ``RKB_DB_NAME`` / 默认 ``rag_studio`` 决定），与知识库元数据同库。

**异常策略**：表不存在（``pgcode == '42P01'``，数据库未初始化）统一收成 :class:`AgentKeyStoreUnavailable`，
由 auth 层回 503；其余数据库异常原样抛，不静默返回空结果 —— 否则「Key 不存在」
与「库挂了」在调用方看起来一样，会变成 401 而不是 503，误导排查。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from infrastructure.db.rows import rows as _rows

from agent.errors import AgentKeyStoreUnavailable

TABLE = 'public.agent_api_key'
USAGE_TABLE = 'public.agent_api_key_usage'

#: 对外的列（不含 key_hash）
_PUBLIC_COLUMNS = (
    'key_prefix, name, description, scopes, kb_ids, rate_limit_per_min, enabled, '
    'expires_at, last_used_at, created_by, created_at, updated_at'
)

_MISSING_TABLE_PGCODE = '42P01'


def _connection():
    """延迟 import ``infrastructure.db.kb``。

    该包的 ``__init__`` 会 import ``router``（进而 import FastAPI）。CLI 的
    ``--help`` 不该因此拉起整棵 Web 依赖树，所以连接只在真正要用时取。
    """
    from infrastructure.db.kb import connection

    return connection()


def _missing_table(error: Exception) -> bool:
    return getattr(error, 'pgcode', None) == _MISSING_TABLE_PGCODE


def _raise_if_missing(error: Exception) -> None:
    if _missing_table(error):
        raise AgentKeyStoreUnavailable() from error


def find_by_prefix(prefix: str) -> Optional[dict[str, Any]]:
    """按 ``key_prefix`` 取一行（含 ``key_hash``，供 auth 常量时间比较）。"""
    try:
        with _connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f'SELECT {_PUBLIC_COLUMNS}, key_hash FROM {TABLE} '
                    'WHERE key_prefix = %s',
                    (prefix,),
                )
                result = _rows(cursor)
    except Exception as error:                                     # noqa: BLE001
        _raise_if_missing(error)
        raise
    return result[0] if result else None


def insert_key(*, name: str, key_prefix: str, key_hash: str,
               scopes: list[str], kb_ids: list[str], rate_limit_per_min: int,
               description: Optional[str] = None, expires_at=None,
               created_by: Optional[str] = None) -> None:
    """插入一把 Key。``key_prefix`` 冲突由调用方重试（DB 唯一约束兜底）。"""
    try:
        with _connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f'INSERT INTO {TABLE} '
                    '(name, description, key_prefix, key_hash, scopes, kb_ids, '
                    ' rate_limit_per_min, expires_at, created_by) '
                    'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
                    (name, description, key_prefix, key_hash, list(scopes),
                     list(kb_ids), int(rate_limit_per_min), expires_at,
                     created_by),
                )
    except Exception as error:                                     # noqa: BLE001
        _raise_if_missing(error)
        raise


def get_key(key_prefix: str) -> Optional[dict[str, Any]]:
    """管理视图单行：只取 ``_PUBLIC_COLUMNS``，**绝不 SELECT key_hash**。"""
    try:
        with _connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f'SELECT {_PUBLIC_COLUMNS} FROM {TABLE} '
                    'WHERE key_prefix = %s',
                    (key_prefix,),
                )
                result = _rows(cursor)
    except Exception as error:                                     # noqa: BLE001
        _raise_if_missing(error)
        raise
    return result[0] if result else None


#: 部分更新的哨兵：区分「没传这个字段」与「显式传 None（清空过期时间）」。
_UNSET = object()

#: 允许更新的列（固定白名单，调用方不能拼 SQL）。
_UPDATABLE_COLUMNS = {
    'name': 'name',
    'description': 'description',
    'scopes': 'scopes',
    'kb_ids': 'kb_ids',
    'rate_limit_per_min': 'rate_limit_per_min',
    'expires_at': 'expires_at',
    'enabled': 'enabled',
}


def update_key(key_prefix: str, *, name=_UNSET, description=_UNSET,
               scopes=_UNSET, kb_ids=_UNSET, rate_limit_per_min=_UNSET,
               expires_at=_UNSET, enabled=_UNSET) -> Optional[dict[str, Any]]:
    """局部更新并返回更新后的公开行；前缀不存在返回 ``None``。

    ``UPDATE ... RETURNING`` 一次完成写与读，避免「先查再改再查」的竞态。所有
    列名来自 :data:`_UPDATABLE_COLUMNS`，值全部走参数绑定。
    """
    values = {
        'name': name,
        'description': description,
        'scopes': scopes,
        'kb_ids': kb_ids,
        'rate_limit_per_min': rate_limit_per_min,
        'expires_at': expires_at,
        'enabled': enabled,
    }
    fields = [(column, value) for column, value in values.items()
              if value is not _UNSET]
    if not fields:
        raise ValueError('no fields to update')

    assignments = ', '.join(f'{_UPDATABLE_COLUMNS[column]} = %s'
                            for column, _value in fields)
    params = [value for _column, value in fields]
    params.append(key_prefix)
    try:
        with _connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f'UPDATE {TABLE} SET {assignments} '
                    f'WHERE key_prefix = %s RETURNING {_PUBLIC_COLUMNS}',
                    tuple(params),
                )
                result = _rows(cursor)
    except Exception as error:                                     # noqa: BLE001
        _raise_if_missing(error)
        raise
    return result[0] if result else None


def ping() -> bool:
    """Key 表可用性探针：表缺失转 :class:`AgentKeyStoreUnavailable`。

    只看表是否存在，不关心有没有行（``LIMIT 0``）。DB 连不上等其它异常原样抛，
    由状态端点记日志后报 ``keyStoreAvailable=false``。
    """
    try:
        with _connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(f'SELECT 1 FROM {TABLE} LIMIT 0')
        return True
    except Exception as error:                                     # noqa: BLE001
        _raise_if_missing(error)
        raise


def list_keys() -> list[dict[str, Any]]:
    """管理视图：不含 ``key_hash``，按创建时间倒序。"""
    try:
        with _connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f'SELECT {_PUBLIC_COLUMNS} FROM {TABLE} '
                    'ORDER BY created_at DESC, key_prefix')
                return _rows(cursor)
    except Exception as error:                                     # noqa: BLE001
        _raise_if_missing(error)
        raise


def set_enabled(key_prefix: str, enabled: bool) -> int:
    """启停一把 Key；返回受影响行数（0 = 前缀不存在）。"""
    try:
        with _connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f'UPDATE {TABLE} SET enabled = %s WHERE key_prefix = %s',
                    (bool(enabled), key_prefix),
                )
                return cursor.rowcount
    except Exception as error:                                     # noqa: BLE001
        _raise_if_missing(error)
        raise


def delete_key(key_prefix: str) -> int:
    """硬删除（审计场景优先用 ``set_enabled(False)``）。"""
    try:
        with _connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f'DELETE FROM {TABLE} WHERE key_prefix = %s', (key_prefix,))
                return cursor.rowcount
    except Exception as error:                                     # noqa: BLE001
        _raise_if_missing(error)
        raise


def touch_last_used(key_prefix: str) -> bool:
    """尽力更新 ``last_used_at``；失败不影响本次请求（返回 False）。"""
    try:
        with _connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f'UPDATE {TABLE} SET last_used_at = now() WHERE key_prefix = %s',
                    (key_prefix,),
                )
        return True
    except Exception:                                              # noqa: BLE001
        return False


def record_usage(key_prefix: str, usage_date: date) -> bool:
    """给 ``(key_prefix, usage_date)`` 累加一次调用；失败不影响本次请求。

    与 ``touch_last_used`` 一样是 best-effort：表可能不存在，这里静默返回 False，鉴权照常通过（页面上的两个调用量指标显示 0）。
    """
    try:
        with _connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f'INSERT INTO {USAGE_TABLE} '
                    '(key_prefix, usage_date, request_count) VALUES (%s, %s, 1) '
                    'ON CONFLICT (key_prefix, usage_date) DO UPDATE '
                    'SET request_count = agent_api_key_usage.request_count + 1',
                    (key_prefix, usage_date),
                )
        return True
    except Exception:                                              # noqa: BLE001
        return False


def usage_summary(since_date: date) -> dict[str, Any]:
    """累计调用量与 ``since_date``（含）之后的调用量，各 Key 求和。

    表缺失 → :class:`AgentKeyStoreUnavailable`，与其它管理接口一样
    由调用方回 503；这里不静默返回 0，否则「没统计」和「库挂了」无法区分。
    """
    try:
        with _connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT COALESCE(SUM(request_count), 0) AS total_calls, '
                    'COALESCE(SUM(request_count) FILTER (WHERE usage_date >= %s), 0) '
                    f'AS calls_7d FROM {USAGE_TABLE}',
                    (since_date,),
                )
                result = _rows(cursor)
    except Exception as error:                                     # noqa: BLE001
        _raise_if_missing(error)
        raise
    if not result:
        return {'total_calls': 0, 'calls_7d': 0}
    return result[0]
