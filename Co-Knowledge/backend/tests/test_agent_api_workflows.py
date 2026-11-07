"""Agent 工作流查询接口的单测（只读；不连 DB/网络）。

工作流的创建/编排/发布在控制台完成，Agent API 只保留 ``GET /agent/workflows``。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent import rest as rest_mod
from agent import service as service_mod
from agent import workflows as workflows_mod
from agent.auth import AgentContext, AgentPrincipal, agent_context
from agent.errors import AgentApiError
from workflow.models import FlowDraft, WorkflowRecord
from workflow.repository import InMemoryFlowStore
from workflow.runtime_config import RuntimeCapabilities
from workflow.service import FlowService

PRINCIPAL = AgentPrincipal('ragk_test', 'demo',
                           frozenset({'workflow:read'}), (), 60)


def _flow_service():
    return FlowService(InMemoryFlowStore(), capabilities=RuntimeCapabilities())


def test_list_publish_type_filter_uses_store():
    store = InMemoryFlowStore()
    for workflow_id, publish_type, updated_at in (
            ('wf-pub', 1, '2026-01-02 00:00:00'),
            ('wf-draft', 0, '2026-01-01 00:00:00')):
        store.create_workflow_with_draft(
            WorkflowRecord(workflow_id=workflow_id, name=workflow_id,
                           publish_type=publish_type, updated_at=updated_at),
            FlowDraft(workflow_id=workflow_id))
    flow_service = FlowService(store, capabilities=RuntimeCapabilities())

    published = workflows_mod.list_workflows(1, 10, None, 1, flow_service=flow_service)
    everything = workflows_mod.list_workflows(1, 10, None, None, flow_service=flow_service)

    assert [item['workFlowId'] for item in published['items']] == ['wf-pub']
    assert published['total'] == 1
    assert everything['total'] == 2


def test_list_requires_workflow_read_scope():
    principal = AgentPrincipal('ragk_test', 'demo', frozenset({'kb:list'}), (), 60)

    with pytest.raises(AgentApiError) as exc:
        service_mod.list_workflows(principal, 1, 10, None, None, 'trace-1')

    assert exc.value.http_status == 403
    assert exc.value.code == 'forbidden_scope'
    assert (exc.value.details or {}).get('required_scope') == 'workflow:read'


def _workflow_vo(**overrides):
    data = {
        'workFlowId': 'RAG_Workflow_x', 'name': 'demo', 'description': None,
        'template': 'Sequential', 'knowledgeType': 'knowledgeBase',
        'publishType': 1, 'status': 1, 'createdBy': 'admin',
        'createdDate': '2026-01-01 00:00:00', 'lastUpdatedDate': '2026-01-01 00:00:00',
        'kbPkIds': [], 'graphKbPkIds': [],
    }
    data.update(overrides)
    return data


def _rest_app(monkeypatch, principal=PRINCIPAL, captured=None):
    captured = captured if captured is not None else {}

    def list_workflows(p, page, size, keyword, publish_type, trace, surface='rest'):
        captured.update(page=page, size=size, keyword=keyword,
                        publish_type=publish_type, trace=trace)
        return {'items': [_workflow_vo()], 'total': 1, 'page': page, 'pageSize': size}

    monkeypatch.setattr(rest_mod.service, 'list_workflows', list_workflows)
    app = rest_mod.build_rest_app()
    app.dependency_overrides[agent_context] = lambda: AgentContext(principal, 'trace-1')
    return app


def test_rest_list_forwards_publish_type(monkeypatch):
    captured = {}
    with TestClient(_rest_app(monkeypatch, captured=captured)) as client:
        response = client.get('/workflows?page=2&size=50&publishType=1&keyword=demo')

    assert response.status_code == 200
    assert response.headers['X-Request-Id'] == 'trace-1'
    assert response.json()['items'][0]['workFlowId'] == 'RAG_Workflow_x'
    assert captured == {'page': 2, 'size': 50, 'keyword': 'demo',
                        'publish_type': 1, 'trace': 'trace-1'}


def test_rest_workflow_validation_errors(monkeypatch):
    with TestClient(_rest_app(monkeypatch)) as client:
        response = client.get('/workflows?publishType=9')

    assert response.status_code == 422
    assert response.headers['content-type'].startswith('application/problem+json')
    assert response.json()['code'] == 'validation_failed'


def test_rest_workflow_openapi_is_get_only(monkeypatch):
    schema = _rest_app(monkeypatch).openapi()
    workflow_path = schema['paths']['/workflows']
    assert set(workflow_path) == {'get'}
    assert workflow_path['get']['parameters']
