"""数据源账号最小权限校验。"""

import pytest

from text_to_sql import account_guard
from text_to_sql.errors import Text2SqlValidationError


class _Cursor:
    def __init__(self, row):
        self._row = row

    def execute(self, sql):
        self.sql = sql

    def fetchone(self):
        return self._row


def test_reads_role_flags():
    state = account_guard.readonly_state(_Cursor((False, False, False)))
    assert state == {'superuser': False, 'createdb': False, 'createrole': False}


def test_superuser_is_rejected():
    with pytest.raises(Text2SqlValidationError) as error:
        account_guard.assert_minimal_privilege({'superuser': True}, host='db')
    assert '只读账号' in error.value.message


def test_createdb_only_warns():
    warnings = account_guard.assert_minimal_privilege(
        {'superuser': False, 'createdb': True, 'createrole': False})
    assert warnings and '只读账号' in warnings[0]


def test_readonly_account_passes_silently():
    assert account_guard.assert_minimal_privilege(
        {'superuser': False, 'createdb': False, 'createrole': False}) == []


def test_unknown_state_does_not_block():
    """读不到 pg_roles 时放行：真正的兜底是只读事务。"""
    assert account_guard.assert_minimal_privilege({}) == []


def test_short_row_is_treated_as_unknown():
    assert account_guard.readonly_state(_Cursor((1,))) == {}


def test_cursor_error_is_treated_as_unknown():
    class Broken(_Cursor):
        def execute(self, sql):
            raise RuntimeError('no privilege')

    assert account_guard.readonly_state(Broken(None)) == {}
