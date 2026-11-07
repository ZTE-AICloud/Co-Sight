"""``auth_user`` / ``auth_session`` 的 PostgreSQL 读写。

连接走 ``infrastructure.db.kb.connection()``（与知识库元数据同库，默认
``rag_studio``）。**延迟 import**：CLI 的 ``--help`` 不该拉起整棵 Web 依赖树。

异常策略：表不存在（``pgcode == '42P01'``）统一收成 ``AuthStoreUnavailable``，
由 API 回 503；其余数据库异常原样抛，不静默返回空结果 —— 否则「账号不存在」
与「库挂了」在调用方看起来一样，会变成 401 而不是 503。
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator, Optional

from auth.errors import AuthStoreUnavailable
from auth.schema import SESSION_TABLE, USER_TABLE
from infrastructure.db.rows import rows as _rows

_MISSING_TABLE_PGCODE = '42P01'

_USER_COLUMNS = (
    'id, username, email, display_name, password_hash, role, enabled, '
    'must_change_password, created_at, updated_at, last_login_at'
)


def _connection():
    from infrastructure.db.kb import connection

    return connection()


@contextmanager
def _cursor() -> Iterator[Any]:
    """借一条连接/游标；``with`` 退出即 commit，异常回滚并翻译缺表。"""
    try:
        with _connection() as conn:
            with conn.cursor() as cursor:
                yield cursor
    except Exception as error:                                     # noqa: BLE001
        if getattr(error, 'pgcode', None) == _MISSING_TABLE_PGCODE:
            raise AuthStoreUnavailable() from error
        raise


def _one(cursor) -> Optional[dict[str, Any]]:
    result = _rows(cursor)
    return result[0] if result else None


def table_exists() -> bool:
    with _cursor() as cursor:
        cursor.execute('SELECT to_regclass(%s)', (USER_TABLE,))
        row = cursor.fetchone()
        return bool(row and row[0])


def count_users() -> int:
    with _cursor() as cursor:
        cursor.execute(f'SELECT count(*) FROM {USER_TABLE}')
        return int(cursor.fetchone()[0])


def list_users() -> list[dict[str, Any]]:
    with _cursor() as cursor:
        cursor.execute(
            f'SELECT {_USER_COLUMNS} FROM {USER_TABLE} ORDER BY lower(username)')
        return _rows(cursor)


def find_user_by_login(login: str) -> Optional[dict[str, Any]]:
    """按用户名或邮箱查找（大小写不敏感）；用户名命中优先。"""
    with _cursor() as cursor:
        cursor.execute(
            f'SELECT {_USER_COLUMNS} FROM {USER_TABLE} '
            'WHERE lower(username) = lower(%s) '
            '   OR (email IS NOT NULL AND lower(email) = lower(%s)) '
            'ORDER BY (lower(username) = lower(%s)) DESC, id '
            'LIMIT 1',
            (login, login, login))
        return _one(cursor)


def find_user_by_username(username: str) -> Optional[dict[str, Any]]:
    with _cursor() as cursor:
        cursor.execute(
            f'SELECT {_USER_COLUMNS} FROM {USER_TABLE} '
            'WHERE lower(username) = lower(%s) LIMIT 1',
            (username,))
        return _one(cursor)


def get_user(user_id: int) -> Optional[dict[str, Any]]:
    with _cursor() as cursor:
        cursor.execute(
            f'SELECT {_USER_COLUMNS} FROM {USER_TABLE} WHERE id = %s',
            (user_id,))
        return _one(cursor)


def create_user(*, username: str, password_hash: str,
                email: Optional[str] = None,
                display_name: Optional[str] = None,
                role: str = 'user',
                enabled: bool = True,
                must_change_password: bool = False) -> dict[str, Any]:
    with _cursor() as cursor:
        cursor.execute(
            f'INSERT INTO {USER_TABLE} '
            '(username, email, display_name, password_hash, role, enabled, '
            ' must_change_password) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s) '
            f'RETURNING {_USER_COLUMNS}',
            (username, email or None, display_name or None, password_hash,
             role, enabled, must_change_password))
        return _one(cursor) or {}


def update_password(user_id: int, password_hash: str, *,
                    must_change_password: bool = False) -> int:
    with _cursor() as cursor:
        cursor.execute(
            f'UPDATE {USER_TABLE} '
            'SET password_hash = %s, must_change_password = %s, updated_at = now() '
            'WHERE id = %s',
            (password_hash, must_change_password, user_id))
        return cursor.rowcount


def set_enabled(user_id: int, enabled: bool) -> int:
    with _cursor() as cursor:
        cursor.execute(
            f'UPDATE {USER_TABLE} SET enabled = %s, updated_at = now() WHERE id = %s',
            (enabled, user_id))
        return cursor.rowcount


def touch_last_login(user_id: int) -> None:
    with _cursor() as cursor:
        cursor.execute(
            f'UPDATE {USER_TABLE} SET last_login_at = now() WHERE id = %s',
            (user_id,))


def delete_user(user_id: int) -> int:
    """删用户 + 其全部会话（同一事务；库里没有外键）。"""
    with _cursor() as cursor:
        cursor.execute(
            f'DELETE FROM {SESSION_TABLE} WHERE user_id = %s', (user_id,))
        cursor.execute(f'DELETE FROM {USER_TABLE} WHERE id = %s', (user_id,))
        return cursor.rowcount


# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------

_SESSION_JOIN_COLUMNS = (
    's.id AS session_id, s.token_hash, s.expires_at, s.revoked_at, '
    'u.id, u.username, u.email, u.display_name, u.role, u.enabled, '
    'u.must_change_password'
)


def create_session(*, user_id: int, token_hash: str, expires_at: datetime,
                   ip: str = '', user_agent: str = '') -> int:
    with _cursor() as cursor:
        cursor.execute(
            f'INSERT INTO {SESSION_TABLE} '
            '(token_hash, user_id, expires_at, ip, user_agent) '
            'VALUES (%s, %s, %s, %s, %s) RETURNING id',
            (token_hash, user_id, expires_at, ip[:64] or None,
             (user_agent or '')[:255] or None))
        return int(cursor.fetchone()[0])


def find_session(token_hash: str) -> Optional[dict[str, Any]]:
    with _cursor() as cursor:
        cursor.execute(
            f'SELECT {_SESSION_JOIN_COLUMNS} '
            f'FROM {SESSION_TABLE} s JOIN {USER_TABLE} u ON u.id = s.user_id '
            'WHERE s.token_hash = %s',
            (token_hash,))
        return _one(cursor)


def touch_session(session_id: int) -> None:
    with _cursor() as cursor:
        cursor.execute(
            f'UPDATE {SESSION_TABLE} SET last_seen_at = now() WHERE id = %s',
            (session_id,))


def revoke_session(token_hash: str) -> int:
    with _cursor() as cursor:
        cursor.execute(
            f'UPDATE {SESSION_TABLE} SET revoked_at = now() '
            'WHERE token_hash = %s AND revoked_at IS NULL',
            (token_hash,))
        return cursor.rowcount


def revoke_user_sessions(user_id: int, *,
                         except_token_hash: Optional[str] = None) -> int:
    with _cursor() as cursor:
        if except_token_hash:
            cursor.execute(
                f'UPDATE {SESSION_TABLE} SET revoked_at = now() '
                'WHERE user_id = %s AND revoked_at IS NULL '
                '  AND token_hash <> %s',
                (user_id, except_token_hash))
        else:
            cursor.execute(
                f'UPDATE {SESSION_TABLE} SET revoked_at = now() '
                'WHERE user_id = %s AND revoked_at IS NULL',
                (user_id,))
        return cursor.rowcount


def delete_expired_sessions(before: datetime) -> int:
    """清理 create 于 ``before`` 之前且已过期/已撤销的会话。"""
    with _cursor() as cursor:
        cursor.execute(
            f'DELETE FROM {SESSION_TABLE} '
            'WHERE expires_at < %s OR (revoked_at IS NOT NULL AND revoked_at < %s)',
            (before, before))
        return cursor.rowcount
