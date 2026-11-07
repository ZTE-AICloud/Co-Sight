"""检索编排运行时。

只保留「一次检索编排」这条链路上的东西：

    POST /query
      → RagContext（从后端取**已发布**画布，
        见 core/config_loader/flow_config_provider.py）
      → Sequential / Blended / Conditional 三种引擎之一 → 改写 → 检索 → 重排 → 合成
      → {code:0, message:'Success', data:{...}}

**不提供**：chatbot_query / guide_questions / aisearch / sql_retriever / sql_executor /
websearch_retriever / 回调类端点 / 图片分发 / chatbot 专属的流式帧生成 /
`/rag_config/_create` 这类「把配置写到本地磁盘」的接口（配置现在存后端）。

`stream=true`（或请求头 `Accept: text/event-stream`）走标准 SSE：具名事件
`retrieval` / `token` / `done` / `error`，每帧一个 JSON `data:`。出第一字节前的失败
仍是真实 HTTP 状态码 + `application/problem+json`；流中途失败发 `event: error`。

鉴权：本端点保持浏览器会话 / 网关令牌；**Agent API Key 的执行入口是
``POST /agent/query``**（``agent.rest`` 懒调用本模块的 ``run_query``，复用同一套
编排与 SSE 逻辑），两者不要在同一条路径上混鉴权。

非流式成功体就是回答对象本身（不再有 `{code,message,data}` 信封），失败同样是
problem+json。`sse-starlette` 负责心跳注释与反代所需的响应头。

黑名单（敏感词屏蔽）在合成出口生效，来源是部署挂载的 `BLACK_LIST_DIR`
（见 `core/config_loader/black_list_loader.py`）。

单副本限制：查询改写用进程内 TTL 缓存记多轮问题（`core/cache/chat_memory.py`），
多副本会各记各的，所以 v1 只能单副本 —— 与原服务同样的约束。
"""
import json
import time
from json.decoder import JSONDecodeError

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse, ServerSentEvent
from starlette.background import BackgroundTask

from shared.problem import (INTERNAL_ERROR, PROBLEM_TYPE_PREFIX, ProblemSpec,
                            generic_detail, problem_response)
from engine.common import const, stage_timing
from engine.common.beans.rag_request import RagRequest
from engine.common.beans.rag_request_headers import RagRequestHeaders
from engine.common.exception.rag_exception import RagException
import engine as rag
from engine.cache import chat_memory
from engine.retrieval_evidence import (
    build_retrieval_evidence,
    prepare_retrieval_frame,
    summarize_source_nodes,
)
from chat.trace_state import TraceState
from chat.trace_writer import enqueue_trace, trace_enabled
from chat.flow_config_provider import get_workflow_config
from chat.gateways import rkb_transport as _rkb_transport
from chat.query_errors import query_problem
from engine.gateways import knowledge_base_client as _knowledge_base_client

# Dependency injection: the engine never imports ``chat``.
_knowledge_base_client.set_transport(_rkb_transport)
from engine.logutil import logger  # noqa: E402
from infrastructure.logging import trace  # noqa: E402

# 本模块只提供**路由**，不自带 FastAPI 实例：由 RKB 用
# `register_query_api(app, prefix)` 挂载。
# 生产路径是 `<prefix>/query`；健康检查统一走 kb_api 的 `<prefix>/health`。
router = APIRouter()


def _check_rag_request(rag_request: RagRequest):
    """入参校验（这两个字段缺一个就没法执行）。"""
    if not rag_request.question:
        logger.warning("no question provided")
        raise RagException(-1, 'required_param_missing', 'question')
    if not rag_request.conversation_id:
        logger.warning("no conversation_id provided")
        raise RagException(-1, 'required_param_missing', 'conversation_id')
    if const.question_length_limit in rag_request.kwargs:
        question_length_limit = rag_request.kwargs.get(const.question_length_limit, -1)
        if not (isinstance(question_length_limit, int) and 0 < question_length_limit < const.question_max_length):
            raise RagException(-1, 'parameter_length_limit_illegal', 'question_length_limit',
                               const.question_max_length)
        if question_length_limit < len(rag_request.question):
            raise RagException(-1, 'question_length_over_limit', question_length_limit,
                               len(rag_request.question))


def _sse(event: str, payload: dict) -> ServerSentEvent:
    """一帧具名 SSE 事件；``data`` 始终是 JSON（换行由 JSON 转义，不破帧）。"""

    return ServerSentEvent(event=event,
                           data=json.dumps(payload, ensure_ascii=False))


def _problem_payload(spec: ProblemSpec, detail: str, conversation_id: str) -> dict:
    """流中途失败时的 ``event: error`` 载荷（与 HTTP problem+json 同字段）。"""

    return {
        'type': PROBLEM_TYPE_PREFIX + spec.code,
        'title': spec.title,
        'status': spec.status,
        'detail': detail,
        'code': spec.code,
        'conversation_id': conversation_id,
    }


def _token_content(data: str) -> str:
    """LLM 适配器的内部 token（``prepare_text_data`` 的 JSON）→ 正文。

    适配器的帧格式是内部实现；SSE 对外只暴露 ``{"content": ...}``。解析失败时
    按原始文本下发（宁可多显示一段，也不静默丢 token）。
    """

    try:
        parsed = json.loads(data)
    except (TypeError, ValueError):
        return data
    output = parsed.get('output') if isinstance(parsed, dict) else None
    content = output.get('content') if isinstance(output, dict) else None
    return content if isinstance(content, str) else data


def _streamer(response, conversation_id, trace_id=None, include_retrieval=False,
              language='zh', timings=None, trace_state=None):
    """SSE 事件生成器。

    事件顺序：可选的 ``retrieval`` → 若干 ``token`` → ``done``；任何中途异常变成
    终态 ``error``。``sse-starlette`` 在空闲时自动发注释心跳（默认 15s），所以长
    推理的首 token 等待不会被反代判死。

    ``include_retrieval=True`` 时在第一个正文 token 之前补检索证据；证据序列化失败
    只记日志，绝不影响问答本身。

    ``trace_id``：生成器可能在线程池里迭代，contextvar 未必跟着过来，所以入口
    显式传入并在生成器内重设；同时记录帧数与耗时。

    ``timings``：同理，阶段耗时在 handler 里 snapshot 后显式传入，生成器内**不读**
    contextvar（此时请求的收集器可能已经 reset）。

    ``trace_state``：`TraceState`（带锁）。这里只填状态，不做任何 DB I/O；终态由
    handler 挂的 background 统一入队/落库。Direct-call 单测可以传 None。
    """
    token = trace.set_trace_id(trace_id) if trace_id else None
    started = time.perf_counter()
    frames = 0
    response_gen = getattr(response, 'response_gen', None)
    try:
        if include_retrieval:
            try:
                evidence = build_retrieval_evidence(
                    getattr(response, 'source_nodes', []),
                    getattr(response, 'query_str', '') or '',
                    timings=timings)
                yield ServerSentEvent(
                    event='retrieval',
                    data=prepare_retrieval_frame(conversation_id, evidence))
                frames += 1
            except Exception:
                # 证据只是展示层：序列化失败不能让用户拿不到答案
                logger.exception('[query] build retrieval evidence failed conversation_id=%s',
                                 conversation_id)
        # 证据帧之后才开始消费模型流；生成耗时从这里算。
        if trace_state is not None:
            trace_state.mark_generation_started(time.perf_counter())
        first_token_marked = False
        for data in response_gen or ():
            if data == '[DONE]':
                break
            empty = data == 'Empty Response'
            content = const.default_answer if empty else _token_content(data)
            if trace_state is not None:
                now = time.perf_counter()
                if not first_token_marked:
                    trace_state.mark_first_token(now)
                    first_token_marked = True
                trace_state.add_answer_chars(len(content))
            yield _sse('token', {'conversation_id': conversation_id, 'content': content})
            frames += 1
            if empty:
                break
        if trace_state is not None:
            trace_state.finish_ok(time.perf_counter())
        yield _sse('done', {'conversation_id': conversation_id, 'finish_reason': 'stop'})
        logger.info('[query] stream finished conversation_id=%s frames=%s elapsed=%.3fs',
                    conversation_id, frames, time.perf_counter() - started)
    except Exception as error:                                      # noqa: BLE001
        if isinstance(error, RagException):
            logger.warning('[query] stream failed conversation_id=%s error=%s',
                           conversation_id, error.get_error_tag())
            spec, detail = query_problem(error.get_error_tag(), error.get_args(), language)
        else:
            logger.exception('[query] stream unexpected error conversation_id=%s', conversation_id)
            spec, detail = INTERNAL_ERROR, generic_detail(INTERNAL_ERROR, language)
        if trace_state is not None:
            # HTTP 已经 200 发出去了；真实 wire 状态是 200，问题规格状态另存。
            trace_state.finish_error(time.perf_counter(), spec.code, 200, spec.status)
        yield _sse('error', _problem_payload(spec, detail, conversation_id))
    finally:
        if trace_state is not None:
            trace_state.finalize_if_running(time.perf_counter())
        # 客户端提前断开时尽量中止上游流，别让模型继续白跑。
        close = getattr(response_gen, 'close', None)
        if callable(close):
            try:
                close()
            except Exception:                                       # noqa: BLE001
                logger.debug('[query] close upstream stream failed', exc_info=True)
        if token is not None:
            trace.reset_trace_id(token)


def _check_response(response):
    if not hasattr(response, 'response_gen'):
        raise RagException(-1, 'question_not_match_desc_info')


def _trace_background(trace_state):
    """background 只入队（不碰 DB）；关闭时返回 None。"""
    return BackgroundTask(enqueue_trace, trace_state) if trace_state is not None else None


def _set_trace_summary(trace_state, source_nodes, conversation_id):
    """命中统计是展示层数据：任何异常都不能让已经算出的答案变成 500。"""
    if trace_state is None:
        return
    try:
        trace_state.set_retrieval_summary(summarize_source_nodes(source_nodes))
    except Exception:                                           # noqa: BLE001
        logger.exception('[query] summarize source nodes failed conversation_id=%s',
                         conversation_id)


def _get_answer_from_result(feedback, conversation_id, result, include_retrieval=False,
                            timings=None):
    """把合成结果收敛成对外的 JSON 响应体。

    **不因为「解析不出 JSON」就报错**：合成路径返回的可能是模型原始输出，
    只有 deepsearch 分支或兜底分支才自带 JSON。这里统一补信封，形状固定：

        {"conversation_id": ..., "answer": ..., "placeholder": {}, "citation": {}}

    不能在 LLM 适配器里包信封：`predict()` 对 chat 模型走 `chat()`，
    适配器分不清「重排」和「合成」两条路（按 formatted 分支会把合成也变成裸文本 →
    这里 json.loads 失败 → 用户拿到「根据当前信息无法回答」这种假错误）。
    """
    raw = result.response
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise JSONDecodeError('not an object', str(raw), 0)
    except JSONDecodeError:
        # 裸文本：补成信封（placeholder/citation 为空对象，形状不变）
        data = {'conversation_id': conversation_id, 'answer': raw, 'placeholder': {}, 'citation': {}}
    if feedback:
        if not data.get('citation'):
            data['related_context'] = []
        else:
            data['related_context'] = chat_memory.get_last_context(conversation_id)
    if include_retrieval:
        try:
            data['retrieval'] = build_retrieval_evidence(
                getattr(result, 'source_nodes', []),
                getattr(result, 'query_str', '') or '',
                timings=timings)
        except Exception:
            # 同流式：证据只是展示层，失败不影响答案
            logger.exception('[query] build retrieval evidence failed conversation_id=%s',
                             conversation_id)
    return data


def _agent_answer_payload(data: dict) -> dict:
    """原生回答信封 → Agent 面的精简响应（去掉历史 placeholder/citation）。"""
    payload = {'conversation_id': data.get('conversation_id'),
               'answer': data.get('answer')}
    if data.get('retrieval') is not None:
        payload['retrieval'] = data['retrieval']
    return payload


def run_query(rag_request: RagRequest, request: Request, *,
              surface: str = 'native'):
    """执行一次编排问答；原生 `/query` 与 `/agent/query` 共用本实现。

    ``surface='agent'`` 只影响**非流式**响应体（去掉 placeholder/citation）；
    SSE 事件本身就是干净结构，不再二次加工。
    """
    # 请求 ID 由最外层的 RequestIdMiddleware 分配（客户端合法值已校验并沿用）；
    # 子应用单独挂载（测试）时回落到请求头。响应头与请求头同名回显。
    trace_token = trace.set_trace_id(trace.request_id_from(request))
    started = time.perf_counter()
    trace_headers = {trace.REQUEST_ID_HEADER: trace.get_trace_id()}
    request_headers = RagRequestHeaders.build_rag_request_header(request.headers)
    language = request_headers.language_option
    wants_stream = (bool(rag_request.stream)
                    or 'text/event-stream' in request.headers.get('accept', '').lower())
    logger.info('[query] entry workflow=%s conversation_id=%s stream=%s question_len=%s '
                'history_pairs=%s kwargs=%s path=%s',
                rag_request.workflow_id, rag_request.conversation_id, wants_stream,
                len(rag_request.question or ''), len(rag_request.chat_history or []),
                sorted((rag_request.kwargs or {}).keys()), request.url.path)
    # 请求级阶段耗时：引擎在改写/检索/重排边界累加，query 返回后立刻快照。
    # 快照必须在 handler 内完成并显式传参——流式生成器可能不在同一 context。
    trace_state = None
    if trace_enabled():
        trace_state = TraceState(
            trace_id=trace.get_trace_id(),
            conversation_id=rag_request.conversation_id or '',
            workflow_id=rag_request.workflow_id or const.default_workflow_id,
            org_id=request_headers.org_id or '',
            is_stream=wants_stream,
            question_len=len(rag_request.question or ''),
            request_started=started,
        )
    timing_token = stage_timing.start()
    try:
        _check_rag_request(rag_request)
        engine = rag.build_query_engine(
            rag_request, request_headers, get_workflow_config)
        if wants_stream:
            response = engine.query(rag_request.question)
            # 流式此时检索已完成、生成还没开始；这个快照就是面板前三段的来源。
            timings = stage_timing.snapshot()
            if trace_state is not None:
                trace_state.set_stage_timings(timings)
            # 出第一字节前的失败仍映射成真实状态码 + problem+json（此时 HTTP
            # 状态还没发出去，不能假装成功再在流里报错）。
            _check_response(response)
            _set_trace_summary(trace_state, getattr(response, 'source_nodes', []),
                               rag_request.conversation_id)
            logger.info('[query] streaming response ready conversation_id=%s elapsed=%.3fs '
                        'timings=%s', rag_request.conversation_id,
                        time.perf_counter() - started, timings)
            return EventSourceResponse(
                _streamer(response, rag_request.conversation_id, trace.get_trace_id(),
                          include_retrieval=rag_request.include_retrieval,
                          language=language, timings=timings,
                          trace_state=trace_state),
                ping=15,
                headers=trace_headers,
                background=_trace_background(trace_state))
        chat_result = engine.query(rag_request.question)
        timings = stage_timing.snapshot()
        if trace_state is not None:
            trace_state.set_stage_timings(timings)
        answer = _get_answer_from_result(request_headers.feedback, rag_request.conversation_id,
                                         chat_result,
                                         include_retrieval=rag_request.include_retrieval,
                                         timings=timings)
        if trace_state is not None:
            _set_trace_summary(trace_state, getattr(chat_result, 'source_nodes', []),
                               rag_request.conversation_id)
            trace_state.finish_non_stream(
                time.perf_counter(), len(str(answer.get('answer') or '')))
        logger.info('[query] answered conversation_id=%s answer_len=%s citation=%s elapsed=%.3fs '
                    'timings=%s', rag_request.conversation_id,
                    len(str(answer.get('answer') or '')), bool(answer.get('citation')),
                    time.perf_counter() - started, timings)
        body = _agent_answer_payload(answer) if surface == 'agent' else answer
        return JSONResponse(body, headers=trace_headers,
                            background=_trace_background(trace_state))
    except RagException as e:
        logger.warning('[query] failed workflow=%s conversation_id=%s error=%s elapsed=%.3fs',
                       rag_request.workflow_id, rag_request.conversation_id,
                       e.get_error_tag(), time.perf_counter() - started)
        spec, detail = query_problem(e.get_error_tag(), e.get_args(), language)
        if trace_state is not None:
            trace_state.set_stage_timings(stage_timing.snapshot())
            trace_state.finish_error(
                time.perf_counter(), spec.code, spec.status, spec.status)
        response = problem_response(spec, detail, instance=request.url.path,
                                    headers=trace_headers)
        response.background = _trace_background(trace_state)
        return response
    except Exception as e:
        logger.exception('[query] unexpected error workflow=%s conversation_id=%s elapsed=%.3fs',
                         rag_request.workflow_id, rag_request.conversation_id,
                         time.perf_counter() - started)
        logger.debug('unexpected error detail: %s', e)
        if trace_state is not None:
            trace_state.set_stage_timings(stage_timing.snapshot())
            trace_state.finish_error(
                time.perf_counter(), INTERNAL_ERROR.code,
                INTERNAL_ERROR.status, INTERNAL_ERROR.status)
        response = problem_response(INTERNAL_ERROR,
                                    generic_detail(INTERNAL_ERROR, language),
                                    instance=request.url.path, headers=trace_headers)
        response.background = _trace_background(trace_state)
        return response
    finally:
        stage_timing.reset(timing_token)
        trace.reset_trace_id(trace_token)


# 全栈唯一健康端点是 `<prefix>/health`（kb_api）。
@router.post('/query')
def chat(rag_request: RagRequest, request: Request):
    """原生编排端点（浏览器会话 / 网关）；Agent Key 走 `/agent/query`。"""
    return run_query(rag_request, request)
