"""Text2SQL 入参校验与 DTO 映射（纯函数，无 DB）。"""

from __future__ import annotations

from uuid import UUID

import pytest

from text_to_sql import models
from text_to_sql.errors import Text2SqlValidationError

DS_ID = UUID('11111111-1111-1111-1111-111111111111')


def _create_body(**overrides):
    body = {
        'name': '电商业务库',
        'host': 'localhost',
        'port': 5432,
        'database': 'commerce_demo',
        'username': 'demo_readonly',
        'password': 'secret',
        'schemas': ['public'],
        'topic': {'name': '电商经营分析', 'description': '分析支付', 'owner': '数据组'},
        'businessDescription': '只读分析库',
        'businessTimezone': 'Asia/Shanghai',
    }
    body.update(overrides)
    return body


def test_parse_create_applies_defaults_and_normalizes():
    fields = models.parse_create_datasource(_create_body())

    assert fields['db_type'] == 'postgresql'
    assert fields['include_schemas'] == ['public']
    assert fields['query_policy'] == models.DEFAULT_QUERY_POLICY
    assert fields['topic']['owner'] == '数据组'
    assert fields['enabled'] is True
    # 未配置 SQL 生成模型 = 跟随部署默认。
    assert fields['llm_model'] is None


def test_datasource_llm_model_is_parsed_and_mutable():
    fields = models.parse_create_datasource(_create_body(llmModel=' qwen3-32b '))
    assert fields['llm_model'] == 'qwen3-32b'

    assert models.parse_update_datasource({'llmModel': 'deepseek-chat'}) == {
        'llm_model': 'deepseek-chat'}
    # 空串 = 清空数据源配置，回到部署默认模型。
    assert models.parse_update_datasource({'llmModel': ''}) == {'llm_model': None}
    # 未出现该字段时保持原值（PATCH 语义）。
    assert 'llm_model' not in models.parse_update_datasource({'name': '新名字'})


def test_parse_create_requires_connection_fields():
    with pytest.raises(Text2SqlValidationError):
        models.parse_create_datasource(_create_body(host='   '))
    with pytest.raises(Text2SqlValidationError):
        models.parse_create_datasource(_create_body(password=''))


def test_parse_create_rejects_unsupported_db_type_and_bad_port():
    with pytest.raises(Text2SqlValidationError):
        models.parse_create_datasource(_create_body(dbType='mysql'))
    with pytest.raises(Text2SqlValidationError):
        models.parse_create_datasource(_create_body(port=0))
    with pytest.raises(Text2SqlValidationError):
        models.parse_create_datasource(_create_body(port=70000))


def test_schemas_are_unique_and_non_empty():
    fields = models.parse_create_datasource(
        _create_body(schemas=['public', 'public', 'analytics']))
    assert fields['include_schemas'] == ['public', 'analytics']

    with pytest.raises(Text2SqlValidationError):
        models.parse_create_datasource(_create_body(schemas=[]))
    with pytest.raises(Text2SqlValidationError):
        models.parse_create_datasource(_create_body(schemas=['public', ' ']))


def test_unknown_timezone_rejected():
    with pytest.raises(Text2SqlValidationError):
        models.parse_create_datasource(_create_body(businessTimezone='Mars/Base'))


def test_query_policy_is_validated():
    fields = models.parse_create_datasource(_create_body(
        queryPolicy={'read_only': True, 'max_rows': 200, 'timeout_ms': 5000}))
    assert fields['query_policy'] == {
        'max_rows': 200, 'timeout_ms': 5000,
        'max_bytes': models.DEFAULT_MAX_BYTES}
    # 只读由执行层强制，不再是可配置项。
    assert 'read_only' not in fields['query_policy']

    # 字节上限缺省取默认值，显式传入时生效。
    assert models.parse_create_datasource(_create_body(
        queryPolicy={'max_bytes': 4096}))['query_policy']['max_bytes'] == 4096

    with pytest.raises(Text2SqlValidationError):
        models.parse_create_datasource(_create_body(queryPolicy={'max_rows': 0}))
    with pytest.raises(Text2SqlValidationError):
        models.parse_create_datasource(_create_body(
            queryPolicy={'max_bytes': 10}))


def test_update_keeps_only_present_fields_and_ignores_empty_password():
    fields = models.parse_update_datasource(
        {'name': ' 新名字 ', 'password': '', 'topic': {'name': '主题'}})

    assert fields['name'] == '新名字'
    assert 'password' not in fields
    assert fields['topic'] == {'name': '主题', 'description': '', 'owner': ''}


def test_table_and_column_updates_validate_types():
    assert models.parse_table_update({'enabled': True}) == {'enabled': True}
    with pytest.raises(Text2SqlValidationError):
        models.parse_table_update({'enabled': 'yes'})

    assert models.parse_column_update({'semanticType': 'measure'}) == {
        'semantic_type': 'measure'}
    with pytest.raises(Text2SqlValidationError):
        models.parse_column_update({'semanticType': 'money'})


def test_derive_status_uses_active_version_revision():
    base = {'active_version_id': DS_ID, 'active_status': 'READY',
            'active_revision': 3, 'config_revision': 3, 'last_sync_at': None}
    assert models.derive_status(base) == models.STATUS_INDEXED

    stale = {**base, 'active_revision': 2}
    assert models.derive_status(stale) == models.STATUS_CONFIGURED

    scanned = {'active_version_id': None, 'last_sync_at': '2026-11-11 10:00:00',
               'config_revision': 1}
    assert models.derive_status(scanned) == models.STATUS_SCANNED

    assert models.derive_status({'config_revision': 1}) == models.STATUS_CONFIGURED


def test_datasource_to_api_hides_credential_and_maps_fields():
    row = {
        'id': DS_ID, 'name': '电商业务库', 'db_type': 'postgresql',
        'host': 'localhost', 'port': 5432, 'database_name': 'commerce_demo',
        'username': 'demo_readonly', 'credential_ref': 'enc:v1:xxx',
        'include_schemas': ['public'], 'business_description': '',
        'topic_name': '电商经营分析', 'topic_description': '分析支付',
        'maintainer_ref': '数据组', 'business_timezone': 'Asia/Shanghai',
        'query_policy': models.DEFAULT_QUERY_POLICY, 'enabled': True,
        'embedding_model': 'Qwen3-Embedding-0.6B', 'llm_model': 'qwen3-32b',
        'config_revision': 1, 'active_version_id': None,
        'active_revision': None, 'active_status': None, 'active_ready_at': None,
        'connection_tested_at': None, 'last_sync_at': '2026-11-11 10:00:00',
        'created_at': '2026-11-11 09:00:00', 'updated_at': '2026-11-11 10:00:00',
    }
    api = models.datasource_to_api(row, selected_tables=['public.order_info'])

    assert api['id'] == str(DS_ID)
    assert api['type'] == 'PostgreSQL'
    assert api['schema'] == 'public'
    assert api['passwordConfigured'] is True
    assert api['status'] == models.STATUS_SCANNED
    assert api['requiresPublication'] is True
    assert api['selectedTables'] == ['public.order_info']
    assert api['embeddingModel'] == 'Qwen3-Embedding-0.6B'
    assert api['llmModel'] == 'qwen3-32b'
    assert 'credential_ref' not in api
    assert 'credentialRef' not in api


def test_table_and_column_to_api_shapes():
    column = {
        'id': UUID('22222222-2222-2222-2222-222222222222'),
        'table_id': UUID('33333333-3333-3333-3333-333333333333'),
        'column_name': 'pay_amount', 'data_type': 'numeric(12,2)',
        'ordinal_position': 3, 'is_nullable': True, 'default_value': None,
        'is_primary_key': False, 'is_unique': False, 'db_comment': None,
        'business_name': None, 'business_description': '支付金额',
        'business_aliases': [], 'semantic_type': 'measure', 'enabled': True,
        'missing_since': None, 'last_seen_at': '2026-11-11 10:00:00',
    }
    table = {
        'id': UUID('33333333-3333-3333-3333-333333333333'),
        'schema_name': 'public', 'table_name': 'order_info',
        'table_type': 'BASE_TABLE', 'db_comment': '订单',
        'business_name': None, 'business_description': '订单主表',
        'business_aliases': ['orders'], 'enabled': True,
        'schema_hash': 'a' * 64, 'missing_since': None,
        'last_seen_at': '2026-11-11 10:00:00',
    }
    api = models.table_to_api(table, [column])

    assert api['fullName'] == 'public.order_info'
    assert api['columns'][0]['name'] == 'pay_amount'
    assert api['columns'][0]['semanticType'] == 'measure'
    assert api['columns'][0]['businessDescription'] == '支付金额'


# ---------------------------------------------------------------------------
# 关联 / 枚举 / 指标 / 版本
# ---------------------------------------------------------------------------
TABLE_A = '11111111-1111-1111-1111-111111111111'
TABLE_B = '22222222-2222-2222-2222-222222222222'
COL_A = '33333333-3333-3333-3333-333333333333'
COL_B = '44444444-4444-4444-4444-444444444444'


def test_parse_relation_create_and_update():
    fields = models.parse_relation_create({
        'name': 'order_user', 'sourceTableId': TABLE_A, 'targetTableId': TABLE_B,
        'cardinality': 'MANY_TO_ONE', 'description': '订单 → 用户',
        'columnPairs': [{'sourceColumnId': COL_A, 'targetColumnId': COL_B}],
    })
    assert fields['column_pairs'] == [(COL_A, COL_B)]
    assert fields['enabled'] is True

    with pytest.raises(Text2SqlValidationError):
        models.parse_relation_create({'name': 'x', 'sourceTableId': TABLE_A,
                                      'targetTableId': TABLE_B, 'columnPairs': []})
    with pytest.raises(Text2SqlValidationError):
        models.parse_relation_create({'name': 'x', 'sourceTableId': TABLE_A,
                                      'targetTableId': TABLE_B,
                                      'cardinality': 'MANY',
                                      'columnPairs': [{'sourceColumnId': COL_A,
                                                       'targetColumnId': COL_B}]})

    assert models.parse_relation_update({'enabled': False}) == {'enabled': False}
    assert models.parse_relation_verification({'verified': True}) is True
    with pytest.raises(Text2SqlValidationError):
        models.parse_relation_update({'columnPairs': [{}]})


def test_parse_value_create_and_update():
    fields = models.parse_value_create({
        'columnId': COL_A, 'rawValue': '2', 'valueType': 'smallint',
        'businessName': '已支付', 'sourceType': 'ENUM'})
    assert fields['source_type'] == 'ENUM'
    assert fields['aliases'] == []

    with pytest.raises(Text2SqlValidationError):
        models.parse_value_create({'columnId': COL_A, 'rawValue': ''})
    with pytest.raises(Text2SqlValidationError):
        models.parse_value_create({'columnId': COL_A, 'rawValue': '2',
                                   'sourceType': 'UNKNOWN'})

    assert models.parse_value_update({'enabled': False}) == {'enabled': False}


def test_parse_metric_create_update_and_status():
    fields = models.parse_metric_create({
        'key': 'paid_amount', 'businessName': '已支付订单金额',
        'baseTableId': TABLE_A, 'expressionSql': 'SUM(pay_amount)',
        'filterDefinition': {'op': 'eq'}, 'timeColumnId': COL_A,
        'aggregationBehavior': 'ADDITIVE',
        'columnDependencies': [{'columnId': COL_A, 'role': 'MEASURE'}],
        'relationDependencies': [],
    })
    assert fields['aggregation_behavior'] == 'ADDITIVE'
    assert fields['column_dependencies'] == [{'column_id': COL_A, 'role': 'MEASURE'}]
    assert fields['business_timezone'] == 'UTC'

    with pytest.raises(Text2SqlValidationError):
        models.parse_metric_create({'key': 'k', 'businessName': 'b',
                                    'baseTableId': TABLE_A, 'expressionSql': ''})
    with pytest.raises(Text2SqlValidationError):
        models.parse_metric_create({'key': 'k', 'businessName': 'b',
                                    'baseTableId': TABLE_A, 'expressionSql': 'SUM(x)',
                                    'aggregationBehavior': 'SUM'})

    partial = models.parse_metric_update({'unit': '人'})
    assert partial == {'unit': '人'}

    assert models.parse_metric_status({'status': 'APPROVED'}) == 'APPROVED'
    with pytest.raises(Text2SqlValidationError):
        models.parse_metric_status({'status': 'DRAFT'})


def test_relation_value_metric_and_version_dto_shapes():
    relation = {
        'id': UUID(TABLE_A), 'source_table_id': UUID(TABLE_B),
        'target_table_id': UUID(COL_A), 'relation_name': 'r', 'relation_type': 'MANUAL',
        'cardinality': 'MANY_TO_ONE', 'description': 'd', 'enabled': True,
        'verified': True, 'verified_by': 'admin', 'verified_at': '2026-11-11',
        'source_table': 'public.a', 'target_table': 'public.b',
        'column_pairs': [{'source_column_id': UUID(COL_B),
                          'source_column_name': 'x',
                          'target_column_id': UUID(COL_A),
                          'target_column_name': 'y'}],
        'created_at': 'c', 'updated_at': 'u',
    }
    api = models.relation_to_api(relation)
    assert api['columnPairs'][0]['sourceColumn'] == 'x'
    assert api['verified'] is True

    value = {
        'id': UUID(TABLE_A), 'column_id': UUID(COL_B), 'raw_value': '2',
        'value_type': 'smallint', 'business_name': '已支付', 'aliases': ['paid'],
        'description': '', 'source_type': 'MANUAL', 'enabled': True,
        'column_name': 'status', 'table_name': 'public.order_info',
        'created_at': 'c', 'updated_at': 'u',
    }
    assert models.value_to_api(value)['businessName'] == '已支付'

    version = {
        'id': UUID(TABLE_A), 'datasource_id': UUID(TABLE_B), 'revision': 3,
        'status': 'READY', 'content_hash': 'a' * 64,
        'expected_knowledge_count': 8, 'indexed_count': 8, 'failed_count': 0,
        'embedding_model': 'm', 'embedding_dimensions': 1024, 'created_by': 'admin',
        'ready_at': 'r', 'created_at': 'c', 'updated_at': 'u',
        'snapshot': {'formatVersion': 1}, 'knowledge': [], 'jobs': [],
    }
    api_version = models.version_to_api(version, include_snapshot=True)
    assert api_version['expectedKnowledgeCount'] == 8
    assert api_version['indexedCount'] == 8
    assert api_version['snapshot'] == {'formatVersion': 1}


def test_distinct_aggregate_defaults_to_non_additive():
    """COUNT(DISTINCT ...) 的月度值不能相加，创建时必须默认 NON_ADDITIVE。"""
    base = {'key': 'paid_users', 'businessName': '付费用户数',
            'baseTableId': '11111111-1111-1111-1111-111111111111',
            'expressionSql': 'COUNT(DISTINCT order_info.user_id)'}
    assert models.parse_metric_create(base)['aggregation_behavior'] == 'NON_ADDITIVE'

    additive = dict(base, expressionSql='SUM(order_info.pay_amount)')
    assert models.parse_metric_create(additive)['aggregation_behavior'] == 'ADDITIVE'

    # 显式值优先：运维确实想标 ADDITIVE 时不推翻。
    explicit = dict(base, aggregationBehavior='ADDITIVE')
    assert models.parse_metric_create(explicit)['aggregation_behavior'] == 'ADDITIVE'


def test_version_dto_exposes_index_bindings():
    """版本详情要能看到每种存储各自的索引状态（Vector / ES）。"""
    row = {
        'id': 'v1', 'datasource_id': 'd1', 'revision': 3, 'status': 'READY',
        'content_hash': 'a' * 64, 'expected_knowledge_count': 10,
        'embedding_model': 'm', 'embedding_dimensions': 1024,
        'created_by': 'admin', 'ready_at': None, 'created_at': None,
        'updated_at': None,
        'knowledge': [{'object_type': 'TABLE', 'index_status': 'INDEXED', 'count': 10}],
        'bindings': [{'store_kind': 'VECTOR', 'state': 'INDEXED', 'count': 10},
                     {'store_kind': 'ES', 'state': 'FAILED', 'count': 2}],
        'jobs': [],
    }
    dto = models.version_to_api(row, include_snapshot=True)
    assert dto['bindings'] == [
        {'storeKind': 'VECTOR', 'state': 'INDEXED', 'count': 10},
        {'storeKind': 'ES', 'state': 'FAILED', 'count': 2},
    ]
