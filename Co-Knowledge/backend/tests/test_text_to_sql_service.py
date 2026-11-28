"""Text2SQL 业务层：数据源生命周期、扫描编排与目录映射（无真实 DB）。"""

from __future__ import annotations

from uuid import UUID

import pytest

from text_to_sql import models
from text_to_sql.credentials import encrypt_password
from text_to_sql.errors import (Text2SqlNotFound, Text2SqlUpstreamError,
                             Text2SqlValidationError)
from text_to_sql.scanner import ScannedColumn, ScannedRelation, ScannedTable, ScanSnapshot
from text_to_sql.service import Text2SqlService

DS_ID = UUID('11111111-1111-1111-1111-111111111111')
TABLE_ID = UUID('33333333-3333-3333-3333-333333333333')
COLUMN_ID = UUID('22222222-2222-2222-2222-222222222222')


def _row(**overrides):
    row = {
        'id': DS_ID, 'name': '电商业务库', 'db_type': 'postgresql',
        'host': 'localhost', 'port': 5432, 'database_name': 'commerce_demo',
        'username': 'demo_readonly', 'credential_ref': encrypt_password('secret'),
        'include_schemas': ['public'], 'business_description': '',
        'topic_name': '', 'topic_description': '', 'maintainer_ref': '',
        'business_timezone': 'UTC', 'query_policy': dict(models.DEFAULT_QUERY_POLICY),
        'enabled': True, 'config_revision': 1, 'active_version_id': None,
        'active_revision': None, 'active_status': None, 'active_ready_at': None,
        'connection_tested_at': None, 'last_sync_at': None,
        'created_at': '2026-11-11 10:00:00', 'updated_at': '2026-11-11 10:00:00',
    }
    row.update(overrides)
    return row


class FakeRepo:
    def __init__(self, rows=None):
        self.rows = {str(row['id']): row for row in (rows or [])}
        self.tables = {}
        self.updated = None

    def list_datasources(self):
        return list(self.rows.values())

    def selected_tables_map(self):
        return {str(DS_ID): ['public.order_info']}

    def get_datasource(self, datasource_id):
        return self.rows.get(str(datasource_id))

    def selected_table_names(self, datasource_id):
        return ['public.order_info']

    def profiling_scope(self, datasource_id):
        return {('public', 'order_info', 'status')}

    def create_datasource(self, fields):
        assert fields['password'] == 'secret'
        row = _row(name=fields['name'])
        self.rows[str(row['id'])] = row
        return row

    def update_datasource(self, datasource_id, fields):
        row = self.rows.get(str(datasource_id))
        if row is None:
            return None
        self.updated = fields
        row = dict(row)
        if 'name' in fields:
            row['name'] = fields['name']
        if 'credential_ref' in fields:
            row['credential_ref'] = fields['credential_ref']
        return row

    def soft_delete_datasource(self, datasource_id):
        return self.rows.pop(str(datasource_id), None) is not None

    def datasource_connection(self, datasource_id):
        row = self.rows.get(str(datasource_id))
        if row is None:
            return None
        return {
            'id': row['id'], 'host': row['host'], 'port': row['port'],
            'database_name': row['database_name'], 'username': row['username'],
            'credential_ref': row['credential_ref'],
            'include_schemas': row['include_schemas'],
        }

    def mark_connection_tested(self, datasource_id):
        row = self.rows.get(str(datasource_id))
        if row is None:
            return None
        row = dict(row, connection_tested_at='2026-11-11 10:01:00')
        self.rows[str(datasource_id)] = row
        return row

    def apply_scan(self, datasource_id, snapshot):
        self.updated = snapshot
        return {'summary': {'tablesAdded': len(snapshot.tables)},
                'revisionChanged': False,
                'datasource': dict(self.rows[str(datasource_id)],
                                   last_sync_at='2026-11-11 10:02:00')}

    def list_tables(self, datasource_id):
        return list(self.tables.values())

    def get_table(self, datasource_id, table_id):
        return self.tables.get(str(table_id))

    def get_column(self, datasource_id, column_id):
        for table in self.tables.values():
            for column in table.get('columns', []):
                if str(column['id']) == str(column_id):
                    return column
        return None

    def update_table(self, datasource_id, table_id, fields):
        table = self.tables.get(str(table_id))
        if table is None:
            return None
        table = dict(table, **fields)
        self.tables[str(table_id)] = table
        return table

    def update_column(self, datasource_id, column_id, fields):
        for table in self.tables.values():
            for index, column in enumerate(table.get('columns', [])):
                if str(column['id']) == str(column_id):
                    updated = dict(column, **fields)
                    table['columns'][index] = updated
                    return updated
        return None


def _snapshot():
    return ScanSnapshot(
        tables=[ScannedTable(
            schema='public', name='order_info', table_type='BASE_TABLE',
            comment='订单', constraints=[],
            columns=[ScannedColumn(
                name='order_id', data_type='bigint', ordinal_position=1,
                nullable=False, default_value=None, primary_key=True,
                unique=True, comment=None)])],
        relations=[ScannedRelation(
            name='order_user', source=('public', 'order_info'),
            target=('public', 'order_info'), cardinality='MANY_TO_ONE',
            description='fk', column_pairs=[('order_id', 'order_id')])],
    )


@pytest.fixture(autouse=True)
def _secret_key(monkeypatch):
    monkeypatch.setenv('RKB_SECRET_KEY', 'unit-test-secret')
    from infrastructure.secrets import box
    box.reset_cache()
    yield
    box.reset_cache()


def test_list_and_get_datasource_map_selected_tables():
    service = Text2SqlService(FakeRepo([_row()]), scan_database=lambda *a, **k: None)

    listed = service.list_datasources()
    assert listed['total'] == 1
    assert listed['items'][0]['selectedTables'] == ['public.order_info']

    got = service.get_datasource(str(DS_ID))
    assert got['status'] == models.STATUS_CONFIGURED
    assert got['passwordConfigured'] is True


def test_create_and_update_never_expose_password():
    repo = FakeRepo([_row()])
    service = Text2SqlService(repo, scan_database=lambda *a, **k: None)

    created = service.create_datasource({
        'name': '新库', 'host': 'localhost', 'database': 'commerce_demo',
        'username': 'u', 'password': 'secret'})
    assert 'password' not in created
    assert created['passwordConfigured'] is True

    updated = service.update_datasource(str(DS_ID), {'name': '改名'})
    assert updated['name'] == '改名'
    assert 'credential_ref' not in updated and 'credentialRef' not in updated


def test_update_unknown_datasource_raises_not_found():
    service = Text2SqlService(FakeRepo([]), scan_database=lambda *a, **k: None)
    with pytest.raises(Text2SqlNotFound):
        service.update_datasource(str(DS_ID), {'name': 'x'})
    with pytest.raises(Text2SqlNotFound):
        service.get_datasource(str(DS_ID))


def test_invalid_uuid_is_rejected():
    service = Text2SqlService(FakeRepo([]), scan_database=lambda *a, **k: None)
    with pytest.raises(Text2SqlValidationError):
        service.get_datasource('not-a-uuid')


def test_scan_decrypts_password_and_returns_summary():
    repo = FakeRepo([_row()])
    captured = {}

    def fake_scan(connection, schemas, **kwargs):
        captured['connection'] = connection
        captured['schemas'] = schemas
        captured['profile_scope'] = kwargs.get('profile_scope')
        return _snapshot()

    service = Text2SqlService(repo, scan_database=fake_scan)
    result = service.scan(str(DS_ID))

    assert captured['connection']['password'] == 'secret'
    assert captured['schemas'] == ['public']
    # 只给已启用表上的已启用列收录取值
    assert captured['profile_scope'] == {('public', 'order_info', 'status')}
    assert result['summary']['tablesAdded'] == 1
    assert result['datasource']['lastSyncAt'] == '2026-11-11 10:02:00'


def test_scan_failure_is_upstream_error():
    repo = FakeRepo([_row()])

    def boom(connection, schemas, **kwargs):
        raise Text2SqlUpstreamError('外部数据库连接失败')

    service = Text2SqlService(repo, scan_database=boom)
    with pytest.raises(Text2SqlUpstreamError):
        service.scan(str(DS_ID))


def test_test_connection_marks_timestamp(monkeypatch):
    repo = FakeRepo([_row()])
    service = Text2SqlService(repo, scan_database=lambda *a, **k: None)

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql):
            self.sql = sql

        def fetchone(self):
            return (1,)

        def fetchall(self):
            return [('public',), ('kb_index',)]

    class _Conn:
        def cursor(self):
            return _Cursor()

        def close(self):
            self.closed = True

    import text_to_sql.service as service_module
    monkeypatch.setattr(service_module.psycopg2, 'connect', lambda **kwargs: _Conn())

    result = service.test_connection(str(DS_ID))
    assert result['ok'] is True
    assert result['testedAt'] == '2026-11-11 10:01:00'
    assert result['datasource']['connectionTestedAt'] == '2026-11-11 10:01:00'
    # 测试连接顺带返回账号可见的 schema，供表单多选
    assert result['schemas'] == ['public', 'kb_index']


def test_catalog_update_returns_mapped_dto():
    repo = FakeRepo([_row()])
    repo.tables = {str(TABLE_ID): {
        'id': TABLE_ID, 'schema_name': 'public', 'table_name': 'order_info',
        'table_type': 'BASE_TABLE', 'db_comment': '订单', 'business_name': None,
        'business_description': '订单主表', 'business_aliases': [], 'enabled': True,
        'schema_hash': 'a' * 64, 'missing_since': None,
        'last_seen_at': '2026-11-11 10:00:00',
        'columns': [{
            'id': COLUMN_ID, 'table_id': TABLE_ID, 'column_name': 'pay_amount',
            'data_type': 'numeric(12,2)', 'ordinal_position': 3,
            'is_nullable': True, 'default_value': None, 'is_primary_key': False,
            'is_unique': False, 'db_comment': None, 'business_name': None,
            'business_description': None, 'business_aliases': [],
            'semantic_type': None, 'enabled': True, 'missing_since': None,
        }],
    }}
    service = Text2SqlService(repo, scan_database=lambda *a, **k: None)

    table = service.update_table(str(DS_ID), str(TABLE_ID),
                                 {'enabled': True, 'businessDescription': '订单'})
    assert table['fullName'] == 'public.order_info'
    assert table['businessDescription'] == '订单'

    column = service.update_column(str(DS_ID), str(COLUMN_ID),
                                   {'semanticType': 'measure'})
    assert column['semanticType'] == 'measure'


def test_empty_update_returns_current_row():
    repo = FakeRepo([_row()])
    repo.tables = {str(TABLE_ID): {
        'id': TABLE_ID, 'schema_name': 'public', 'table_name': 'order_info',
        'table_type': 'BASE_TABLE', 'db_comment': None, 'business_name': None,
        'business_description': None, 'business_aliases': [], 'enabled': False,
        'schema_hash': None, 'missing_since': None, 'last_seen_at': None,
        'columns': [],
    }}
    service = Text2SqlService(repo, scan_database=lambda *a, **k: None)
    table = service.update_table(str(DS_ID), str(TABLE_ID), {})
    assert table['enabled'] is False


# ---------------------------------------------------------------------------
# 目录（关联 / 枚举 / 指标）与版本
# ---------------------------------------------------------------------------
REL_ID = UUID('55555555-5555-5555-5555-555555555555')
VALUE_ID = UUID('66666666-6666-6666-6666-666666666666')
METRIC_ID = UUID('77777777-7777-7777-7777-777777777777')
VERSION_ID = UUID('88888888-8888-8888-8888-888888888888')


def _relation_row(**overrides):
    row = {
        'id': REL_ID, 'datasource_id': DS_ID, 'source_table_id': TABLE_ID,
        'target_table_id': TABLE_ID, 'relation_name': 'order_user',
        'relation_type': 'MANUAL', 'cardinality': 'MANY_TO_ONE',
        'description': '订单 → 用户', 'enabled': True, 'verified': False,
        'verified_by': None, 'verified_at': None,
        'source_table': 'public.order_info', 'target_table': 'public.order_info',
        'column_pairs': [{'relation_id': REL_ID, 'ordinal_position': 1,
                          'source_column_id': COLUMN_ID,
                          'source_column_name': 'user_id',
                          'target_column_id': COLUMN_ID,
                          'target_column_name': 'user_id'}],
        'created_at': '2026-11-11 10:00:00', 'updated_at': '2026-11-11 10:00:00',
    }
    row.update(overrides)
    return row


class FakeCatalog:
    def __init__(self):
        self.created = None

    def list_relations(self, datasource_id):
        return [_relation_row()]

    def create_relation(self, datasource_id, fields):
        self.created = fields
        return str(REL_ID)

    def get_relation(self, datasource_id, relation_id):
        return _relation_row()

    def update_relation(self, datasource_id, relation_id, fields):
        return True

    def delete_relation(self, datasource_id, relation_id):
        return True

    def verify_relation(self, datasource_id, relation_id, actor, verified):
        return True

    def list_values(self, datasource_id, column_id=None):
        return [{'id': VALUE_ID, 'column_id': COLUMN_ID, 'raw_value': '2',
                 'value_type': 'smallint', 'business_name': '已支付',
                 'aliases': [], 'description': '', 'source_type': 'MANUAL',
                 'enabled': True, 'column_name': 'status',
                 'table_name': 'public.order_info',
                 'created_at': '2026-11-11 10:00:00',
                 'updated_at': '2026-11-11 10:00:00'}]

    def create_value(self, datasource_id, fields):
        self.created = fields
        return str(VALUE_ID)

    def get_value(self, datasource_id, value_id):
        return self.list_values(datasource_id)[0]

    def update_value(self, datasource_id, value_id, fields):
        return True

    def delete_value(self, datasource_id, value_id):
        return True

    def list_metrics(self, datasource_id):
        return [self._metric_row()]

    def create_metric(self, datasource_id, fields):
        self.created = fields
        return str(METRIC_ID)

    def get_metric(self, datasource_id, metric_id):
        return self._metric_row()

    def update_metric(self, datasource_id, metric_id, fields):
        return True

    def delete_metric(self, datasource_id, metric_id):
        return True

    def set_metric_status(self, datasource_id, metric_id, status, actor):
        return True

    def _metric_row(self):
        return {
            'id': METRIC_ID, 'datasource_id': DS_ID, 'base_table_id': TABLE_ID,
            'metric_key': 'paid_amount', 'business_name': '已支付订单金额',
            'business_description': '', 'aliases': [],
            'expression_sql': 'SUM(order_info.pay_amount)',
            'filter_definition': {'op': 'eq'},
            'time_column_id': COLUMN_ID, 'unit': '元',
            'business_timezone': 'Asia/Shanghai',
            'aggregation_behavior': 'ADDITIVE', 'attribution_description': '',
            'status': 'APPROVED', 'verified_by': 'admin',
            'verified_at': '2026-11-11 10:00:00',
            'base_table': 'public.order_info', 'time_column': 'create_time',
            'column_dependencies': [], 'relation_dependencies': [],
            'created_at': '2026-11-11 10:00:00',
            'updated_at': '2026-11-11 10:00:00',
        }


def test_relation_and_value_and_metric_dtos():
    catalog = FakeCatalog()
    service = Text2SqlService(FakeRepo([_row()]), scan_database=lambda *a, **k: None,
                              catalog=catalog)

    relations = service.list_relations(str(DS_ID))
    assert relations['total'] == 1
    assert relations['items'][0]['columnPairs'][0]['sourceColumn'] == 'user_id'

    created = service.create_relation(str(DS_ID), {
        'name': 'order_user',
        'sourceTableId': str(TABLE_ID), 'targetTableId': str(TABLE_ID),
        'columnPairs': [{'sourceColumnId': str(COLUMN_ID),
                         'targetColumnId': str(COLUMN_ID)}]})
    assert created['name'] == 'order_user'
    assert catalog.created['column_pairs'] == [(str(COLUMN_ID), str(COLUMN_ID))]

    value = service.create_value(str(DS_ID), {
        'columnId': str(COLUMN_ID), 'rawValue': '2', 'businessName': '已支付'})
    assert value['businessName'] == '已支付'

    metric = service.create_metric(str(DS_ID), {
        'key': 'paid_amount', 'businessName': '已支付订单金额',
        'baseTableId': str(TABLE_ID), 'expressionSql': 'SUM(x)'})
    assert metric['key'] == 'paid_amount'
    # 未显式给时区时继承数据源的 business_timezone
    assert catalog.created['business_timezone'] == 'UTC'


class FakeVersions:
    def __init__(self):
        self.finished = None

    def create_version(self, datasource_id, model, dimensions, actor):
        return {'version_id': str(VERSION_ID), 'status': 'BUILDING',
                'revision': 1, 'created': True}

    def get_version(self, datasource_id, version_id):
        return {
            'id': VERSION_ID, 'datasource_id': ds_uuid(), 'revision': 1,
            'status': 'READY', 'content_hash': 'a' * 64,
            'expected_knowledge_count': 1, 'embedding_model': 'm',
            'embedding_dimensions': 2, 'created_by': 'smoke',
            'ready_at': '2026-11-11 10:00:00',
            'created_at': '2026-11-11 10:00:00',
            'updated_at': '2026-11-11 10:00:00',
            'indexed_count': 1, 'failed_count': 0,
            'snapshot': {}, 'knowledge': [], 'jobs': [],
        }

    def prepare_build(self, datasource_id, version_id, worker_id):
        return {'status': 'BUILDING', 'job_id': 'job-1',
                'pending': [{'id': str(COLUMN_ID), 'content': '文本'}],
                'total': 1, 'embedding_model': 'm', 'embedding_dimensions': 2}

    def finish_build(self, datasource_id, version_id, job_id, embeddings, errors):
        self.finished = (embeddings, errors)
        return {'status': 'READY', 'processed': 1, 'failed': 0, 'errors': {},
                'version': {}}

    def list_versions(self, datasource_id):
        return []

    def publish_version(self, datasource_id, version_id, expected_revision, actor):
        return {'id': 'pub-1', 'datasource_id': ds_uuid(),
                'previous_version_id': None, 'version_id': version_id,
                'actor_id': actor, 'created_at': '2026-11-11 10:00:00',
                'revision': expected_revision}

    def list_publications(self, datasource_id):
        return []


def ds_uuid():
    return str(DS_ID)


def test_version_build_uses_injected_embedder():
    versions = FakeVersions()
    calls = []

    def fake_embed(texts, model):
        calls.append((texts, model))
        return [[0.1, 0.2] for _ in texts]

    service = Text2SqlService(FakeRepo([_row()]), scan_database=lambda *a, **k: None,
                              versions=versions, embed=fake_embed)
    result = service.build_version(str(DS_ID), str(VERSION_ID))

    assert result['status'] == 'READY'
    assert calls == [(['文本'], 'm')]
    assert list(versions.finished[0]) == [str(COLUMN_ID)]


def test_publish_maps_publication_and_validates_revision():
    service = Text2SqlService(FakeRepo([_row()]), scan_database=lambda *a, **k: None,
                              versions=FakeVersions())
    published = service.publish(str(DS_ID), {
        'versionId': str(VERSION_ID), 'expectedRevision': 3}, 'admin')
    assert published['versionId'] == str(VERSION_ID)
    assert published['revision'] == 3

    with pytest.raises(Text2SqlValidationError):
        service.publish(str(DS_ID), {'versionId': str(VERSION_ID)}, 'admin')
    with pytest.raises(Text2SqlValidationError):
        service.publish(str(DS_ID), {'versionId': str(VERSION_ID),
                                     'expectedRevision': 0}, 'admin')


def test_cleanup_versions_archives_and_purges():
    """GC 接口：保留 N 个 READY，其余交给数据库函数归档并清知识。"""
    repo = FakeRepo([_row()])
    service = Text2SqlService(repo, scan_database=lambda *a, **k: None)
    calls = {}

    class _Versions:
        def archive_versions(self, datasource_id, keep):
            calls['args'] = (str(datasource_id), keep)
            return {'archived': 2, 'purgedKnowledge': 7}

        def list_versions(self, datasource_id):
            return []

    service._versions = _Versions()
    result = service.cleanup_versions('11111111-1111-1111-1111-111111111111', 3)
    assert result['archived'] == 2 and result['purgedKnowledge'] == 7
    assert calls['args'] == ('11111111-1111-1111-1111-111111111111', 3)


def test_cleanup_versions_rejects_negative_keep():
    service = Text2SqlService(FakeRepo([_row()]), scan_database=lambda *a, **k: None)
    with pytest.raises(Text2SqlValidationError):
        service.cleanup_versions('11111111-1111-1111-1111-111111111111', -1)


def test_start_build_enqueues_and_short_circuits_ready(monkeypatch):
    service = Text2SqlService(FakeRepo([_row()]), scan_database=lambda *a, **k: None)
    submitted = []
    monkeypatch.setattr('text_to_sql.build_queue.enabled', lambda: True)
    monkeypatch.setattr('text_to_sql.build_queue.enqueue',
                        lambda ds, vid: submitted.append((ds, vid)) or 'task-9')

    class _Versions:
        status = 'BUILDING'

        def get_version(self, datasource_id, version_id):
            return {'id': version_id, 'datasource_id': datasource_id,
                    'revision': 1, 'status': self.status, 'content_hash': 'a' * 64,
                    'expected_knowledge_count': 1, 'embedding_model': 'm',
                    'embedding_dimensions': 8, 'created_by': 'a', 'ready_at': None,
                    'created_at': None, 'updated_at': None}

    service._versions = _Versions()
    result = service.start_build('11111111-1111-1111-1111-111111111111',
                                 '22222222-2222-2222-2222-222222222222')
    assert result['status'] == 'QUEUED' and result['taskId'] == 'task-9'
    assert submitted

    service._versions.status = 'READY'
    ready = service.start_build('11111111-1111-1111-1111-111111111111',
                                '22222222-2222-2222-2222-222222222222')
    assert ready['status'] == 'READY' and ready['queued'] is False
    assert len(submitted) == 1


def test_build_queue_execute_marks_task_done(monkeypatch):
    """worker 执行成功 -> complete；失败 -> fail，且不抛给循环。"""
    from text_to_sql import build_queue

    calls = []

    class _Ok:
        def build_version(self, ds, vid):
            calls.append((ds, vid))
            return {'status': 'READY'}

    monkeypatch.setattr('text_to_sql.service.get_service', lambda: _Ok())
    monkeypatch.setattr(build_queue.pg_queue, 'heartbeat', lambda *a, **k: None)
    monkeypatch.setattr(build_queue.pg_queue, 'complete',
                        lambda task_id, worker, progress=100: calls.append(('complete', task_id)))
    monkeypatch.setattr(build_queue.pg_queue, 'fail',
                        lambda task_id, worker, reason: calls.append(('fail', task_id)))

    build_queue._execute({'id': 't1', 'payload': {'datasourceId': 'd',
                                                  'versionId': 'v'}}, 'w')
    assert ('complete', 't1') in calls

    calls.clear()

    class _Boom:
        def build_version(self, ds, vid):
            raise RuntimeError('boom')

    monkeypatch.setattr('text_to_sql.service.get_service', lambda: _Boom())
    build_queue._execute({'id': 't2', 'payload': {'datasourceId': 'd',
                                                  'versionId': 'v'}}, 'w')
    assert ('fail', 't2') in calls


def test_versions_use_datasource_embedding_model_and_pin_it(monkeypatch):
    """模型以数据源为准：首次建版本时写回配置，之后换模型必须新建数据源。"""
    class _Repo(FakeRepo):
        def __init__(self):
            super().__init__([_row()])
            self.updated = []

        def get_datasource(self, datasource_id):
            row = dict(_row())
            row['embedding_model'] = self.embedding_model
            return row

        embedding_model = None

        def update_datasource(self, datasource_id, fields):
            self.updated.append(fields)
            self.embedding_model = fields.get('embedding_model', self.embedding_model)
            return self.get_datasource(datasource_id)

    class _Versions:
        def __init__(self):
            self.used = []

        def create_version(self, datasource_id, model, dimensions, actor):
            self.used.append((model, dimensions))
            return {'version_id': 'v1', 'status': 'BUILDING', 'revision': 1,
                    'created': True}

        def get_version(self, datasource_id, version_id):
            return {'id': version_id, 'datasource_id': datasource_id, 'revision': 1,
                    'status': 'BUILDING', 'content_hash': 'a' * 64,
                    'expected_knowledge_count': 0, 'embedding_model': 'm',
                    'embedding_dimensions': 8, 'created_by': 'a', 'ready_at': None,
                    'created_at': None, 'updated_at': None}

    repo = _Repo()
    service = Text2SqlService(repo, scan_database=lambda *a, **k: None)
    service._versions = _Versions()
    service._resolve_embedding = lambda requested: (requested or 'm-default', 1024)

    service.create_version('11111111-1111-1111-1111-111111111111',
                           {'embeddingModel': 'Qwen3'}, 'admin')
    assert service._versions.used == [('Qwen3', 1024)]
    assert repo.updated == [{'embedding_model': 'Qwen3'}]

    with pytest.raises(Text2SqlValidationError):
        service.create_version('11111111-1111-1111-1111-111111111111',
                               {'embeddingModel': 'other'}, 'admin')
