"""Agent API 的错误类型。

REST 与 MCP 共用同一组错误码；REST 层把 ``http_status`` + ``code`` 映射成
``application/problem+json``，MCP 层把 ``code: message`` 转成 ``ToolError``。
``http_api.py`` 的父级处理器对 ``/api/co-knowledge/v1/*`` 有兜底，
REST 子应用必须自己先兜住所有异常，避免错误形状漂移。
"""

from __future__ import annotations

from typing import Any, Optional


class AgentApiError(Exception):
    """带 HTTP 语义的领域错误。"""

    def __init__(self, http_status: int, code: str, message: str,
                 details: Any = None):
        super().__init__(message)
        self.http_status = http_status
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict:
        return {'code': self.code, 'message': self.message, 'details': self.details}


class AgentKeyStoreUnavailable(AgentApiError):
    """Key 表不存在 / 不可读。"""

    def __init__(self, message: str = 'agent api key store is not ready'):
        super().__init__(503, 'agent_key_store_unavailable', message)


def configuration_error(message: str) -> AgentApiError:
    return AgentApiError(503, 'configuration_error', message)


def unauthorized(message: str = 'Invalid or missing API key') -> AgentApiError:
    return AgentApiError(401, 'unauthorized', message)


def forbidden_scope(scope: str) -> AgentApiError:
    return AgentApiError(
        403, 'forbidden_scope',
        f'API key does not have the required scope: {scope}',
        {'required_scope': scope})


def knowledge_base_forbidden(kb_id: str) -> AgentApiError:
    return AgentApiError(
        403, 'knowledge_base_forbidden',
        'The API key is not allowed to access this knowledge base',
        {'knowledge_base_id': kb_id})


def knowledge_base_not_found(kb_id: str) -> AgentApiError:
    return AgentApiError(
        404, 'knowledge_base_not_found',
        'Knowledge base not found',
        {'knowledge_base_id': kb_id})


def invalid_request(message: str, details: Any = None) -> AgentApiError:
    return AgentApiError(400, 'invalid_request', message, details)


def no_accessible_knowledge_bases() -> AgentApiError:
    return AgentApiError(
        400, 'no_accessible_knowledge_bases',
        'No accessible document knowledge bases for this API key')


def rate_limited(retry_after: int) -> AgentApiError:
    return AgentApiError(
        429, 'rate_limited',
        'Too many requests for this API key',
        {'retry_after_seconds': retry_after})


def retrieval_failed(message: str = 'retrieval failed') -> AgentApiError:
    return AgentApiError(502, 'retrieval_failed', message)


def answer_unavailable(message: str = 'No generation model configured') -> AgentApiError:
    return AgentApiError(503, 'answer_unavailable', message)


def answer_failed(message: str = 'answer generation failed') -> AgentApiError:
    return AgentApiError(502, 'answer_failed', message)


def internal_error(trace_id: Optional[str] = None) -> AgentApiError:
    return AgentApiError(
        500, 'internal_error', 'Internal server error',
        {'trace_id': trace_id} if trace_id else None)
