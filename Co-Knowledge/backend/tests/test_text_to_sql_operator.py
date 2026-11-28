"""Text2SQL 作为 Query Operator：四段契约与注册表。"""

import pytest

from knowledge_engine.operator import (OperatorRegistry, QueryOperator,
                                       QueryPlan)
from text_to_sql import sql_guard
from text_to_sql.operator import Text2SqlOperator, get_operator

SNAPSHOT = {
    'datasource': {'dbType': 'postgresql', 'businessTimezone': 'UTC'},
    'tables': [{'id': 't1', 'schema': 'public', 'name': 'orders',
                'columns': [{'id': 'c1', 'name': 'id', 'dataType': 'bigint'},
                            {'id': 'c2', 'name': 'amount', 'dataType': 'numeric'}]}],
    'relations': [], 'values': [], 'metrics': [],
}

HITS = [{'object_type': 'TABLE', 'object_key': 't1', 'table_id': 't1',
         'score': 0.9}]


def _operator():
    return Text2SqlOperator(llm=lambda **kwargs: {
        'sql': 'SELECT count(*) FROM public.orders',
        'explanation': '统计订单数',
        'usage': {'total_tokens': 42}})


def test_implements_the_protocol_and_is_registered():
    operator = get_operator()
    assert isinstance(operator, QueryOperator)
    assert operator.name == 'nl2sql'
    assert 'TABLE' in operator.knowledge_types

    from knowledge_engine.operator import registry
    assert 'nl2sql' in registry.names()
    assert any(item['name'] == 'nl2sql' for item in registry.describe())


def test_retrieve_uses_retrieval_hits_to_pick_tables():
    operator = _operator()
    context = operator.retrieve('订单数', datasource_id='ds',
                                params={'snapshot': SNAPSHOT, 'hits': HITS})
    assert 'public.orders' in context.text
    assert context.objects == [{'type': 'TABLE', 'name': 'public.orders'}]
    assert context.fallback is False


def test_full_four_phase_flow(monkeypatch):
    monkeypatch.setattr(sql_guard, 'execute_readonly', lambda *a, **k: {
        'columns': ['count'], 'rows': [[3]], 'row_count': 1, 'truncated': False,
        'byte_truncated': False, 'explain': None, 'explain_ms': 0,
        'execute_ms': 1, 'total_ms': 2})

    operator = _operator()
    params = {'snapshot': SNAPSHOT, 'connection': {}, 'policy': {}}
    context = operator.retrieve('订单数', datasource_id='ds',
                                params={**params, 'hits': HITS})
    plan = operator.plan('订单数', context, params=params)
    assert isinstance(plan, QueryPlan) and plan.language == 'sql'
    assert plan.usage == {'total_tokens': 42}

    validated = operator.validate(plan, params=params)
    assert validated.query.startswith('SELECT')

    result = operator.execute(validated, params=params)
    assert result.rows == [[3]] and result.truncated is False


def test_validate_rejects_out_of_scope_query():
    operator = _operator()
    plan = QueryPlan(query='SELECT * FROM public.secret', language='sql')
    with pytest.raises(sql_guard.SqlGuardError) as error:
        operator.validate(plan, params={'snapshot': SNAPSHOT})
    assert error.value.code == 'SQL_TABLE_NOT_ALLOWED'


def test_registry_rejects_duplicate_lookup_misses():
    registry = OperatorRegistry()
    with pytest.raises(KeyError):
        registry.get('nope')
    with pytest.raises(ValueError):
        registry.register(object())
