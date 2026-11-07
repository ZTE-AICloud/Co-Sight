"""成功响应的统一构造。

约定（与 ``docs/api-reference.md`` 第 1 节一致）：

* 单资源 / 动作结果：HTTP 200，body 是资源对象或结果对象本身；
* 创建可寻址资源：HTTP 201 + ``Location``（相对路径）；
* 异步任务：HTTP 202 + ``{taskId}`` 或 ``{accepted: true}``；
* 无返回（删除等）：HTTP 204，空 body；
* 下载/导出：直接返回 ``StreamingResponse``/``Response``，不经这里。
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from fastapi.responses import JSONResponse, Response


def json_response(
    data: Any,
    *,
    status_code: int = 200,
    headers: Optional[Mapping[str, str]] = None,
) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=data,
                        headers=dict(headers or {}))


def created(
    data: Any,
    *,
    location: Optional[str] = None,
    headers: Optional[Mapping[str, str]] = None,
) -> JSONResponse:
    """201 Created；``location`` 用相对路径（不拼主机名）。"""

    merged = dict(headers or {})
    if location:
        merged['Location'] = location
    return JSONResponse(status_code=201, content=data, headers=merged)


def accepted(
    data: Any = None,
    *,
    location: Optional[str] = None,
    headers: Optional[Mapping[str, str]] = None,
) -> JSONResponse:
    """202 Accepted；没有具体结果时回 ``{"accepted": true}``。"""

    merged = dict(headers or {})
    if location:
        merged['Location'] = location
    return JSONResponse(
        status_code=202,
        content={'accepted': True} if data is None else data,
        headers=merged,
    )


def no_content(headers: Optional[Mapping[str, str]] = None) -> Response:
    """204 No Content；不写 body。"""

    return Response(status_code=204, headers=dict(headers or {}))
