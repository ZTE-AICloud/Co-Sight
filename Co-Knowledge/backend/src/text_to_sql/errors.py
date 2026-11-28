"""Text2SQL 接口的异常类型。

复用 kb_api 的错误渲染链路（RFC 9457 problem+json），但文案是**字面量**：
本域的错误 detail 只面向集成方与日志，前端按 ``problem_code`` 展示自己的文案。
"""

from __future__ import annotations

from typing import Optional

from shared.errors.api import CODE_BUSINESS_ERROR, KbLiteralError

__all__ = ['Text2SqlError', 'Text2SqlConflict', 'Text2SqlNotFound',
           'Text2SqlUpstreamError', 'Text2SqlValidationError',
           'SqlGuardError', 'QueryExecutionError']


class Text2SqlError(KbLiteralError):
    """通用业务错误（400）。"""

    def __init__(self, message: str, *, status: Optional[int] = None,
                 problem_code: Optional[str] = None):
        super().__init__(message, code=CODE_BUSINESS_ERROR, status=status or 400,
                         problem_code=problem_code or 'text2sql.bad_request')


class Text2SqlValidationError(Text2SqlError):
    """入参校验失败 → 422。"""

    def __init__(self, message: str):
        super().__init__(message, status=422,
                         problem_code='text2sql.validation_failed')


class Text2SqlNotFound(Text2SqlError):
    """资源不存在 → 404。"""

    def __init__(self, message: str):
        super().__init__(message, status=404,
                         problem_code='text2sql.not_found')


class Text2SqlConflict(Text2SqlError):
    """重名 / 状态冲突 → 409。"""

    def __init__(self, message: str, *, problem_code: str = 'text2sql.conflict'):
        super().__init__(message, status=409, problem_code=problem_code)


class Text2SqlUpstreamError(Text2SqlError):
    """外部数据库不可达 / 查询失败 → 502。"""

    def __init__(self, message: str):
        super().__init__(message, status=502,
                         problem_code='text2sql.upstream_unavailable')


class SqlGuardError(ValueError):
    """SQL 未通过安全校验。``code`` 直接进前端错误对象。

    不属于 HTTP 错误：查询编排把它折成 ``t2s_query_run`` 的失败记录，
    仍以 200 + error 对象返回给前端。
    """

    def __init__(self, code: str, message: str, stage: str = 'validation'):
        super().__init__(message)
        self.code = code
        self.message = message
        self.stage = stage


class QueryExecutionError(RuntimeError):
    """外部库执行失败（已归一成前端可展示的 code）。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
