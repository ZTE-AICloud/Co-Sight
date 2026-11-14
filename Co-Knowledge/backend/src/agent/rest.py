"""Agent REST facade（挂载在 ``/api/co-knowledge/v1/agent``）。

与其余 ``/api/co-knowledge/v1`` 端点同一契约：成功 body 就是资源本身
（列表是 JSON 数组、详情/检索/问答是对象），失败是真实 HTTP 状态码 +
``application/problem+json``。``X-Request-Id`` 仍在响应头里，body 不再重复。
OpenAPI 由这个子应用自动生成（3.0.2，便于 Dify/Coze 导入）。

子应用的异常处理器必须自己兜住所有错误；父应用（``http_api.py``）
的处理器也已把 ``/agent`` 纳入 problem 契约，两道兜底同形。
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from infrastructure.logging import trace
from infrastructure.logging.logutil import log
from infrastructure.http.openapi_contract import (
    normalize_nullable_schemas,
    normalize_object_schemas,
)

from agent import config, query as agent_query, service
from agent.auth import (AgentContext, agent_context, error_headers,
                        require_scope)
from agent.errors import AgentApiError, internal_error
from agent.schemas import (
    AnswerData,
    AnswerRequest,
    KnowledgeBaseInfo,
    Problem,
    SearchData,
    SearchRequest,
    WorkflowPage,
    WorkflowQueryAnswer,
    WorkflowQueryRequest,
)
from shared.problem import PROBLEM_MEDIA_TYPE, ProblemSpec, problem_response, title_for
from workflow.models import MAX_PAGE_SIZE, DEFAULT_PAGE_SIZE

router = APIRouter()

_PROBLEM_RESPONSE = {'model': Problem}


def _request_id(request: Request) -> str:
    """本次请求的 ID：中间件分配的优先，独立挂载（测试）时兜底生成。"""
    return (getattr(request.state, 'request_id', None)
            or getattr(request.state, 'trace_id', None)
            or uuid.uuid4().hex)


def _error_response(request: Request, error: AgentApiError) -> JSONResponse:
    spec = ProblemSpec(error.http_status, error.code, title_for(error.code))
    headers = error_headers(error)
    headers[trace.REQUEST_ID_HEADER] = _request_id(request)
    extensions = error.details if isinstance(error.details, dict) else None
    return problem_response(
        spec, error.message, instance=request.url.path,
        headers=headers, extensions=extensions)


def _agent_error_handler(request: Request, exc: AgentApiError) -> JSONResponse:
    return _error_response(request, exc)


def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {'loc': list(item.get('loc') or []), 'msg': item.get('msg'), 'type': item.get('type')}
        for item in exc.errors()
    ]
    error = AgentApiError(422, 'validation_failed', 'Request validation failed')
    spec = ProblemSpec(error.http_status, error.code, title_for(error.code))
    headers = error_headers(error)
    headers[trace.REQUEST_ID_HEADER] = _request_id(request)
    return problem_response(
        spec, error.message, instance=request.url.path,
        headers=headers, extensions={'errors': details})


def _http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == 404:
        return _error_response(request, AgentApiError(404, 'not_found', 'Not found'))
    if exc.status_code == 405:
        return _error_response(
            request, AgentApiError(405, 'method_not_allowed', 'Method not allowed'))
    return _error_response(
        request,
        AgentApiError(exc.status_code, 'http_error', str(exc.detail or 'HTTP error')))


def _unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = _request_id(request)
    # ``log.exception`` 在这里拿不到 active exception（FastAPI 的 Exception 处理器
    # 可能不在 except 上下文里），会打成 ``NoneType: None``；显式把 exc 交给
    # ``exc_info`` 才能留下 traceback。
    log.error('agent rest unexpected error trace=%s', trace_id, exc_info=exc)
    return _error_response(request, internal_error())


@router.get('/knowledge-bases', response_model=list[KnowledgeBaseInfo],
            responses={401: _PROBLEM_RESPONSE, 403: _PROBLEM_RESPONSE})
def list_knowledge_bases(
    response: Response,
    ctx: AgentContext = Depends(agent_context),
):
    data = service.list_knowledge_bases(ctx.principal, ctx.trace_id)
    response.headers[trace.REQUEST_ID_HEADER] = ctx.trace_id
    return data


@router.get('/knowledge-bases/{kb_id}', response_model=KnowledgeBaseInfo,
            responses={401: _PROBLEM_RESPONSE, 403: _PROBLEM_RESPONSE,
                       404: _PROBLEM_RESPONSE})
def get_knowledge_base(
    kb_id: str,
    response: Response,
    ctx: AgentContext = Depends(agent_context),
):
    data = service.get_knowledge_base(ctx.principal, kb_id, ctx.trace_id)
    response.headers[trace.REQUEST_ID_HEADER] = ctx.trace_id
    return data


@router.post('/search', response_model=SearchData,
             responses={400: _PROBLEM_RESPONSE, 401: _PROBLEM_RESPONSE,
                        403: _PROBLEM_RESPONSE, 404: _PROBLEM_RESPONSE,
                        422: _PROBLEM_RESPONSE, 429: _PROBLEM_RESPONSE,
                        502: _PROBLEM_RESPONSE})
def search(
    payload: SearchRequest,
    response: Response,
    ctx: AgentContext = Depends(agent_context),
):
    data = service.search(ctx.principal, payload, ctx.trace_id, service.SURFACE_REST)
    response.headers[trace.REQUEST_ID_HEADER] = ctx.trace_id
    return data


@router.post('/answer', response_model=AnswerData,
             responses={400: _PROBLEM_RESPONSE, 401: _PROBLEM_RESPONSE,
                        403: _PROBLEM_RESPONSE, 404: _PROBLEM_RESPONSE,
                        422: _PROBLEM_RESPONSE, 429: _PROBLEM_RESPONSE,
                        502: _PROBLEM_RESPONSE, 503: _PROBLEM_RESPONSE})
def answer(
    payload: AnswerRequest,
    response: Response,
    ctx: AgentContext = Depends(agent_context),
):
    data = service.answer(ctx.principal, payload, ctx.trace_id, service.SURFACE_REST)
    response.headers[trace.REQUEST_ID_HEADER] = ctx.trace_id
    return data


@router.post('/query', response_model=WorkflowQueryAnswer,
             responses={
                 200: {
                     'description': 'Non-stream JSON answer, or SSE when stream=true',
                     'content': {'text/event-stream': {'schema': {'type': 'string'}}},
                 },
                 400: _PROBLEM_RESPONSE,
                 401: _PROBLEM_RESPONSE,
                 403: _PROBLEM_RESPONSE,
                 404: _PROBLEM_RESPONSE,
                 422: _PROBLEM_RESPONSE,
                 429: _PROBLEM_RESPONSE,
                 502: _PROBLEM_RESPONSE,
                 503: _PROBLEM_RESPONSE,
             })
def query_workflow(
    payload: WorkflowQueryRequest,
    request: Request,
    ctx: AgentContext = Depends(agent_context),
):
    """Execute a published workflow with the Agent API key.

    The response is the same object as the native ``POST /query``; when
    ``stream=true`` (or ``Accept: text/event-stream``) the response is SSE.
    """
    require_scope(ctx.principal, agent_query.QUERY_SCOPE)
    rag_request = payload.to_rag_request()
    agent_query.prepare_request(ctx.principal, rag_request)
    # 延迟 import：让 Agent OpenAPI/CLI 路径不拉起 chat/engine 依赖树；
    # 运行期 chat 已由宿主装配加载，这里只是取同一个 run_query 实现。
    from chat.app import run_query

    return run_query(rag_request, request, surface='agent')


@router.get('/workflows', response_model=WorkflowPage,
            responses={401: _PROBLEM_RESPONSE, 403: _PROBLEM_RESPONSE})
def list_workflows(
    response: Response,
    page: int = Query(1, ge=1, le=10000),
    size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    keyword: Optional[str] = Query(None, max_length=255),
    publish_type: Optional[int] = Query(None, alias='publishType', ge=0, le=2,
                                        description='0=unpublished, 1=published, '
                                                    '2=published with draft changes'),
    ctx: AgentContext = Depends(agent_context),
):
    data = service.list_workflows(ctx.principal, page, size, keyword, publish_type,
                                  ctx.trace_id, service.SURFACE_REST)
    response.headers[trace.REQUEST_ID_HEADER] = ctx.trace_id
    return data


_OPENAPI_DESCRIPTION = (
    'Knowledge retrieval, citation-grounded answers, workflow discovery and '
    'published workflow execution for agents. Bearer API key required; see '
    'docs/agent-integration.md. Errors use application/problem+json (RFC 9457); '
    'X-Request-Id is a response header.'
)


def _build_openapi(app: FastAPI) -> dict:
    """生成 OpenAPI 3.0.2，并把所有错误响应的媒体类型改成 problem+json。

    FastAPI 默认把 ``responses={...: {'model': ...}}`` 画成 ``application/json``；
    运行时错误实际是 ``application/problem+json``，这里统一改写，契约不撒谎。
    """

    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        servers=[{'url': config.public_base()}],
    )
    # FastAPI 生成的是 3.1 结构；本接口没用到 3.1 特性，Dify/Coze 只认 3.0。
    schema['openapi'] = '3.0.2'
    normalize_object_schemas(schema)
    normalize_nullable_schemas(schema)
    # FastAPI 0.162 给 ValidationError 增加了 ctx/input；本契约保持原有形状。
    validation_error = (schema.get('components', {}).get('schemas', {})
                        .get('ValidationError', {}).get('properties', {}))
    validation_error.pop('ctx', None)
    validation_error.pop('input', None)
    for path_item in schema.get('paths', {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            for status, response in (operation.get('responses') or {}).items():
                if str(status).startswith('2'):
                    continue
                content = response.get('content') or {}
                if 'application/json' in content:
                    content[PROBLEM_MEDIA_TYPE] = content.pop('application/json')
    app.openapi_schema = schema
    return schema


def build_rest_app() -> FastAPI:
    app = FastAPI(
        title='Knowledge Studio Agent API',
        description=_OPENAPI_DESCRIPTION,
        version='1.4.0',
        openapi_url='/openapi.json',
        docs_url=None,          # 与主应用一致：不暴露 Swagger UI
        redoc_url=None,
        servers=[{'url': config.public_base()}],
    )
    app.include_router(router)
    app.add_exception_handler(AgentApiError, _agent_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(Exception, _unexpected_handler)
    app.openapi = lambda: _build_openapi(app)                  # noqa: E731
    return app
