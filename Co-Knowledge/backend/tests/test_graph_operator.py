"""NL2Graph：schema 知识、类型白名单、四段流程。"""


import pytest

from graph_operator.operator import Nl2GraphOperator, build_objects, normalize
from knowledge_engine.operator import OperatorError, QueryOperator

SCHEMA = {
    'entity_types': {'Company': {'properties': ['name', 'industry']},
                     'City': {'properties': ['name']}},
    'edge_types': {'LOCATED_IN': {'properties': ['since']}},
}


def _operator(call, captured=None, result=None):
    def runner(payload):
        if captured is not None:
            captured.append(payload)
        return result or {'entities': [{'name': '甲公司'}], 'edges': []}

    return Nl2GraphOperator(llm=lambda **kwargs: call,
                            schema_loader=lambda key: SCHEMA, query_runner=runner)


def test_implements_protocol_and_builds_objects():
    assert isinstance(_operator({}), QueryOperator)
    objects = build_objects('kb-1', SCHEMA)
    assert {item['type'] for item in objects} == {'SCHEMA', 'ENTITY_TYPE', 'EDGE_TYPE'}
    assert any('Company' in item['content'] for item in objects)


def test_normalize_accepts_graph_domain_shape():
    normalized = normalize({'vertices': {'Company': [{'name': 'name'}]},
                            'edges': {'LOCATED_IN': {'attrs': ['since']}}})
    assert list(normalized['entity_types']) == ['Company']
    assert normalized['edge_types']['LOCATED_IN']['properties'] == ['since']


def test_full_flow_builds_structured_payload():
    captured = []
    operator = _operator({'query_type': 'sub_graph',
                          'entityTypes': ['Company'], 'edgeTypes': ['LOCATED_IN'],
                          'depth': 2}, captured=captured)
    params = {'schema': SCHEMA, 'kb_id': 'kb-1'}
    context = operator.retrieve('Company 位于哪些城市', datasource_id='kb-1',
                                params=params)
    assert 'Company' in context.text
    plan = operator.plan('Company 位于哪些城市', context, params=params)
    assert plan.language == 'graph_query'

    validated = operator.validate(plan, params=params)
    assert validated.details == {'queryType': 'sub_graph', 'depth': 2}
    result = operator.execute(validated, params=params)
    assert captured[0]['query_type'] == 'sub_graph'
    assert captured[0]['filters'][0]['entity_type'] == ['Company']
    assert result.extra['entityCount'] == 1


@pytest.mark.parametrize('call,code', [
    ({'query_type': 'cypher', 'depth': 1}, 'GRAPH_QUERY_INVALID'),
    ({'query_type': 'entity', 'depth': 9}, 'GRAPH_QUERY_INVALID'),
    ({'query_type': 'entity', 'entityTypes': ['Secret'], 'depth': 1},
     'GRAPH_TYPE_NOT_ALLOWED'),
    ({'query_type': 'path', 'edgeTypes': ['HACKS'], 'depth': 1},
     'GRAPH_TYPE_NOT_ALLOWED'),
])
def test_validate_rejects_out_of_schema_queries(call, code):
    operator = _operator(call)
    params = {'schema': SCHEMA, 'kb_id': 'kb-1'}
    context = operator.retrieve('x', datasource_id='kb-1', params=params)
    plan = operator.plan('x', context, params=params)
    with pytest.raises(OperatorError) as error:
        operator.validate(plan, params=params)
    assert error.value.code == code


def test_missing_schema_is_operator_error():
    operator = Nl2GraphOperator(llm=lambda **kwargs: {},
                                schema_loader=lambda key: {})
    with pytest.raises(OperatorError) as error:
        operator.retrieve('x', datasource_id='nope', params={})
    assert error.value.code == 'GRAPH_SCHEMA_NOT_FOUND'
