"""把 Agent REST 子应用与 MCP 原始 ASGI 路由挂到主应用。

**注册顺序是硬约束**：``register_agent_api`` 必须在 ``register_rkb_api`` 之前调用。
后者带一条 ``/{unknown_path:path}`` 兜底路由；同一前缀下它会吃掉后注册的
``/agent/*`` 与 ``/mcp``，症状是「请求拿到 200 + 0005 而不是 404/401」。

MCP 不用 ``app.mount``：``Mount`` 会把路径前缀剥掉，而 ``StreamableHTTPSessionManager``
希望拿到完整的 ASGI scope；这里用 Starlette 原始 ``Route`` 精确匹配，并**必须**
以类实例作为 endpoint（函数会被当成 ``request_response()``，POST 直接 405）。
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from starlette.responses import JSONResponse
from starlette.routing import Route

from infrastructure.logging.logutil import log

from shared.prefixes import AGENT_MCP_PATH, AGENT_PREFIX
from agent import config
from agent.admin_rest import register_agent_admin_api
from agent.auth import AuthenticatedMCPApp
from agent.mcp_server import build_mcp
from agent.rest import build_rest_app


class _DisabledApp:
    """总开关关闭时占位：明确回 404 problem，而不是落到 kb_api 的兜底路由。"""

    async def __call__(self, scope, receive, send) -> None:
        response = JSONResponse(
            {'type': 'urn:ragstudio:problem:not_found',
             'title': 'Not found',
             'status': 404,
             'detail': 'agent api is disabled',
             'code': 'not_found',
             'instance': scope.get('path') or ''},
            status_code=404,
            media_type='application/problem+json',
        )
        await response(scope, receive, send)


def register_agent_api(app) -> None:
    # 管理接口先注册：即使 Agent 接口总开关关闭，页面仍要能看状态、清理 Key。
    # 同样必须在 register_rkb_api 之前（理由见模块 docstring）。
    register_agent_admin_api(app)

    if not config.api_enabled():
        app.mount(AGENT_PREFIX, _DisabledApp())
        app.router.routes.append(Route(AGENT_MCP_PATH, endpoint=_DisabledApp()))
        app.router.routes.append(Route(AGENT_MCP_PATH + '/', endpoint=_DisabledApp()))
        log.info('agent api disabled (RKB_AGENT_API_ENABLED=false)')
        return

    if config.rest_enabled():
        app.mount(AGENT_PREFIX, build_rest_app())
        log.info('agent rest mounted at %s', AGENT_PREFIX)
    else:
        app.mount(AGENT_PREFIX, _DisabledApp())

    if config.mcp_enabled():
        server = build_mcp()
        # 创建 StreamableHTTPSessionManager（返回的 Starlette app 丢弃）。
        # 真正的 run() 在 lifespan 里，导入期只做对象构造。
        server.streamable_http_app()
        endpoint = AuthenticatedMCPApp(server.session_manager)
        app.router.routes.append(Route(AGENT_MCP_PATH, endpoint=endpoint))
        app.router.routes.append(Route(AGENT_MCP_PATH + '/', endpoint=endpoint))
        app.state.agent_mcp_server = server
        log.info('agent mcp mounted at %s', AGENT_MCP_PATH)
    else:
        app.router.routes.append(Route(AGENT_MCP_PATH, endpoint=_DisabledApp()))
        app.router.routes.append(Route(AGENT_MCP_PATH + '/', endpoint=_DisabledApp()))


@asynccontextmanager
async def agent_lifespan(app):
    """主 lifespan 里运行 MCP session manager。

    ``StreamableHTTPSessionManager.run()`` 每个实例只能进入一次；这里从
    ``app.state`` 取 server，测试里为每个 app 建新 server 即可多次运行。
    """
    server = getattr(app.state, 'agent_mcp_server', None)
    if server is None:
        yield
        return
    async with server.session_manager.run():
        yield
