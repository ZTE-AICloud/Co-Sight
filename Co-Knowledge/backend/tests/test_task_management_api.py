"""统一任务管理 HTTP 面：参数透传、响应形状与错误映射。"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from infrastructure.http.pagination import page as paginate
from infrastructure.tasks import api as task_api
from infrastructure.tasks import management
from shared.errors.api import KbConflictError, KbNotFoundError
from shared.prefixes import RKB_PREFIX


@pytest.fixture()
def client():
    app = FastAPI()
    task_api.register_task_api(app, RKB_PREFIX)
    return TestClient(app)


def _task():
    return {'id': 't1', 'taskType': 'FILE_IMPORT', 'status': 'PENDING'}


def test_list_passes_filters_and_pagination(client, monkeypatch):
    seen = {}

    def fake_list(**kwargs):
        seen.update(kwargs)
        return paginate([_task()], 1, kwargs['page'], kwargs['size'])

    monkeypatch.setattr(management, 'list_tasks', fake_list)
    response = client.get(
        f'{RKB_PREFIX}/tasks',
        params={'task_type': 'FILE_IMPORT', 'status': 'PENDING,RUNNING',
                'lane': 'file_import', 'kbase_id': 'kb1', 'keyword': 'task-1',
                'page': 2, 'size': 5})

    assert response.status_code == 200
    assert response.json()['items'] == [_task()]
    assert response.json()['pageSize'] == 5
    assert seen == {
        'task_type': 'FILE_IMPORT', 'status': 'PENDING,RUNNING',
        'lane': 'file_import', 'kbase_id': 'kb1', 'keyword': 'task-1',
        'page': 2, 'size': 5,
    }


def test_groups_passes_filters(client, monkeypatch):
    seen = {}

    def fake_groups(**kwargs):
        seen.update(kwargs)
        return paginate([{'kbaseId': 'kb1', 'total': 2}], 1,
                        kwargs['page'], kwargs['size'])

    monkeypatch.setattr(management, 'list_task_groups', fake_groups)
    response = client.get(
        f'{RKB_PREFIX}/tasks/groups',
        params={'task_type': 'FILE_IMPORT', 'status': 'FAILED',
                'keyword': 'demo', 'page': 1, 'size': 10})

    assert response.status_code == 200
    assert response.json()['items'][0]['kbaseId'] == 'kb1'
    assert seen == {
        'task_type': 'FILE_IMPORT', 'status': 'FAILED', 'lane': None,
        'kbase_id': None, 'keyword': 'demo', 'page': 1, 'size': 10,
    }


def test_stats_and_detail(client, monkeypatch):
    monkeypatch.setattr(management, 'stats', lambda: {'total': 1})
    monkeypatch.setattr(management, 'get_task', lambda task_id: {'id': task_id})

    stats = client.get(f'{RKB_PREFIX}/tasks/stats')
    detail = client.get(f'{RKB_PREFIX}/tasks/t1')

    assert stats.status_code == 200
    assert stats.json() == {'total': 1}
    assert detail.status_code == 200
    assert detail.json() == {'id': 't1'}


def test_cancel_accepts_optional_reason(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(management, 'cancel_task',
                        lambda task_id, reason: seen.update(
                            task_id=task_id, reason=reason) or {'id': task_id})

    no_body = client.post(f'{RKB_PREFIX}/tasks/t1/cancel')
    with_body = client.post(f'{RKB_PREFIX}/tasks/t2/cancel',
                            json={'reason': 'duplicate upload'})

    assert no_body.status_code == 200
    assert with_body.status_code == 200
    assert seen == {'task_id': 't2', 'reason': 'duplicate upload'}


def test_retry_and_priority(client, monkeypatch):
    monkeypatch.setattr(management, 'retry_task', lambda task_id: {'id': task_id})
    seen = {}
    monkeypatch.setattr(management, 'set_priority',
                        lambda task_id, priority: seen.update(
                            task_id=task_id, priority=priority) or {'id': task_id})

    retry = client.post(f'{RKB_PREFIX}/tasks/t1/retry')
    patch = client.patch(f'{RKB_PREFIX}/tasks/t2', json={'priority': 5})

    assert retry.status_code == 200
    assert patch.status_code == 200
    assert seen == {'task_id': 't2', 'priority': 5}


def test_not_found_and_conflict_are_problem_json(client, monkeypatch):
    def missing(task_id):
        raise KbNotFoundError(None, problem_code='task_not_found')

    def conflict(task_id):
        raise KbConflictError(None, problem_code='task_not_cancellable')

    monkeypatch.setattr(management, 'get_task', missing)
    monkeypatch.setattr(management, 'cancel_task', lambda task_id, reason: conflict(task_id))

    not_found = client.get(f'{RKB_PREFIX}/tasks/nope')
    conflict_response = client.post(f'{RKB_PREFIX}/tasks/t1/cancel')

    assert not_found.status_code == 404
    assert not_found.headers['content-type'].startswith('application/problem+json')
    assert not_found.json()['code'] == 'task_not_found'
    assert conflict_response.status_code == 409
    assert conflict_response.json()['code'] == 'task_not_cancellable'
