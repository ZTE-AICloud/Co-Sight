"""``POST /agent/query`` 的边界测试（不连 DB / 不跑真实引擎）。"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sse_starlette.sse import EventSourceResponse, ServerSentEvent
from starlette.background import BackgroundTask
from starlette.datastructures import Headers

import chat.app as app_module
from agent import query as query_mod
from agent import rest as rest_mod
from agent import workflows as workflows_mod
from agent.auth import AgentContext, AgentPrincipal, agent_context
from agent.errors import AgentApiError
from agent.schemas import WorkflowQueryRequest
from shared.prefixes import AGENT_PREFIX

WF = 'RAG_Workflow_demo'
PRINCIPAL = AgentPrincipal('ragk_test', 'demo',
                           frozenset({'workflow:run'}), (), 60)


class _FakeResult:
    response = '回答正文'
    source_nodes: list = []
    query_str = '问题'


class _FakeEngine:
    def __init__(self, calls):
        self.calls = calls

    def query(self, question):
        self.calls.append(question)
        return _FakeResult()


def _client(monkeypatch, principal=PRINCIPAL, calls=None):
    calls = calls if calls is not None else []
    monkeypatch.setattr(
        app_module.rag, 'build_query_engine',
        lambda *args, **kwargs: _FakeEngine(calls))

    def _ctx(request: Request):
        request.state.trace_id = 'trace-1'
        return AgentContext(principal, 'trace-1')

    app = rest_mod.build_rest_app()
    app.dependency_overrides[agent_context] = _ctx
    return TestClient(app)


def _body(**overrides):
    payload = {'question': '如何配置检索编排？', 'conversation_id': 'd-001',
               'workflow_id': WF}
    payload.update(overrides)
    return payload


def test_agent_query_runs_published_workflow(monkeypatch):
    calls = []
    client = _client(monkeypatch, calls=calls)

    response = client.post('/query', json=_body())

    assert response.status_code == 200
    assert response.json() == {'conversation_id': 'd-001', 'answer': '回答正文'}
    # Agent 面复用 agent_context 的 trace id，和鉴权/用量审计对得上
    assert response.headers['X-Request-Id'] == 'trace-1'
    assert calls == ['如何配置检索编排？']


def test_agent_query_requires_workflow_run_scope(monkeypatch):
    principal = AgentPrincipal('ragk_test', 'demo',
                               frozenset({'workflow:read'}), (), 60)
    client = _client(monkeypatch, principal=principal)

    response = client.post('/query', json=_body())

    assert response.status_code == 403
    assert response.headers['content-type'].startswith('application/problem+json')
    body = response.json()
    assert body['code'] == 'forbidden_scope'
    assert body['required_scope'] == 'workflow:run'


def test_agent_query_requires_workflow_id(monkeypatch):
    client = _client(monkeypatch)
    body = _body()
    body.pop('workflow_id')

    response = client.post('/query', json=body)

    assert response.status_code == 422
    assert response.json()['code'] == 'validation_failed'


def test_agent_query_rejects_unknown_fields(monkeypatch):
    """外部模型不暴露 scope/kwargs 等内部字段；传了就是 422。"""
    client = _client(monkeypatch)

    response = client.post('/query', json=_body(scope='dev'))

    assert response.status_code == 422
    assert response.json()['code'] == 'validation_failed'


def test_agent_query_kb_whitelist_blocks_foreign_workflow(monkeypatch):
    calls = []
    principal = AgentPrincipal('ragk_test', 'demo',
                               frozenset({'workflow:run'}), ('kb-allowed',), 60)
    client = _client(monkeypatch, principal=principal, calls=calls)
    monkeypatch.setattr(query_mod.workflows, 'bound_kb_ids',
                        lambda workflow_id: ('kb-other',))

    response = client.post('/query', json=_body())

    assert response.status_code == 403
    body = response.json()
    assert body['code'] == 'knowledge_base_forbidden'
    assert body['knowledge_base_id'] == 'kb-other'
    assert calls == []


def test_agent_query_kb_whitelist_allows_bound_workflow(monkeypatch):
    calls = []
    principal = AgentPrincipal('ragk_test', 'demo',
                               frozenset({'workflow:run'}), ('kb-allowed',), 60)
    client = _client(monkeypatch, principal=principal, calls=calls)
    monkeypatch.setattr(query_mod.workflows, 'bound_kb_ids',
                        lambda workflow_id: ('kb-allowed',))

    response = client.post('/query', json=_body())

    assert response.status_code == 200
    assert calls == ['如何配置检索编排？']


def test_agent_answer_payload_drops_legacy_fields():
    payload = app_module._agent_answer_payload({
        'conversation_id': 'd-1', 'answer': 'a',
        'placeholder': {}, 'citation': {}, 'related_context': [],
        'retrieval': {'query': 'q', 'items': []},
    })

    assert payload == {
        'conversation_id': 'd-1', 'answer': 'a',
        'retrieval': {'query': 'q', 'items': []},
    }


def test_agent_answer_payload_omits_missing_retrieval():
    assert app_module._agent_answer_payload({
        'conversation_id': 'd-1', 'answer': 'a',
        'placeholder': {}, 'citation': {},
    }) == {'conversation_id': 'd-1', 'answer': 'a'}


def test_workflow_query_request_converts_to_rag_request():
    payload = WorkflowQueryRequest(
        question='q', conversation_id='d', workflow_id=WF,
        stream=True, include_retrieval=True,
        chat_history=[{'question': 'q1', 'answer': 'a1'}])

    rag_request = payload.to_rag_request()

    assert rag_request.question == 'q'
    assert rag_request.conversation_id == 'd'
    assert rag_request.workflow_id == WF
    assert rag_request.stream is True
    assert rag_request.include_retrieval is True
    assert rag_request.chat_history == [{'question': 'q1', 'answer': 'a1'}]


def test_bound_kb_ids_reads_published_snapshot():
    class _Service:
        def get_published_flow_config(self, app_id, language):
            return {'nodeConfigDTOList': [
                {'variables': {'retriever': [
                    {'kwargs': {'knowledge_info_list': [
                        {'knowledge_base_name': 'doc_uuid-a'},
                        {'knowledge_base_name': 'doc_uuid-a'},
                    ]}},
                ]}},
                {'variables': {'retriever': [
                    {'kwargs': {'knowledge_base_name': [
                        'graph_uuid-b', 'data_uuid-c',
                    ]}},
                ]}},
            ]}

    # 图谱库不在 Agent Key 白名单内，跳过；文档/结构化库参与校验。
    assert workflows_mod.bound_kb_ids(WF, flow_service=_Service()) == (
        'uuid-a', 'uuid-c')


# ---------------------------------------------------------------------------
# MCP run_workflow 共用的执行函数（agent.query.execute）
# ---------------------------------------------------------------------------

def _payload(**overrides):
    values = {'question': '如何配置检索编排？', 'conversation_id': 'c-1',
              'workflow_id': WF}
    values.update(overrides)
    return WorkflowQueryRequest(**values)


def _sse_response(*events):
    def _gen():
        for event, payload in events:
            yield ServerSentEvent(event=event, data=json.dumps(payload))
    return EventSourceResponse(_gen())


def test_execute_uses_engine_request_and_runs_background(monkeypatch):
    captured = {}
    background = []

    def _fake_run_query(rag_request, request, *, surface='native'):
        captured.update(rag=rag_request, request=request, surface=surface)
        return JSONResponse(
            {'conversation_id': rag_request.conversation_id, 'answer': 'ok'},
            background=BackgroundTask(lambda: background.append(True)))

    monkeypatch.setattr(app_module, 'run_query', _fake_run_query)

    result = asyncio.run(query_mod.execute(
        PRINCIPAL, _payload(), headers=Headers({
            'authorization': 'Bearer ragk_x',
            'accept': 'application/json, text/event-stream',
            'language-option': 'en'}), trace_id='trace-9'))

    assert result == {'conversation_id': 'c-1', 'answer': 'ok'}
    assert captured['surface'] == 'agent'
    assert captured['rag'].question == '如何配置检索编排？'
    # MCP 客户端总是带 text/event-stream；stream=false 时必须改写成 JSON
    assert captured['request'].headers.get('accept') == 'application/json'
    assert captured['request'].headers.get('language-option') == 'en'
    assert captured['request'].url.path == AGENT_PREFIX + '/query'
    assert captured['request'].state.trace_id == 'trace-9'
    assert background == [True]


def test_execute_maps_problem_json_to_agent_error(monkeypatch):
    monkeypatch.setattr(app_module, 'run_query', lambda *args, **kwargs: JSONResponse(
        {'type': 'urn:ragstudio:problem:published_workflow_not_found',
         'title': 'Published workflow not found', 'status': 404,
         'detail': 'Workflow is not published', 'code': 'published_workflow_not_found'},
        status_code=404, media_type='application/problem+json'))

    with pytest.raises(AgentApiError) as info:
        asyncio.run(query_mod.execute(PRINCIPAL, _payload(), headers=Headers(),
                                      trace_id='t'))

    assert info.value.http_status == 404
    assert info.value.code == 'published_workflow_not_found'
    assert info.value.message == 'Workflow is not published'


def test_execute_consumes_sse_and_reports_progress(monkeypatch):
    progress = []

    async def _on_progress(delta, answer_len):
        progress.append((delta, answer_len))

    monkeypatch.setattr(app_module, 'run_query', lambda *args, **kwargs: _sse_response(
        ('retrieval', {'conversation_id': 'c-2',
                       'evidence': {'query': 'q', 'items': []}}),
        ('token', {'conversation_id': 'c-2', 'content': '你'}),
        ('token', {'conversation_id': 'c-2', 'content': '好'}),
        ('done', {'conversation_id': 'c-2', 'finish_reason': 'stop'})))

    result = asyncio.run(query_mod.execute(
        PRINCIPAL, _payload(conversation_id='c-2', stream=True, include_retrieval=True),
        headers=Headers(), trace_id='t', on_progress=_on_progress))

    assert result == {'conversation_id': 'c-2', 'answer': '你好',
                      'retrieval': {'query': 'q', 'items': []}}
    # 节流窗口可能把两个 token 合到一次通知；无论怎么切，内容不能丢、长度要递增
    assert ''.join(delta for delta, _ in progress) == '你好'
    assert progress[-1][1] == 2


def test_execute_raises_on_sse_error_event(monkeypatch):
    monkeypatch.setattr(app_module, 'run_query', lambda *args, **kwargs: _sse_response(
        ('error', {'status': 502, 'code': 'answer_failed', 'detail': 'boom'})))

    with pytest.raises(AgentApiError) as info:
        asyncio.run(query_mod.execute(PRINCIPAL, _payload(stream=True),
                                      headers=Headers(), trace_id='t'))

    assert (info.value.http_status, info.value.code) == (502, 'answer_failed')


def test_execute_requires_workflow_run_scope(monkeypatch):
    called = []
    monkeypatch.setattr(app_module, 'run_query',
                        lambda *args, **kwargs: called.append(True))
    principal = AgentPrincipal('ragk_test', 'demo',
                               frozenset({'workflow:read'}), (), 60)

    with pytest.raises(AgentApiError) as info:
        asyncio.run(query_mod.execute(principal, _payload(), headers=Headers(),
                                      trace_id='t'))

    assert info.value.code == 'forbidden_scope'
    assert called == []
