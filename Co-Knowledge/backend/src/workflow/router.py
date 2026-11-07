"""HTTP 层：端点定义 + 单前缀注册。

**单前缀**：flow API 只挂在 ``/api/co-knowledge/v1`` 下。

**handler 是 async 的、DB 调用走线程池**：FastAPI 的 async handler 在事件循环里跑，
而 flow_api 的存储是阻塞的 psycopg2。用 ``run_in_threadpool`` 把整段业务（含响应构造）
放进线程池，既不阻塞事件循环，也不用为每个端点写一遍 try/except。

**鉴权由 ``AuthMiddleware`` 统一负责**（``AUTH_MODE=local`` 时校验会话 Cookie）；
本模块只用 ``current_user`` 解析归属，不再自己实现一套头解析。
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Request, Response
from starlette.concurrency import run_in_threadpool

from workflow import responses
from shared.prefixes import RKB_PREFIX
from workflow.errors import (FlowError,
                                    FlowMalformedRequestError, FlowStoreError)
from workflow.messages import normalize_template_language
from workflow.runtime import get_flow_service
from workflow.service import FlowService
from workflow.repository import create_default_store
from infrastructure.http.identity import current_user
from infrastructure.logging.logutil import log


def build_router(service: FlowService) -> APIRouter:
    """构造全部端点（不绑定前缀；注册时挂在唯一对外前缀下）。"""
    router = APIRouter()

    # ------------------------------------------------------------------
    # 工作流集合
    #
    # 原 `/workflow` 的列表/建流/更新/删除四条动作式路径收敛为 REST 动词。
    # `/workflows/knowledge-bases` 是画布与对话页共用的知识库下拉源；
    # 静态子路径统一排在 `/{workflow_id}` 之前，避免被动态段吃掉。
    # ------------------------------------------------------------------

    @router.get('/workflows')
    async def page_workflows(request: Request):
        query = request.query_params
        page = query.get('page') or query.get('currentPage')
        size = query.get('size') or query.get('pageSize')
        keyword = query.get('keyword', query.get('name'))
        publish_type = query.get('publishType', query.get('publish_type'))
        return await _dispatch(
            request,
            lambda _payload: service.page_workflows(page, size, keyword, publish_type))

    @router.post('/workflows')
    async def create_workflow(request: Request):
        return await _dispatch(
            request,
            # 建流播种取的是**模板变体**语言（language-option），不是文案语言：
            # 它决定画布里的中文/英文提示词，落库后就不再变
            lambda payload: service.create_workflow(payload, current_user(request),
                                                    _template_language(request)),
            with_body=True, body_required=True, ok_status=201,
            location=lambda result: (
                f'{RKB_PREFIX}/workflows/'
                f'{result.get("workflowId") or result.get("appId") or result.get("id")}'
                if isinstance(result, dict) and (
                    result.get('workflowId') or result.get('appId') or result.get('id'))
                else None),
        )

    @router.get('/workflows/knowledge-bases')
    async def all_status_kbase(request: Request):
        embedding = request.query_params.get('embedding')
        return await _dispatch(
            request,
            lambda _payload: service.list_all_status_kbases({'embedding': embedding}))

    @router.patch('/workflows/{workflow_id}')
    async def update_workflow(request: Request, workflow_id: str):
        return await _dispatch(
            request,
            lambda payload: service.update_workflow(
                {**payload, 'workflowId': workflow_id}, _message_language(request)),
            with_body=True, body_required=True,
        )

    @router.delete('/workflows/{workflow_id}')
    async def delete_workflow(request: Request, workflow_id: str):
        return await _dispatch(
            request,
            lambda _payload: service.delete_workflow(
                {'workflowId': workflow_id}, _message_language(request)),
            ok_status=204)

    # ------------------------------------------------------------------
    # 单个工作流的画布与发布
    # ------------------------------------------------------------------

    @router.get('/workflows/{workflow_id}/flow')
    async def get_flow_config(request: Request, workflow_id: str):
        return await _dispatch(
            request,
            lambda _payload: service.get_flow_config(
                workflow_id, _message_language(request)))

    @router.put('/workflows/{workflow_id}/flow')
    async def save_flow_config(request: Request, workflow_id: str):
        return await _dispatch(
            request,
            lambda payload: {'version': service.save_flow_config(
                workflow_id, payload, current_user(request), _message_language(request))},
            with_body=True, body_required=True,
        )

    @router.post('/workflows/{workflow_id}/validate')
    async def pre_check(request: Request, workflow_id: str):
        return await _dispatch(
            request,
            lambda payload: service.precheck(
                workflow_id, payload, _message_language(request)),
            with_body=True, body_required=True,
        )

    @router.get('/workflows/{workflow_id}/publication')
    async def get_published_flow_config(request: Request, workflow_id: str):
        return await _dispatch(
            request,
            lambda _payload: service.get_published_flow_config(
                workflow_id, _message_language(request)))

    @router.post('/workflows/{workflow_id}/publication')
    async def publish(request: Request, workflow_id: str):
        return await _dispatch(
            request,
            lambda _payload: {'version': service.publish(
                workflow_id, current_user(request), _message_language(request))},
            ok_status=201,
            location=f'{RKB_PREFIX}/workflows/{workflow_id}/publication')

    @router.delete('/workflows/{workflow_id}/publication')
    async def unpublish(request: Request, workflow_id: str):
        return await _dispatch(
            request,
            lambda _payload: service.unpublish(workflow_id),
            ok_status=204)

    @router.get('/workflows/{workflow_id}/export')
    async def download_asset(request: Request, workflow_id: str):
        """导出画布 JSON。

        响应体**不能**是 ``application/json`` —— 前端 axios 拦截器会把 json 的 blob
        当成错误信封解析，然后 ``download()`` 拿到一个普通对象、下载出 ``[object Object]``。
        但**出错时**必须回信封（JSON），否则前端只会看到「下载失败」，
        拿不到「工作流不存在」。
        """
        language = _message_language(request)
        try:
            filename, content = await run_in_threadpool(
                service.export_flow_config, workflow_id, language)
        except Exception as error:  # noqa: BLE001 —— 与其他端点同一条错误翻译路径
            return _render_error(request, language, error)
        headers = {
            'Content-Disposition': "attachment; filename*=utf-8''" + quote(filename, safe=''),
        }
        return Response(content=content, media_type='application/octet-stream', headers=headers)

    return router


def register_flow_api(app, store=None, capabilities=None, kbase_provider=None,
                      model_probe=None) -> None:
    """把 flow API 挂到 app 的唯一对外前缀下。

    :param store: 省略时用生产默认（``PgFlowStore``，读 ``flow_*`` 三表）；测试注入内存实现
    :param model_probe: 可用模型探测器的替身；省略且 ``capabilities`` 也是省略时，
        由 :class:`~workflow.service.FlowService` 按环境变量建一个真的
    """
    # 全默认（= 生产装配）时取**运行时单例**：编排在进程内读的是同一份配置，
    # 两边不会各建一个 FlowService 而悄悄分叉（见 workflow/runtime.py）。
    # 测试注入了 store/capabilities/kbase_provider/model_probe 任一项时仍各建各的，
    # 隔离语义不变。
    if store is None and capabilities is None and kbase_provider is None and model_probe is None:
        service = get_flow_service()
    else:
        service = FlowService(
            store if store is not None else create_default_store(),
            capabilities,
            kbase_provider,
            model_probe,
        )
    router = build_router(service)
    app.include_router(router, prefix=RKB_PREFIX)
    log.info('Registered flow api under %s', RKB_PREFIX)


# ----------------------------------------------------------------------
# 请求分发
# ----------------------------------------------------------------------


def _message_language(request: Request) -> str:
    """**文案语言**：``Accept-Language`` 的主标签语义。

    直接委托 kb_api 的 ``identity.language`` —— 同一实现、同一张归一化表，
    两套接口对同一请求头必然给出同一结论。不要改读 ``language-option``：
    浏览器只发 ``Accept-Language``，那会让画布页的报错文案**语言相反**。

    延迟 import 与 ``service.py`` 里 ``knowledge_base.kbase_options`` 同一约定：
    避免两个接口族在导入期互相牵连。
    """
    from infrastructure.http.identity import language

    return language(request)


def _template_language(request: Request) -> str:
    """**模板变体语言**：``language-option``（RKB ``httputil.get_language_option`` 规则）。

    只影响建流播种时选中文还是英文模板 —— 是「内容变体」，不是「文案」。
    对应 kb_api 里 ``header_language()``（内容命名）与 ``language()``（文案）的二分。
    """
    return normalize_template_language(request.headers.get('language-option'))


def _enforce_body_content_type(request: Request, raw: bytes) -> None:
    """JSON 体端点的 Content-Type 闸门 —— 按 JSON 请求体的媒体类型判定。

    判定表与字节级依据见 ``infrastructure/http/content_type.py`` 模块头（flow 与 kb 是
    同一套媒体类型语义、同一轮实测）。两个归宿：

    * 媒体类型不合格（**含「没有 Content-Type + 非空体」**）→ 0005 + ``msg:null``
      （``FlowError(None)`` 的新形态；修复前这里会照常解析）；
    * form-urlencoded 体解不出 / multipart 缺 boundary → 0001（读体阶段抛）。

    调用点在 appId 必填校验**之后** —— 参数绑定先于请求体
    （实测：``/flow/preCheck`` 缺 appId + text/plain → 0004，不是 0005）。
    """
    from infrastructure.http import content_type

    verdict = content_type.classify(request.headers.get('content-type'), raw)
    if verdict == content_type.BAD_FORM:
        raise FlowMalformedRequestError()
    if verdict is not None:
        raise FlowError(None, status=415, problem_code='unsupported_media_type')


async def _dispatch(request: Request, fn, with_body: bool = False,
                    body_required: bool = False, ok_status: int = 200,
                    location=None):
    """统一的「解析 → 执行 → 构造纯 REST 响应」。

    业务执行放线程池（psycopg2 是阻塞的）；异常在这里翻译成 problem+json。
    ``ok_status`` / ``location`` 用于创建（201）、异步（202）与删除（204）。
    """
    raw = await request.body() if with_body else b''
    return await run_in_threadpool(
        _dispatch_sync, request, raw, fn, body_required, with_body,
        ok_status, location)


def _dispatch_sync(request: Request, raw: bytes, fn, body_required: bool = False,
                   with_body: bool = False, ok_status: int = 200, location=None):
    language = _message_language(request)
    try:
        if with_body:
            _enforce_body_content_type(request, raw)
        payload = responses.parse_json_body(raw, required=body_required)
        data = fn(payload)
        if isinstance(data, Response):
            return data
        if ok_status == 204 or data is None:
            return responses.no_content()
        loc = location(data) if callable(location) else location
        if ok_status == 201:
            return responses.created(data, location=loc)
        if ok_status == 202:
            return responses.accepted(data, location=loc)
        return responses.json_response(data, status_code=ok_status)
    except Exception as error:  # noqa: BLE001 —— 顶层兜底，任何异常都翻成 problem 而不是 500 裸页
        return _render_error(request, language, error)


def _render_error(request: Request, language: str, error: Exception):
    """异常 → problem+json（普通端点与下载端点共用同一条路径）。"""
    if isinstance(error, FlowError):
        return responses.error(request, error, language)
    if isinstance(error, (ValueError, UnicodeDecodeError)):
        log.warning('Bad request body on %s: %s', responses.route_path(request), error)
        return responses.error(request, FlowMalformedRequestError(), language)
    if isinstance(error, FlowStoreError):
        # 存储层错误：日志留原始信息（表不存在时第一现场就在这里），响应只给通用文案
        log.error('Flow store error (%s) on %s: %s',
                  error.kind, responses.route_path(request), error.detail)
        return responses.store_error(request, error, language)
    log.exception('Unhandled error on %s', responses.route_path(request))
    return responses.server_error(request, language)
