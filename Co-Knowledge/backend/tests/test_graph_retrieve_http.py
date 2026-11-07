"""``POST /retrieval/graph`` 的 HTTP 契约（统一 REST + RFC 9457）。

图谱检索没有 ``{code,message,data}`` 信封：成功体就是结果对象，
失败是真实状态码 + ``application/problem+json``（含 FastAPI 的入参绑定失败）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import app as app_module
from graph.service.graph_retrieve_gateway import GraphRetrieveError
from shared.prefixes import GRAPH_RETRIEVE_PATH
from shared.problem import INTERNAL_ERROR

BODY = {'query': 'q', 'embedding': 'e', 'bases': ['graph_kb_1']}


def _client():
    return TestClient(app_module.app)


def test_success_returns_the_result_object(monkeypatch):
    result = {'base_results': [{'base': 'graph_kb_1'}], 'base_count': 1}
    monkeypatch.setattr(app_module, '_graph_retrieve_result',
                        lambda retrieve_dto, headers: result)

    response = _client().post(GRAPH_RETRIEVE_PATH, json=BODY)

    assert response.status_code == 200
    assert response.json() == result
    assert response.headers['X-Request-Id']


def test_failure_returns_problem_json(monkeypatch):
    def _raise(retrieve_dto, headers):
        raise GraphRetrieveError(INTERNAL_ERROR, 'graph down')

    monkeypatch.setattr(app_module, '_graph_retrieve_result', _raise)

    response = _client().post(GRAPH_RETRIEVE_PATH, json=BODY)

    assert response.status_code == 500
    assert response.headers['content-type'].startswith('application/problem+json')
    assert response.json()['code'] == 'internal_error'
    assert response.json()['detail'] == 'graph down'


def test_binding_failure_is_a_422_problem(monkeypatch):
    response = _client().post(GRAPH_RETRIEVE_PATH, json={'query': 'q'})

    assert response.status_code == 422
    assert response.headers['content-type'].startswith('application/problem+json')
    assert response.json()['code'] == 'validation_failed'
