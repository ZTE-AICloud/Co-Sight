"""PG 图谱后端的纯逻辑（过滤条件、行形状、库名规则）。"""

from __future__ import annotations

import json

from graph.repository import graph_pg


def test_condition_builds_parameterized_sql():
    params = []
    assert graph_pg._condition('name', 'Alice', params) == "properties->>'name' = %s"
    assert params == ['Alice']

    params = []
    assert graph_pg._condition('age', {'op': 'gte', 'value': 18}, params) == \
        "(properties->>'age')::numeric >= %s"
    assert params == [18]

    params = []
    assert graph_pg._condition('tags', {'op': 'contains', 'value': 'vip'}, params) == \
        "properties->'tags' @> %s::jsonb"
    assert json.loads(params[0]) == ['vip']

    params = []
    assert graph_pg._condition('name', {'op': 'like', 'value': 'A%'}, params) == \
        "properties->>'name' LIKE %s"
    assert params == ['A%']


def test_condition_rejects_unsafe_property_name():
    try:
        graph_pg._condition('x; DROP TABLE kb_kbase', 'v', [])
    except ValueError:
        return
    raise AssertionError('unsafe property name must be rejected')


def test_vertex_row_keeps_graph_row_shape():
    row = ('Person_1', 'Person', {'name': 'Alice'}, 7)
    shaped = graph_pg._vertex_row(row)

    assert shaped == {'@rid': '#7:0', '@class': 'Person',
                      'entity_id': 'Person_1', 'name': 'Alice'}


def test_edge_row_uses_vertex_rids_for_out_in():
    row = ('Knows_1', 'Knows', 'Person_1', 'Person_2', {'since': '2024'}, 3, 7, 8)
    shaped = graph_pg._edge_row(row)

    assert shaped['@rid'] == '#3:0'
    assert shaped['@class'] == 'Knows'
    assert shaped['source_id'] == 'Person_1'
    assert shaped['target_id'] == 'Person_2'
    assert shaped['out'] == '#7:0'
    assert shaped['in'] == '#8:0'
    assert shaped['since'] == '2024'


def test_graph_db_name_for_query_is_prefix_idempotent():
    assert graph_pg.graph_db_name_for_query('graph_demo') == 'graph_demo'
    assert graph_pg.graph_db_name_for_query('demo') == 'graph_demo'
