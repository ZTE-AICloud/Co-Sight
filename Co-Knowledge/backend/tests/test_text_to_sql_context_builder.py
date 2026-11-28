"""Context Builder：检索命中决定选表，预算决定取舍。"""

from text_to_sql import context_builder


def _table(table_id, name, columns, description=''):
    return {
        'id': table_id, 'schema': 'public', 'name': name,
        'businessDescription': description,
        'columns': [{'id': f'{table_id}-{column}', 'name': column,
                     'dataType': 'text'} for column in columns],
    }


def _snapshot(tables, relations=(), values=(), metrics=()):
    return {'datasource': {'dbType': 'postgresql', 'businessTimezone': 'UTC'},
            'tables': list(tables), 'relations': list(relations),
            'values': list(values), 'metrics': list(metrics)}


def _hit(object_type, table_id, score=0.5):
    return {'object_type': object_type, 'table_id': table_id,
            'object_key': table_id, 'score': score}


ORDERS = _table('t1', 'order_info', ['order_id', 'user_id', 'pay_amount'],
                '订单主表')
USERS = _table('t2', 'user_info', ['user_id', 'city_id'], '用户表')
REGIONS = _table('t3', 'region_info', ['city_id', 'city_name'], '城市表')
AUDIT = _table('t4', 'audit_log', ['log_id', 'payload'], '审计日志')

RELATIONS = [
    {'id': 'r1', 'name': 'order_user', 'cardinality': 'MANY_TO_ONE',
     'sourceTableId': 't1', 'targetTableId': 't2',
     'columnPairs': [{'sourceColumnId': 't1-user_id', 'targetColumnId': 't2-user_id'}]},
    {'id': 'r2', 'name': 'user_city', 'cardinality': 'MANY_TO_ONE',
     'sourceTableId': 't2', 'targetTableId': 't3',
     'columnPairs': [{'sourceColumnId': 't2-city_id', 'targetColumnId': 't3-city_id'}]},
]


def test_retrieval_decides_which_tables_enter_context():
    snapshot = _snapshot([ORDERS, USERS, REGIONS, AUDIT], RELATIONS)

    orders_only = context_builder.build(snapshot, [_hit('TABLE', 't1', 0.9)])
    # 订单表是种子，用户表由关系扩展补进来；城市表两跳也补；审计日志无关。
    assert orders_only.tables == ['public.order_info', 'public.user_info',
                                  'public.region_info']
    assert 'public.audit_log' not in orders_only.text
    assert orders_only.fallback is False

    audit_only = context_builder.build(snapshot, [_hit('TABLE', 't4', 0.9)])
    assert audit_only.tables == ['public.audit_log']
    assert 'public.order_info' not in audit_only.text


def test_no_hits_falls_back_to_full_snapshot():
    snapshot = _snapshot([ORDERS, AUDIT])
    result = context_builder.build(snapshot, [])
    assert result.fallback is True
    assert set(result.tables) == {'public.order_info', 'public.audit_log'}


def test_relations_only_rendered_when_both_ends_selected():
    snapshot = _snapshot([ORDERS, USERS, REGIONS], RELATIONS)
    text = context_builder.build(snapshot, [_hit('TABLE', 't1')]).text
    assert 'order_user' in text and 'user_city' in text

    only_orders = _snapshot([ORDERS], [])
    assert '表关联' not in context_builder.build(only_orders, [_hit('TABLE', 't1')]).text


def test_table_budget_marks_omitted_instead_of_truncating_mid_table():
    tables = [_table(f't{i}', f'table_{i:02d}', ['a', 'b', 'c']) for i in range(8)]
    snapshot = _snapshot(tables)
    result = context_builder.build(
        snapshot, [], budget=context_builder.ContextBudget(max_tables=3))
    assert len(result.tables) == 3
    assert len(result.omitted_tables) == 5
    assert result.truncated is True
    # 每张渲染出来的表都完整出现三列，不会出现半行。
    for name in result.tables:
        assert result.text.count(name) >= 1
    assert result.text.count('    a text') == 3


def test_char_budget_stops_before_a_table_and_lists_it_as_omitted():
    tables = [_table(f't{i}', f'table_{i:02d}', ['a', 'b', 'c'],
                     description='说明' * 60) for i in range(6)]
    snapshot = _snapshot(tables)
    result = context_builder.build(
        snapshot, [], budget=context_builder.ContextBudget(max_chars=900))
    assert result.truncated is True
    assert result.omitted_tables
    assert '上下文超出预算' in result.text
    # 没有把某张表写成半截：渲染出的每张表都带齐三列。
    assert result.text.count('    c text') == len(result.tables)


def test_values_and_metrics_filtered_to_selected_tables():
    snapshot = _snapshot(
        [ORDERS, USERS],
        values=[{'id': 'v1', 'columnId': 't1-pay_amount', 'rawValue': '2',
                 'businessName': '已支付'},
                {'id': 'v2', 'columnId': 't2-city_id', 'rawValue': '1',
                 'businessName': '西安市'}],
        metrics=[{'id': 'm1', 'key': 'gmv', 'businessName': '成交额',
                  'baseTableId': 't1', 'expressionSql': 'SUM(pay_amount)',
                  'aggregationBehavior': 'ADDITIVE'},
                 {'id': 'm2', 'key': 'users', 'businessName': '用户数',
                  'baseTableId': 't2', 'expressionSql': 'COUNT(*)',
                  'aggregationBehavior': 'ADDITIVE'}])
    text = context_builder.build(snapshot, [_hit('TABLE', 't1')]).text
    assert '已支付' in text and '西安市' not in text
    assert 'gmv' in text and 'users' not in text


def test_column_hit_pulls_in_its_table():
    snapshot = _snapshot([ORDERS, AUDIT])
    hit = {'object_type': 'COLUMN', 'column_id': 't4-log_id',
           'object_key': 't4-log_id', 'score': 0.7}
    result = context_builder.build(snapshot, [hit])
    assert result.tables == ['public.audit_log']


def test_wide_table_keeps_essential_columns_with_explicit_omission():
    """整表放不下时保留 JOIN 键/度量/时间，并写明省略了多少列。"""
    wide = _table('t9', 'wide_table',
                  ['id', 'user_id', 'amount', 'created_at'] + [f'filler_{i}' for i in range(40)])
    other = _table('t1', 'order_info', ['order_id', 'user_id'])
    relation = {'id': 'r9', 'name': 'wide_user', 'type': 'FOREIGN_KEY',
                'sourceTableId': 't9', 'targetTableId': 't1',
                'columnPairs': [{'sourceColumnId': 't9-user_id',
                                 'targetColumnId': 't1-user_id'}]}
    snapshot = _snapshot([wide, other], [relation])
    result = context_builder.build(
        snapshot, [], budget=context_builder.ContextBudget(max_chars=700, max_tables=4))
    assert 'public.wide_table' in result.text
    assert 'user_id' in result.text          # JOIN 键保留
    assert '已省略' in result.text
    assert 'filler_0' not in result.text


def test_relation_expansion_prefers_verified_relations():
    """表数预算紧张时，先扩展已验证/外键关系，再扩展推断关系。"""
    hub = _table('h', 'hub', ['id'])
    trusted = _table('t1', 'trusted', ['id'])
    guessed = _table('t2', 'guessed', ['id'])
    relations = [
        {'id': 'r1', 'name': 'hub_guessed', 'type': 'INFERRED',
         'sourceTableId': 'h', 'targetTableId': 't2', 'columnPairs': []},
        {'id': 'r2', 'name': 'hub_trusted', 'type': 'FOREIGN_KEY', 'verified': True,
         'sourceTableId': 'h', 'targetTableId': 't1', 'columnPairs': []},
    ]
    snapshot = _snapshot([hub, trusted, guessed], relations)
    result = context_builder.build(
        snapshot, [_hit('TABLE', 'h')],
        budget=context_builder.ContextBudget(max_tables=2))
    assert result.tables == ['public.hub', 'public.trusted']
    assert 'public.guessed' in result.omitted_tables


def test_metric_dependencies_are_pulled_into_context():
    """指标依赖的字段必须进上下文——否则模型知道怎么算、找不到算谁。"""
    orders = _table('t1', 'order_info', ['order_id', 'status', 'pay_amount'])
    wide = _table('t9', 'wide_metric_table',
                  ['id', 'status', 'pay_amount'] + [f'filler_{i}' for i in range(30)])
    snapshot = _snapshot(
        [orders, wide],
        metrics=[{'id': 'm1', 'key': 'gmv', 'businessName': '成交额',
                  'baseTableId': 't9', 'expressionSql': 'SUM(pay_amount)',
                  'aggregationBehavior': 'ADDITIVE',
                  'columnDependencies': [{'columnId': 't9-pay_amount',
                                          'role': 'MEASURE'},
                                         {'columnId': 't9-status',
                                          'role': 'FILTER'}]}])
    result = context_builder.build(
        snapshot, [_hit('TABLE', 't9')],
        budget=context_builder.ContextBudget(max_chars=450, max_tables=2))
    assert 'gmv' in result.text
    assert 'pay_amount' in result.text      # 度量字段保留
    assert 'status' in result.text          # 过滤字段保留
    assert '已省略' in result.text
