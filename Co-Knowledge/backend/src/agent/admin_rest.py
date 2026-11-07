"""Agent Key 的 UI 管理接口（挂载在 ``/api/co-knowledge/v1/agent-keys``）。

**契约与其余 UI 接口相同**：成功是纯 JSON / 分页
``{items,total,page,pageSize}``，失败是真实状态码 + ``application/problem+json``。
追踪 ID 由最外层 ``RequestIdMiddleware`` 统一分配并回显 ``X-Request-Id``，
与 Agent REST 同一个约定，本模块不需要单独处理。

**注册顺序**：``register_agent_admin_api`` 必须在 ``register_rkb_api`` 之前调用 ——
后者带一条 ``/{unknown_path:path}`` 兜底路由，会吃掉同前缀下晚注册的
``/agent-keys``。同时本接口与 ``AGENT_PREFIX``（``/agent`` 子应用）平级：
``/agent`` 下的所有请求都要求 Agent Key，管理接口不能混进去。

**鉴权边界**：本接口与其它 UI 接口同级 —— ``AUTH_MODE=gateway`` 时由
``auth.middleware.AuthMiddleware`` 统一要求会话/网关令牌；``AUTH_MODE=none``
（开源默认）时没有应用层鉴权，只能靠网络隔离。``RKB_AGENT_KEY_ADMIN_ENABLED``
是总开关；``status`` 不受它限制，页面据此解释“为什么不能管理”。
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from infrastructure.logging.logutil import log

from infrastructure.http import kb_responses as responses
from shared.errors.api import (CODE_SERVER_ERROR, KbApiError,
                                  KbMalformedRequestError)
from infrastructure.http.identity import current_user, language
from shared.prefixes import AGENT_ADMIN_PREFIX

from agent import config, key_ops
from agent.errors import AgentKeyStoreUnavailable


def _no_store(response):
    """管理面的响应一律不缓存（含 Key 元数据；创建响应里还有明文）。"""
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Pragma'] = 'no-cache'
    return response


def _query_int(request: Request, name: str, default: int) -> int:
    try:
        return int(request.query_params.get(name) or default)
    except (TypeError, ValueError):
        return default


def _query_bool(request: Request, name: str) -> bool | None:
    """可选布尔查询参数：缺省/空串 → None，其他按 true/false 解析。"""
    raw = request.query_params.get(name)
    if raw is None or raw == '':
        return None
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


def _dispatch_sync(request: Request, raw: bytes, fn, *,
                   body_required: bool, require_admin: bool,
                   ok_status: int = 200, location=None):
    lang = language(request)
    if require_admin and not config.key_admin_enabled():
        return _no_store(responses.error(
            KbApiError('agent.key.admin.disabled'), lang, request=request))
    try:
        payload = responses.parse_json_body(raw, required=body_required)
        result = fn(payload)
        if ok_status == 204 or result is None:
            response = responses.no_content()
        else:
            loc = location(result) if callable(location) else location
            if ok_status == 201:
                response = responses.created(result, location=loc)
            elif ok_status == 202:
                response = responses.accepted(result, location=loc)
            else:
                response = responses.success(result, status_code=ok_status)
        return _no_store(response)
    except key_ops.KeyAdminError as error:
        # 轻量异常（key_ops 不依赖 FastAPI）在这里翻译成 ApiError。
        kb_error = KbApiError(error.key, *error.args, code=error.code)
        return _no_store(responses.error(kb_error, lang, request=request))
    except AgentKeyStoreUnavailable:
        return _no_store(responses.error(
            KbApiError('agent.key.store.unavailable', code=CODE_SERVER_ERROR),
            lang, request=request))
    except KbApiError as error:
        return _no_store(responses.error(error, lang, request=request))
    except ValueError as error:
        # 请求体畸形 / 字段类型对不上 → 400 malformed_request。
        log.warning('agent key admin malformed request: %s', error)
        return _no_store(responses.error(
            KbMalformedRequestError('RetCode.illegalArgument'), lang,
            request=request))
    except Exception:                                             # noqa: BLE001
        log.exception('agent key admin unexpected error')
        return _no_store(responses.server_error(lang, request=request))


async def _dispatch(request: Request, fn, *, with_body: bool = False,
                    body_required: bool = False, require_admin: bool = True,
                    ok_status: int = 200, location=None):
    raw = await request.body() if with_body else b''
    return await run_in_threadpool(
        _dispatch_sync, request, raw, fn,
        body_required=body_required, require_admin=require_admin,
        ok_status=ok_status, location=location)


def build_admin_router() -> APIRouter:
    router = APIRouter()

    # ⚠️ ``/status`` 必须排在 ``/{key_prefix}`` 之前（虽然当前没有 GET 单行，
    # 但顺序写清楚能防将来加端点时被路径参数吃掉）。
    @router.get(AGENT_ADMIN_PREFIX + '/status')
    async def status(request: Request):
        """服务状态。**不受管理开关限制**，否则页面无法解释为什么被禁用。"""
        return await _dispatch(
            request,
            lambda _payload: key_ops.build_status(
                request.scope.get('root_path') or ''),
            require_admin=False,
        )

    @router.get(AGENT_ADMIN_PREFIX + '/stats')
    async def usage_stats(request: Request):
        """调用量指标（累计 / 最近 7 天）。与列表同受管理开关限制。"""
        # 同一个响应里带 Key 概览计数（keySummary）：列表端点的 pageSize 上限是 100，
        # 页面顶部四张卡不能再靠「拉 500 条本地数」，聚合放到这里做。
        return await _dispatch(
            request,
            lambda _payload: {
                **key_ops.usage_stats(),
                'keySummary': key_ops.key_summary(),
            },
        )

    @router.get(AGENT_ADMIN_PREFIX)
    async def list_keys(request: Request):
        return await _dispatch(
            request,
            lambda _payload: key_ops.list_keys(
                current_page=_query_int(request, 'currentPage', 1),
                page_size=_query_int(request, 'pageSize', 50),
                keyword=request.query_params.get('keyword') or '',
                enabled=_query_bool(request, 'enabled'),
                sort_by=request.query_params.get('sortBy') or '',
                sort_order=request.query_params.get('sortOrder') or '',
            ),
        )

    @router.post(AGENT_ADMIN_PREFIX)
    async def create_key(request: Request):
        created_by = current_user(request)
        return await _dispatch(
            request,
            lambda payload: key_ops.create_key(payload, created_by),
            with_body=True,
            body_required=True,
            ok_status=201,
            location=lambda result: (
                f'{AGENT_ADMIN_PREFIX}/'
                f'{(result.get("key") or {}).get("keyPrefix")}'
                if isinstance(result, dict)
                and isinstance(result.get('key'), dict)
                and result['key'].get('keyPrefix') else None),
        )

    @router.patch(AGENT_ADMIN_PREFIX + '/{key_prefix}')
    async def update_key(request: Request, key_prefix: str):
        return await _dispatch(
            request,
            lambda payload: key_ops.update_key(key_prefix, payload),
            with_body=True,
            body_required=True,
        )

    @router.delete(AGENT_ADMIN_PREFIX + '/{key_prefix}')
    async def delete_key(request: Request, key_prefix: str):
        return await _dispatch(
            request,
            lambda _payload: key_ops.delete_key(key_prefix),
        )

    return router


def register_agent_admin_api(app) -> None:
    """把管理接口挂到主应用。**必须在 register_rkb_api 之前调用。**"""
    app.include_router(build_admin_router())
    log.info('Registered agent key admin api under %s', AGENT_ADMIN_PREFIX)
