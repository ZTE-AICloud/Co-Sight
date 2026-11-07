"""kb_api 的响应构造（纯 REST + RFC 9457）。

取代原 ``envelope.py``：成功不再包 ``{code,bo,other}``，错误不再 HTTP 200。
成功体规则见 ``infrastructure.http.responses``；错误体见 ``shared.problem``。

保留 ``parse_json_body``：它实现的是**请求体绑定**语义（缺体/``null``/畸形/非对象），
与响应信封无关，路由层继续使用。
"""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import Request

from infrastructure.http.responses import (accepted, created, json_response,  # noqa: F401
                                  no_content)
from shared.errors.api import KbLiteralValidationError, KbStoreError
from shared.problem import (ApiError, INTERNAL_ERROR, NOT_FOUND, CONFLICT,
                            error_response, generic_detail, problem_response)


def success(data: Any, *, status_code: int = 200):
    """成功响应：body 就是 ``data`` 本身。"""

    return json_response(data, status_code=status_code)


def error(kb_error: ApiError, language: str, request: Optional[Request] = None):
    """把家族异常翻译成 problem+json（真实状态码）。"""

    return error_response(
        kb_error,
        language=language,
        instance=request.url.path if request is not None else None,
    )


def server_error(language: str, request: Optional[Request] = None):
    """未预期异常：日志里留堆栈，响应只给通用 500 文案。"""

    return problem_response(
        INTERNAL_ERROR,
        generic_detail(INTERNAL_ERROR, language),
        instance=request.url.path if request is not None else None,
    )


def store_error(store_error: KbStoreError, language: str,
                request: Optional[Request] = None):
    """存储层错误 → 409/404/500（详情只进日志，不回给客户端）。"""

    spec = {
        KbStoreError.DUPLICATE: CONFLICT,
        KbStoreError.NOT_FOUND: NOT_FOUND,
    }.get(store_error.kind, INTERNAL_ERROR)
    return problem_response(
        spec,
        generic_detail(spec, language),
        instance=request.url.path if request is not None else None,
    )


def parse_json_body(raw: bytes, required: bool = False) -> dict:
    """解析请求体，按 JSON 请求体的绑定语义。

    四种体的归宿（状态码按最佳实践落位）：

    ==========================  ==================================================
    请求体                       结果
    ==========================  ==================================================
    0 字节 / 字面量 ``null``      ``required=True`` → 400 ``malformed_request``；
                                否则 → ``{}``（与「DTO 为 null」在服务层等价）
    空白 / 畸形 JSON              ``json`` 解析异常 → 400 ``malformed_request``
    非对象（数组 / 数字 / 字符串） ``ValueError`` → 400 ``malformed_request``
    合法对象                     继续走业务
    ==========================  ==================================================

    故意不用 Pydantic 模型做入口校验：四个家族的错误文案与渲染规则各不相同，
    统一走本层的显式映射比 FastAPI 的自动 422 结构更可控。
    """

    if not raw:
        if required:
            raise KbLiteralValidationError(
                'Required request body is missing',
                status=400, problem_code='malformed_request')
        return {}
    payload = json.loads(raw.decode('utf-8'))     # 空白体也走这条
    if payload is None:
        if required:
            raise KbLiteralValidationError(
                'Required request body is missing',
                status=400, problem_code='malformed_request')
        return {}
    if not isinstance(payload, dict):
        raise ValueError('request body must be a JSON object')
    return payload
