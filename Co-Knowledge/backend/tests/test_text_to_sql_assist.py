"""AI 辅助：只输出「能对回目录」的建议，编造的 id 一律丢弃。"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from text_to_sql import assist
from text_to_sql.errors import Text2SqlValidationError
from text_to_sql.service import Text2SqlService

DS_ID = uuid4()
TABLE_ID = uuid4()
COLUMN_ID = uuid4()
VALUE_ID = uuid4()
BOGUS_ID = uuid4()


class _Repo:
    def get_datasource(self, datasource_id):
        return {'id': str(DS_ID), 'name': 'Demo', 'database_name': 'demo',
                'business_description': '订单库', 'topic_name': '电商',
                'topic_description': ''}

    def profiling_scope(self, datasource_id):
        return set()

    def selected_table_names(self, datasource_id):
        return []

    def list_tables(self, datasource_id):
        return [{
            'id': str(TABLE_ID), 'schema_name': 'public', 'table_name': 'orders',
            'db_comment': None, 'business_name': None, 'business_description': None,
            'enabled': True, 'missing_since': None,
            'columns': [{'id': str(COLUMN_ID), 'column_name': 'pay_amount',
                         'data_type': 'numeric', 'is_primary_key': False,
                         'is_nullable': True}],
        }]


class _Catalog:
    def list_relations(self, datasource_id):
        return [{'relation_name': 'fk', 'source_table': 'public.orders',
                 'target_table': 'public.users', 'cardinality': 'MANY_TO_ONE'}]

    def list_metrics(self, datasource_id):
        return []

    def list_values(self, datasource_id):
        return [{'id': str(VALUE_ID), 'table_name': 'public.orders',
                 'column_name': 'status', 'raw_value': '1',
                 'business_name': None, 'enabled': True}]


def _service(payload: dict):
    def fake_model(system, user, model=None):
        return json.dumps(payload, ensure_ascii=False), {'total_tokens': 10}, 'fake-llm'

    return Text2SqlService(_Repo(), catalog=_Catalog(), assist_model=fake_model)


def test_descriptions_drop_invented_ids():
    payload = {
        'tables': [{'id': str(TABLE_ID), 'businessName': '订单',
                    'businessDescription': '订单主表', 'aliases': ['订单表']},
                   {'id': str(BOGUS_ID), 'businessName': '编造表'}],
        'columns': [{'id': str(COLUMN_ID), 'businessName': '支付金额',
                     'businessDescription': '订单实付金额', 'semanticType': 'measure'},
                    {'id': str(BOGUS_ID), 'businessName': '编造列'}],
    }
    result = _service(payload).assist(str(DS_ID), {
        'kind': 'descriptions', 'includeSamples': False})

    targets = [(item['target'], item['id']) for item in result['suggestions']]
    assert targets == [('table', str(TABLE_ID)), ('column', str(COLUMN_ID))]
    column = result['suggestions'][1]
    assert column['semanticType'] == 'measure'
    assert column['businessDescription'] == '订单实付金额'
    assert result['model'] == 'fake-llm'


def test_tables_kind_returns_reasons_only_for_real_tables():
    payload = {'tables': [{'id': str(TABLE_ID), 'reason': '订单事实表'},
                          {'id': str(BOGUS_ID), 'reason': '编造'}]}
    result = _service(payload).assist(str(DS_ID), {'kind': 'tables'})

    assert [item['id'] for item in result['suggestions']] == [str(TABLE_ID)]
    assert result['suggestions'][0]['reason'] == '订单事实表'


def test_values_kind_carries_raw_value_and_aliases():
    payload = {'values': [{'id': str(VALUE_ID), 'businessName': '已支付',
                           'aliases': ['已付款', '已付款', '已支付']}]}
    result = _service(payload).assist(str(DS_ID), {
        'kind': 'values', 'includeSamples': False})

    suggestion = result['suggestions'][0]
    assert suggestion['target'] == 'value'
    assert suggestion['businessName'] == '已支付'
    assert suggestion['aliases'] == ['已付款', '已支付']   # 重复别名只留一个
    assert suggestion['rawValue'] == '1'


def test_assist_requires_tables_in_scope():
    class _Empty(_Repo):
        def list_tables(self, datasource_id):
            return []

    service = Text2SqlService(_Empty(), catalog=_Catalog(),
                              assist_model=lambda *a, **k: ('{}', {}, 'x'))
    with pytest.raises(Text2SqlValidationError):
        service.assist(str(DS_ID), {'kind': 'descriptions'})


def test_unknown_kind_is_rejected():
    service = _service({})
    with pytest.raises(Text2SqlValidationError):
        service.assist(str(DS_ID), {'kind': 'magic'})


USER_TABLE_ID = uuid4()
USER_COLUMN_ID = uuid4()
ORDERS_USER_COLUMN_ID = uuid4()


def _two_tables():
    """固定 id 的两表目录：orders(user_id) ↔ users(user_id)。"""
    orders = _Repo().list_tables(str(DS_ID))[0]
    orders['columns'].append(
        {'id': str(ORDERS_USER_COLUMN_ID), 'column_name': 'user_id',
         'data_type': 'bigint', 'is_primary_key': False, 'is_nullable': True})
    users = {
        'id': str(USER_TABLE_ID), 'schema_name': 'public', 'table_name': 'users',
        'db_comment': None, 'business_name': None, 'business_description': None,
        'enabled': True, 'missing_since': None,
        'columns': [{'id': str(USER_COLUMN_ID), 'column_name': 'user_id',
                     'data_type': 'bigint', 'is_primary_key': True,
                     'is_nullable': False}],
    }
    return [orders, users]


class _TwoTableRepo(_Repo):
    def list_tables(self, datasource_id):
        return _two_tables()


class _RelationCatalog(_Catalog):
    def list_relations(self, datasource_id):
        # 已存在 orders.user_id → users.user_id，模型再提一次应当被丢弃
        return [{
            'id': str(uuid4()), 'relation_name': 'orders_users',
            'source_table': 'public.orders', 'source_table_id': str(TABLE_ID),
            'target_table': 'public.users', 'target_table_id': str(USER_TABLE_ID),
            'cardinality': 'MANY_TO_ONE',
            'column_pairs': [{'source_column_id': str(ORDERS_USER_COLUMN_ID),
                              'target_column_id': str(USER_COLUMN_ID)}],
        }]


def test_relations_resolve_names_and_skip_existing_pairs():
    payload = {'relations': [
        {'sourceTableId': str(TABLE_ID), 'sourceColumnName': 'user_id',
         'targetTableId': str(USER_TABLE_ID), 'targetColumnName': 'user_id',
         'cardinality': 'MANY_TO_ONE', 'reason': '同名字段'},
        {'sourceTableId': str(TABLE_ID), 'sourceColumnName': 'nope',
         'targetTableId': str(USER_TABLE_ID), 'targetColumnName': 'user_id'},
    ]}
    service = Text2SqlService(
        _TwoTableRepo(), catalog=_RelationCatalog(),
        assist_model=lambda *a, **k: (json.dumps(payload, ensure_ascii=False), {}, 'm'))
    result = service.assist(str(DS_ID), {'kind': 'relations', 'includeSamples': False})

    assert result['suggestions'] == []      # 已有关系 + 未知字段都丢弃


def test_relations_are_named_and_carry_column_pairs():
    payload = {'relations': [{
        'sourceTableId': str(TABLE_ID), 'sourceColumnName': 'pay_amount',
        'targetTableId': str(USER_TABLE_ID), 'targetColumnName': 'user_id',
        'cardinality': 'ONE_TO_ONE', 'reason': '样本取值匹配'}]}
    service = Text2SqlService(
        _TwoTableRepo(), catalog=_Catalog(),
        assist_model=lambda *a, **k: (json.dumps(payload, ensure_ascii=False), {}, 'm'))
    result = service.assist(str(DS_ID), {'kind': 'relations', 'includeSamples': False})

    suggestion = result['suggestions'][0]
    assert suggestion['name'].startswith('inferred_orders_users')
    assert suggestion['cardinality'] == 'ONE_TO_ONE'
    assert suggestion['columnPairs'][0]['targetColumnId'] == str(USER_COLUMN_ID)
    assert suggestion['label'].startswith('public.orders.pay_amount →')


class _MetricCatalog(_Catalog):
    def list_metrics(self, datasource_id):
        return [{'metric_key': 'pay_amount_total', 'business_name': '支付总额',
                 'base_table_id': str(TABLE_ID)}]


def test_metrics_validate_expression_and_dedupe_keys():
    payload = {'metrics': [
        {'baseTableId': str(TABLE_ID), 'key': 'pay_amount_total',
         'businessName': '支付总额', 'expressionSql': 'SUM(orders.pay_amount)'},
        {'baseTableId': str(TABLE_ID), 'key': 'bad_column',
         'businessName': '不存在的列', 'expressionSql': 'SUM(orders.nope)'},
        {'baseTableId': str(TABLE_ID), 'key': 'no_aggregate',
         'businessName': '没有聚合', 'expressionSql': 'orders.pay_amount'},
    ]}
    service = Text2SqlService(
        _Repo(), catalog=_MetricCatalog(),
        assist_model=lambda *a, **k: (json.dumps(payload, ensure_ascii=False), {}, 'm'))
    result = service.assist(str(DS_ID), {'kind': 'metrics', 'includeSamples': False})

    metrics = result['suggestions']
    assert len(metrics) == 1
    assert metrics[0]['key'] == 'pay_amount_total_2'   # 与已有指标重名时加后缀
    assert metrics[0]['expressionSql'] == 'SUM(orders.pay_amount)'


def test_questions_are_deduped_and_capped():
    payload = {'questions': [
        {'question': '最近 30 天的支付趋势如何？', 'hint': '订单表'},
        {'question': '最近 30 天的支付趋势如何？', 'hint': '重复'},
        {'question': ''},
    ]}
    service = _service(payload)
    result = service.assist(str(DS_ID), {'kind': 'questions'})

    assert [item['question'] for item in result['suggestions']] == [
        '最近 30 天的支付趋势如何？']
    assert result['suggestions'][0]['target'] == 'question'


def test_query_examples_parser_accepts_strings_and_objects():
    from text_to_sql import models

    fields = models.parse_update_datasource({'queryExamples': [
        '各城市订单量对比', {'question': '支付总额是多少', 'hint': '订单表'}]})
    assert fields['query_examples'] == [
        {'question': '各城市订单量对比', 'hint': ''},
        {'question': '支付总额是多少', 'hint': '订单表'},
    ]
    with pytest.raises(Text2SqlValidationError):
        models.parse_update_datasource({'queryExamples': ['x'] * 9})


def test_prompt_includes_samples_and_ids():
    tables = _Repo().list_tables(str(DS_ID))
    _, user = assist.prompt_for(
        'descriptions',
        datasource={'name': 'Demo', 'database': 'demo'},
        tables=tables, relations=_Catalog().list_relations(str(DS_ID)),
        values=[], samples={'public.orders': [{'order_id': 1, 'pay_amount': 9.9}]})
    assert str(TABLE_ID) in user
    assert 'order_id' in user and '9.9' in user
