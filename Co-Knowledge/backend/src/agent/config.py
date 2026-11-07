"""Agent 接口的环境变量读取。

本仓的配置惯例是「容器里 os.environ 已经是最终值」（compose 显式转发 ``.env``），
所以这里按调用时读取，不做模块级常量 —— 单测可以 monkeypatch 环境变量，
不必 reload 模块。
"""

from __future__ import annotations

import os
from typing import Optional

_TRUE = {'1', 'true', 'yes', 'on'}


def _env(name: str, default: str = '') -> str:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in _TRUE


def _int(name: str, default: int, minimum: int = 0) -> int:
    try:
        value = int(_env(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def api_enabled() -> bool:
    return _bool('RKB_AGENT_API_ENABLED', True)


def key_admin_enabled() -> bool:
    """UI「远程接入 → 密钥管理」接口开关。

    与 ``api_enabled`` **独立**：关闭 Agent 接口后仍要能在页面里查看/清理 Key。
    关闭本开关时 ``status`` 仍可读（供页面解释原因），其余管理端点返回业务错误。
    """
    return _bool('RKB_AGENT_KEY_ADMIN_ENABLED', True)


def rest_enabled() -> bool:
    return api_enabled() and _bool('RKB_AGENT_REST_ENABLED', True)


def mcp_enabled() -> bool:
    return api_enabled() and _bool('RKB_AGENT_MCP_ENABLED', True)


def answer_enabled() -> bool:
    return _bool('RKB_AGENT_ANSWER_ENABLED', True)


def key_pepper() -> str:
    """失败关闭：空 pepper 时 auth 必须报 503，CLI 必须拒绝建 Key。"""
    return _env('RKB_AGENT_KEY_PEPPER')


def max_top_k() -> int:
    return _int('RKB_AGENT_MAX_TOP_K', 20, minimum=1)


def max_kbs() -> int:
    return _int('RKB_AGENT_MAX_KBS', 50, minimum=1)


def answer_timeout() -> int:
    return _int('RKB_AGENT_ANSWER_TIMEOUT', 120, minimum=1)


def answer_model() -> str:
    return _env('RKB_AGENT_ANSWER_MODEL')


def reasoning_effort() -> str:
    return _env('RKB_AGENT_REASONING_EFFORT')


def log_query() -> bool:
    return _bool('RKB_AGENT_LOG_QUERY', False)


def mcp_stateless() -> bool:
    return _bool('RKB_AGENT_MCP_STATELESS', False)


def mcp_json_response() -> bool:
    return _bool('RKB_AGENT_MCP_JSON_RESPONSE', False)


def mcp_dns_rebinding_protection() -> bool:
    return _bool('RKB_AGENT_MCP_DNS_REBINDING_PROTECTION', False)


def _csv(name: str) -> list[str]:
    raw = _env(name)
    return [item.strip() for item in raw.split(',') if item.strip()] if raw else []


def mcp_allowed_hosts() -> list[str]:
    return _csv('RKB_AGENT_MCP_ALLOWED_HOSTS')


def mcp_allowed_origins() -> list[str]:
    return _csv('RKB_AGENT_MCP_ALLOWED_ORIGINS')


def public_base() -> str:
    return _env('RKB_AGENT_PUBLIC_BASE', '/api/co-knowledge/v1/agent')


def answer_model_for(request_model: Optional[str]) -> Optional[str]:
    """``RKB_AGENT_ANSWER_MODEL`` 非空时强制使用它（忽略请求里的 model）。"""
    return answer_model() or (request_model or '').strip() or None
