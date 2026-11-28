"""Text2SQL 接口层契约：路径、状态码、problem+json 与响应字段。

业务实现用假 service 注入 —— 这里只钉路由/装配，校验与扫描由 service/models
的用例覆盖。
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from text_to_sql import register_text_to_sql_api, TEXT2SQL_PREFIX
from text_to_sql.errors import Text2SqlNotFound, Text2SqlValidationError

BASE = TEXT2SQL_PREFIX


def _datasource():
    return {
        'id': '11111111-1111-1111-1111-111111111111',
        'name': '电商业务库', 'type': 'PostgreSQL', 'dbType': 'postgresql',
        'host': 'localhost', 'port': 5432, 'database': 'commerce_demo',
        'schema': 'public', 'includeSchemas': ['public'],
        'username': 'demo_readonly', 'passwordConfigured': True,
        'status': 'scanned', 'enabled': True, 'revision': 1,
        'scannedAt': '2026-11-11 10:00:00', 'indexedAt': None,
        'connectionTestedAt': None, 'lastSyncAt': '2026-11-11 10:00:00',
        'activeVersionId': None, 'requiresPublication': True,
        'topic': {'name': '', 'description': '', 'owner': ''},
        'businessDescription': '', 'businessTimezone': 'UTC',
        'queryPolicy': {'read_only': True, 'max_rows': 1000, 'timeout_ms': 30000},
        'selectedTables': ['public.order_info'],
        'createdAt': '2026-11-11 09:00:00', 'updatedAt': '2026-11-11 10:00:00',
    }


class FakeService:
    def list_datasources(self):
        return {'items': [_datasource()], 'total': 1}

    def get_datasource(self, datasource_id):
        if datasource_id == 'missing':
            raise Text2SqlNotFound('数据源不存在或已删除')
        return _datasource()

    def create_datasource(self, payload):
        if not payload.get('host'):
            raise Text2SqlValidationError('host 不能为空')
        return _datasource()

    def update_datasource(self, datasource_id, payload):
        return _datasource()

    def delete_datasource(self, datasource_id):
        return None

    def test_connection(self, datasource_id):
        return {'ok': True, 'latencyMs': 12, 'testedAt': '2026-11-11 10:01:00',
                'datasource': _datasource()}

    def test_connection_payload(self, payload):
        return {'ok': True, 'latencyMs': 10}

    def scan(self, datasource_id):
        return {'datasource': _datasource(),
                'summary': {'tablesAdded': 1}, 'revisionChanged': False}

    def list_tables(self, datasource_id):
        return {'items': [{'id': 't1', 'fullName': 'public.order_info',
                           'columns': []}], 'total': 1}

    def update_table(self, datasource_id, table_id, payload):
        return {'id': table_id, 'fullName': 'public.order_info'}

    def update_column(self, datasource_id, column_id, payload):
        if payload.get('semanticType') == 'bad':
            raise Text2SqlValidationError('semanticType 不合法')
        return {'id': column_id, 'semanticType': payload.get('semanticType')}


@pytest.fixture()
def client():
    app = FastAPI()
    register_text_to_sql_api(app, service=FakeService())
    return TestClient(app)


def test_list_and_get_datasource(client):
    listed = client.get(f'{BASE}/datasources')
    assert listed.status_code == 200
    body = listed.json()
    assert body['total'] == 1
    assert body['items'][0]['passwordConfigured'] is True
    assert 'credential_ref' not in body['items'][0]

    got = client.get(f'{BASE}/datasources/abc')
    assert got.status_code == 200
    assert got.json()['status'] == 'scanned'


def test_get_missing_datasource_is_problem_json(client):
    response = client.get(f'{BASE}/datasources/missing')
    assert response.status_code == 404
    assert response.headers['content-type'].startswith('application/problem+json')
    assert response.json()['status'] == 404


def test_create_returns_201_and_location(client):
    response = client.post(f'{BASE}/datasources', json={'name': '新库', 'host': 'h'})
    assert response.status_code == 201
    assert response.headers['location'].endswith(
        '/datasources/11111111-1111-1111-1111-111111111111')


def test_create_validation_error_is_422(client):
    response = client.post(f'{BASE}/datasources', json={'name': '新库'})
    assert response.status_code == 422
    assert response.headers['content-type'].startswith('application/problem+json')


def test_delete_returns_204(client):
    response = client.delete(f'{BASE}/datasources/abc')
    assert response.status_code == 204
    assert response.content == b''


def test_table_and_column_patch(client):
    table = client.patch(f'{BASE}/datasources/ds/tables/t1',
                         json={'enabled': True})
    assert table.status_code == 200
    assert table.json()['id'] == 't1'

    column = client.patch(f'{BASE}/datasources/ds/columns/c1',
                          json={'semanticType': 'measure'})
    assert column.status_code == 200
    assert column.json()['semanticType'] == 'measure'

    rejected = client.patch(f'{BASE}/datasources/ds/columns/c1',
                            json={'semanticType': 'bad'})
    assert rejected.status_code == 422


def test_scan_and_connection_test_paths(client):
    scan = client.post(f'{BASE}/datasources/ds/scan')
    assert scan.status_code == 200
    assert scan.json()['summary']['tablesAdded'] == 1

    tested = client.post(f'{BASE}/datasources/ds/connection-test')
    assert tested.status_code == 200
    assert tested.json()['ok'] is True


# ---------------------------------------------------------------------------
# 关联 / 枚举 / 指标 / 版本
# ---------------------------------------------------------------------------

class CatalogService(FakeService):
    def list_relations(self, datasource_id):
        return {'items': [{'id': 'rel-1', 'name': 'r'}], 'total': 1}

    def create_relation(self, datasource_id, payload):
        return {'id': 'rel-1', 'name': 'r'}

    def update_relation(self, datasource_id, relation_id, payload):
        return {'id': relation_id, 'name': 'r'}

    def delete_relation(self, datasource_id, relation_id):
        return None

    def verify_relation(self, datasource_id, relation_id, payload, actor):
        return {'id': relation_id, 'verified': True}

    def list_values(self, datasource_id, column_id=None):
        return {'items': [{'id': 'val-1'}], 'total': 1}

    def create_value(self, datasource_id, payload):
        return {'id': 'val-1'}

    def update_value(self, datasource_id, value_id, payload):
        return {'id': value_id}

    def delete_value(self, datasource_id, value_id):
        return None

    def list_metrics(self, datasource_id):
        return {'items': [{'id': 'met-1'}], 'total': 1}

    def create_metric(self, datasource_id, payload):
        return {'id': 'met-1'}

    def update_metric(self, datasource_id, metric_id, payload):
        return {'id': metric_id}

    def delete_metric(self, datasource_id, metric_id):
        return None

    def set_metric_status(self, datasource_id, metric_id, payload, actor):
        return {'id': metric_id, 'status': payload['status']}

    def create_version(self, datasource_id, payload, actor):
        return {'version_id': 'ver-1', 'status': 'BUILDING', 'revision': 1,
                'created': payload.get('_created', True), 'version': {}}

    def list_versions(self, datasource_id):
        return {'items': [], 'total': 0}

    def get_version(self, datasource_id, version_id):
        return {'id': version_id}

    def start_build(self, datasource_id, version_id):
        return {'status': 'QUEUED', 'taskId': 'task-1', 'queued': True,
                'version': {'id': version_id, 'status': 'BUILDING'}}

    def publish(self, datasource_id, payload, actor):
        return {'id': 'pub-1', 'versionId': payload['versionId']}

    def list_publications(self, datasource_id):
        return {'items': [], 'total': 0}


@pytest.fixture()
def catalog_client():
    app = FastAPI()
    register_text_to_sql_api(app, service=CatalogService())
    return TestClient(app)


def test_relation_routes(catalog_client):
    assert catalog_client.get(f'{BASE}/datasources/ds/relations').status_code == 200
    created = catalog_client.post(f'{BASE}/datasources/ds/relations', json={'name': 'r'})
    assert created.status_code == 201
    assert catalog_client.patch(f'{BASE}/datasources/ds/relations/rel-1',
                                json={'enabled': False}).status_code == 200
    assert catalog_client.delete(f'{BASE}/datasources/ds/relations/rel-1').status_code == 204
    verified = catalog_client.post(f'{BASE}/datasources/ds/relations/rel-1/verification',
                                   json={'verified': True})
    assert verified.status_code == 200
    assert verified.json()['verified'] is True


def test_value_routes(catalog_client):
    assert catalog_client.get(f'{BASE}/datasources/ds/values?columnId=c1').status_code == 200
    assert catalog_client.post(f'{BASE}/datasources/ds/values',
                               json={'columnId': 'c1', 'rawValue': '2'}).status_code == 201
    assert catalog_client.patch(f'{BASE}/datasources/ds/values/val-1',
                                json={'enabled': False}).status_code == 200
    assert catalog_client.delete(f'{BASE}/datasources/ds/values/val-1').status_code == 204


def test_metric_routes(catalog_client):
    assert catalog_client.get(f'{BASE}/datasources/ds/metrics').status_code == 200
    assert catalog_client.post(f'{BASE}/datasources/ds/metrics',
                               json={'key': 'k'}).status_code == 201
    assert catalog_client.patch(f'{BASE}/datasources/ds/metrics/met-1',
                                json={'unit': '元'}).status_code == 200
    approved = catalog_client.post(f'{BASE}/datasources/ds/metrics/met-1/status',
                                   json={'status': 'APPROVED'})
    assert approved.status_code == 200
    assert approved.json()['status'] == 'APPROVED'
    assert catalog_client.delete(f'{BASE}/datasources/ds/metrics/met-1').status_code == 204


def test_version_and_publication_routes(catalog_client):
    created = catalog_client.post(f'{BASE}/datasources/ds/versions', json={})
    assert created.status_code == 201
    assert created.json()['version_id'] == 'ver-1'
    assert catalog_client.get(f'{BASE}/datasources/ds/versions').status_code == 200
    assert catalog_client.get(f'{BASE}/datasources/ds/versions/ver-1').status_code == 200
    built = catalog_client.post(f'{BASE}/datasources/ds/versions/ver-1/build')
    assert built.status_code == 200
    assert built.json()['status'] == 'QUEUED'
    assert built.json()['taskId'] == 'task-1'
    published = catalog_client.post(f'{BASE}/datasources/ds/publication',
                                    json={'versionId': 'ver-1', 'expectedRevision': 1})
    assert published.status_code == 201
    assert published.json()['versionId'] == 'ver-1'
    assert catalog_client.get(f'{BASE}/datasources/ds/publications').status_code == 200


class FakeQueryService:
    def run_query(self, datasource_id, payload, actor, *, on_stage=None):
        if on_stage is not None:
            on_stage('tables', 'running')
            on_stage('tables', 'success', 12)
        return {'id': 'run-1', 'request_id': 'req-1', 'question': payload['question'],
                'result': {'columns': ['n'], 'rows': [[1]], 'row_count': 1,
                           'truncated': False}, 'error': None}

    def list_runs(self, actor, **kwargs):
        return {'items': [{'id': 'run-1', 'request_id': 'req-1'}], 'total': 1,
                'page': 1, 'pageSize': 20}

    def get_run(self, run_id, actor):
        return {'id': run_id, 'request_id': 'req-1'}

    def delete_run(self, run_id, actor):
        return None

    def clear_runs(self, actor, datasource_id=None):
        return None

    def create_feedback(self, run_id, payload, actor):
        return {'id': 'fb-1', 'runId': run_id, 'category': payload['category']}

    def list_feedback(self, datasource_id):
        return {'items': [{'id': 'fb-1'}], 'total': 1}

    def list_favorites(self, actor):
        return {'items': [{'id': 'fav-1'}], 'total': 1}

    def create_favorite(self, payload, actor):
        return {'id': 'fav-1', 'name': payload['name']}

    def update_favorite(self, favorite_id, payload, actor):
        return {'id': favorite_id, **payload}

    def delete_favorite(self, favorite_id, actor):
        return None

    def get_workspace(self, actor):
        return {'questionDraft': ''}

    def save_workspace(self, payload, actor):
        return payload


@pytest.fixture(autouse=True)
def _reset_sse_app_status():
    """sse-starlette 的退出信号是模块级全局量，跨事件循环残留会让下个用例报错。"""
    from sse_starlette.sse import AppStatus

    AppStatus.should_exit_event = None
    yield


@pytest.fixture()
def query_client():
    from text_to_sql.api import build_router

    app = FastAPI()
    app.include_router(build_router(FakeService(), query_service=FakeQueryService()),
                       prefix=BASE)
    return TestClient(app)


def test_query_and_history_routes(query_client):
    created = query_client.post(f'{BASE}/datasources/ds/query',
                                json={'question': '有多少订单？'})
    assert created.status_code == 200
    assert created.json()['request_id'] == 'req-1'
    assert query_client.get(f'{BASE}/runs?size=20').json()['total'] == 1
    assert query_client.get(f'{BASE}/runs/run-1').json()['id'] == 'run-1'
    assert query_client.delete(f'{BASE}/runs/run-1').status_code == 204
    assert query_client.delete(f'{BASE}/runs?datasourceId=ds-1').status_code == 204


def test_query_stream_emits_stage_result_and_done(query_client):
    with query_client.stream('POST', f'{BASE}/datasources/ds/query/stream',
                             json={'question': '有多少订单？'}) as response:
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('text/event-stream')
        body = ''.join(response.iter_text())

    events = [line.removeprefix('event: ') for line in body.splitlines()
              if line.startswith('event: ')]
    assert events == ['stage', 'stage', 'result', 'done']
    stage = next(json.loads(line.removeprefix('data: '))
                 for line in body.splitlines()
                 if line.startswith('data: ') and '"tables"' in line)
    assert stage == {'id': 'tables', 'status': 'running', 'ms': None}
    payload = next(json.loads(line.removeprefix('data: '))
                   for line in body.splitlines()
                   if line.startswith('data: ') and '"request_id"' in line)
    assert payload['request_id'] == 'req-1'
    assert payload['result']['rows'] == [[1]]


class FailingQueryService(FakeQueryService):
    def run_query(self, datasource_id, payload, actor, *, on_stage=None):
        raise Text2SqlNotFound('数据源不存在或已删除')


@pytest.fixture()
def failing_query_client():
    from text_to_sql.api import build_router

    app = FastAPI()
    app.include_router(
        build_router(FakeService(), query_service=FailingQueryService()),
        prefix=BASE)
    return TestClient(app)


def test_query_stream_reports_mid_stream_failure_as_error_event(failing_query_client):
    with failing_query_client.stream(
            'POST', f'{BASE}/datasources/ds/query/stream',
            json={'question': 'q'}) as response:
        # HTTP 状态已经发出（200），失败只能进终态 error 帧
        assert response.status_code == 200
        body = ''.join(response.iter_text())

    events = [line.removeprefix('event: ') for line in body.splitlines()
              if line.startswith('event: ')]
    assert events == ['error']
    problem = json.loads(next(line.removeprefix('data: ')
                              for line in body.splitlines()
                              if line.startswith('data: ')))
    assert problem['status'] == 404
    assert problem['code'] == 'text2sql.not_found'
    assert problem['detail'] == '数据源不存在或已删除'


def test_query_stream_rejects_malformed_body_before_streaming(query_client):
    response = query_client.post(
        f'{BASE}/datasources/ds/query/stream', content=b'{',
        headers={'Content-Type': 'application/json'})
    assert response.status_code == 400
    assert response.headers['content-type'].startswith('application/problem+json')


def test_feedback_and_favorites_routes(query_client):
    feedback = query_client.post(f'{BASE}/runs/run-1/feedback',
                                 json={'category': 'meaning', 'notes': '口径不对'})
    assert feedback.status_code == 201
    assert feedback.json()['runId'] == 'run-1'
    assert query_client.get(f'{BASE}/feedback?datasourceId=ds-1').status_code == 200

    favorite = query_client.post(f'{BASE}/favorites',
                                 json={'name': '常用', 'question': 'q',
                                       'datePolicy': 'relative'})
    assert favorite.status_code == 201
    assert query_client.get(f'{BASE}/favorites').status_code == 200
    assert query_client.patch(f'{BASE}/favorites/fav-1',
                              json={'notes': 'x'}).status_code == 200
    assert query_client.delete(f'{BASE}/favorites/fav-1').status_code == 204


def test_workspace_and_payload_connection_test(query_client):
    assert query_client.get(f'{BASE}/workspace').status_code == 200
    saved = query_client.put(f'{BASE}/workspace', json={'questionDraft': '草稿'})
    assert saved.status_code == 200
    assert saved.json()['questionDraft'] == '草稿'
    tested = query_client.post(f'{BASE}/datasources/connection-test',
                               json={'host': 'db'})
    assert tested.status_code == 200
    assert tested.json()['ok'] is True


# ----------------------------------------------------------------------
# 数据源写操作授权
# ----------------------------------------------------------------------
def _client_with_role(role):
    from types import SimpleNamespace

    app = FastAPI()
    register_text_to_sql_api(app, service=FakeService())

    @app.middleware('http')
    async def _stamp(request, call_next):
        request.state.auth_user = SimpleNamespace(role=role)
        return await call_next(request)

    return TestClient(app)


def test_datasource_writes_require_admin():
    user = _client_with_role('user')
    payload = {'name': 'x', 'host': 'db', 'database': 'd', 'username': 'u',
               'password': 'p'}
    assert user.post(f'{BASE}/datasources', json=payload).status_code == 403
    assert user.patch(f'{BASE}/datasources/abc',
                      json={'name': 'y'}).status_code == 403
    assert user.delete(f'{BASE}/datasources/abc').status_code == 403
    assert user.post(f'{BASE}/datasources/connection-test',
                     json=payload).status_code == 403
    assert user.post(f'{BASE}/datasources/abc/connection-test').status_code == 403
    assert user.post(f'{BASE}/datasources/abc/scan').status_code == 403


def test_datasource_writes_allowed_for_admin():
    admin = _client_with_role('admin')
    payload = {'name': 'x', 'host': 'db', 'database': 'd', 'username': 'u',
               'password': 'p'}
    assert admin.post(f'{BASE}/datasources', json=payload).status_code == 201
    assert admin.post(f'{BASE}/datasources/abc/scan').status_code == 200
