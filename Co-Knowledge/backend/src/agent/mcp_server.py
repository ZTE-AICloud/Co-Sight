"""MCP Server（Streamable HTTP）与 5 个工具。

与 REST 共用 ``service.py`` / ``query.py``，不经过 HTTP 回环。两个实现细节必须守住：

1. **同步 I/O 下沉线程池**：FastMCP 1.12.4 对同步工具函数是**在事件循环里直接调用**
   （``fn_metadata.call_fn_with_arg_validation`` 的 else 分支），而检索/生成全是同步的
   psycopg2/requests。工具写成 ``async def`` + ``run_in_threadpool``，否则一次慢 answer
   会卡死整个 RKB 进程。
2. **principal 从请求状态取**：ASGI 鉴权层把 ``agent_principal`` 写进 ``scope['state']``，
   FastMCP 又把当前 Starlette ``Request`` 放进 ``ctx.request_context.request``。

``run_workflow`` 的 ``stream=true`` 不等于「工具结果流」（MCP 没有这种能力）：
它消费 ``/query`` 的具名 SSE 帧，把 token 转成 ``notifications/progress``，
完整答案仍在工具结果里返回。
"""

# ⚠️ 不要加 ``from __future__ import annotations``：FastMCP 1.12.4 用
# ``issubclass(param.annotation, Context)`` 识别 Context 参数，字符串注解会直接炸
# ``TypeError: issubclass() arg 1 must be a class``。
from typing import Annotated, Literal, Optional

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError
from starlette.concurrency import run_in_threadpool

from infrastructure.logging.logutil import log

from agent import auth, config, query as agent_query, service
from agent.schemas import AnswerRequest, ChatHistoryItem, SearchRequest, WorkflowQueryRequest

SEARCH_MODES = ('auto', 'hybrid', 'vector', 'keyword')

SERVER_INSTRUCTIONS = """Knowledge Studio knowledge retrieval.
- Call list_knowledge_bases first to discover the knowledge bases this API key can access.
- Use search_knowledge when you need raw source passages to reason over yourself.
- Use ask_knowledge_base when you want a synthesized answer grounded in the sources;
  it returns citations in [S1] style and is slower (requires a generation model).
- Use list_workflows to discover workflows and their publish status. Workflow
  creation, canvas editing and model/retrieval parameters are done in the Knowledge Studio
  console, not through this API.
- Use run_workflow to execute a published workflow (requires the workflow:run scope).
  With stream=true, generated tokens also arrive as MCP progress notifications;
  the complete answer is returned in the tool result either way.
- Never invent citations. If a tool returns isError, surface the message to the user.
"""

_READ_ONLY = dict(readOnlyHint=True, destructiveHint=False, openWorldHint=False)


def _transport_security() -> TransportSecuritySettings:
    if not config.mcp_dns_rebinding_protection():
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=config.mcp_allowed_hosts(),
        allowed_origins=config.mcp_allowed_origins(),
    )


def _tool_error(error: Exception) -> ToolError:
    from agent.errors import AgentApiError

    if isinstance(error, AgentApiError):
        return ToolError(f'{error.code}: {error.message}')
    return ToolError(f'internal_error: {error}')


def build_mcp() -> FastMCP:
    mcp = FastMCP(
        name='rag-studio-knowledge',
        instructions=SERVER_INSTRUCTIONS,
        log_level='WARNING',
        stateless_http=config.mcp_stateless(),
        json_response=config.mcp_json_response(),
        transport_security=_transport_security(),
    )

    @mcp.tool(name='list_knowledge_bases',
              description='List document knowledge bases accessible to this API key.',
              annotations=ToolAnnotations(idempotentHint=True, **_READ_ONLY),
              structured_output=False)
    async def list_knowledge_bases(ctx: Context) -> dict:
        principal = auth.principal_from_context(ctx)
        trace_id = auth.trace_id_from_context(ctx)
        try:
            rows = await run_in_threadpool(
                lambda: service.list_knowledge_bases(principal, trace_id, service.SURFACE_MCP))
        except Exception as error:                                 # noqa: BLE001
            raise _tool_error(error) from error
        return {'trace_id': trace_id, 'knowledge_bases': rows}

    @mcp.tool(name='search_knowledge',
              description=(
                  'Search accessible document knowledge bases and return ranked chunks '
                  'with citation IDs. Use this when you need raw source passages.'
              ),
              annotations=ToolAnnotations(idempotentHint=True, **_READ_ONLY),
              structured_output=False)
    async def search_knowledge(
        query: Annotated[str, Field(min_length=1, max_length=2000,
                                    description='Natural-language query')],
        ctx: Context,
        knowledge_base_ids: Annotated[
            Optional[list[str]], Field(description='Omit/empty = all accessible')] = None,
        mode: Annotated[Literal['auto', 'hybrid', 'vector', 'keyword'],
                        Field(description='Retrieval mode')] = 'auto',
        top_k: Annotated[int, Field(ge=1, description='Result count (default 20 max)')] = 8,
    ) -> dict:
        principal = auth.principal_from_context(ctx)
        trace_id = auth.trace_id_from_context(ctx)
        try:
            request = SearchRequest(query=query, knowledge_base_ids=knowledge_base_ids,
                                    mode=mode, top_k=top_k)
        except ValidationError as error:
            raise ToolError(f'validation_error: {error.errors()[0].get("msg")}') from error
        try:
            data = await run_in_threadpool(
                lambda: service.search(principal, request, trace_id, service.SURFACE_MCP))
        except Exception as error:                                 # noqa: BLE001
            raise _tool_error(error) from error
        return {'trace_id': trace_id, **data}

    @mcp.tool(name='ask_knowledge_base',
              description=(
                  'Answer a question from accessible document knowledge bases with '
                  'citation-grounded sources ([S1] style). Slower than search_knowledge '
                  'because it calls a generation model.'
              ),
              annotations=ToolAnnotations(idempotentHint=False, **_READ_ONLY),
              structured_output=False)
    async def ask_knowledge_base(
        question: Annotated[str, Field(min_length=1, max_length=2000)],
        ctx: Context,
        knowledge_base_ids: Annotated[
            Optional[list[str]], Field(description='Omit/empty = all accessible')] = None,
        mode: Annotated[Literal['auto', 'hybrid', 'vector', 'keyword'],
                        Field(description='Retrieval mode')] = 'auto',
        top_k: Annotated[int, Field(ge=1, description='Number of sources')] = 8,
        model: Annotated[Optional[str], Field(max_length=255,
                                              description='Optional registered LLM name')] = None,
    ) -> dict:
        principal = auth.principal_from_context(ctx)
        trace_id = auth.trace_id_from_context(ctx)
        try:
            request = AnswerRequest(question=question, knowledge_base_ids=knowledge_base_ids,
                                    mode=mode, top_k=top_k, model=model)
        except ValidationError as error:
            raise ToolError(f'validation_error: {error.errors()[0].get("msg")}') from error
        try:
            data = await run_in_threadpool(
                lambda: service.answer(principal, request, trace_id, service.SURFACE_MCP))
        except Exception as error:                                 # noqa: BLE001
            raise _tool_error(error) from error
        return {'trace_id': trace_id, **data}

    @mcp.tool(name='list_workflows',
              description=(
                  'List workflows visible to this API key with their publish status. '
                  'Use publish_type to filter: 0=unpublished, 1=published, '
                  '2=published with draft changes.'
              ),
              annotations=ToolAnnotations(idempotentHint=True, **_READ_ONLY),
              structured_output=False)
    async def list_workflows(
        ctx: Context,
        page: Annotated[int, Field(ge=1, le=10000, description='Page number, 1-based')] = 1,
        size: Annotated[int, Field(ge=1, le=1000, description='Page size')] = 20,
        keyword: Annotated[Optional[str], Field(max_length=255,
                                                description='Workflow name filter')] = None,
        publish_type: Annotated[
            Optional[int],
            Field(ge=0, le=2,
                  description='0=unpublished, 1=published, 2=published with changes')] = None,
    ) -> dict:
        principal = auth.principal_from_context(ctx)
        trace_id = auth.trace_id_from_context(ctx)
        try:
            data = await run_in_threadpool(
                lambda: service.list_workflows(principal, page, size, keyword,
                                               publish_type, trace_id, service.SURFACE_MCP))
        except Exception as error:                                 # noqa: BLE001
            raise _tool_error(error) from error
        return {'trace_id': trace_id, **data}

    @mcp.tool(name='run_workflow',
              description=(
                  'Execute a published workflow and return its answer (same as REST '
                  'POST /agent/query). Requires the workflow:run scope. Set '
                  'stream=true to additionally receive generated tokens as MCP '
                  'progress notifications over the SSE session; the complete answer '
                  'is always returned in the tool result.'
              ),
              annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False,
                                          destructiveHint=False, openWorldHint=False),
              structured_output=False)
    async def run_workflow(
        question: Annotated[str, Field(min_length=1, max_length=2000,
                                       description='Natural-language question')],
        conversation_id: Annotated[str, Field(min_length=1, max_length=255,
                                              description='Conversation ID (multi-turn key)')],
        workflow_id: Annotated[str, Field(min_length=1, max_length=255,
                                          description='Published workflow ID')],
        ctx: Context,
        stream: Annotated[bool, Field(
            description='Also emit token progress notifications')] = False,
        include_retrieval: Annotated[bool, Field(
            description='Include retrieval evidence in the result')] = False,
        chat_history: Annotated[Optional[list[ChatHistoryItem]], Field(
            description='Previous question/answer pairs for multi-turn context')] = None,
    ) -> dict:
        principal = auth.principal_from_context(ctx)
        trace_id = auth.trace_id_from_context(ctx)
        try:
            payload = WorkflowQueryRequest(
                question=question, conversation_id=conversation_id,
                workflow_id=workflow_id, stream=stream,
                include_retrieval=include_retrieval, chat_history=chat_history)
        except ValidationError as error:
            raise ToolError(f'validation_error: {error.errors()[0].get("msg")}') from error

        try:
            data = await agent_query.execute(
                principal, payload, headers=auth.headers_from_context(ctx),
                trace_id=trace_id, on_progress=_progress_callback(ctx, trace_id))
        except Exception as error:                                 # noqa: BLE001
            raise _tool_error(error) from error
        return {'trace_id': trace_id, **data}

    return mcp


def _progress_callback(ctx: Context, trace_id: str):
    """构造 token 进度回调；客户端没带 ``progressToken`` 时返回 None。

    不用 ``Context.report_progress`` 而是直接调 ``send_progress_notification``：
    FastMCP 1.12.4 不带 ``related_request_id``，通知会落到独立的 GET SSE 流；
    带上它才能和工具结果走**同一个** POST SSE 响应对（MCP Streamable HTTP 对
    「与请求相关的通知」的要求）。
    """
    try:
        context = ctx.request_context
    except ValueError:                                             # pragma: no cover
        return None
    token = getattr(getattr(context, 'meta', None), 'progressToken', None)
    if token is None:
        return None

    async def _report(delta: str, answer_len: int) -> None:
        # 进度只是体验层：发送失败不该让已经跑起来的生成任务变成错误。
        try:
            await context.session.send_progress_notification(
                progress_token=token, progress=answer_len, message=delta,
                related_request_id=context.request_id)
        except Exception:                                          # noqa: BLE001
            log.debug('agent mcp progress notification failed trace=%s', trace_id)

    return _report
