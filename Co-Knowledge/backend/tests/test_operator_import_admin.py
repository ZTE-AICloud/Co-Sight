"""算子导入的管理员门禁。

算子导入等同于在服务端执行代码（沙箱只是 AST 黑名单，不是安全边界），
本地账号模式下必须只允许 ``role=admin``。
"""

from types import SimpleNamespace

import pytest

from operators.api import _require_admin
from shared.errors.api import KbApiError


def _request(role=None):
    state = SimpleNamespace()
    if role is not None:
        state.auth_user = SimpleNamespace(role=role)
    return SimpleNamespace(state=state)


def test_non_admin_is_rejected():
    with pytest.raises(KbApiError) as exc:
        _require_admin(_request('user'))
    assert exc.value.status == 403


def test_admin_is_allowed():
    _require_admin(_request('admin'))          # 不抛


def test_gateway_or_none_has_no_local_principal():
    """gateway/none 模式下没有本地会话，由前置网关/部署边界负责。"""
    _require_admin(_request(None))             # 不抛
