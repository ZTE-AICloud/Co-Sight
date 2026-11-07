"""``POST /agent/query`` 的请求边界与执行（执行已发布工作流）。

Agent Key 的执行入口是 **``/agent/query``**（与 `/agent/workflows` 同一前缀、
同一 OpenAPI）；原生 ``POST /query`` 仍是浏览器会话/网关面，不在这里做鉴权。
本模块负责「Key 能执行什么」的边界，不碰 HTTP 鉴权（由 ``agent_context`` /
``AuthenticatedMCPApp`` 完成）。

约束：

* ``scope=dev`` 对 API Key 一律拒绝，只执行**已发布快照**；
* ``workflow_id`` 必须显式给出，避免误跑默认工作流；
* Key 的 ``kbIds`` 非空时，校验**发布快照**绑定的文档/结构化知识库；
  ``flow_workflow.bound_info`` 只在建流时写入，不能作为权限依据。
* 图谱库不在 Agent Key 的白名单下拉里，跳过；含图谱检索的工作流由
  ``workflow:run`` scope 显式授权。

MCP 工具 ``run_workflow`` 与 REST 走**同一个** ``chat.app.run_query``，不经过
HTTP 回环：本模块传一个只具备 ``headers`` / ``url.path`` / ``state.trace_id``
的鸭子类型请求，再按响应类型收口 —— JSON 直接解出答案体；SSE 则消费同一份
具名事件帧，把 token 转成 MCP progress 通知，结束后拼出与非流式同形的答案。
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Awaitable, Callable, Optional

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers

from infrastructure.logging.logutil import log
from shared.prefixes import AGENT_PREFIX

from agent import workflows
from agent.auth import AgentPrincipal, require_scope
from agent.errors import AgentApiError, knowledge_base_forbidden
from agent.schemas import WorkflowQueryRequest
from engine.common import const

#: 执行已发布工作流所需的 scope。
QUERY_SCOPE = 'workflow:run'

#: 流式 token 转 MCP 进度通知的最小间隔（秒）。逐 token 发会把 SSE 连接淹没，
#: 0.25s 足够让客户端看到「正在生成」，又不丢可读性。
PROGRESS_INTERVAL_SECONDS = 0.25

#: ``(本次新增文本, 已生成字符数) -> None``；MCP 层用它发 progress 通知。
ProgressCallback = Callable[[str, int], Awaitable[None]]

_DEFAULT_WORKFLOW_ID = const.default_workflow_id


def prepare_request(principal: AgentPrincipal, rag_request) -> None:
    """API Key 调用的额外约束（在入参校验之前执行）。"""
    if str(getattr(rag_request, 'scope', '') or '').strip().lower() == 'dev':
        raise AgentApiError(400, 'invalid_request',
                            'scope=dev is not available for API key access')

    workflow_id = str(getattr(rag_request, 'workflow_id', '') or '').strip()
    if not workflow_id or workflow_id == _DEFAULT_WORKFLOW_ID:
        raise AgentApiError(422, 'validation_failed',
                            'workflow_id is required for API key access')

    _enforce_kb_whitelist(principal, workflow_id)


def _enforce_kb_whitelist(principal: AgentPrincipal, workflow_id: str) -> None:
    """Key 有知识库白名单时，校验工作流发布快照绑定的文档/结构化库。

    ``principal.kb_ids`` 为空表示不限制，直接放行（也省掉一次快照读取）。
    图谱库由 ``workflow:run`` 授权，不参与 ``kbIds`` 比较（见 ``bound_kb_ids``）。
    """
    if not principal.kb_ids:
        return
    try:
        bound = workflows.bound_kb_ids(workflow_id)
    except AgentApiError as error:
        # 与 `/query` 的运行期语义对齐：工作流不存在/未发布统一报
        # published_workflow_not_found，而不是 404 workflow_not_found。
        if error.http_status == 404 and error.code == 'workflow_not_found':
            raise AgentApiError(404, 'published_workflow_not_found',
                                'Workflow is not published') from error
        raise
    allowed = set(principal.kb_ids)
    for kb_id in bound:
        if kb_id not in allowed:
            raise knowledge_base_forbidden(kb_id)


class _EngineRequest:
    """``chat.app.run_query`` 用到的最小请求面。

    MCP 工具没有 FastAPI 的 ``Request``，但 ``run_query`` 只读三处：``headers``、
    ``url.path``（日志 / problem ``instance``）与 ``state.trace_id``。用鸭子类型
    复用同一条执行路径，避免把进程内调用改成 HTTP 回环。
    """

    def __init__(self, headers: Headers, path: str, trace_id: str) -> None:
        self.headers = headers
        self.url = SimpleNamespace(path=path)
        self.state = SimpleNamespace(trace_id=trace_id)


def _engine_headers(inbound: Optional[Headers], *, stream: bool) -> Headers:
    """透传入站头，但 ``Accept`` 由工具参数决定。

    MCP 客户端每个请求都带 ``Accept: application/json, text/event-stream``；
    原样透传会让 ``run_query`` 把所有调用都判成流式（``stream=false`` 失效）。
    """
    pairs = [(key, value) for key, value in (inbound or Headers()).items()
             if key.lower() != 'accept']
    pairs.append(('accept', 'text/event-stream' if stream else 'application/json'))
    return Headers(dict(pairs))


async def execute(principal: AgentPrincipal, payload: WorkflowQueryRequest, *,
                  headers: Optional[Headers] = None, trace_id: str,
                  on_progress: Optional[ProgressCallback] = None) -> dict:
    """执行一次已发布工作流，返回 Agent 面的答案对象。

    ``stream=true`` 时返回体与非流式同形（``{conversation_id, answer, retrieval?}``）：
    MCP 没有「工具结果流」，token 通过 ``on_progress`` 转成 progress 通知，
    完整答案在结束时一次性返回。调用方负责把 ``AgentApiError`` 渲染成自己的错误形状。
    """
    require_scope(principal, QUERY_SCOPE)
    rag_request = payload.to_rag_request()
    prepare_request(principal, rag_request)

    # 延迟 import：让 Agent OpenAPI/CLI 路径不拉起 chat/engine 依赖树。
    from chat.app import run_query

    engine_request = _EngineRequest(
        _engine_headers(headers, stream=bool(rag_request.stream)),
        AGENT_PREFIX + '/query', trace_id)
    # 编排是同步 I/O（psycopg2 / requests）；流式到这里只等「检索完成」这一段。
    response = await run_in_threadpool(run_query, rag_request, engine_request,
                                       surface='agent')
    if hasattr(response, 'body_iterator'):
        return await _consume_stream(response, rag_request, on_progress)
    return await _consume_json(response)


async def _consume_json(response) -> dict:
    """解出 ``run_query`` 的 JSON 响应体；problem 响应翻成 ``AgentApiError``。"""
    try:
        body = json.loads(bytes(response.body))
    finally:
        await _run_background(response)
    status = int(getattr(response, 'status_code', 200))
    if status >= 400:
        raise AgentApiError(status, body.get('code') or 'internal_error',
                            body.get('detail') or 'Workflow execution failed')
    return body


async def _consume_stream(response, rag_request: WorkflowQueryRequest,
                          on_progress: Optional[ProgressCallback]) -> dict:
    """消费 ``EventSourceResponse`` 的具名事件，拼出答案并转发 token 进度。"""
    parts: list[str] = []
    retrieval = None
    pending: list[str] = []
    answer_len = 0
    flushed_at = time.monotonic()
    try:
        async for item in response.body_iterator:
            event, payload = _decode_event(item)
            if event == 'retrieval':
                retrieval = payload.get('evidence')
            elif event == 'token':
                content = payload.get('content') or ''
                if not content:
                    continue
                parts.append(content)
                answer_len += len(content)
                if on_progress is not None:
                    pending.append(content)
                    now = time.monotonic()
                    if now - flushed_at >= PROGRESS_INTERVAL_SECONDS:
                        await _flush_progress(on_progress, pending, answer_len)
                        flushed_at = now
            elif event == 'done':
                break
            elif event == 'error':
                raise AgentApiError(
                    int(payload.get('status') or 500),
                    payload.get('code') or 'internal_error',
                    payload.get('detail') or 'Workflow execution failed')
    finally:
        # 直接迭代 body_iterator 不会经过 Response.__call__，background 必须自己跑，
        # 否则 MCP 的调用不会写 query trace。
        await _run_background(response)
    await _flush_progress(on_progress, pending, answer_len)
    result = {'conversation_id': rag_request.conversation_id,
              'answer': ''.join(parts)}
    if rag_request.include_retrieval and retrieval is not None:
        result['retrieval'] = retrieval
    return result


def _decode_event(item) -> tuple[str, dict]:
    """SSE 帧 → ``(事件名, JSON 载荷)``；畸形载荷按空对象处理。"""
    data = getattr(item, 'data', item)
    if isinstance(data, (bytes, bytearray)):
        data = data.decode('utf-8', errors='replace')
    try:
        payload = json.loads(data) if isinstance(data, str) else {}
    except ValueError:
        payload = {}
    event = getattr(item, 'event', None) or 'message'
    return event, payload if isinstance(payload, dict) else {}


async def _flush_progress(callback: Optional[ProgressCallback], pending: list[str],
                          answer_len: int) -> None:
    if not pending:
        return
    chunk = ''.join(pending)
    pending.clear()
    if callback is not None:
        await callback(chunk, answer_len)


async def _run_background(response) -> None:
    """执行响应挂的 background（query trace 入队），失败只记日志。"""
    background = getattr(response, 'background', None)
    if background is None:
        return
    try:
        await background()
    except Exception:                                              # noqa: BLE001
        log.exception('agent query background task failed')
