"""rag-knowledge-search 客户端测试（co-knowledge Agent API）。

运行: python -m pytest tests/knowledge/test_rag_client.py -q
"""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = PLUGIN_ROOT / "knowledge" / "skill" / "rag-knowledge-search"
CLIENT_PATH = SKILL_DIR / "scripts" / "rag_knowledge_search.py"
EXECUTE_PATH = SKILL_DIR / "scripts" / "execute.py"

QUERY_PATH = "/api/co-knowledge/v1/agent/query"
FRAMEWORK_ACTIVE_PATH = "/api/framework/v1/rag-knowledge/active"

ENV_VARS = (
    "CO_KNOWLEDGE_BASE_URL",
    "CO_KNOWLEDGE_API_KEY",
    "CO_KNOWLEDGE_WORKFLOW_ID",
    "CO_KNOWLEDGE_TIMEOUT",
    "FRAMEWORK_BASE_URL",
    "FRAMEWORK_TIMEOUT_MS",
    "COSIGHT_HOME",
    "CO_KNOWLEDGE_USE_PROXY",
)


def _load_client():
    spec = importlib.util.spec_from_file_location("rag_knowledge_search", CLIENT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def client():
    return _load_client()


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    """隔离环境变量；COSIGHT_HOME 指向空目录以禁用真实框架回落。"""
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("COSIGHT_HOME", str(tmp_path))
    return monkeypatch


class _FakeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _handle(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw_body = self.rfile.read(length).decode("utf-8") if length else ""
        path_only = self.path.split("?", 1)[0]
        self.server.requests.append(
            {
                "method": self.command,
                "path": self.path,
                "headers": dict(self.headers),
                "body": json.loads(raw_body) if raw_body else None,
            }
        )
        status, payload = self.server.routes.get(
            (self.command, path_only), self.server.response
        )
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    do_GET = _handle  # noqa: N815 - http.server 约定
    do_POST = _handle  # noqa: N815 - http.server 约定

    def log_message(self, *args):  # 静默测试日志
        return


def _start_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeHandler)
    server.requests = []
    server.routes = {}
    server.response = (200, {})
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}", thread


def _stop_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


@pytest.fixture()
def fake_server():
    server, base_url, thread = _start_server()
    try:
        yield server, base_url
    finally:
        _stop_server(server, thread)


SUCCESS_BODY = {
    "conversation_id": "conv-server-1",
    "answer": "按需配置告警阈值即可。",
    "retrieval": {
        "query": "如何配置告警阈值",
        "items": [],
        "stats": {"count": 0},
        "timings": {"total_ms": 12},
    },
}

LEGACY_SUCCESS_BODY = {
    "code": 0,
    "message": "Success",
    "data": {
        "dialogue_id": "dlg-server-1",
        "answer": "按需配置告警阈值即可。",
        "placeholder": {},
        "citation": {
            "引文-1": {
                "type": "text",
                "data": {"source": "运维手册.pdf", "content_expand": "阈值配置说明", "node_id": "n-1"},
            }
        },
        "retrieval": {"query": "如何配置告警阈值", "items": [], "stats": {"count": 0}},
    },
}


def test_request_shape_and_success_mapping(client, fake_server):
    server, base_url = fake_server
    server.response = (200, SUCCESS_BODY)

    result = client.rag_knowledge_search(
        "  如何配置告警阈值  ",
        conversation_id="conv-1",
        workflow_id="RAG_Workflow_780f",
        base_url=base_url,
        api_key="test-key",
        timeout=5,
    )

    assert result["success"] is True
    assert result["answer"] == "按需配置告警阈值即可。"
    assert result["conversation_id"] == "conv-server-1"
    assert result["dialogue_id"] == "conv-server-1"
    assert result["citations"] == []
    assert result["placeholder"] == {}
    assert result["error"] is None
    assert result["retrieval"] == SUCCESS_BODY["retrieval"]

    assert len(server.requests) == 1
    request = server.requests[0]
    assert request["method"] == "POST"
    assert request["path"] == QUERY_PATH
    assert request["body"] == {
        "question": "如何配置告警阈值",
        "conversation_id": "conv-1",
        "workflow_id": "RAG_Workflow_780f",
        "stream": False,
        "include_retrieval": True,
    }
    assert "dialogue_id" not in request["body"]
    assert "scope" not in request["body"]
    assert request["headers"]["Content-Type"].startswith("application/json")
    assert request["headers"]["Authorization"] == "Bearer test-key"


def test_dialogue_id_is_accepted_as_deprecated_alias(client, fake_server):
    server, base_url = fake_server
    server.response = (200, SUCCESS_BODY)

    result = client.rag_knowledge_search(
        "q",
        dialogue_id="dlg-legacy",
        workflow_id="wf_1",
        base_url=base_url,
        api_key="test-key",
        timeout=5,
    )

    assert result["success"] is True
    assert server.requests[0]["body"]["conversation_id"] == "dlg-legacy"
    assert "dialogue_id" not in server.requests[0]["body"]


def test_conversation_id_generated_when_missing(client, fake_server):
    server, base_url = fake_server
    server.response = (200, SUCCESS_BODY)

    result = client.rag_knowledge_search(
        "q", workflow_id="wf_1", base_url=base_url, api_key="test-key", timeout=5
    )

    generated = server.requests[0]["body"]["conversation_id"]
    assert generated
    assert result["conversation_id"] == "conv-server-1"


def test_legacy_envelope_is_still_understood(client, fake_server):
    server, base_url = fake_server
    server.response = (200, LEGACY_SUCCESS_BODY)

    result = client.rag_knowledge_search(
        "q", workflow_id="wf_1", base_url=base_url, api_key="test-key", timeout=5
    )

    assert result["success"] is True
    assert result["conversation_id"] == "dlg-server-1"
    assert result["citations"] == [
        {"source": "运维手册.pdf", "content_expand": "阈值配置说明", "node_id": "n-1"}
    ]


def test_business_error_uses_code_not_http_status(client, fake_server):
    server, base_url = fake_server
    server.response = (200, {"code": 1001, "message": "published-workflow-not-found", "data": None})

    result = client.rag_knowledge_search(
        "q", workflow_id="wf_1", base_url=base_url, api_key="test-key", timeout=5
    )

    assert result["success"] is False
    assert result["error"] == "CO_KNOWLEDGE_ERROR code=1001 message=published-workflow-not-found"
    assert result["answer"] == ""


def test_problem_json_error_reports_detail(client, fake_server):
    server, base_url = fake_server
    server.response = (
        401,
        {"type": "about:blank", "status": 401, "code": "unauthorized", "detail": "invalid api key"},
    )

    result = client.rag_knowledge_search(
        "q", workflow_id="wf_1", base_url=base_url, api_key="bad-key", timeout=5
    )

    assert result["success"] is False
    assert result["error"] == "HTTP 401: invalid api key"
    assert "bad-key" not in result["error"]


def test_http_error_mapping(client, fake_server):
    server, base_url = fake_server
    server.response = (500, b"boom")

    result = client.rag_knowledge_search(
        "q", workflow_id="wf_1", base_url=base_url, api_key="test-key", timeout=5
    )

    assert result["success"] is False
    assert result["error"].startswith("HTTP 500:")


@pytest.mark.parametrize(
    ("status", "payload", "prefix"),
    [
        (200, b"not-json", "INVALID_RESPONSE"),
        (200, b"", "INVALID_RESPONSE"),
        (200, [1, 2, 3], "INVALID_RESPONSE"),
        (200, {"code": 0, "message": "Success"}, "INVALID_RESPONSE"),
    ],
)
def test_invalid_response_mapping(client, fake_server, status, payload, prefix):
    server, base_url = fake_server
    server.response = (status, payload)

    result = client.rag_knowledge_search(
        "q", workflow_id="wf_1", base_url=base_url, api_key="test-key", timeout=5
    )

    assert result["success"] is False
    assert result["error"].startswith(prefix)


def test_connection_refused(client):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()  # 端口已释放, 连接应被拒绝

    result = client.rag_knowledge_search(
        "q",
        workflow_id="wf_1",
        base_url=f"http://127.0.0.1:{port}",
        api_key="test-key",
        timeout=2,
    )

    assert result["success"] is False
    assert result["error"].startswith("CONNECTION_ERROR")


@pytest.mark.parametrize(
    ("kwargs", "prefix"),
    [
        ({"question": "   ", "api_key": "k"}, "INVALID_ARGUMENT"),
        ({"question": "q", "workflow_id": "bad id!", "api_key": "k"}, "INVALID_ARGUMENT"),
        ({"question": "q", "workflow_id": "wf_1", "base_url": "ftp://x", "api_key": "k"}, "INVALID_ARGUMENT"),
        (
            {"question": "q", "workflow_id": "wf_1", "base_url": "http://127.0.0.1:1",
             "api_key": "k", "timeout": "abc"},
            "INVALID_ARGUMENT",
        ),
        ({"question": "q", "workflow_id": "wf_1"}, "MISSING_API_KEY"),
    ],
)
def test_argument_validation(client, kwargs, prefix):
    result = client.rag_knowledge_search(**kwargs)
    assert result["success"] is False
    assert result["error"].startswith(prefix)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://203.0.113.10", "http://203.0.113.10/api/co-knowledge/v1/agent/query"),
        ("http://203.0.113.10/", "http://203.0.113.10/api/co-knowledge/v1/agent/query"),
        ("http://h/#/login", "http://h/api/co-knowledge/v1/agent/query"),
        ("http://h/api/co-knowledge", "http://h/api/co-knowledge/v1/agent/query"),
        ("http://h/api/co-knowledge/v1", "http://h/api/co-knowledge/v1/agent/query"),
        ("http://h/api/co-knowledge/v1/", "http://h/api/co-knowledge/v1/agent/query"),
        ("http://h/api/co-knowledge/v1/agent", "http://h/api/co-knowledge/v1/agent/query"),
        (
            "http://h/api/co-knowledge/v1/agent/query",
            "http://h/api/co-knowledge/v1/agent/query",
        ),
    ],
)
def test_build_query_url_variants(client, raw, expected):
    assert client.build_query_url(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "ftp://h", "http://", "not-a-url"])
def test_build_query_url_rejects_invalid(client, raw):
    assert client.build_query_url(raw) is None


def test_build_workflows_url(client):
    assert client.build_workflows_url(
        "http://h/api/co-knowledge/v1/agent/query"
    ) == "http://h/api/co-knowledge/v1/agent/workflows?page=1&size=1&publishType=1"


def test_resolve_knowledge_source_env_fallback(client, clean_env):
    clean_env.setenv("CO_KNOWLEDGE_BASE_URL", "http://env-host/api/co-knowledge/v1/agent")
    clean_env.setenv("CO_KNOWLEDGE_API_KEY", "env-key")

    assert client.resolve_knowledge_source() == (
        "http://env-host/api/co-knowledge/v1/agent",
        "env-key",
    )


def test_resolve_knowledge_source_defaults(client):
    base, key = client.resolve_knowledge_source()
    assert base == client.DEFAULT_BASE_URL
    assert key == ""


def test_framework_route_takes_precedence(client, fake_server, clean_env, tmp_path):
    server, co_base_url = fake_server
    server.response = (200, SUCCESS_BODY)

    framework, framework_url, framework_thread = _start_server()
    try:
        framework.routes[("GET", FRAMEWORK_ACTIVE_PATH)] = (
            200,
            {
                "success": True,
                "data": {
                    "routeUrl": f"{co_base_url}/api/co-knowledge/v1/agent",
                    "apiKey": "framework-key",
                    "username": "",
                    "hasPassword": False,
                    "hasApiKey": True,
                },
                "error": None,
            },
        )
        clean_env.setenv("FRAMEWORK_BASE_URL", framework_url)
        clean_env.setenv("COSIGHT_HOME", str(tmp_path))
        (tmp_path / ".module-token").write_text("m" * 32, encoding="utf-8")

        # 环境变量存在也必须被框架生效路由覆盖
        clean_env.setenv("CO_KNOWLEDGE_BASE_URL", "http://env-host")
        clean_env.setenv("CO_KNOWLEDGE_API_KEY", "env-key")

        result = client.rag_knowledge_search("q", workflow_id="wf_1", timeout=5)

        assert result["success"] is True
        assert [r["path"].split("?")[0] for r in server.requests] == [QUERY_PATH]
        assert server.requests[0]["headers"]["Authorization"] == "Bearer framework-key"

        assert len(framework.requests) == 1
        active = framework.requests[0]
        assert active["method"] == "GET"
        assert active["path"] == FRAMEWORK_ACTIVE_PATH
        assert active["headers"]["Authorization"] == f"Bearer {'m' * 32}"
    finally:
        _stop_server(framework, framework_thread)


def test_framework_fields_resolve_per_field(client, fake_server, clean_env, tmp_path):
    server, co_base_url = fake_server
    server.response = (200, SUCCESS_BODY)

    framework, framework_url, framework_thread = _start_server()
    try:
        # 框架只给 routeUrl，API Key 由环境变量补齐
        framework.routes[("GET", FRAMEWORK_ACTIVE_PATH)] = (
            200,
            {"success": True, "data": {"routeUrl": f"{co_base_url}/api/co-knowledge/v1/agent"}},
        )
        clean_env.setenv("FRAMEWORK_BASE_URL", framework_url)
        clean_env.setenv("COSIGHT_HOME", str(tmp_path))
        (tmp_path / ".module-token").write_text("t" * 32, encoding="utf-8")
        clean_env.setenv("CO_KNOWLEDGE_API_KEY", "env-key")
        clean_env.setenv("CO_KNOWLEDGE_BASE_URL", "http://env-host")

        result = client.rag_knowledge_search("q", workflow_id="wf_1", timeout=5)

        assert result["success"] is True
        assert server.requests[0]["headers"]["Authorization"] == "Bearer env-key"
    finally:
        _stop_server(framework, framework_thread)


def test_framework_unavailable_falls_back_to_env(client, fake_server, clean_env):
    server, base_url = fake_server
    server.response = (200, SUCCESS_BODY)

    # 无模块令牌：不得发起框架请求，直接回落环境变量
    clean_env.setenv("FRAMEWORK_BASE_URL", "http://127.0.0.1:1")
    clean_env.setenv("CO_KNOWLEDGE_BASE_URL", base_url)
    clean_env.setenv("CO_KNOWLEDGE_API_KEY", "env-key")

    result = client.rag_knowledge_search("q", workflow_id="wf_1", timeout=5)

    assert result["success"] is True
    assert server.requests[0]["headers"]["Authorization"] == "Bearer env-key"


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("a" * 32, "a" * 32),
        ("  " + "b" * 20 + "  \n", "b" * 20),
        ("short", None),          # 形状非法
        ("token with spaces!!", None),
        ("", None),
    ],
)
def test_read_module_token(client, clean_env, tmp_path, content, expected):
    clean_env.setenv("COSIGHT_HOME", str(tmp_path))
    (tmp_path / ".module-token").write_text(content, encoding="utf-8")
    assert client.read_module_token() == expected


def test_read_module_token_missing_file(client):
    assert client.read_module_token() is None


def test_normalize_citations_handles_both_shapes(client):
    assert client.normalize_citations({}) == []
    assert client.normalize_citations(None) == []
    assert client.normalize_citations(
        [{"source": "s", "content_expand": "c", "node_id": "n"}]
    ) == [{"source": "s", "content_expand": "c", "node_id": "n"}]
    assert client.normalize_citations(
        {"引文-1": {"type": "text", "data": {"source": "s2"}}}
    ) == [{"source": "s2", "content_expand": "", "node_id": ""}]


def test_problem_detail_prefers_rfc7807_detail(client):
    assert client.problem_detail('{"status":422,"detail":"workflow_id invalid"}') == "workflow_id invalid"
    assert client.problem_detail('{"message":"legacy message"}') == "legacy message"
    assert client.problem_detail('{"error":{"message":"nested"}}') == "nested"
    assert client.problem_detail("plain text") == "plain text"


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("localhost", True),
        ("LOCALHOST", True),
        ("app.localhost", True),
        ("127.0.0.1", True),
        ("::1", True),
        ("10.0.0.1", True),
        ("192.168.1.10", True),
        ("172.16.0.1", True),
        ("8.8.8.8", False),
        ("example.com", False),
        ("", False),
    ],
)
def test_is_private_host(client, host, expected):
    assert client.is_private_host(host) is expected


def _enabled_proxies(opener):
    """返回 opener 中实际生效（proxies 非空）的 ProxyHandler。

    注: ProxyHandler({}) 没有任何 *_open 方法, urllib 不会把它 append 进
    opener.handlers——"没有生效的代理"正是绕过代理的预期形态。
    """
    return [
        h for h in opener.handlers
        if isinstance(h, urllib.request.ProxyHandler) and h.proxies
    ]


def test_private_host_bypasses_env_proxy(client, monkeypatch):
    monkeypatch.delenv("CO_KNOWLEDGE_USE_PROXY", raising=False)
    monkeypatch.setenv("http_proxy", "http://proxy.example:8080")
    opener = client.build_opener("http://localhost:4910")
    assert _enabled_proxies(opener) == [], "私网地址不得挂载生效的代理"

    # 公网地址仍走环境代理（确认上面的断言不是因为环境无代理变量而空转）
    public = client.build_opener("http://example.com")
    assert _enabled_proxies(public), "公网地址应使用环境代理"

    monkeypatch.setenv("CO_KNOWLEDGE_USE_PROXY", "1")
    forced = client.build_opener("http://localhost:4910")
    assert _enabled_proxies(forced), "CO_KNOWLEDGE_USE_PROXY=1 时应强制走代理"


def _execute_env(base_url: str) -> dict:
    env = dict(os.environ)
    for name in ENV_VARS:
        env.pop(name, None)
    env["CO_KNOWLEDGE_BASE_URL"] = base_url
    env["CO_KNOWLEDGE_API_KEY"] = "test-key"
    # 指向不存在的目录：不读取开发机真实的框架模块令牌
    env["COSIGHT_HOME"] = "/nonexistent-cosight-home-for-tests"
    return env


def test_execute_script_contract(fake_server):
    server, base_url = fake_server
    server.response = (200, SUCCESS_BODY)

    completed = subprocess.run(
        [sys.executable, str(EXECUTE_PATH)],
        input=json.dumps(
            {"question": "怎么配置", "conversation_id": "conv-9", "workflow_id": "RAG_Workflow_780f"}
        ),
        capture_output=True,
        text=True,
        env=_execute_env(base_url),
        timeout=20,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert set(payload) == {
        "success", "answer", "conversation_id", "dialogue_id",
        "citations", "placeholder", "error", "retrieval",
    }
    assert payload["success"] is True
    assert payload["conversation_id"] == "conv-server-1"
    assert payload["dialogue_id"] == "conv-server-1"
    assert server.requests[0]["body"]["conversation_id"] == "conv-9"


def test_execute_script_accepts_deprecated_dialogue_id(fake_server):
    server, base_url = fake_server
    server.response = (200, SUCCESS_BODY)

    completed = subprocess.run(
        [sys.executable, str(EXECUTE_PATH)],
        input=json.dumps({"question": "q", "dialogue_id": "dlg-old"}),
        capture_output=True,
        text=True,
        env=_execute_env(base_url),
        timeout=20,
    )

    assert completed.returncode == 0, completed.stderr
    assert server.requests[0]["body"]["conversation_id"] == "dlg-old"


def test_execute_script_exit_code_on_failure():
    completed = subprocess.run(
        [sys.executable, str(EXECUTE_PATH)],
        input=json.dumps({"question": ""}),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["success"] is False
    # execute.py 在调用客户端前做入口校验, 错误前缀为 INVALID_INPUT
    assert payload["error"].startswith("INVALID_INPUT")
