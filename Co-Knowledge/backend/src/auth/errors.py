"""认证领域的轻量异常。

``service.py`` 不 import FastAPI，所以这里只携带「HTTP 状态码 + 稳定机器码」；
``api.py`` 在最外层把它们翻成 RFC 9457 problem+json（文案按 ``Accept-Language``
在 ``shared/problem.py`` 的 ``SPECIFIC_DETAILS`` 里取）。
"""

from __future__ import annotations


class AuthError(Exception):
    """认证失败。``problem_code`` 会出现在响应体的 ``code`` 字段。"""

    def __init__(self, status: int, problem_code: str, *,
                 retry_after: int = 0):
        super().__init__(problem_code)
        self.status = status
        self.problem_code = problem_code
        self.retry_after = int(retry_after or 0)


class AuthStoreUnavailable(Exception):
    """账号/会话表不存在（数据库未初始化）。

    单独一个类型是为了让 API 回 **503** 而不是 500，并给出“联系管理员/检查数据库
    初始化”的明确提示；与 Agent Key 的 ``AgentKeyStoreUnavailable`` 同一思路。
    """


def invalid_credentials() -> AuthError:
    return AuthError(401, 'invalid_credentials')


def account_disabled() -> AuthError:
    return AuthError(403, 'account_disabled')


def unauthorized() -> AuthError:
    return AuthError(401, 'unauthorized')


def session_expired() -> AuthError:
    return AuthError(401, 'session_expired')


def login_rate_limited(retry_after: int = 0) -> AuthError:
    return AuthError(429, 'login_rate_limited', retry_after=retry_after)


def auth_not_initialized() -> AuthError:
    return AuthError(503, 'auth_not_initialized')


def auth_not_enabled() -> AuthError:
    return AuthError(409, 'auth_not_enabled')


def invalid_current_password() -> AuthError:
    return AuthError(422, 'invalid_current_password')


def password_policy() -> AuthError:
    return AuthError(422, 'password_policy')


def invalid_email() -> AuthError:
    return AuthError(422, 'invalid_email')


def user_not_found() -> AuthError:
    return AuthError(404, 'user_not_found')


def password_change_required() -> AuthError:
    return AuthError(403, 'password_change_required')


def csrf_rejected() -> AuthError:
    return AuthError(403, 'csrf_rejected')
