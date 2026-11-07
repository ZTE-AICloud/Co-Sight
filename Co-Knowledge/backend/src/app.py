import os
import time
from collections import defaultdict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from auth.middleware import AuthMiddleware

from infrastructure.http.middleware.content_type_validation import ContentTypeValidationMiddleware
from graph.models.graph_retrieve_dto import GraphRetrieveDto
from graph.service.graph_retrieve_gateway import (
    GraphRetrieveError,
    retrieve_result as _graph_retrieve_result,
)
from shared.problem import (INTERNAL_ERROR, generic_detail,
                            problem_response)
from infrastructure.http import headers as httputil
from infrastructure.logging import trace
from infrastructure.logging.logutil import log

context_path = os.environ.get('URL_CONTEXT_PATH', '')
context_path = f'/{context_path}' if context_path else ''
# 禁用 Swagger UI 文档以避免信息泄露风险（生产环境安全要求）
#
# ``lifespan`` 负责常驻后台任务的启停。**不要改回模块级 start**：沙箱用
# spawn/forkserver 会重新执行入口模块，每个沙箱子进程都会再起一份语料队列消费者
# 与文件清理任务。详见 ``startup.py`` 的模块 docstring。
from startup import build_lifespan  # noqa: E402  (须在 app 构造前导入)

app = FastAPI(
    title='RAG Knowledge Base Service',
    root_path=context_path,
    docs_url=None,      # 禁用 /docs 端点
    redoc_url=None,     # 禁用 /redoc 端点
    openapi_url=None,   # 禁用 /openapi.json 端点
    lifespan=build_lifespan,
)
app.add_middleware(AuthMiddleware)
app.add_middleware(ContentTypeValidationMiddleware)
# 容忍路径里的连续 ``/``（web 的 operator.js 会发 ``//operator/...``，见
# infrastructure/http/path_normalization.py）。注意：**最外层是文末的
# RequestIdMiddleware**（后注册 = 先执行）。
from infrastructure.http.path_normalization import CollapseDuplicateSlashesMiddleware  # noqa: E402

app.add_middleware(CollapseDuplicateSlashesMiddleware)

# 对外契约前缀：单点定义见 shared/prefixes.py
from shared.prefixes import GRAPH_RETRIEVE_PATH, RKB_PREFIX  # noqa: E402

# 检索编排运行时：一个端点
#   POST <prefix>/query（stream=true 时 SSE）
# 健康检查统一由 kb_api 的 `GET <prefix>/health` 提供。
# ⚠️ **必须在 register_rkb_api 之前注册**：kb_api 接口层带一条兜底路由
# ``@router.api_route('/{unknown_path:path}')``，同一前缀下它会**吃掉**后面注册的
# ``/query`` —— 症状是提问拿到 ``0005 + msg:null`` 信封而不是报错，极难排查。
from chat.router import register_query_api  # noqa: E402

register_query_api(app, RKB_PREFIX)

# 检索编排（/flow 与 /workflow 系列）接口层：双前缀注册，见 workflow 与
# 后端存储为 flow_* 三表（表未建时端点显式报错）。
from workflow import register_flow_api  # noqa: E402

register_flow_api(app)

# 模型注册与管理（{RKB_PREFIX}/models）：三类 OpenAI 兼容端点的增删改查 + 连接测试。
# ⚠️ **同样必须在 register_rkb_api 之前**（理由与上面的 /query 一样，是同一个兜底路由）。
# 首次调用时会把 deploy/.env 里的模型播种进 model_registry，见 model/seed.py。
from model import register_model_api  # noqa: E402

register_model_api(app)

# Agent 接口（REST + MCP + Key 管理）：REST 挂 {RKB_PREFIX}/agent，MCP 走精确
# 路径 {RKB_PREFIX}/mcp，UI 管理面挂 {RKB_PREFIX}/agent-keys。⚠️ **必须在
# register_rkb_api 之前**：kb_api 的 ``/{unknown_path:path}`` 兜底会把晚注册的
# 这几段吃掉（返回 200 + 0005）。开关与子路径见 agent_api/mount.py 与
# docs/agent-integration.md。
from agent.mount import register_agent_api  # noqa: E402

register_agent_api(app)


# 图谱向量检索：对外唯一入口 ``<RKB_PREFIX>/retrieval/graph``，统一走对外前缀。
# ⚠️ **必须在 register_rkb_api 之前注册**：kb_api 的 ``/{unknown_path:path}``
# 兜底会把晚注册的同前缀路径吃掉（症状：200 + 0005，与 /query、/agent 同一个坑）。
@app.post(GRAPH_RETRIEVE_PATH)
def graph_retrieve(retrieve_dto: GraphRetrieveDto, request: Request):
    """图检索接口 - 通过向量检索找到种子节点，然后按深度传播获取子图

    实现在 `graph.service.graph_retrieve_gateway`，编排在同进程内走**同一份**。
    成功直接返回检索结果对象，失败返回真实状态码 + ``application/problem+json``
    （不是 ``{code:0|-1,...}`` 信封）。入参绑定失败由 ``http_api`` 的异常处理器
    转成 422 problem。
    """
    trace_token = trace.set_trace_id(trace.request_id_from(request))
    started = time.perf_counter()
    trace_headers = {trace.REQUEST_ID_HEADER: trace.get_trace_id()}
    log.info('[graph-retrieve] entry bases=%s seed_k=%s depth=%s score=%s labels=%s '
             'query_len=%s',
             retrieve_dto.bases, retrieve_dto.seed_k, retrieve_dto.depth,
             retrieve_dto.score, retrieve_dto.labels, len(retrieve_dto.query or ''))
    try:
        http_headers = httputil.build_http_headers(request.headers)
        data = _graph_retrieve_result(retrieve_dto, http_headers) or {}
        base_results = data.get('base_results') or []
        log.info('[graph-retrieve] done ok=True base_results=%s entities=%s edges=%s '
                 'elapsed=%.3fs',
                 len(base_results),
                 sum(int(item.get('entity_count') or 0) for item in base_results),
                 sum(int(item.get('edge_count') or 0) for item in base_results),
                 time.perf_counter() - started)
        return JSONResponse(content=data, headers=trace_headers)
    except GraphRetrieveError as error:
        log.warning('[graph-retrieve] failed bases=%s status=%s code=%s elapsed=%.3fs',
                    retrieve_dto.bases, error.spec.status, error.spec.code,
                    time.perf_counter() - started)
        return problem_response(error.spec, error.detail,
                                instance=request.url.path, headers=trace_headers)
    except Exception:
        log.exception('[graph-retrieve] failed bases=%s elapsed=%.3fs',
                      retrieve_dto.bases, time.perf_counter() - started)
        language = httputil.build_http_headers(request.headers).get_language_option()
        return problem_response(
            INTERNAL_ERROR, generic_detail(INTERNAL_ERROR, language),
            instance=request.url.path, headers=trace_headers)
    finally:
        trace.reset_trace_id(trace_token)


# 本地账号登录（{RKB_PREFIX}/auth）：status/login/logout/me/password。
# ⚠️ **必须在 register_rkb_api 之前**：kb_api 的 ``/{unknown_path:path}``
# 兜底会把晚注册的 /auth/* 吃掉（症状：200 + 404 problem，而不是真正的登录响应）。
from auth.api import register_auth_api  # noqa: E402

register_auth_api(app)

# 知识库（/api/co-knowledge/v1）接口层：单前缀注册，见 http_api 与
# 当前只有健康端点，业务端点按批次落入。
from http_api import register_rkb_api  # noqa: E402

register_rkb_api(app)

log.info(">>> start app....")

# 存储请求时间戳
request_times = defaultdict(list)

# 限流配置字典（仅图检索保留）
rate_limits = {
    GRAPH_RETRIEVE_PATH: {"limit": 300, "window": 1},
}

# 慢请求埋点：单进程后端在后台抽取/入库并发时，简单只读接口可能被拖过客户端超时
# （例如 GET /system/embedding-models 超过 15s）。超过阈值的请求打一条 warning，
# 按 method/path/耗时对账；阈值可用 RKB_SLOW_REQUEST_LOG_MS 调整（0 表示全部记录）。
SLOW_REQUEST_LOG_MS = int(os.environ.get('RKB_SLOW_REQUEST_LOG_MS', '2000') or 2000)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    started_at = time.perf_counter()
    response = None
    path = request.url.path
    try:
        if request.client is None:
            log.warning("Request client is None, cannot apply rate limiting.")
            return await call_next(request)  # 直接调用下一个中间件
        client_ip = request.client.host
        current_time = time.time()

        # 获取当前路由的限流配置
        limit_info = rate_limits.get(path)
        if limit_info:
            limit = limit_info["limit"]
            window = limit_info["window"]

            # 清理过期的请求时间戳
            request_times[client_ip] = [timestamp for timestamp in request_times[client_ip] if
                                        current_time - timestamp < window]

            # 检查请求次数
            if len(request_times[client_ip]) >= limit:
                log.warning(f"Rate limit exceeded for IP: {client_ip} on path: {path}")
                from infrastructure.http.identity import language as _language
                from shared.problem import (RATE_LIMITED, generic_detail,
                                            problem_response)
                return problem_response(
                    RATE_LIMITED, generic_detail(RATE_LIMITED, _language(request)),
                    instance=path, headers={'Retry-After': str(window)})

            # 记录当前请求的时间戳
            request_times[client_ip].append(current_time)

        response = await call_next(request)
        return response
    finally:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        if elapsed_ms >= SLOW_REQUEST_LOG_MS:
            log.warning(
                "slow request: %s %s -> %s in %.0f ms",
                request.method, path,
                getattr(response, 'status_code', 'no-response'), elapsed_ms)


# 健康检查只有唯一端点 `GET <prefix>/health`（kb_api 提供，纯文本 ok）。
# 容器内探活使用 `http://localhost:8091/api/co-knowledge/v1/health`。

# 请求 ID：**必须最后注册**（= 最外层），才能覆盖鉴权 401、限流 429、路由 404/422
# 以及 Agent 子应用/MCP 这些不经过业务 handler 的响应。客户端传合法
# ``X-Request-Id`` 就沿用，不合法则丢弃重新生成；响应头同名回显。
# 见 infrastructure/http/middleware/request_id.py。
from infrastructure.http.middleware.request_id import RequestIdMiddleware  # noqa: E402

app.add_middleware(RequestIdMiddleware)
