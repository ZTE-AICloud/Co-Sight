"""`/query-traces` 三条只读路由的契约（不连 DB）。"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from chat import trace_service
from chat.trace_api import router
from chat.trace_errors import QueryTraceStoreUnavailable

PREFIX = '/api/test'


def _client():
    app = FastAPI()
    app.include_router(router, prefix=PREFIX)
    return TestClient(app)


def _item(row_id=1):
    return {
        'id': row_id,
        'traceId': 'trace-1',
        'conversationId': 'dlg-1',
        'workflowId': 'wf-1',
        'orgId': '',
        'isStream': True,
        'status': 'ok',
        'errorCode': '',
        'httpStatus': 200,
        'errorStatus': None,
        'questionLen': 3,
        'answerLen': 8,
        'understandingMs': 12.3,
        'retrievalMs': 20.0,
        'rerankMs': 30.0,
        'generateMs': 40.0,
        'firstTokenMs': 50.0,
        'totalMs': 60.0,
        'hitCount': 5,
        'sourceCount': 3,
        'kbCount': 1,
        'topScore': 6.0,
        'createdAt': datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc),
    }


def _stage(count=1):
    return {'count': count, 'p50': 1.0, 'p95': 2.0, 'p99': 3.0}


def _summary():
    return {
        'count': 2, 'okCount': 2, 'errorCount': 0, 'clientDisconnectCount': 0,
        'hitRate': 0.5, 'avgHitCount': 3.5, 'avgSourceCount': 2.0,
        'understanding': _stage(), 'retrieval': _stage(), 'rerank': _stage(),
        'generate': _stage(), 'firstToken': _stage(), 'total': _stage(),
    }


def test_list_passes_filters_aliases_and_paginates(monkeypatch):
    captured = {}

    def fake_list(**kwargs):
        captured.update(kwargs)
        return [_item(2), _item(1)], 2

    monkeypatch.setattr(trace_service, 'list_traces', fake_list)

    response = _client().get(
        f'{PREFIX}/query-traces',
        params={
            'workflowId': 'wf-1', 'conversationId': 'dlg-1', 'traceId': 'trace-1',
            'orgId': 'org-1', 'status': 'ok', 'from': '2026-10-25',
            'to': '2026-10-26', 'page': 2, 'size': 10,
        })

    assert response.status_code == 200
    body = response.json()
    assert body['total'] == 2 and body['page'] == 2 and body['pageSize'] == 10
    assert [item['id'] for item in body['items']] == [2, 1]
    assert captured['workflow_id'] == 'wf-1'
    assert captured['from_value'] == '2026-10-25'
    assert captured['to_value'] == '2026-10-26'
    assert captured['page'] == 2 and captured['size'] == 10


def test_stats_route_is_not_shadowed_by_detail(monkeypatch):
    captured = {}

    def fake_stats(**kwargs):
        captured.update(kwargs)
        series_item = dict(_summary(), bucket=datetime(2026, 10, 25, tzinfo=timezone.utc))
        return {'summary': _summary(), 'series': [series_item]}

    monkeypatch.setattr(trace_service, 'stats', fake_stats)

    response = _client().get(
        f'{PREFIX}/query-traces/stats',
        params={'workflowId': 'wf-1', 'bucket': 'day'})

    assert response.status_code == 200
    body = response.json()
    assert body['summary']['count'] == 2
    assert body['series'][0]['bucket'].startswith('2026-10-25')
    assert captured == {'workflow_id': 'wf-1', 'org_id': None, 'from_value': None,
                        'to_value': None, 'bucket': 'day'}


def test_detail_returns_item_and_404_problem(monkeypatch):
    monkeypatch.setattr(trace_service, 'get_trace', lambda row_id: _item(row_id))
    response = _client().get(f'{PREFIX}/query-traces/7')
    assert response.status_code == 200
    assert response.json()['id'] == 7

    monkeypatch.setattr(trace_service, 'get_trace', lambda row_id: None)
    missing = _client().get(f'{PREFIX}/query-traces/8')
    assert missing.status_code == 404
    assert missing.headers['content-type'].startswith('application/problem+json')
    assert missing.json()['code'] == 'query_trace_not_found'


def test_store_unavailable_maps_to_503(monkeypatch):
    def boom(**kwargs):
        raise QueryTraceStoreUnavailable('db down')

    monkeypatch.setattr(trace_service, 'list_traces', boom)
    response = _client().get(f'{PREFIX}/query-traces')
    assert response.status_code == 503
    assert response.headers['content-type'].startswith('application/problem+json')
    assert response.json()['code'] == 'query_trace_store_unavailable'


def test_semantic_validation_maps_to_422_problem(monkeypatch):
    def boom(**kwargs):
        raise trace_service.TraceQueryError('from must be earlier')

    monkeypatch.setattr(trace_service, 'stats', boom)
    response = _client().get(
        f'{PREFIX}/query-traces/stats',
        params={'from': '2026-10-26', 'to': '2026-10-25'})
    assert response.status_code == 422
    assert response.headers['content-type'].startswith('application/problem+json')
    assert response.json()['code'] == 'validation_failed'


def test_path_and_query_enums_are_validated(monkeypatch):
    monkeypatch.setattr(trace_service, 'list_traces', lambda **kwargs: ([], 0))
    assert _client().get(f'{PREFIX}/query-traces/not-an-int').status_code == 422
    assert _client().get(
        f'{PREFIX}/query-traces', params={'status': 'weird'}).status_code == 422
    assert _client().get(
        f'{PREFIX}/query-traces', params={'size': 0}).status_code == 422
