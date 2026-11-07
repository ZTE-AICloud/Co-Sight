"""为每个请求分配并同名回显 ``X-Request-Id``。

为什么放在最外层：鉴权中间件（401）、限流（429）、404/422、Agent 子应用与 MCP
的原始 ASGI 路由都会**绕过业务 handler** 直接出响应。只有把本中间件挂在
``app.add_middleware`` 的最后（= 最外层），这些响应才都能带上同一个 id。

实现是**纯 ASGI**（不是 ``BaseHTTPMiddleware``）：同一 context 内执行，contextvar
能直接传给下游；响应头在 ``http.response.start`` 上追加，SSE 流式响应也不会被缓冲。

约定（与业界一致）：

* 请求头与响应头**同名** ``X-Request-Id``，客户端带合法值就原样回显；
* 合法性：``[A-Za-z0-9._-]``、1–64 字符，**不合法就丢弃并重新生成**（防止日志注入
  与伪造）。校验在 :func:`infrastructure.logging.trace.normalize`。
"""
from __future__ import annotations

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from infrastructure.logging import trace


class RequestIdMiddleware:
    """入口取/生成 request id，出口写入同名响应头。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get('type') != 'http':
            await self.app(scope, receive, send)
            return

        request_id = trace.normalize(Headers(scope=scope).get(trace.REQUEST_ID_HEADER))
        # ``Mount`` 只对 scope 做浅拷贝，``state`` 仍是同一个 dict，下游（含 Agent
        # 子应用、MCP 路由）统一从这里取；``trace_id`` 是内部沿用的键名。
        state = scope.setdefault('state', {})
        state['request_id'] = request_id
        state['trace_id'] = request_id
        token = trace.set_trace_id(request_id)

        async def send_with_request_id(message: Message) -> None:
            if message['type'] == 'http.response.start':
                MutableHeaders(scope=message)[trace.REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            trace.reset_trace_id(token)
