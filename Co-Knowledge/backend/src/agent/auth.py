"""Agent API 的鉴权、作用域、限流与 MCP 请求状态注入。

两种入口共用同一份 :func:`authenticate`：

* REST：FastAPI 依赖 :func:`agent_context`（``HTTPBearer`` 只用于 OpenAPI 文档，
  真正的校验在这里）；
* MCP：:class:`AuthenticatedMCPApp` 是包在 ``StreamableHTTPSessionManager`` 外的
  原始 ASGI 中间层，校验通过后把 principal / trace_id 写进 ``scope['state']``，
  FastMCP 的工具再从 ``ctx.request_context.request.state`` 读出来。

**限流是进程内的**：RKB 本来就只能单副本（多轮会话缓存在进程内），所以按 Key 的
滑动窗口放在内存里是有效的；多副本部署需要把这里换成共享存储。
"""

from __future__ import annotations

import math
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from infrastructure.logging.logutil import log

from agent import config, keys, repository_pg as store_pg
from agent.errors import (
    AgentApiError,
    configuration_error,
    forbidden_scope,
    internal_error,
    rate_limited,
    unauthorized,
)

WINDOW_SECONDS = 60.0
LAST_USED_TOUCH_SECONDS = 60.0
#: 调用计数按自然日切分；口径与 compose / PostgreSQL 的 CST 一致。
USAGE_TIMEZONE = ZoneInfo('Asia/Shanghai')

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AgentPrincipal:
    """一次请求的不可变身份快照。"""

    key_prefix: str
    name: str
    scopes: frozenset[str]
    kb_ids: tuple[str, ...]
    rate_limit_per_min: int

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def can_access(self, kb_id: str) -> bool:
        return not self.kb_ids or kb_id in self.kb_ids


@dataclass(frozen=True)
class AgentContext:
    principal: AgentPrincipal
    trace_id: str


class _RateLimiter:
    """按 Key 的 60s 滑动窗口。``limit <= 0`` 表示不限制。"""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, now: Optional[float] = None) -> tuple[bool, int]:
        if limit <= 0:
            return True, 0
        current = time.monotonic() if now is None else now
        with self._lock:
            events = self._events.setdefault(key, deque())
            cutoff = current - WINDOW_SECONDS
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                retry_after = max(1, int(math.ceil(events[0] + WINDOW_SECONDS - current)))
                return False, retry_after
            events.append(current)
            return True, 0


_RATE_LIMITER = _RateLimiter()

_touch_lock = threading.Lock()
_last_touch: dict[str, float] = {}


def reset_rate_limiter() -> None:
    """测试用：清空限流与 last_used 节流状态。"""
    with _RATE_LIMITER._lock:                                      # noqa: SLF001
        _RATE_LIMITER._events.clear()                              # noqa: SLF001
    with _touch_lock:
        _last_touch.clear()


def _maybe_touch_last_used(prefix: str, now: Optional[float] = None) -> None:
    current = time.monotonic() if now is None else now
    with _touch_lock:
        if current - _last_touch.get(prefix, 0.0) < LAST_USED_TOUCH_SECONDS:
            return
        _last_touch[prefix] = current
    # 写失败不影响鉴权（best-effort；见 store_pg.touch_last_used）
    store_pg.touch_last_used(prefix)


def _record_usage(prefix: str) -> None:
    """每次鉴权通过计一次调用（best-effort；见 store_pg.record_usage）。

    计数点放在 ``authenticate`` 是因为 REST（``agent_context``）与 MCP
    （``AuthenticatedMCPApp``）都只经过这里：一次 HTTP 请求 = 一次计数，
    与具体调了哪个工具无关。401/429 在计数之前就抛出了，不计入。
    """
    store_pg.record_usage(prefix, datetime.now(USAGE_TIMEZONE).date())


def _extract_token(authorization: Optional[str], x_api_key: Optional[str]) -> Optional[str]:
    if authorization:
        scheme, _, value = authorization.partition(' ')
        if scheme.lower() == 'bearer' and value.strip():
            return value.strip()
    if x_api_key and x_api_key.strip():
        return x_api_key.strip()
    return None


def _is_expired(expires_at, now: Optional[datetime] = None) -> bool:
    if expires_at is None:
        return False
    current = now or datetime.now(timezone.utc)
    if getattr(expires_at, 'tzinfo', None) is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return current >= expires_at


def authenticate(authorization: Optional[str] = None,
                 x_api_key: Optional[str] = None,
                 now: Optional[float] = None) -> AgentPrincipal:
    """校验 ``Authorization: Bearer`` / ``X-API-Key``，返回 principal。

    失败语义：配置缺失 → 503；Key 缺失/非法/停用/过期 → 401；超限 → 429。
    不对调用方区分「前缀不存在」与「哈希不对」，避免枚举。
    """
    pepper = config.key_pepper()
    if not pepper:
        raise configuration_error(
            'RKB_AGENT_KEY_PEPPER is not configured; agent api is disabled')

    token = _extract_token(authorization, x_api_key)
    if not token:
        raise unauthorized()

    prefix = keys.key_prefix(token)
    if prefix is None:
        raise unauthorized()

    row = store_pg.find_by_prefix(prefix)
    if row is None:
        raise unauthorized()
    if not keys.verify_key(token, row.get('key_hash') or '', pepper):
        raise unauthorized()
    if not row.get('enabled'):
        raise AgentApiError(401, 'unauthorized', 'API key is disabled')
    if _is_expired(row.get('expires_at')):
        raise AgentApiError(401, 'unauthorized', 'API key has expired')

    limit = int(row.get('rate_limit_per_min') or 0)
    allowed, retry_after = _RATE_LIMITER.check(prefix, limit, now)
    if not allowed:
        raise rate_limited(retry_after)

    _maybe_touch_last_used(prefix, now)
    _record_usage(prefix)
    return AgentPrincipal(
        key_prefix=prefix,
        name=row.get('name') or '',
        scopes=frozenset(row.get('scopes') or []),
        kb_ids=tuple(row.get('kb_ids') or []),
        rate_limit_per_min=limit,
    )


def authenticate_headers(headers: Headers) -> AgentPrincipal:
    return authenticate(headers.get('authorization'), headers.get('x-api-key'))


def require_scope(principal: AgentPrincipal, scope: str) -> None:
    if not principal.has_scope(scope):
        raise forbidden_scope(scope)


def _request_from_context(ctx):
    """FastMCP 把当前 Streamable HTTP 的 Starlette ``Request`` 塞在这里。"""
    return getattr(getattr(ctx, 'request_context', None), 'request', None)


def principal_from_context(ctx) -> AgentPrincipal:
    """从 FastMCP 的 ``Context`` 取 ASGI 层注入的 principal。

    ``ctx.request_context.request`` 是当前 Streamable HTTP 请求的 Starlette
    ``Request``（mcp 1.12.4 的 ``streamable_http.py`` 这样塞进来的）。取不到时
    退回按请求头再验一次（纵深防御，也让直接调用工具的单测能工作）。
    """
    request = _request_from_context(ctx)
    state = getattr(request, 'state', None) if request is not None else None
    principal = getattr(state, 'agent_principal', None) if state is not None else None
    if principal is not None:
        return principal
    if request is not None:
        return authenticate(request.headers.get('authorization'),
                            request.headers.get('x-api-key'))
    raise unauthorized('MCP request context is unavailable')


def trace_id_from_context(ctx) -> str:
    request = _request_from_context(ctx)
    state = getattr(request, 'state', None) if request is not None else None
    value = getattr(state, 'trace_id', None) if state is not None else None
    return value or uuid.uuid4().hex


def headers_from_context(ctx) -> Headers:
    """MCP 请求头（给编排透传 ``language-option`` / ``X-Org-Id`` 等）。

    取不到时返回空头而不是抛错：这些头只影响展示语言与审计字段，缺了也不该
    让一次执行失败。
    """
    request = _request_from_context(ctx)
    headers = getattr(request, 'headers', None)
    return headers if headers is not None else Headers()


def error_headers(error: AgentApiError) -> dict[str, str]:
    headers: dict[str, str] = {}
    if error.http_status == 401:
        headers['WWW-Authenticate'] = 'Bearer'
    if error.http_status == 429:
        retry_after = (error.details or {}).get('retry_after_seconds')
        if retry_after:
            headers['Retry-After'] = str(retry_after)
    return headers


def error_payload(trace_id: str, error: AgentApiError) -> dict:
    """MCP 鉴权层的错误体（MCP 保持自己的 ``{trace_id,error}`` 形状）。

    REST 走 :mod:`agent_api.rest` 的 ``application/problem+json``，不用这个函数。
    """

    return {'trace_id': trace_id, 'error': error.as_dict()}


async def _send_error(scope, receive, send, trace_id: str, error: AgentApiError) -> None:
    response = JSONResponse(
        error_payload(trace_id, error),
        status_code=error.http_status,
        headers=error_headers(error),
    )
    await response(scope, receive, send)


class AuthenticatedMCPApp:
    """包在 ``StreamableHTTPSessionManager`` 外的 ASGI 鉴权层。

    **必须是类实例**：Starlette 0.37.2 把函数/绑定方法当 ``request_response()``
    （GET-only，POST 直接 405），只有类实例按原始 ASGI 处理。
    """

    def __init__(self, manager) -> None:
        self._manager = manager

    async def __call__(self, scope, receive, send) -> None:
        if scope.get('type') != 'http':
            await self._manager.handle_request(scope, receive, send)
            return

        # 复用最外层 RequestIdMiddleware 分配的 id：MCP 工具结果里的 trace_id
        # 与 HTTP 响应头 X-Request-Id 必须是同一个；独立挂载时兜底生成。
        trace_id = (scope.get('state') or {}).get('request_id') or uuid.uuid4().hex
        headers = Headers(scope=scope)
        try:
            principal = await run_in_threadpool(authenticate_headers, headers)
        except AgentApiError as error:
            await _send_error(scope, receive, send, trace_id, error)
            return
        except Exception:                                          # noqa: BLE001
            log.exception('agent mcp auth failed trace=%s', trace_id)
            await _send_error(scope, receive, send, trace_id, internal_error(trace_id))
            return

        state = scope.setdefault('state', {})
        state['agent_principal'] = principal
        state['trace_id'] = trace_id
        try:
            await self._manager.handle_request(scope, receive, send)
        except Exception:                                          # noqa: BLE001
            # 响应可能已经开始，无法再写 500；记录后交给 ASGI 服务器收尾。
            # kb_api 的异常处理器已被 _owns_path 排除，不会把它改写成 200 信封。
            log.exception('agent mcp request failed trace=%s', trace_id)
            raise


def agent_context(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> AgentContext:
    """REST 依赖：复用请求 ID、校验 Key、把 principal 挂到 request.state。"""
    # 客户端传的合法 X-Request-Id 已在中间件里沿用（同名回显）；这里不能另生成，
    # 否则响应头、审计日志、用量统计会各说各话。
    trace_id = (getattr(request.state, 'request_id', None)
                or uuid.uuid4().hex)
    request.state.trace_id = trace_id
    # ``HTTPBearer`` 已经剥掉了 "Bearer " 前缀；``authenticate`` 期望的是完整
    # Authorization 头（MCP 路径直接传原头）。这里拼回去，避免两条入口的 token
    # 语义不一致（症状：MCP 通、REST 恒 401）。
    authorization = (f'Bearer {credentials.credentials}'
                     if credentials is not None else None)
    principal = authenticate(authorization, request.headers.get('x-api-key'))
    request.state.agent_principal = principal
    return AgentContext(principal=principal, trace_id=trace_id)
