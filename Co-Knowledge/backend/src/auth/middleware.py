"""认证中间件：``AUTH_MODE=none|local|gateway``。

三种模式：

- ``none``（默认）：**放行所有请求**；
- ``local``：校验 HttpOnly Cookie ``ragstudio_session``，把
  ``AuthUser`` 写到 ``request.state.auth_user``；``/agent/*`` 与 ``/mcp`` 绕过
  （它们有自己的 API Key 鉴权）；``/health``、``/auth/status|login|logout`` 公开；
- ``gateway``：仅做「网关令牌存在性」检查（``X-Auth-Value`` / ``X-Auth-Token`` /
  ``Authorization`` 任一非空），真正的鉴权由前置网关完成。**网关必须剥离客户端
  伪造的 ``X-Emp-No`` 等身份头**，否则下游身份可被冒充。

未知 ``AUTH_MODE`` 在启动期由 ``auth.service.validate_auth_mode`` 拒绝启动；
本中间件不再把未知值当成 ``none`` 放行。
"""

from __future__ import annotations

import logging
import os

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

#: 额外白名单前缀（供 `app.py` 赋值；**前缀匹配**）。
filterfree: list[str] = []

#: 日志目录（仅记录目录，用于启动期校验）
log_path: str | None = None

_TOKEN_HEADERS = ('x-auth-value', 'x-auth-token', 'authorization')
_UNSAFE_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})


def _prefixes():
    from shared.prefixes import AGENT_MCP_PATH, AGENT_PREFIX, AUTH_PREFIX, RKB_PREFIX

    public = frozenset({
        f'{RKB_PREFIX}/health',
        '/health',
        '/healthcheck',
        f'{AUTH_PREFIX}/status',
        f'{AUTH_PREFIX}/login',
        f'{AUTH_PREFIX}/logout',
    })
    return public, AGENT_PREFIX, AGENT_MCP_PATH, AUTH_PREFIX, RKB_PREFIX


def _route_path(request: Request) -> str:
    """``URL_CONTEXT_PATH`` 部署时剥掉 root_path，与 ContentType 中间件同一口径。"""
    path = request.url.path
    root = request.scope.get('root_path') or ''
    if root and path.startswith(root):
        return path[len(root):] or '/'
    return path


def _is_public(path: str, extra: list[str]) -> bool:
    public, _agent_prefix, _mcp, _auth_prefix, _rkb_prefix = _prefixes()
    normalized = path.rstrip('/') or '/'
    if normalized in public:
        return True
    return any(path.startswith(prefix) for prefix in extra)


def _is_agent_bypass(path: str) -> bool:
    _public, agent_prefix, mcp_path, _auth_prefix, _rkb_prefix = _prefixes()
    return (path == mcp_path
            or path.startswith(mcp_path + '/')
            or path.startswith(agent_prefix + '/'))


def _has_gateway_token(headers) -> bool:
    lowered = {str(key).lower(): value for key, value in headers.items()}
    return any(lowered.get(name) for name in _TOKEN_HEADERS)


def _plain_unauthorized() -> JSONResponse:
    return JSONResponse(
        content={'code': 401, 'message': '未携带网关令牌，拒绝访问'},
        status_code=401,
    )


def _unauthorized_response(request: Request, path: str, error=None):
    """RKB 路径回 problem+json；其它路径回简单的 ``{code,message}``。"""
    from shared.problem import UNAUTHORIZED, generic_detail, owns_problem_path, problem_response

    from infrastructure.http.identity import language

    if owns_problem_path(path):
        if error is not None:
            from auth.api import auth_problem_response

            return auth_problem_response(request, error)
        return problem_response(
            UNAUTHORIZED, generic_detail(UNAUTHORIZED, language(request)),
            instance=path)
    return _plain_unauthorized()


class AuthMiddleware(BaseHTTPMiddleware):
    """按 ``AUTH_MODE`` 执行 none/local/gateway 三种策略。"""

    filterfree = filterfree
    log_path = log_path

    async def dispatch(self, request: Request, call_next):
        from auth.errors import AuthError, AuthStoreUnavailable
        from auth import service, sessions

        mode = service.auth_mode()
        path = _route_path(request)

        if mode == 'none':
            return await call_next(request)

        if request.method == 'OPTIONS':
            return await call_next(request)

        if _is_public(path, type(self).filterfree):
            return await call_next(request)

        if mode == 'gateway':
            if _has_gateway_token(request.headers):
                return await call_next(request)
            logger.warning('reject unauthenticated request: %s', path)
            return _unauthorized_response(request, path)

        # ---- local ----
        _public, _agent_prefix, _mcp, _auth_prefix, rkb_prefix = _prefixes()
        if not path.startswith(rkb_prefix):
            # 非 RKB 路径（静态资源不走后端）不在会话鉴权范围内。
            return await call_next(request)
        if _is_agent_bypass(path):
            # Agent REST / MCP 用自己的 API Key 鉴权，不能要求浏览器会话。
            return await call_next(request)

        token = sessions.extract_session_token(request.cookies)
        try:
            user = service.validate_session(token)
        except AuthStoreUnavailable:
            from auth.errors import auth_not_initialized

            return _unauthorized_response(
                request, path, auth_not_initialized())
        except AuthError as error:
            return _unauthorized_response(request, path, error)

        if request.method in _UNSAFE_METHODS and not sessions.origin_allowed(
                request.headers, required=True):
            from auth.errors import csrf_rejected

            return _unauthorized_response(request, path, csrf_rejected())

        request.state.auth_user = user

        normalized = path.rstrip('/') or '/'
        if user.must_change_password and normalized not in {
                f'{_auth_prefix}/me', f'{_auth_prefix}/password'}:
            from auth.errors import password_change_required

            return _unauthorized_response(
                request, path, password_change_required())

        return await call_next(request)

    @classmethod
    def set_log_path(cls, path: str | None):
        """设置鉴权日志目录（原私有包签名一致）。仅记录，不再写文件。"""
        if path:
            cls.log_path = path
            os.makedirs(path, exist_ok=True)
            logger.info('auth middleware log path set to %s', path)
