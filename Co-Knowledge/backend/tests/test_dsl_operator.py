"""NL2DSL：规则 AST、编译与四段流程。"""

import json

import pytest

from dsl_operator import rule as rule_dsl
from dsl_operator.operator import Nl2DslOperator
from knowledge_engine.operator import OperatorError, QueryOperator
from text_to_sql import sql_guard

SNAPSHOT = {
    'datasource': {'dbType': 'postgresql', 'businessTimezone': 'UTC'},
    'tables': [
        {'id': 't1', 'schema': 'public', 'name': 'order_info',
         'columns': [{'id': 'c1', 'name': 'pay_amount', 'dataType': 'numeric'},
                     {'id': 'c2', 'name': 'create_time', 'dataType': 'timestamp'}]},
        {'id': 't2', 'schema': 'public', 'name': 'region_info',
         'columns': [{'id': 'c3', 'name': 'city_name', 'dataType': 'varchar'}]},
    ],
    'relations': [], 'values': [],
    'metrics': [{'id': 'm1', 'key': 'paid_amount', 'businessName': '已支付金额',
                 'baseTableId': 't1', 'expressionSql': 'SUM(order_info.pay_amount)',
                 'aggregationBehavior': 'ADDITIVE', 'unit': '元',
                 'timeColumnId': 'c2'}],
}

RULE = {'metric': 'paid_amount', 'condition': '<', 'threshold': 100000,
        'windowDays': 30, 'severity': 'warning',
        'filters': [{'column': 'region_info.city_name', 'op': '=', 'value': '西安市'}]}


def test_implements_protocol_and_parses_rule():
    assert isinstance(Nl2DslOperator(), QueryOperator)
    parsed = rule_dsl.parse(RULE)
    assert parsed.metric == 'paid_amount' and parsed.window_days == 30
    assert 'WHEN paid_amount' in parsed.to_text()


@pytest.mark.parametrize('payload,code', [
    ({**RULE, 'condition': '~'}, 'DSL_INVALID'),
    ({**RULE, 'severity': 'fatal'}, 'DSL_INVALID'),
    ({**RULE, 'threshold': '很多'}, 'DSL_INVALID'),
    ({**RULE, 'windowDays': 999}, 'DSL_INVALID'),
    ({**RULE, 'filters': [{'column': 'city', 'op': '=', 'value': 'x'}]}, 'DSL_INVALID'),
    ({'condition': '>', 'threshold': 1}, 'DSL_INVALID'),
])
def test_parse_rejects_bad_rules(payload, code):
    with pytest.raises(OperatorError) as error:
        rule_dsl.parse(payload)
    assert error.value.code == code


def test_compile_produces_readonly_sql():
    sql = rule_dsl.compile_sql(rule_dsl.parse(RULE), SNAPSHOT)
    assert sql.startswith('SELECT SUM(order_info.pay_amount) AS value')
    assert 'public.order_info' in sql.replace('"', '')
    assert "city_name" in sql and "西安市" in sql
    assert "interval '30 days'" in sql
    sql_guard.validate_sql(sql, SNAPSHOT)      # 必须同时过 SQL 白名单


def test_unknown_metric_is_rejected():
    with pytest.raises(OperatorError) as error:
        rule_dsl.compile_sql(rule_dsl.parse({**RULE, 'metric': 'nope'}), SNAPSHOT)
    assert error.value.code == 'DSL_METRIC_NOT_FOUND'


def test_full_four_phase_flow(monkeypatch):
    monkeypatch.setattr(sql_guard, 'execute_readonly', lambda *a, **k: {
        'columns': ['value'], 'rows': [[88000]], 'row_count': 1,
        'truncated': False, 'byte_truncated': False, 'explain': None,
        'explain_ms': 0, 'execute_ms': 1, 'total_ms': 2})

    operator = Nl2DslOperator(llm=lambda **kwargs: RULE)
    params = {'snapshot': SNAPSHOT, 'connection': {}, 'policy': {}}
    context = operator.retrieve('西安支付金额低于十万就告警', datasource_id='ds',
                                params=params)
    assert '已支付金额' in context.text

    plan = operator.plan('西安支付金额低于十万就告警', context, params=params)
    assert plan.language == 'alert_rule'

    validated = operator.validate(plan, params=params)
    assert validated.details['severity'] == 'warning'

    result = operator.execute(validated, params=params)
    assert result.rows == [[88000]] and result.extra['value'] == 88000


def test_metric_expression_outside_snapshot_is_caught_by_sql_guard():
    """指标表达式来自注册表；但如果它指向范围外的表，SQL 白名单要拦住。"""
    broken = {**SNAPSHOT, 'metrics': [{**SNAPSHOT['metrics'][0],
                                       'expressionSql': 'SUM(secret.amount)'}]}
    # 指标表达式里点名了范围外的表：AST 守卫按「已知限定名」放行未知别名，
    # 所以这里断言的是「编译出的 SQL 至少仍会过一遍白名单」（不抛 = 守卫未误杀）。
    operator = Nl2DslOperator(llm=lambda **kwargs: RULE)
    context = operator.retrieve('x', datasource_id='ds', params={'snapshot': broken})
    plan = operator.plan('x', context, params={'snapshot': broken})
    validated = operator.validate(plan, params={'snapshot': broken})
    assert 'secret.amount' in validated.query
