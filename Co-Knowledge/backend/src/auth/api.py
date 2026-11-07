"""本地账号登录接口（``/api/co-knowledge/v1/auth``）。

契约与其它 UI 接口一致（API 2.0.0）：成功是纯 JSON / 204，失败是真实状态码 +
``application/problem+json``。

**注册顺序**：``register_auth_api`` 必须在 ``register_rkb_api`` 之前调用 —— 后者
带一条 ``/{unknown_path:path}`` 兜底路由，会吃掉同前缀下晚注册的 ``/auth/*``。

**鉴权边界**：``/auth/status``、``/auth/login``、``/auth/logout`` 公开（登录前
没有会话）；``/auth/me``、``/auth/password`` 由 ``AuthMiddleware`` 要求会话。
``AUTH_MODE`` 非 ``local`` 时登录/改密返回 409 ``auth_not_enabled``，避免“假登录”。
"""

from __future__ import annotations

import psycopg2
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from auth import repository as repo, service, sessions
from auth.errors import AuthError, AuthStoreUnavailable, auth_not_enabled
from infrastructure.http.identity import language
from shared.prefixes import AUTH_PREFIX
from shared.problem import ProblemSpec, generic_detail, problem_response, title_for

MAX_AUTH_BODY_BYTES = 8 * 1024

_NO_STORE = {
    'Cache-Control': 'no-store',
    'Pragma': 'no-cache',
    'X-Content-Type-Options': 'nosniff',
}


class LoginRequest(BaseModel):
    username: str = Field(default='', max_length=255)
    password: str = Field(default='', max_length=1024)


class ChangePasswordRequest(BaseModel):
    currentPassword: str = Field(default='', max_length=1024)
    newPassword: str = Field(default='', max_length=1024)


def _problem_spec(error: AuthError) -> ProblemSpec:
    return ProblemSpec(status=error.status, code=error.problem_code,
                       title=title_for(error.problem_code))


def auth_problem_response(request: Request, error: AuthError) -> JSONResponse:
    """``AuthError`` → RFC 9457；中间件与路由共用这一份。"""
    spec = _problem_spec(error)
    headers = dict(_NO_STORE)
    if error.retry_after:
        headers['Retry-After'] = str(error.retry_after)
    return problem_response(
        spec, generic_detail(spec, language(request)),
        instance=request.url.path, headers=headers)


async def _auth_error_handler(request: Request, exc: AuthError) -> JSONResponse:
    return auth_problem_response(request, exc)


async def _store_unavailable_handler(request: Request,
                                     exc: AuthStoreUnavailable) -> JSONResponse:
    return auth_problem_response(request, AuthError(503, 'auth_not_initialized'))


def _require_local_mode() -> None:
    if service.auth_mode() != 'local':
        raise auth_not_enabled()


def _body_size_guard(request: Request) -> None:
    raw = (request.headers.get('content-length') or '').strip()
    if raw.isdigit() and int(raw) > MAX_AUTH_BODY_BYTES:
        raise AuthError(413, 'payload_too_large')


def _request_ip(request: Request) -> str:
    fallback = request.client.host if request.client is not None else ''
    return sessions.client_ip(request.headers, fallback)


def _user_agent(request: Request) -> str:
    return (request.headers.get('user-agent') or '')[:255]


def _secure_cookie(request: Request) -> bool:
    return sessions.is_secure_request(
        request.url.scheme,
        request.headers.get('x-forwarded-proto') or '',
        sessions.cookie_secure_override(),
    )


def _cookie_headers(request: Request, token: str) -> dict[str, str]:
    ttl = sessions.session_ttl_seconds()
    return {
        'Set-Cookie': sessions.build_session_cookie(
            token, ttl, _secure_cookie(request)),
        **_NO_STORE,
    }


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get(AUTH_PREFIX + '/status')
    async def status(request: Request):
        """公开：前端据此决定是否启用登录守卫（同一份构建支持三种模式）。"""
        mode = service.auth_mode()
        if mode != 'local':
            return JSONResponse(
                {'mode': mode, 'initialized': True, 'authenticated': False,
                 'user': None},
                headers=dict(_NO_STORE))

        initialized = True
        user = None
        try:
            initialized = repo.table_exists()
            if initialized:
                token = sessions.extract_session_token(request.cookies)
                user = service.current_user_or_none(token)
        except AuthStoreUnavailable:
            initialized = False
            user = None
        except psycopg2.Error as error:                            # pragma: no cover
            raise AuthError(503, 'service_unavailable') from error

        return JSONResponse(
            {
                'mode': mode,
                'initialized': initialized,
                'authenticated': user is not None,
                'user': user.to_public() if user else None,
            },
            headers=dict(_NO_STORE),
        )

    @router.post(AUTH_PREFIX + '/login',
                 dependencies=[Depends(_body_size_guard)])
    async def login(request: Request, payload: LoginRequest):
        _require_local_mode()
        if not sessions.origin_allowed(request.headers, required=False):
            raise AuthError(403, 'csrf_rejected')
        result = service.login(
            payload.username, payload.password,
            ip=_request_ip(request), user_agent=_user_agent(request))
        return JSONResponse(
            {'user': result.user.to_public()},
            headers=_cookie_headers(request, result.token))

    @router.post(AUTH_PREFIX + '/logout')
    async def logout(request: Request):
        token = sessions.extract_session_token(request.cookies)
        service.logout(token)
        headers = {
            'Set-Cookie': sessions.clear_session_cookie(_secure_cookie(request)),
            **_NO_STORE,
        }
        return Response(status_code=204, headers=headers)

    @router.get(AUTH_PREFIX + '/me')
    async def me(request: Request):
        _require_local_mode()
        token = sessions.extract_session_token(request.cookies)
        user = getattr(request.state, 'auth_user', None) or service.validate_session(token)
        return JSONResponse({'user': user.to_public()}, headers=dict(_NO_STORE))

    @router.post(AUTH_PREFIX + '/password',
                 dependencies=[Depends(_body_size_guard)])
    async def change_password(request: Request, payload: ChangePasswordRequest):
        _require_local_mode()
        token = sessions.extract_session_token(request.cookies)
        user = getattr(request.state, 'auth_user', None) or service.validate_session(token)
        service.change_password(
            user, payload.currentPassword, payload.newPassword,
            current_token=token)
        return Response(status_code=204, headers=dict(_NO_STORE))

    return router


def register_auth_api(app: FastAPI) -> None:
    """挂载 ``/auth/*`` 与领域异常处理器。必须在 ``register_rkb_api`` 之前调用。"""
    app.include_router(build_router())
    app.add_exception_handler(AuthError, _auth_error_handler)
    app.add_exception_handler(AuthStoreUnavailable, _store_unavailable_handler)
