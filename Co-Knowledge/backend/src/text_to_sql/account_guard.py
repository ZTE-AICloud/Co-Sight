"""数据源账号的最小权限校验。

只读事务（``set_session(readonly=True)``）能挡住写，挡不住**读**：一个超级用户
账号配合任意可执行的 SQL，就能读到该实例的任意库表。AST 校验已经把「任意 SQL」
收窄到白名单，但账号本身仍应是只读角色——这是数据库侧唯一可靠的边界。

校验发生在**用户显式连接的动作**上（连接测试、结构扫描），不在每条查询上都做：
一次查询多一次 ``pg_roles`` 往返不值得，且账号权限不会在运行期变化。
"""

from __future__ import annotations

from typing import Any

from text_to_sql.errors import Text2SqlValidationError

_STATE_SQL = ("SELECT r.rolsuper, r.rolcreatedb, r.rolcreaterole "
              "FROM pg_catalog.pg_roles r WHERE r.rolname = current_user")


def readonly_state(cursor) -> dict[str, Any]:
    """读取当前连接账号的角色属性；``pg_roles`` 不可见时返回空字典。"""
    try:
        cursor.execute(_STATE_SQL)
        row = cursor.fetchone()
    except Exception:                                      # noqa: BLE001
        return {}
    if not row or len(row) < 3:
        return {}
    return {'superuser': bool(row[0]), 'createdb': bool(row[1]),
            'createrole': bool(row[2])}


def assert_minimal_privilege(state: dict[str, Any], *, host: str = '') -> list[str]:
    """超级用户拒绝；能建库/建角色只作为告警返回。

    ``state`` 为空（``pg_roles`` 读不到）时不做判断——校验失败不应变成阻断，
    真正的兜底是只读事务。
    """
    if not state:
        return []
    if state.get('superuser'):
        raise Text2SqlValidationError(
            f'数据源 {host or ""} 使用的是超级用户账号；请改用只有 SELECT 权限的'
            '只读账号（超级用户可绕过只读事务读到任意库表）'.replace('  ', ' '))
    warnings: list[str] = []
    if state.get('createdb') or state.get('createrole'):
        warnings.append('该账号可建库或建角色，建议改用只读账号')
    return warnings
