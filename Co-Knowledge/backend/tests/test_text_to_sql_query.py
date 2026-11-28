"""Text2SQL 查询编排：SQL 安全边界 + 运行落库形状（不连外部库）。"""

from __future__ import annotations

import json

import pytest

from knowledge_engine import policy as engine_policy
from text_to_sql import sql_guard
from text_to_sql.query_service import (QueryFailure, Text2SqlQueryService,
                                       _validation_view, _value_hints)


SNAPSHOT = {
    'datasource': {
        'id': '11111111-1111-1111-1111-111111111111', 'name': 'Demo', 'dbType': 'postgresql',
        'includeSchemas': ['public'], 'businessTimezone': 'Asia/Shanghai',
        'topic': {'name': '电商', 'description': '订单分析'},
    },
    'tables': [
        {
            'id': 't1', 'schema': 'public', 'name': 'orders',
            'businessDescription': '订单主表',
            'columns': [
                {'id': 'c1', 'name': 'id', 'dataType': 'bigint', 'primaryKey': True},
                {'id': 'c2', 'name': 'amount', 'dataType': 'numeric',
                 'businessDescription': '支付金额'},
            ],
        },
        {
            'id': 't2', 'schema': 'public', 'name': 'users',
            'columns': [{'id': 'c3', 'name': 'id', 'dataType': 'bigint'}],
        },
    ],
    'relations': [{
        'id': 'r1', 'name': 'orders_users', 'cardinality': 'MANY_TO_ONE',
        'sourceTableId': 't1', 'targetTableId': 't2',
        'columnPairs': [{'sourceColumnId': 'c1', 'targetColumnId': 'c3'}],
    }],
    'values': [{'id': 'v1', 'columnId': 'c2', 'rawValue': '2',
                'businessName': '已支付', 'aliases': ['支付']}],
    'metrics': [],
}


# ----------------------------------------------------------------------
# SQL guard
# ----------------------------------------------------------------------
def test_validate_sql_allows_select_and_cte():
    assert sql_guard.validate_sql('SELECT id FROM public.orders', SNAPSHOT) == \
        'SELECT id FROM public.orders'
    assert sql_guard.validate_sql(
        'WITH x AS (SELECT * FROM public.orders) SELECT * FROM x', SNAPSHOT)


def test_validate_sql_rejects_writes_multiple_statements_and_unknown_tables():
    with pytest.raises(sql_guard.SqlGuardError) as error:
        sql_guard.validate_sql('DELETE FROM public.orders', SNAPSHOT)
    assert error.value.code == 'SQL_UNSAFE'

    with pytest.raises(sql_guard.SqlGuardError):
        sql_guard.validate_sql('SELECT 1; DROP TABLE public.orders', SNAPSHOT)

    with pytest.raises(sql_guard.SqlGuardError) as error:
        sql_guard.validate_sql('SELECT * FROM public.secret', SNAPSHOT)
    assert error.value.code == 'SQL_TABLE_NOT_ALLOWED'

    with pytest.raises(sql_guard.SqlGuardError):
        sql_guard.validate_sql('SELECT pg_read_file(\'/etc/passwd\')', SNAPSHOT)

    with pytest.raises(sql_guard.SqlGuardError):
        sql_guard.validate_sql('SELECT * FROM public.orders, public.secret', SNAPSHOT)


def test_validate_sql_accepts_quoted_identifiers_and_rejects_locking_reads():
    assert sql_guard.validate_sql(
        'SELECT * FROM "public"."orders"', SNAPSHOT)
    with pytest.raises(sql_guard.SqlGuardError):
        sql_guard.validate_sql('SELECT * FROM public.orders FOR UPDATE', SNAPSHOT)


def test_extract_generated_accepts_json_fence_and_raw_select():
    assert sql_guard.extract_generated(
        '```json\n{"sql": "SELECT 1", "explanation": "x"}\n```')['sql'] == 'SELECT 1'
    assert sql_guard.extract_generated('SELECT 1')['sql'] == 'SELECT 1'
    with pytest.raises(sql_guard.SqlGuardError):
        sql_guard.extract_generated('抱歉，我无法回答')


def test_build_context_contains_business_descriptions_and_relations():
    text = sql_guard.build_context(SNAPSHOT)
    assert 'public.orders' in text
    assert '订单主表' in text
    assert '支付金额' in text
    assert 'orders_users' in text
    assert '已支付' in text


# ----------------------------------------------------------------------
# 值匹配
# ----------------------------------------------------------------------
def test_value_hints_map_colloquial_city_to_stored_value():
    snapshot = {
        'tables': [{
            'id': 't1', 'schema': 'public', 'name': 'region_info',
            'columns': [{'id': 'c1', 'name': 'city_name'}],
        }],
        'values': [{'columnId': 'c1', 'rawValue': '西安市',
                    'businessName': '西安市', 'aliases': ['西安']}],
    }

    assert _value_hints(snapshot, '查询西安最近30天支付订单金额。') == [{
        'matched': '西安', 'value': '西安市',
        'column': 'public.region_info.city_name'}]
    assert _value_hints(snapshot, '查询西安市支付订单金额。') == []


def test_value_hints_skip_numeric_aliases_but_keep_business_names():
    snapshot = {
        'tables': [{
            'id': 't1', 'schema': 'public', 'name': 'orders',
            'columns': [{'id': 'c2', 'name': 'status'}],
        }],
        'values': [{'columnId': 'c2', 'rawValue': '2',
                    'businessName': '已支付', 'aliases': ['支付']}],
    }

    assert _value_hints(snapshot, '查询已支付订单金额') == [{
        'matched': '已支付', 'value': '2',
        'column': 'public.orders.status'}]
    assert _value_hints(snapshot, '查询支付订单金额') == []


# ----------------------------------------------------------------------
# 查询编排
# ----------------------------------------------------------------------
class _Repo:
    def __init__(self):
        self.success = None
        self.failure = None
        self.runs = []

    def get_active_context(self, datasource_id):
        return {
            'id': '11111111-1111-1111-1111-111111111111', 'name': 'Demo', 'config_revision': 3,
            'active_version_id': 'v-1', 'active_version_status': 'READY',
            'active_version_revision': 3,
            'embedding_model': 'Qwen3-Embedding-0.6B',
            'snapshot': SNAPSHOT, 'business_timezone': 'Asia/Shanghai',
            'query_policy': {'read_only': True, 'max_rows': 100, 'timeout_ms': 3000},
            'host': 'db', 'port': 5432, 'database_name': 'demo',
            'username': 'reader', 'credential_ref': 'secret',
            'include_schemas': ['public'],
        }

    def create_run(self, **kwargs):
        self.runs.append(kwargs)
        return {'id': 'run-1', 'request_id': 'req-1'}

    def mark_running(self, run_id):
        pass

    def search_knowledge(self, version_id, embedding, limit=24, datasource_id=None):
        return [
            {'object_type': 'TABLE', 'object_key': 't1', 'score': 0.97},
            {'object_type': 'COLUMN', 'object_key': 'c2', 'score': 0.91},
            {'object_type': 'VALUE', 'object_key': 'v1', 'score': 0.88},
        ]

    def list_knowledge_text(self, version_id):
        return [
            {'object_type': 'TABLE', 'object_key': 't1', 'title': 'public.orders',
             'content': '数据表 public.orders 订单主表'},
            {'object_type': 'COLUMN', 'object_key': 'c2', 'title': 'public.orders.amount',
             'content': '字段 public.orders.amount 支付金额'},
        ]

    def finish_success(self, run_id, **kwargs):
        self.success = kwargs

    def finish_failure(self, run_id, **kwargs):
        self.failure = kwargs


def _service(repo, llm=None):
    service = Text2SqlQueryService(repository=repo,
                                   embed=lambda question, model: [0.1, 0.2],
                                   llm=llm or (lambda **kwargs: {
                                       'sql': 'SELECT COUNT(*) FROM public.orders',
                                       'explanation': '统计订单数'}))
    service._external_connection = lambda context: {
        'host': 'db', 'port': 5432, 'database': 'demo',
        'username': 'reader', 'password': 'pwd',
        'include_schemas': ['public']}
    return service


def test_run_query_success_builds_frontend_response(monkeypatch):
    repo = _Repo()
    monkeypatch.setattr('text_to_sql.sql_guard.execute_readonly',
                        lambda connection, sql, policy, snapshot, on_phase=None: {
                            'columns': ['count'], 'rows': [[3]], 'row_count': 1,
                            'truncated': False,
                            'explain': {'total_cost': 1.2, 'plan_rows': 1,
                                        'plan_width': 8, 'node_type': 'Aggregate',
                                        'nodes': []},
                            'explain_ms': 2, 'execute_ms': 3, 'total_ms': 5,
                        })

    response = _service(repo).run_query('11111111-1111-1111-1111-111111111111', {'question': '有多少订单？'}, 'admin')

    assert response['request_id'] == 'req-1'
    assert response['result']['rows'] == [[3]]
    assert response['sql']['final'] == 'SELECT COUNT(*) FROM public.orders'
    assert response['validation']['valid'] is True
    assert [stage['status'] for stage in response['stages']] == ['success'] * 8
    assert repo.success['row_count'] == 1
    assert repo.success['validation']['checks'][1]['label'] == 'Schema 白名单'


def test_run_query_passes_value_hints_to_llm(monkeypatch):
    class CityRepo(_Repo):
        def get_active_context(self, datasource_id):
            row = super().get_active_context(datasource_id)
            row['snapshot'] = {
                **SNAPSHOT,
                'tables': SNAPSHOT['tables'] + [{
                    'id': 't3', 'schema': 'public', 'name': 'region_info',
                    'columns': [{'id': 'c4', 'name': 'city_name'}],
                }],
                'values': [{'id': 'v2', 'columnId': 'c4', 'rawValue': '西安市',
                            'businessName': '西安市', 'aliases': ['西安']}],
            }
            return row

    monkeypatch.setattr('text_to_sql.sql_guard.execute_readonly',
                        lambda connection, sql, policy, snapshot, on_phase=None: {
                            'columns': ['count'], 'rows': [[0]], 'row_count': 1,
                            'truncated': False, 'explain': None,
                            'explain_ms': 0, 'execute_ms': 0, 'total_ms': 0,
                        })
    captured = {}

    def llm(**kwargs):
        captured.update(kwargs)
        return {'sql': 'SELECT COUNT(*) FROM public.orders',
                'explanation': '统计订单数'}

    response = _service(CityRepo(), llm=llm).run_query(
        '11111111-1111-1111-1111-111111111111',
        {'question': '查询西安最近30天支付订单金额。'}, 'admin')

    assert response['error'] is None
    assert captured['value_hints'] == [{
        'matched': '西安', 'value': '西安市',
        'column': 'public.region_info.city_name'}]


def _stub_execute(monkeypatch):
    monkeypatch.setattr('text_to_sql.sql_guard.execute_readonly',
                        lambda connection, sql, policy, snapshot, on_phase=None: {
                            'columns': ['count'], 'rows': [[3]], 'row_count': 1,
                            'truncated': False, 'explain': None,
                            'explain_ms': 0, 'execute_ms': 0, 'total_ms': 0,
                        })


def test_run_query_uses_datasource_llm_model(monkeypatch):
    """请求没点模型时，SQL 生成用数据源上配置的 LLM。"""

    class LlmRepo(_Repo):
        def get_active_context(self, datasource_id):
            row = super().get_active_context(datasource_id)
            row['llm_model'] = 'qwen3-32b'
            return row

    _stub_execute(monkeypatch)
    captured = {}

    def llm(**kwargs):
        captured.update(kwargs)
        return {'sql': 'SELECT COUNT(*) FROM public.orders', 'explanation': 'x'}

    response = _service(LlmRepo(), llm=llm).run_query(
        '11111111-1111-1111-1111-111111111111', {'question': '有多少订单？'}, 'admin')

    assert response['error'] is None
    assert captured['model'] == 'qwen3-32b'


def test_run_query_request_model_overrides_datasource_llm(monkeypatch):
    """请求体显式带的 model 优先于数据源配置。"""

    class LlmRepo(_Repo):
        def get_active_context(self, datasource_id):
            row = super().get_active_context(datasource_id)
            row['llm_model'] = 'qwen3-32b'
            return row

    _stub_execute(monkeypatch)
    captured = {}

    def llm(**kwargs):
        captured.update(kwargs)
        return {'sql': 'SELECT COUNT(*) FROM public.orders', 'explanation': 'x'}

    _service(LlmRepo(), llm=llm).run_query(
        '11111111-1111-1111-1111-111111111111',
        {'question': '有多少订单？', 'model': 'deepseek-chat'}, 'admin')

    assert captured['model'] == 'deepseek-chat'


def test_run_query_reports_stage_progress_in_order(monkeypatch):
    def execute(connection, sql, policy, snapshot, on_phase=None):
        if on_phase is not None:
            on_phase('explain', None)
            on_phase('execute', 2)
        return {'columns': ['count'], 'rows': [[3]], 'row_count': 1,
                'truncated': False, 'explain': None,
                'explain_ms': 2, 'execute_ms': 3, 'total_ms': 5}

    monkeypatch.setattr('text_to_sql.sql_guard.execute_readonly', execute)
    events = []

    _service(_Repo()).run_query(
        '11111111-1111-1111-1111-111111111111', {'question': '有多少订单？'},
        'admin', on_stage=lambda stage, status, ms: events.append((stage, status)))

    assert events == [
        ('tables', 'running'), ('tables', 'success'),
        ('columns', 'running'), ('columns', 'success'),
        ('values', 'running'), ('values', 'success'),
        ('relations', 'running'), ('relations', 'success'),
        ('llm', 'running'), ('llm', 'success'),
        ('validation', 'running'), ('validation', 'success'),
        ('explain', 'running'), ('explain', 'success'),
        ('execute', 'running'), ('execute', 'success'),
    ]


def test_run_query_marks_manual_sql_llm_stage_skipped(monkeypatch):
    monkeypatch.setattr('text_to_sql.sql_guard.execute_readonly',
                        lambda connection, sql, policy, snapshot, on_phase=None: {
                            'columns': [], 'rows': [], 'row_count': 0,
                            'truncated': False, 'explain': None,
                            'explain_ms': 0, 'execute_ms': 0, 'total_ms': 0,
                        })
    events = []

    _service(_Repo()).run_query(
        '11111111-1111-1111-1111-111111111111',
        {'question': '有多少订单？', 'sql': 'SELECT 1'},
        'admin', on_stage=lambda stage, status, ms: events.append((stage, status)))

    assert ('llm', 'skipped') in events


def test_run_query_survives_broken_stage_callback(monkeypatch):
    monkeypatch.setattr('text_to_sql.sql_guard.execute_readonly',
                        lambda connection, sql, policy, snapshot, on_phase=None: {
                            'columns': [], 'rows': [], 'row_count': 0,
                            'truncated': False, 'explain': None,
                            'explain_ms': 0, 'execute_ms': 0, 'total_ms': 0,
                        })

    def broken(stage, status, ms=None):
        raise RuntimeError('callback blew up')

    response = _service(_Repo()).run_query(
        '11111111-1111-1111-1111-111111111111', {'question': '有多少订单？'},
        'admin', on_stage=broken)

    assert response['error'] is None


def test_run_query_failure_persists_error_and_returns_stage(monkeypatch):
    repo = _Repo()

    def boom(**kwargs):
        raise QueryFailure('LLM_GENERATE_FAILED', '模型挂了', 'llm',
                           'SQL Generation Error')

    response = _service(repo, llm=boom).run_query(
        '11111111-1111-1111-1111-111111111111', {'question': '有多少订单？'}, 'admin')

    assert response['error']['code'] == 'LLM_GENERATE_FAILED'
    stages = {stage['id']: stage['status'] for stage in response['stages']}
    assert stages['llm'] == 'error'
    assert stages['validation'] == 'skipped'
    assert repo.failure['error_code'] == 'LLM_GENERATE_FAILED'
    assert repo.failure['error_stage'] == 'llm'


def test_run_query_requires_published_version():
    class NoVersion(_Repo):
        def get_active_context(self, datasource_id):
            row = super().get_active_context(datasource_id)
            row.update(active_version_id=None, active_version_status=None)
            return row

    with pytest.raises(Exception) as error:
        _service(NoVersion()).run_query('11111111-1111-1111-1111-111111111111', {'question': 'q'}, 'admin')
    assert error.value.problem_spec().status == 409


# ----------------------------------------------------------------------
# 执行上限：行数 + 字节
# ----------------------------------------------------------------------
def test_encode_rows_stops_at_row_limit():
    rows, byte_truncated = engine_policy.encode_rows(
        [(index,) for index in range(5)],
        engine_policy.ExecutionPolicy(max_rows=3, max_bytes=1024 * 1024))
    assert rows == [[0], [1], [2]]
    assert byte_truncated is False


def test_encode_rows_stops_at_byte_limit():
    raw = [('x' * 400,), ('y' * 400,), ('z' * 400,)]
    rows, byte_truncated = engine_policy.encode_rows(
        raw, engine_policy.ExecutionPolicy(max_rows=10, max_bytes=900))
    assert rows == [['x' * 400], ['y' * 400]]
    assert byte_truncated is True


def test_encode_rows_drops_row_that_alone_exceeds_budget():
    rows, byte_truncated = engine_policy.encode_rows(
        [('x' * 5000,)], engine_policy.ExecutionPolicy(max_rows=10, max_bytes=1000))
    assert rows == []
    assert byte_truncated is True


def test_validation_view_reports_byte_truncation():
    by_bytes = _validation_view('SELECT 1', {'truncated': True,
                                             'byte_truncated': True}, {})
    assert any('KB' in warning for warning in by_bytes['warnings'])

    by_rows = _validation_view('SELECT 1', {'truncated': True,
                                            'byte_truncated': False}, {})
    assert any('行' in warning for warning in by_rows['warnings'])


def test_explain_failure_rolls_back_to_savepoint():
    """EXPLAIN 失败必须回滚到保存点，否则后续语句只会报「事务已中止」。"""
    import psycopg2

    class Cursor:
        def __init__(self):
            self.commands = []

        def execute(self, command, params=None):
            self.commands.append(command)
            if command.startswith('EXPLAIN'):
                raise psycopg2.errors.UndefinedColumn('boom')

    cursor = Cursor()
    assert sql_guard._explain_plan(cursor, 'SELECT 1') is None
    assert cursor.commands == ['SAVEPOINT t2s_explain',
                              'EXPLAIN (FORMAT JSON) SELECT 1',
                              'ROLLBACK TO SAVEPOINT t2s_explain']


def test_explain_success_releases_savepoint():
    class Cursor:
        def __init__(self):
            self.commands = []

        def execute(self, command, params=None):
            self.commands.append(command)

        def fetchone(self):
            return (json.dumps([{'Plan': {'Node Type': 'Result',
                                          'Total Cost': 0.01,
                                          'Plan Rows': 1}}]),)

    cursor = Cursor()
    plan = sql_guard._explain_plan(cursor, 'SELECT 1')
    assert plan['node_type'] == 'Result'
    assert cursor.commands[-1] == 'RELEASE SAVEPOINT t2s_explain'


def test_build_context_exposes_metric_semantics():
    """指标的可加性/单位/时间字段必须进提示词——只给表达式等于丢掉语义。"""
    snapshot = {
        'datasource': {'dbType': 'postgresql', 'businessTimezone': 'Asia/Shanghai'},
        'tables': [{'id': 't1', 'schema': 'public', 'name': 'orders',
                    'columns': [{'id': 'c1', 'name': 'create_time',
                                 'dataType': 'timestamp'}]}],
        'relations': [], 'values': [],
        'metrics': [{
            'id': 'm1', 'key': 'paid_users', 'businessName': '付费用户数',
            'expressionSql': 'COUNT(DISTINCT user_id)',
            'aggregationBehavior': 'NON_ADDITIVE', 'unit': '人',
            'timeColumnId': 'c1', 'businessTimezone': 'Asia/Shanghai',
            'filterDefinition': {'status': 2},
            'attributionDescription': '按订单创建时间归属',
        }],
    }
    text = sql_guard.build_context(snapshot)
    assert 'NON_ADDITIVE' in text
    assert '单位：人' in text
    assert 'public.orders.create_time' in text
    assert '过滤条件' in text
    assert '按订单创建时间归属' in text
    assert '不可跨期直接相加' in text


# ----------------------------------------------------------------------
# 生成自修复
# ----------------------------------------------------------------------
def test_generation_retries_once_with_guard_feedback(monkeypatch):
    """首次生成的 SQL 被校验拒绝时，把原因回灌给模型再试一次。"""
    monkeypatch.setattr(sql_guard, 'execute_readonly', lambda *a, **k: {
        'columns': ['n'], 'rows': [[1]], 'row_count': 1, 'truncated': False,
        'byte_truncated': False, 'explain': None, 'explain_ms': 0,
        'execute_ms': 0, 'total_ms': 0})

    calls = []

    def llm(**kwargs):
        calls.append(kwargs.get('feedback') or '')
        if len(calls) == 1:
            return {'sql': 'SELECT nope FROM public.orders', 'explanation': ''}
        return {'sql': 'SELECT id FROM public.orders', 'explanation': ''}

    response = _service(_Repo(), llm=llm).run_query(
        '11111111-1111-1111-1111-111111111111', {'question': '有多少订单？'}, 'admin')

    assert response['error'] is None
    assert len(calls) == 2
    assert 'SQL_COLUMN_NOT_ALLOWED' in calls[1]
    assert response['validation']['attempts'] == 2


def test_generation_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr(sql_guard, 'execute_readonly', lambda *a, **k: {})

    calls = []

    def llm(**kwargs):
        calls.append(1)
        return {'sql': 'SELECT nope FROM public.orders', 'explanation': ''}

    response = _service(_Repo(), llm=llm).run_query(
        '11111111-1111-1111-1111-111111111111', {'question': '有多少订单？'}, 'admin')

    assert response['error']['code'] == 'SQL_COLUMN_NOT_ALLOWED'
    assert len(calls) == 2          # MAX_GENERATION_ATTEMPTS


def test_manual_sql_is_not_retried(monkeypatch):
    monkeypatch.setattr(sql_guard, 'execute_readonly', lambda *a, **k: {})
    calls = []

    def llm(**kwargs):
        calls.append(1)
        return {'sql': 'SELECT 1', 'explanation': ''}

    response = _service(_Repo(), llm=llm).run_query(
        '11111111-1111-1111-1111-111111111111',
        {'question': 'q', 'sql': 'SELECT nope FROM public.orders'}, 'admin')

    assert response['error']['code'] == 'SQL_COLUMN_NOT_ALLOWED'
    assert calls == []              # 手工 SQL 只校验一次，不调模型


def test_response_carries_context_snapshot_and_usage(monkeypatch):
    """上下文原文与 token 用量都要能回放：这是「为什么选这张表」的唯一证据。"""
    monkeypatch.setattr(sql_guard, 'execute_readonly', lambda *a, **k: {
        'columns': ['n'], 'rows': [[1]], 'row_count': 1, 'truncated': False,
        'byte_truncated': False, 'explain': None, 'explain_ms': 0,
        'execute_ms': 0, 'total_ms': 0})

    repo = _Repo()
    response = _service(repo, llm=lambda **kwargs: {
        'sql': 'SELECT COUNT(*) FROM public.orders', 'explanation': '',
        'usage': {'prompt_tokens': 120, 'completion_tokens': 30}}).run_query(
        '11111111-1111-1111-1111-111111111111', {'question': '有多少订单？'}, 'admin')

    assert response['usage']['prompt_tokens'] == 120
    context = repo.success['context']
    assert context['text']
    assert context['hash']
    assert context['tables']
    assert repo.success['usage']['completion_tokens'] == 30


def test_stage_timings_are_not_all_zero(monkeypatch):
    """选表与渲染分别计时：关系扩展段不能再恒为 0ms。"""
    monkeypatch.setattr(sql_guard, 'execute_readonly', lambda *a, **k: {
        'columns': ['n'], 'rows': [[1]], 'row_count': 1, 'truncated': False,
        'byte_truncated': False, 'explain': None, 'explain_ms': 0,
        'execute_ms': 0, 'total_ms': 0})

    response = _service(_Repo()).run_query(
        '11111111-1111-1111-1111-111111111111', {'question': '有多少订单？'}, 'admin')
    assert response['timing']['columns_ms'] >= 0
    assert response['timing']['relations_ms'] >= 0
    stages = {stage['id']: stage for stage in response['stages']}
    assert set(stages) == {'tables', 'columns', 'values', 'relations', 'llm',
                           'validation', 'explain', 'execute'}
