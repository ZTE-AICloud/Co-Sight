"""模型管理接口（``{RKB_PREFIX}/models``）。

**装配顺序是硬约束**：必须在 ``register_rkb_api`` **之前**注册 —— 那个路由末尾有一条
catch-all ``/{unknown_path:path}``，晚注册的端点会被它整批吃掉，症状是「接口全返回 404」。

**响应**是纯 JSON：单资源 / 数组 / ``{items,total,page,pageSize}``；错误是
RFC 9457 ``application/problem+json``。前端 axios 拦截器直接消费 body。
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from starlette.concurrency import run_in_threadpool

from infrastructure.http import kb_responses as responses
from shared.errors.api import (KbApiError, KbMalformedRequestError,
                                  KbStoreError, KbValidationError)
from infrastructure.http.identity import current_user, language
from shared.prefixes import RKB_PREFIX
from model.errors import ModelApiError
from model.service import ModelService
from infrastructure.logging.logutil import log

MODEL_PREFIX = RKB_PREFIX

#: 进程内单例（惰性建，见 :func:`get_model_service`）
_service = None


def _require_admin(request: Request) -> None:
    """模型写操作与连接测试只允许管理员（本地账号模式）。

    ``gateway`` / ``none`` 没有本地会话，由前置网关或部署边界负责；``local``
    模式下 ``role != 'admin'`` 一律拒绝。
    """
    principal = getattr(request.state, 'auth_user', None)
    if principal is not None and getattr(principal, 'role', 'user') != 'admin':
        raise KbApiError(None, status=403, problem_code='forbidden')


def get_model_service() -> ModelService:
    """生产默认的 ModelService（惰性建、进程内唯一）。

    惰性而非模块级：``PgModelStore`` 的 import 会牵进 psycopg2，
    而单测环境只需要 fastapi + pytest。

    首次调用时**顺带播种**（``seed_if_empty``）：播种是「让升级后的下拉与既有部署一致」
    的一次性动作，放在这里而不是模块级，是为了不污染 ``import app``——
    本仓为沙箱子进程重复执行入口模块踩过一次坑，见 ``workflow/runtime.py``。
    """
    global _service
    if _service is None:
        _service = _build_default_service()
    return _service


def _build_default_service() -> ModelService:
    from model.seed import seed_if_empty
    from model.repository_pg import PgModelStore

    store = PgModelStore()
    try:
        written = seed_if_empty(store)
        if written:
            log.info('model registry seeded %d row(s) from deploy config', written)
    except Exception:
        # 播种失败不能挡住服务启动：注册表为空时解析层会回落到 .env
        log.warning('model registry seeding skipped', exc_info=True)
    return ModelService(store)


def reset_model_service_for_tests() -> None:
    """清掉进程内单例（单测注入自己的 service 之后重置用）。"""
    global _service
    _service = None


# ---------------------------------------------------------------------------
# 调度：解析请求体 → 线程池执行 → 装信封（与 kb_api 的 _dispatch 同形）
# ---------------------------------------------------------------------------
async def _dispatch(request: Request, fn, with_body: bool = False,
                    ok_status: int = 200, location=None):
    raw = await request.body() if with_body else b''
    return await run_in_threadpool(
        _dispatch_sync, request, raw, fn, ok_status, location)


def _dispatch_sync(request: Request, raw: bytes, fn,
                   ok_status: int = 200, location=None):
    lang = language(request)
    try:
        payload = responses.parse_json_body(raw)
        result = fn(payload)
        if isinstance(result, Response):
            return result
        if ok_status == 204 or result is None:
            return responses.no_content()
        loc = location(result) if callable(location) else location
        if ok_status == 201:
            return responses.created(result, location=loc)
        if ok_status == 202:
            return responses.accepted(result, location=loc)
        return responses.success(result, status_code=ok_status)
    except ModelApiError as model_error:
        return responses.error(model_error, lang, request=request)
    except KbValidationError as validation_error:
        return responses.error(validation_error, lang, request=request)
    except ValueError as error:
        # 请求体畸形 / 字段类型对不上 → 400 malformed_request
        log.warning('model api malformed request body: %s', error)
        return responses.error(KbMalformedRequestError('RetCode.illegalArgument'),
                               lang, request=request)
    except KbApiError as kb_error:
        return responses.error(kb_error, lang, request=request)
    except KbStoreError as store_error:
        # 存储层细节只进日志（可能含表名/主机）
        log.error('model api store error [%s]: %s', store_error.kind, store_error.detail)
        if store_error.kind == KbStoreError.DUPLICATE:
            return responses.error(ModelApiError('model.name.duplicate', ''),
                                   lang, request=request)
        return responses.store_error(store_error, lang, request=request)
    except Exception:
        log.exception('model api unexpected error')
        return responses.server_error(lang, request=request)


def _query_int(request: Request, name: str, default: int) -> int:
    try:
        return int(request.query_params.get(name) or default)
    except (TypeError, ValueError):
        return default


def build_router(service: ModelService) -> APIRouter:
    """构造端点（不绑定前缀；由 :func:`register_model_api` 挂载）。"""
    router = APIRouter()

    @router.get('/models')
    async def list_models(request: Request):
        def run(_payload):
            return service.list_models(
                kind=(request.query_params.get('kind') or '').strip() or None,
                keyword=request.query_params.get('keyword') or '',
                current_page=_query_int(request, 'currentPage', 1),
                page_size=_query_int(request, 'pageSize', 50),
            )

        return await _dispatch(request, run)

    # ⚠️ 静态路径必须排在 `/models/{model_id}` 之前，否则会被当成 model_id。
    @router.get('/models/thinking-presets')
    async def thinking_presets(request: Request):
        def run(_payload):
            return service.list_thinking_presets(
                kind=(request.query_params.get('kind') or '').strip() or None,
                model_name=request.query_params.get('modelName') or '',
                api_model=request.query_params.get('apiModel') or '',
                base_url=request.query_params.get('baseUrl') or '',
            )

        return await _dispatch(request, run)

    # ⚠️ 必须排在 `/models/{model_id}` 之前：路径参数会吃掉 'test' 这一段
    @router.post('/models/test')
    async def test_unsaved(request: Request):
        _require_admin(request)
        return await _dispatch(
            request, lambda payload: service.test_connection(payload), with_body=True)

    @router.post('/models')
    async def create_model(request: Request):
        _require_admin(request)
        return await _dispatch(
            request,
            lambda payload: service.create_model(payload, current_user(request)).to_public(),
            with_body=True, ok_status=201,
            location=lambda result: (
                f'{MODEL_PREFIX}/models/{result.get("modelId")}'
                if isinstance(result, dict) and result.get('modelId') else None))

    @router.get('/models/{model_id}')
    async def get_model(request: Request, model_id: str):
        return await _dispatch(request, lambda _payload: service.get_model(model_id).to_public())

    @router.put('/models/{model_id}')
    async def update_model(request: Request, model_id: str):
        _require_admin(request)
        return await _dispatch(
            request,
            lambda payload: service.update_model(model_id, payload).to_public(),
            with_body=True)

    @router.delete('/models/{model_id}')
    async def delete_model(request: Request, model_id: str):
        _require_admin(request)

        def run(_payload):
            service.delete_model(model_id)
            return {'modelId': model_id}

        return await _dispatch(request, run)

    @router.post('/models/{model_id}/test')
    async def test_saved(request: Request, model_id: str):
        _require_admin(request)

        def run(payload):
            record = service.get_model(model_id)
            merged = record.to_public()
            merged['modelKind'] = record.model_kind
            merged['apiKey'] = record.api_key
            payload = dict(payload or {})
            # 安全约束：前端没有重新提供 apiKey 时，这次测试用的就是**库里那把 key**，
            # 因此端点 / 路径也必须固定为库里保存的值。否则调用方可以把 baseUrl 换成
            # 任意主机，让服务端带着已保存的密钥去请求（密钥外泄 + SSRF）。
            # 想测一个改过端点的新配置，必须显式重新输入 apiKey。
            if not payload.get('apiKey'):
                for key in ('apiKey', 'baseUrl', 'chatPath', 'embeddingsPath',
                            'modelsPath', 'rerankPath'):
                    payload.pop(key, None)
            merged.update(payload)
            return service.test_connection(merged)

        return await _dispatch(request, run, with_body=True)

    return router


def register_model_api(app, service: ModelService = None) -> None:
    """把模型管理接口挂到 app 上。

    **调用点必须在 ``register_rkb_api`` 之前**（见模块 docstring）。
    """
    service = service or get_model_service()
    app.include_router(build_router(service), prefix=MODEL_PREFIX)
    log.info('Registered model api under %s', MODEL_PREFIX)
