"""REST facade、MCP 工具注册/完整调用、挂载顺序与 schemas 的单测。"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sse_starlette.sse import EventSourceResponse, ServerSentEvent
from starlette.routing import Route

import chat.app as chat_app
from agent import auth, service
from agent import rest as rest_mod
from agent.auth import AgentContext, AgentPrincipal, agent_context
from agent.errors import configuration_error, rate_limited
from agent.mcp_server import build_mcp
from agent.mount import AuthenticatedMCPApp, agent_lifespan, register_agent_api
from agent.schemas import AnswerRequest, SearchRequest
from shared.prefixes import AGENT_ADMIN_PREFIX, AGENT_MCP_PATH, AGENT_PREFIX, RKB_PREFIX

PRINCIPAL = AgentPrincipal('ragk_test', 'demo',
                           frozenset({'kb:list', 'kb:search', 'kb:answer',
                                      'workflow:run'}), (), 60)


def _kb_info():
    return {'id': 'kb-1', 'name': 'demo', 'description': None, 'type': 'document',
            'embedding_model': 'm', 'status': '7', 'created_date': None}


def _search_data(query='q'):
    return {'query': query, 'mode': 'hybrid', 'results': [{
        'citation_id': 'S1', 'knowledge_base_id': 'kb-1', 'knowledge_base_name': 'demo',
        'chunk_id': '1', 'document_id': 'f1', 'source': 'a.md', 'score': 0.5,
        'scores': None, 'text': 'hello', 'metadata': None}],
        'degraded': False, 'warnings': []}


def _answer_data():
    return {'answer': 'hi [S1]', 'citations': [{
        'citation_id': 'S1', 'knowledge_base_id': 'kb-1', 'document_id': 'f1',
        'source': 'a.md', 'chunk_id': '1', 'text': 'hello'}],
        'model': 'm', 'usage': None, 'no_results': False, 'reason': None, 'warnings': []}


def _rest_app(monkeypatch, principal=PRINCIPAL):
    monkeypatch.setattr(rest_mod.service, 'list_knowledge_bases',
                        lambda p, t, surface='rest': [_kb_info()])
    monkeypatch.setattr(rest_mod.service, 'get_knowledge_base',
                        lambda p, kb, t, surface='rest': _kb_info())
    monkeypatch.setattr(rest_mod.service, 'search',
                        lambda p, req, t, surface='rest': _search_data(req.query))
    monkeypatch.setattr(rest_mod.service, 'answer',
                        lambda p, req, t, surface='rest': _answer_data())
    app = rest_mod.build_rest_app()
    app.dependency_overrides[agent_context] = lambda: AgentContext(principal, 'trace-1')
    return app


def test_rest_endpoints_return_plain_resources(monkeypatch):
    with TestClient(_rest_app(monkeypatch)) as client:
        r = client.get('/knowledge-bases')
        assert r.status_code == 200
        assert r.headers['X-Request-Id'] == 'trace-1'
        assert r.json()[0]['id'] == 'kb-1'

        assert client.get('/knowledge-bases/kb-1').json()['id'] == 'kb-1'
        assert client.post('/search', json={'query': 'q'}).json()['results'][0]['citation_id'] == 'S1'
        assert client.post('/answer', json={'question': 'q'}).json()['answer'] == 'hi [S1]'
        assert 'trace_id' not in client.post('/search', json={'query': 'q'}).json()


def test_rest_validation_404_and_noauth(monkeypatch):
    with TestClient(_rest_app(monkeypatch)) as client:
        r = client.post('/search', json={'query': 'q', 'top_k': 999})
        assert r.status_code == 422
        assert r.headers['content-type'].startswith('application/problem+json')
        assert r.json()['code'] == 'validation_failed'
        assert r.json()['errors']
        r = client.post('/search', json={'query': 'q', 'extra': 1})
        assert r.status_code == 422
        r = client.get('/nope')
        assert r.status_code == 404 and r.json()['code'] == 'not_found'

    app = rest_mod.build_rest_app()
    monkeypatch.setenv('RKB_AGENT_KEY_PEPPER', 'pepper')
    with TestClient(app) as client:
        r = client.get('/knowledge-bases')
        assert r.status_code == 401
        assert r.headers['WWW-Authenticate'] == 'Bearer'
        assert r.headers['content-type'].startswith('application/problem+json')
        assert r.json()['code'] == 'unauthorized'


def test_rest_429_and_503(monkeypatch):
    app = rest_mod.build_rest_app()
    app.dependency_overrides[agent_context] = lambda: (_ for _ in ()).throw(rate_limited(7))
    with TestClient(app) as client:
        r = client.get('/knowledge-bases')
        assert r.status_code == 429
        assert r.headers['Retry-After'] == '7'

    app = _rest_app(monkeypatch)
    monkeypatch.setattr(rest_mod.service, 'list_knowledge_bases',
                        lambda p, t, surface='rest': (_ for _ in ()).throw(
                            configuration_error('no pepper')))
    with TestClient(app) as client:
        r = client.get('/knowledge-bases')
        assert r.status_code == 503 and r.json()['code'] == 'configuration_error'


def test_rest_openapi_is_30_and_has_security(monkeypatch):
    app = _rest_app(monkeypatch)
    schema = app.openapi()
    assert schema['openapi'] == '3.0.2'
    assert schema['servers'] == [{'url': '/api/co-knowledge/v1/agent'}]
    assert set(schema['paths']) == {'/knowledge-bases', '/knowledge-bases/{kb_id}',
                                    '/search', '/answer', '/workflows', '/query'}
    assert schema['components']['securitySchemes']['HTTPBearer']['scheme'] == 'bearer'


def test_schemas_enforce_limits_and_extra():
    with pytest.raises(Exception):
        SearchRequest(query='q', top_k=999)
    with pytest.raises(Exception):
        SearchRequest(query='q', unexpected=1)
    request = SearchRequest(query='q', knowledge_base_ids=[' kb-1 ', 'kb-1', ''])
    assert request.knowledge_base_ids == ['kb-1']
    assert AnswerRequest(question='q').top_k == 8


def test_owns_path_includes_agent_rest_and_graph():
    from infrastructure.http.rkb_support import owns_problem_path as _owns_path

    # Agent REST 与图谱检索都走 problem+json 契约
    assert _owns_path(AGENT_PREFIX + '/search') is True
    assert _owns_path(RKB_PREFIX + '/retrieval/graph') is True
    assert _owns_path(AGENT_ADMIN_PREFIX) is True
    assert _owns_path(AGENT_ADMIN_PREFIX + '/status') is True
    assert _owns_path(AGENT_MCP_PATH) is False
    assert _owns_path(AGENT_MCP_PATH + '/') is False
    # 段级匹配：不能因为字符串前缀把 /agent-keys-extra 也当成 /agent 的子路径
    assert _owns_path(RKB_PREFIX + '/agent-keys-extra') is True
    assert _owns_path(RKB_PREFIX + '/nope') is True


def test_route_order_mounts_agent_before_kb_catch_all():
    from app import app

    from route_helpers import route_paths

    paths = route_paths(app)
    catch_all = paths.index(RKB_PREFIX + '/{unknown_path:path}')
    assert paths.index(AGENT_PREFIX) < catch_all
    assert paths.index(AGENT_ADMIN_PREFIX) < catch_all
    assert paths.index(AGENT_MCP_PATH) < catch_all


def test_disabled_agent_api_returns_404(monkeypatch):
    monkeypatch.setenv('RKB_AGENT_API_ENABLED', 'false')
    app = FastAPI()
    register_agent_api(app)
    with TestClient(app) as client:
        r = client.get(AGENT_PREFIX + '/knowledge-bases')
        assert r.status_code == 404
        assert r.headers['content-type'].startswith('application/problem+json')
        assert r.json()['code'] == 'not_found'
        assert r.json()['detail'] == 'agent api is disabled'


# ---------------------------------------------------------------------------
# MCP
# ---------------------------------------------------------------------------

def test_mcp_tools_registered_without_context_argument():
    import asyncio

    tools = asyncio.run(build_mcp().list_tools())
    by_name = {tool.name: tool for tool in tools}
    assert set(by_name) == {
        'list_knowledge_bases', 'search_knowledge', 'ask_knowledge_base',
        'list_workflows', 'run_workflow',
    }
    assert (by_name['search_knowledge'].inputSchema or {}).get('required') == ['query']
    assert 'ctx' not in (by_name['search_knowledge'].inputSchema or {}).get('properties', {})
    assert by_name['search_knowledge'].annotations.readOnlyHint is True
    assert by_name['list_workflows'].annotations.readOnlyHint is True
    workflow_props = (by_name['list_workflows'].inputSchema or {}).get('properties', {})
    assert {'page', 'size', 'keyword', 'publish_type'} <= set(workflow_props)
    assert 'ctx' not in workflow_props
    # 执行工具会真正跑工作流并调用生成模型，不能标成只读
    assert by_name['run_workflow'].annotations.readOnlyHint is False
    run_props = (by_name['run_workflow'].inputSchema or {}).get('properties', {})
    assert {'question', 'conversation_id', 'workflow_id', 'stream',
            'include_retrieval', 'chat_history'} == set(run_props)
    assert (by_name['run_workflow'].inputSchema or {}).get('required') == [
        'question', 'conversation_id', 'workflow_id']


def _sse_payloads(text):
    payloads = [json.loads(line[6:]) for line in text.splitlines()
                if line.startswith('data: ') and line[6:].strip()]
    return payloads or [json.loads(text)]


def _sse_payload(text):
    """最后一个 JSON-RPC 帧（工具结果）；前面的可能是 progress 通知。"""
    return _sse_payloads(text)[-1]


def _sse_response(*events):
    def _gen():
        for event, payload in events:
            yield ServerSentEvent(event=event, data=json.dumps(payload))
    return EventSourceResponse(_gen())


def test_mcp_full_roundtrip_with_auth_and_tools(monkeypatch):
    seen = []
    engine_requests = []
    monkeypatch.setattr(auth, 'authenticate_headers',
                        lambda headers: PRINCIPAL if headers.get('authorization')
                        else (_ for _ in ()).throw(auth.unauthorized()))
    monkeypatch.setattr(service, 'list_knowledge_bases',
                        lambda p, t, surface='rest': (seen.append((p.key_prefix, surface)) or [_kb_info()]))
    monkeypatch.setattr(service, 'search',
                        lambda p, req, t, surface='rest': (seen.append((p.key_prefix, surface)) or _search_data(req.query)))
    monkeypatch.setattr(service, 'answer',
                        lambda p, req, t, surface='rest': (seen.append((p.key_prefix, surface)) or _answer_data()))
    monkeypatch.setattr(
        service, 'list_workflows',
        lambda p, page, size, keyword, publish_type, t, surface='rest':
        (seen.append((p.key_prefix, surface))
         or {'items': [{'workFlowId': 'wf-1', 'name': 'demo', 'publishType': 1}],
             'total': 1, 'page': page, 'pageSize': size}))

    def _fake_run_query(rag_request, request, *, surface='native'):
        engine_requests.append(request)
        if rag_request.stream:
            return _sse_response(
                ('token', {'conversation_id': rag_request.conversation_id,
                           'content': 'wf '}),
                ('token', {'conversation_id': rag_request.conversation_id,
                           'content': 'stream'}),
                ('done', {'conversation_id': rag_request.conversation_id,
                          'finish_reason': 'stop'}))
        return JSONResponse({'conversation_id': rag_request.conversation_id,
                             'answer': 'wf answer'})

    # run_workflow 与 REST 共用 chat.app.run_query，但不经过 HTTP 回环
    monkeypatch.setattr(chat_app, 'run_query', _fake_run_query)

    server = build_mcp()
    server.streamable_http_app()
    app = FastAPI(lifespan=agent_lifespan)
    app.state.agent_mcp_server = server
    app.router.routes.append(Route(AGENT_MCP_PATH, endpoint=AuthenticatedMCPApp(server.session_manager)))

    headers = {'Accept': 'application/json, text/event-stream',
               'Content-Type': 'application/json',
               'Authorization': 'Bearer ragk_x'}
    with TestClient(app) as client:
        r = client.post(AGENT_MCP_PATH, headers=headers, json={
            'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
            'params': {'protocolVersion': '2025-06-18', 'capabilities': {},
                       'clientInfo': {'name': 'test', 'version': '0'}}})
        assert r.status_code == 200
        session = r.headers['mcp-session-id']
        call_headers = {**headers, 'Mcp-Session-Id': session}
        assert client.post(AGENT_MCP_PATH, headers=call_headers, json={
            'jsonrpc': '2.0', 'method': 'notifications/initialized'}).status_code == 202

        r = client.post(AGENT_MCP_PATH, headers=call_headers, json={
            'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
            'params': {'name': 'list_knowledge_bases', 'arguments': {}}})
        result = _sse_payload(r.text)['result']
        assert result['isError'] is False
        assert 'kb-1' in result['content'][0]['text']

        r = client.post(AGENT_MCP_PATH, headers=call_headers, json={
            'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
            'params': {'name': 'search_knowledge', 'arguments': {'query': 'hello'}}})
        assert _sse_payload(r.text)['result']['isError'] is False

        r = client.post(AGENT_MCP_PATH, headers=call_headers, json={
            'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call',
            'params': {'name': 'list_workflows', 'arguments': {'publish_type': 1}}})
        result = _sse_payload(r.text)['result']
        assert result['isError'] is False
        assert 'wf-1' in result['content'][0]['text']

        r = client.post(AGENT_MCP_PATH, headers=call_headers, json={
            'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call',
            'params': {'name': 'run_workflow', 'arguments': {
                'question': 'hello', 'conversation_id': 'c-1',
                'workflow_id': 'RAG_Workflow_demo'}}})
        result = _sse_payload(r.text)['result']
        assert result['isError'] is False
        payload = json.loads(result['content'][0]['text'])
        assert payload['conversation_id'] == 'c-1'
        assert payload['answer'] == 'wf answer'
        assert payload['trace_id']

        # stream=true：token 以 progress 通知落在同一次 tools/call 的 SSE 响应里，
        # 工具结果仍是拼好的完整答案。
        r = client.post(AGENT_MCP_PATH, headers=call_headers, json={
            'jsonrpc': '2.0', 'id': 6, 'method': 'tools/call',
            'params': {'name': 'run_workflow',
                       'arguments': {'question': 'hello', 'conversation_id': 'c-2',
                                     'workflow_id': 'RAG_Workflow_demo',
                                     'stream': True},
                       '_meta': {'progressToken': 'progress-1'}}})
        frames = _sse_payloads(r.text)
        progress = [frame for frame in frames
                    if frame.get('method') == 'notifications/progress']
        assert progress, r.text[:500]
        assert progress[0]['params']['progressToken'] == 'progress-1'
        assert ''.join(frame['params'].get('message') or '' for frame in progress) == 'wf stream'
        result = _sse_payload(r.text)['result']
        assert result['isError'] is False
        payload = json.loads(result['content'][0]['text'])
        assert payload['conversation_id'] == 'c-2'
        assert payload['answer'] == 'wf stream'

    assert ('ragk_test', 'mcp') in seen
    # MCP 客户端总是带 Accept: text/event-stream；stream=false 时必须改写成 JSON，
    # 否则 run_query 会把每次调用都判成流式。
    assert engine_requests[0].headers.get('accept') == 'application/json'
    assert engine_requests[0].url.path == AGENT_PREFIX + '/query'
