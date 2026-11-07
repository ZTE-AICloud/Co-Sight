"""认证领域的不可变数据对象。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class AuthUser:
    """一次请求/一次校验用的用户快照。**不含 password_hash**。"""

    id: int
    username: str
    email: str
    display_name: str
    role: str
    enabled: bool
    must_change_password: bool

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> 'AuthUser':
        return cls(
            id=int(row['id']),
            username=str(row.get('username') or ''),
            email=str(row.get('email') or ''),
            display_name=str(row.get('display_name') or ''),
            role=str(row.get('role') or 'user'),
            enabled=bool(row.get('enabled')),
            must_change_password=bool(row.get('must_change_password')),
        )

    @property
    def display(self) -> str:
        """界面展示名：优先中文名，其次账号。"""
        return self.display_name or self.username

    def to_public(self) -> dict[str, Any]:
        """对外的用户形状（``docs/api-reference.md`` 的 ``AuthUser``）。

        **永远不要**在这里加 ``password_hash`` / ``token`` 一类字段。
        """
        return {
            'username': self.username,
            'displayName': self.display_name or self.username,
            'email': self.email,
            'role': self.role,
            'mustChangePassword': self.must_change_password,
        }
