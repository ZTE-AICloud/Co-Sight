"""flow_api 的响应构造（纯 REST + RFC 9457）。

取代原 ``envelope.py``：成功不再包 ``{code,bo,other}``，错误不再 HTTP 200。
"""

from __future__ import annotations

import json

from fastapi import Request

from infrastructure.http.responses import (accepted, created, json_response,  # noqa: F401
                                  no_content)
from workflow.errors import (FlowError, FlowMalformedRequestError,
                                    FlowStoreError)
from shared.problem import (CONFLICT, INTERNAL_ERROR, NOT_FOUND,
                            error_response, generic_detail, problem_response)


def route_path(request: Request) -> str:
    """取**匹配到的路由路径**（含前缀，不含 root_path）。"""

    route = request.scope.get('route')
    path = getattr(route, 'path', None)
    return path or request.url.path


def error(request: Request, flow_error: FlowError, language: str):
    """业务错误 → 真实状态码 + problem+json。"""

    return error_response(flow_error, language=language,
                          instance=request.url.path)


def server_error(request: Request, language: str):
    """未预期异常 → 500 problem+json。"""

    return problem_response(
        INTERNAL_ERROR, generic_detail(INTERNAL_ERROR, language),
        instance=request.url.path)


def store_error(request: Request, store_error: FlowStoreError, language: str):
    """存储层错误 → 409/404/500。"""

    spec = {
        FlowStoreError.DUPLICATE: CONFLICT,
        FlowStoreError.NOT_FOUND: NOT_FOUND,
    }.get(store_error.kind, INTERNAL_ERROR)
    return problem_response(spec, generic_detail(spec, language),
                            instance=request.url.path)


def parse_json_body(raw: bytes, required: bool = False) -> dict:
    """解析请求体，按 JSON 请求体的绑定语义。

    与 kb_api 同一套规则，但抛 flow 自己的异常类（路由层的异常阶梯只认
    ``FlowError`` 一族）：缺体/``null`` → 400，畸形 JSON / 非对象 → 400。
    """

    if not raw:
        if required:
            raise FlowMalformedRequestError()
        return {}
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as error:
        raise FlowMalformedRequestError() from error
    if payload is None:
        if required:
            raise FlowMalformedRequestError()
        return {}
    if not isinstance(payload, dict):
        raise FlowMalformedRequestError()
    return payload
