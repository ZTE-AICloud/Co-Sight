"""结构防线：设计/发布库状态与图谱 scope 不得复活。"""

from __future__ import annotations

import inspect

from graph.models.graph_query_dto import GraphQueryDto
from graph.models.graph_retrieve_dto import GraphRetrieveDto
from infrastructure.db.pool import DatabaseOperator


def test_database_operator_has_no_design_publish_modes():
    for name in ('get_publish_db_conn', 'get_desigh_db_conn', '_get_db_conn_by_mode',
                 'create_extension', 'truncate_async', 'back'):
        assert not hasattr(DatabaseOperator, name), f'{name} should be removed'


def test_parameterized_query_signature_has_no_mode_or_database():
    params = list(inspect.signature(
        DatabaseOperator.pg_select_zip_values_operator_with_params).parameters)
    assert params == ['self', 'sql', 'params']


def test_graph_dtos_have_no_scope():
    assert 'scope' not in GraphRetrieveDto.model_fields
    assert 'scope' not in GraphQueryDto.model_fields


def test_graph_retrieve_dto_has_no_mode_helpers():
    for name in ('get_mode', 'get_dbname'):
        assert not hasattr(GraphRetrieveDto, name), f'{name} should be removed'
    assert not hasattr(GraphQueryDto, 'get_dbname')
