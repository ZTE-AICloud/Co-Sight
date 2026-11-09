#!/usr/bin/env python3
"""co-knowledge RAG 查询客户端（Agent API）。

调用 co-knowledge 的 ``POST /api/co-knowledge/v1/agent/query``（非流式 JSON 模式），
把服务端响应归一为 skill 的统一输出结构：

    {success, answer, conversation_id, dialogue_id, citations, placeholder, error, retrieval}

配置优先级（逐字段，高 -> 低）::

    base_url    函数参数 > 框架生效路由 routeUrl > CO_KNOWLEDGE_BASE_URL > http://localhost:4910
    api_key     函数参数 > 框架生效路由 apiKey  > CO_KNOWLEDGE_API_KEY   > 空（报 MISSING_API_KEY）
    workflow_id 函数参数 > CO_KNOWLEDGE_WORKFLOW_ID > DEFAULT_WORKFLOW_ID（注入时替换）
    timeout     函数参数 > CO_KNOWLEDGE_TIMEOUT > 180（秒）

框架生效路由：``GET {FRAMEWORK_BASE_URL}/api/framework/v1/rag-knowledge/active``，
用 ``{COSIGHT_HOME}/.module-token`` 的模块令牌鉴权（与 smart-factory 列表代理同一套口径）。
框架不可达、没有生效路由或字段缺失时**静默**回落到环境变量。

安全约束：
  - base_url / api_key 只来自函数参数、框架或环境变量，不接受来自 knowledge.json 的输入。
  - api_key 只进 ``Authorization`` 头，不写日志、不进错误消息、不进 URL。
  - workflow_id 只允许 [A-Za-z0-9_-]，因为它会被写进 Python 字面量。
  - 本地/私网地址默认绕过 HTTP 代理（CO_KNOWLEDGE_USE_PROXY=1 可强制走代理）。
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import urllib.error
import urllib.request
import uuid
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse, urlunparse

DEFAULT_BASE_URL = "http://localhost:4910"
AGENT_API_PATH = "/api/co-knowledge/v1/agent"
QUERY_SUFFIX = "/query"
DEFAULT_QUERY_PATH = "/api/co-knowledge/v1/agent/query"
DEFAULT_TIMEOUT = 180
DEFAULT_WORKFLOW_ID = 'default_workflow_id'

DEFAULT_FRAMEWORK_BASE_URL = "http://127.0.0.1:4300"
FRAMEWORK_ACTIVE_PATH = "/api/framework/v1/rag-knowledge/active"
DEFAULT_FRAMEWORK_TIMEOUT_MS = 2000
MIN_FRAMEWORK_TIMEOUT_MS = 100
MAX_FRAMEWORK_TIMEOUT_MS = 30000

WORKFLOW_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
MODULE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,}$")
MAX_ERROR_BODY = 500


def _fail(error: str, conversation_id: Optional[str]) -> Dict[str, Any]:
    return {
        "success": False,
        "answer": "",
        "conversation_id": conversation_id or "",
        "dialogue_id": conversation_id or "",
        "citations": [],
        "placeholder": {},
        "error": error,
        "retrieval": None,
    }


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def resolve_conversation_id(
    conversation_id: Optional[str] = None, dialogue_id: Optional[str] = None
) -> str:
    """会话标识：conversation_id 优先，dialogue_id 为旧字段兼容；都缺省时生成 UUID。"""
    return _first_non_empty(conversation_id, dialogue_id) or str(uuid.uuid4())


def resolve_cosight_home() -> str:
    """与框架同一口径：COSIGHT_HOME 未设置时落到 ``~/.cosight-harness``。"""
    return os.environ.get("COSIGHT_HOME") or os.path.join(os.path.expanduser("~"), ".cosight-harness")


def read_module_token() -> Optional[str]:
    """读取模块令牌；文件不存在或形状非法都返回 None（由调用方静默回落）。"""
    path = os.path.join(resolve_cosight_home(), ".module-token")
    try:
        with open(path, encoding="utf-8") as handle:
            token = handle.read().strip()
    except OSError:
        return None
    return token if MODULE_TOKEN_RE.match(token) else None


def _framework_timeout_seconds() -> float:
    raw = os.environ.get("FRAMEWORK_TIMEOUT_MS", "")
    try:
        value = int(raw) if raw.strip() else DEFAULT_FRAMEWORK_TIMEOUT_MS
    except ValueError:
        value = DEFAULT_FRAMEWORK_TIMEOUT_MS
    value = max(MIN_FRAMEWORK_TIMEOUT_MS, min(MAX_FRAMEWORK_TIMEOUT_MS, value))
    return value / 1000.0


def fetch_framework_active() -> Optional[Dict[str, Any]]:
    """读取框架「知识库路由设置」里生效的一条；任何失败都返回 None。"""
    token = read_module_token()
    if token is None:
        return None

    base = (os.environ.get("FRAMEWORK_BASE_URL") or DEFAULT_FRAMEWORK_BASE_URL).strip().rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    url = f"{base}{FRAMEWORK_ACTIVE_PATH}"
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with build_opener(url).open(request, timeout=_framework_timeout_seconds()) as response:
            raw = response.read().decode("utf-8", errors="replace")
        body = json.loads(raw)
    except Exception:  # noqa: BLE001 - 框架是可选增强，任何失败都回落环境变量
        return None

    data = body.get("data") if isinstance(body, dict) else None
    return data if isinstance(data, dict) else None


def resolve_knowledge_source(
    base_url: Optional[str] = None, api_key: Optional[str] = None
) -> Tuple[str, str]:
    """逐字段解析 (base_url, api_key)；框架优先于环境变量。"""
    active: Dict[str, Any] = {}
    if not (base_url and api_key):
        active = fetch_framework_active() or {}

    resolved_base = _first_non_empty(
        base_url,
        active.get("routeUrl"),
        os.environ.get("CO_KNOWLEDGE_BASE_URL"),
        DEFAULT_BASE_URL,
    )
    resolved_key = _first_non_empty(
        api_key,
        active.get("apiKey"),
        os.environ.get("CO_KNOWLEDGE_API_KEY"),
    )
    return resolved_base, resolved_key


def resolve_workflow_id(workflow_id: Optional[str] = None) -> str:
    value = _first_non_empty(workflow_id, os.environ.get("CO_KNOWLEDGE_WORKFLOW_ID"), DEFAULT_WORKFLOW_ID)
    return value


def resolve_timeout(timeout: Optional[float] = None) -> float:
    if timeout is not None:
        return float(timeout)
    return float(os.environ.get("CO_KNOWLEDGE_TIMEOUT", DEFAULT_TIMEOUT))


def build_query_url(base_url: str) -> Optional[str]:
    """把各种形态的知识库地址归一为 Agent query 的完整 URL。

    接受 ``http://host``、``http://host/#/login``、``http://host/api/co-knowledge/v1``、
    ``.../v1/agent`` 以及完整的 ``.../v1/agent/query``。无法解析时返回 None。
    """
    raw = (base_url or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    path = re.sub(r"/+$", "", parsed.path)
    lowered = path.lower()
    if lowered.endswith(DEFAULT_QUERY_PATH.lower()):
        query_path = path
    elif lowered.endswith(AGENT_API_PATH.lower()):
        query_path = f"{path}{QUERY_SUFFIX}"
    elif lowered.endswith("/api/co-knowledge/v1"):
        query_path = f"{path}/agent{QUERY_SUFFIX}"
    elif lowered.endswith("/api/co-knowledge"):
        query_path = f"{path}/v1/agent{QUERY_SUFFIX}"
    else:
        # 根地址或知识库网页地址：取源站 + 固定 Agent API 路径
        query_path = DEFAULT_QUERY_PATH
    return urlunparse((parsed.scheme, parsed.netloc, query_path, "", "", ""))


def build_workflows_url(query_url: str) -> str:
    """由 query URL 推出「已发布工作流」列表 URL（自检用，不触发 LLM）。"""
    base = query_url[: -len(QUERY_SUFFIX)] if query_url.endswith(QUERY_SUFFIX) else query_url
    return f"{base}/workflows?page=1&size=1&publishType=1"


def _validate_base_url(base_url: str) -> Optional[str]:
    if build_query_url(base_url) is None:
        return f"INVALID_ARGUMENT: base_url 必须形如 http(s)://host[:port][/path]，当前为 {base_url!r}"
    return None


def is_private_host(host: str) -> bool:
    """判断是否为本地/私网地址（决定是否绕过环境代理）。"""
    normalized = (host or "").strip().strip("[]").lower()
    if not normalized:
        return False
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


def build_opener(base_url: str) -> urllib.request.OpenerDirector:
    """私网/本地地址默认绕过代理，避免 http_proxy 环境变量劫持内部请求。"""
    force_proxy = os.environ.get("CO_KNOWLEDGE_USE_PROXY", "0").strip() == "1"
    host = urlparse(base_url).hostname or ""
    if not force_proxy and is_private_host(host):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def normalize_citations(citation_raw: Any) -> list:
    """把服务端 citation dict 归一为列表。

    服务端形态::

        {"引文-1": {"type": "text", "data": {"source": "...", "content_expand": "...", "node_id": "..."}}}

    无检索结果时为 ``{}``；也兼容直接返回列表的形态。
    """
    if isinstance(citation_raw, list):
        normalized = []
        for item in citation_raw:
            if not isinstance(item, dict):
                continue
            inner = item.get("data") if isinstance(item.get("data"), dict) else item
            normalized.append({
                "source": str(inner.get("source", "") or ""),
                "content_expand": str(inner.get("content_expand", "") or ""),
                "node_id": str(inner.get("node_id", "") or ""),
            })
        return normalized
    if not isinstance(citation_raw, dict):
        return []

    normalized = []
    for key in sorted(citation_raw.keys(), key=str):
        item = citation_raw.get(key)
        if not isinstance(item, dict):
            continue
        inner = item.get("data") if isinstance(item.get("data"), dict) else item
        normalized.append({
            "source": str(inner.get("source", "") or ""),
            "content_expand": str(inner.get("content_expand", "") or ""),
            "node_id": str(inner.get("node_id", "") or ""),
        })
    return normalized


def problem_detail(raw: str) -> str:
    """从 RFC7807 problem+json（或旧版 message）里取最可读的一句。"""
    text = (raw or "").strip()
    try:
        body = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text
    if not isinstance(body, dict):
        return text
    for key in ("detail", "message", "code"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    error = body.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return text


def _extract_http_error(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace")[:MAX_ERROR_BODY]
    except Exception:  # pragma: no cover - 读取失败不影响错误上报
        body = ""
    return f"HTTP {exc.code}: {problem_detail(body)}".strip()


def _extract_url_error(exc: urllib.error.URLError) -> str:
    reason = exc.reason
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return "TIMEOUT"
    if isinstance(reason, ConnectionRefusedError):
        return f"CONNECTION_ERROR: {reason}"
    if isinstance(reason, socket.gaierror):
        return f"INVALID_ENDPOINT: {reason}"
    return f"CONNECTION_ERROR: {reason}"


def rag_knowledge_search(
    question: str,
    conversation_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: Optional[float] = None,
    include_retrieval: bool = True,
    dialogue_id: Optional[str] = None,
) -> Dict[str, Any]:
    """调用 co-knowledge Agent query 接口，始终返回统一结构，不抛异常。"""
    resolved_conversation = resolve_conversation_id(conversation_id, dialogue_id)

    if not isinstance(question, str) or not question.strip():
        return _fail("INVALID_ARGUMENT: question 必填且不能为空", resolved_conversation)

    resolved_base, resolved_key = resolve_knowledge_source(base_url, api_key)
    invalid = _validate_base_url(resolved_base)
    if invalid:
        return _fail(invalid, resolved_conversation)
    if not resolved_key:
        return _fail(
            "MISSING_API_KEY: 未配置知识库 Agent API Key；"
            "请在框架「知识库路由设置」中配置，或设置 CO_KNOWLEDGE_API_KEY",
            resolved_conversation,
        )

    resolved_workflow = resolve_workflow_id(workflow_id)
    if not WORKFLOW_ID_RE.match(resolved_workflow):
        return _fail(
            "INVALID_ARGUMENT: workflow_id 只允许 [A-Za-z0-9_-]{1,128}，"
            f"当前为 {resolved_workflow!r}",
            resolved_conversation,
        )

    try:
        resolved_timeout = resolve_timeout(timeout)
    except (TypeError, ValueError):
        return _fail("INVALID_ARGUMENT: timeout 必须是数字（秒）", resolved_conversation)

    payload = {
        "question": question.strip(),
        "conversation_id": resolved_conversation,
        "workflow_id": resolved_workflow,
        "stream": False,
        "include_retrieval": bool(include_retrieval),
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {resolved_key}",
    }

    url = build_query_url(resolved_base)
    if url is None:  # pragma: no cover - _validate_base_url 已拦截
        return _fail("INVALID_ARGUMENT: base_url 非法", resolved_conversation)
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        opener = build_opener(resolved_base)
        with opener.open(request, timeout=resolved_timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            return _fail(f"TIMEOUT: 超过 {resolved_timeout:g}s", resolved_conversation)
        return _fail(_extract_http_error(exc), resolved_conversation)
    except urllib.error.URLError as exc:
        detail = _extract_url_error(exc)
        if detail == "TIMEOUT":
            detail = f"TIMEOUT: 超过 {resolved_timeout:g}s"
        return _fail(detail, resolved_conversation)
    except (socket.timeout, TimeoutError):
        return _fail(f"TIMEOUT: 超过 {resolved_timeout:g}s", resolved_conversation)
    except Exception as exc:  # pragma: no cover - 兜底
        return _fail(f"INTERNAL_ERROR: {type(exc).__name__}: {exc}", resolved_conversation)

    if not raw.strip():
        return _fail("INVALID_RESPONSE: 服务端返回空响应", resolved_conversation)

    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        return _fail(
            f"INVALID_RESPONSE: 非 JSON 响应（{exc}）: {raw[:MAX_ERROR_BODY]}",
            resolved_conversation,
        )

    if not isinstance(body, dict):
        return _fail("INVALID_RESPONSE: 响应顶层不是 JSON 对象", resolved_conversation)

    # 旧版网关的错误同样使用 HTTP 200，必须按 body.code 判断。
    code = body.get("code")
    if code is not None and code != 0:
        message = problem_detail(json.dumps(body, ensure_ascii=False))
        return _fail(
            f"CO_KNOWLEDGE_ERROR code={code} message={message}",
            resolved_conversation,
        )

    data = body.get("data") if isinstance(body.get("data"), dict) else body
    if not isinstance(data, dict):
        return _fail("INVALID_RESPONSE: 响应缺少 answer/retrieval 字段", resolved_conversation)
    if "answer" not in data and "retrieval" not in data:
        return _fail("INVALID_RESPONSE: 响应缺少 answer/retrieval 字段", resolved_conversation)

    answer = data.get("answer")
    if not isinstance(answer, str):
        answer = "" if answer is None else str(answer)
    conversation = _first_non_empty(
        data.get("conversation_id"), data.get("dialogue_id"), resolved_conversation
    )
    placeholder = data.get("placeholder")

    return {
        "success": True,
        "answer": answer,
        "conversation_id": conversation,
        "dialogue_id": conversation,
        "citations": normalize_citations(
            data.get("citation") if "citation" in data else data.get("citations")
        ),
        "placeholder": placeholder if isinstance(placeholder, dict) else {},
        "error": None,
        "retrieval": data.get("retrieval"),
    }


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_QUERY_PATH",
    "DEFAULT_TIMEOUT",
    "DEFAULT_WORKFLOW_ID",
    "build_opener",
    "build_query_url",
    "build_workflows_url",
    "fetch_framework_active",
    "is_private_host",
    "normalize_citations",
    "problem_detail",
    "rag_knowledge_search",
    "read_module_token",
    "resolve_conversation_id",
    "resolve_knowledge_source",
    "resolve_timeout",
    "resolve_workflow_id",
]
