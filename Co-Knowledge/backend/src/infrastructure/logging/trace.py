"""请求级 trace id：让一次请求的所有日志能串起来。

为什么需要它：RKB 是单进程多线程（uvicorn）且一次 `/query` 会横跨改写、检索、重排、
合成多个模块，日志按时间混在一起。只在入口打一行 workflow/conversation 不足以定位
「这次请求到底走了哪条检索器、命中多少、为什么是空」。这里用 contextvar：

* 最外层的 ``RequestIdMiddleware`` 为**每个请求**取/生成 id 并同名回显到
  ``X-Request-Id`` 响应头（客户端带了合法值就沿用）；
* 两个 logutil 的 Formatter 都带 ``%(trace_id)s``，由 :class:`TraceIdFilter` 从
  contextvar 注入 —— **不需要每个模块传参**；
* 线程池/异步任务里 contextvar 会随 asyncio task 继承；显式起线程时需手动传递
  （本仓库的常驻线程与请求链路无关，不受影响）。

**请求头与响应头同名**（``X-Request-Id``），方便网关/客户端用同一个名字对账。
id 只用于关联日志，不是安全边界：格式不合法就丢弃并重新生成
（字符集 ``[A-Za-z0-9._-]``、长度 1–64），避免日志注入与伪造。
"""
from __future__ import annotations

import contextvars
import re
import uuid
from typing import Optional

_TRACE_ID: contextvars.ContextVar[str] = contextvars.ContextVar('rag_trace_id', default='-')

#: 请求头与响应头同名：客户端可传，服务端校验后原样回显
REQUEST_ID_HEADER = 'X-Request-Id'

_MAX_LEN = 64
#: 合法字符集刻意取窄：拒绝空白、换行、引号等可能污染日志的值
_REQUEST_ID_RE = re.compile(r'^[A-Za-z0-9._-]{1,%d}$' % _MAX_LEN)


def normalize(value: Optional[str]) -> str:
    """合法就沿用客户端值，否则生成 16 位十六进制 id。"""
    value = (value or '').strip()
    if value and _REQUEST_ID_RE.match(value):
        return value
    return uuid.uuid4().hex[:16]


def request_id_from(request) -> Optional[str]:
    """取本次请求的 id：中间件写入的 state 优先，其次客户端请求头。

    中间件已经把不合法值丢掉并生成过 id，所以生产链路走 ``request.state``；
    直接调用路由函数（单测/子应用独立挂载）时才回落到原始请求头，
    由 :func:`set_trace_id` 再做一次校验。
    """
    state = getattr(request, 'state', None)
    for attr in ('request_id', 'trace_id'):
        value = getattr(state, attr, None)
        if value:
            return value
    return request.headers.get(REQUEST_ID_HEADER)


def set_trace_id(value: Optional[str] = None):
    """设置当前请求的 trace id，返回 token（供 :func:`reset_trace_id`）。"""
    return _TRACE_ID.set(normalize(value))


def get_trace_id() -> str:
    return _TRACE_ID.get()


def reset_trace_id(token) -> None:
    try:
        _TRACE_ID.reset(token)
    except (ValueError, TypeError):
        # token 不属于当前 context（跨线程误用）：兜底清成默认值，别让异常盖住业务错误
        _TRACE_ID.set('-')


class TraceIdFilter:
    """把 contextvar 里的 trace id 塞进 LogRecord，Formatter 用 ``%(trace_id)s`` 取。"""

    def filter(self, record) -> bool:  # noqa: ANN001 - logging 的固定签名
        record.trace_id = get_trace_id()
        return True
