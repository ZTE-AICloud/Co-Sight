"""NL2Search：mapping 知识、DSL 白名单、四段流程。"""

import json

import pytest

from knowledge_engine.operator import OperatorError, QueryOperator
from search_operator import knowledge as mapping_knowledge
from search_operator import validator
from search_operator.operator import Nl2SearchOperator

MAPPING = {
    'doc_kb1': {
        'mappings': {
            'properties': {
                'title': {'type': 'text', 'analyzer': 'ik_smart'},
                'city': {'type': 'keyword'},
                'amount': {'type': 'double'},
                'created_at': {'type': 'date'},
                'meta': {'properties': {'source': {'type': 'keyword'}}},
            }
        }
    }
}
FIELDS = {'title', 'city', 'amount', 'created_at', 'meta.source'}


def _operator(body=None, hits=None):
    return Nl2SearchOperator(
        llm=lambda **kwargs: {'query': body or {'match_all': {}}, 'size': 5},
        mapping_loader=lambda index: MAPPING,
        searcher=lambda index, query: hits or {
            'hits': {'total': {'value': 1},
                     'hits': [{'_id': '1', '_score': 1.2,
                               '_source': {'title': 'x'}}]}})


def test_implements_the_operator_protocol():
    assert isinstance(_operator(), QueryOperator)
    assert _operator().name == 'nl2search'


def test_mapping_becomes_index_and_field_objects():
    objects = mapping_knowledge.build_objects('doc_kb1', MAPPING['doc_kb1']['mappings']['properties'])
    kinds = {item.object_type for item in objects}
    assert kinds == {'INDEX', 'FIELD'}
    paths = {item.object_key for item in objects if item.object_type == 'FIELD'}
    assert 'meta.source' in paths and 'amount' in paths
    assert mapping_knowledge.field_types(
        MAPPING['doc_kb1']['mappings']['properties'])['city'] == 'keyword'


def test_retrieve_focuses_on_question_fields():
    context = _operator().retrieve('按城市过滤金额', datasource_id='doc_kb1',
                                   params={'index': 'doc_kb1'})
    assert 'doc_kb1' in context.text
    assert context.objects


def test_full_flow_generates_validated_and_executed_result():
    operator = _operator(body={'query': {'bool': {'filter': [
        {'term': {'city': '西安市'}}]}}, 'size': 5})
    context = operator.retrieve('西安的记录', datasource_id='doc_kb1',
                                params={'index': 'doc_kb1'})
    plan = operator.plan('西安的记录', context, params={'index': 'doc_kb1'})
    assert plan.language == 'es_dsl'
    validated = operator.validate(plan, params={'index': 'doc_kb1'})
    assert json.loads(validated.query)['size'] == 5
    result = operator.execute(validated, params={'index': 'doc_kb1'})
    assert result.columns == ['_id', '_score', '_source']
    assert result.rows and result.rows[0][0] == '1'


@pytest.mark.parametrize('body,code', [
    ({'query': {'term': {'secret_field': 'x'}}}, 'SEARCH_FIELD_NOT_ALLOWED'),
    ({'query': {'script': {'script': 'x'}}}, 'SEARCH_DSL_DENIED'),
    ({'query': {'wildcard': {'title': 'x*'}}}, 'SEARCH_DSL_DENIED'),
    ({'query': {'match_all': {}}, 'size': 5000}, 'SEARCH_DSL_INVALID'),
    ({'query': {'match_all': {}}, 'routing': 'x'}, 'SEARCH_DSL_INVALID'),
])
def test_validator_rejects(body, code):
    with pytest.raises(OperatorError) as error:
        validator.validate(body, FIELDS)
    assert error.value.code == code


def test_validator_accepts_common_clauses():
    body = {'query': {'bool': {
        'must': [{'match': {'title': '报表'}}],
        'filter': [{'range': {'created_at': {'gte': '2026-01-01'}}},
                   {'terms': {'city': ['西安市']}}],
        'must_not': [{'exists': {'field': 'meta.source'}}],
        'minimum_should_match': 1}},
        'size': 20, 'sort': [{'created_at': 'desc'}],
        '_source': ['title', 'city']}
    assert validator.validate(body, FIELDS) is body


def test_plan_falls_back_to_match_all_when_model_returns_nothing():
    operator = Nl2SearchOperator(llm=lambda **kwargs: {},
                                 mapping_loader=lambda index: MAPPING,
                                 searcher=lambda index, query: {'hits': {'hits': []}})
    context = operator.retrieve('x', datasource_id='doc_kb1', params={'index': 'doc_kb1'})
    plan = operator.plan('x', context, params={'index': 'doc_kb1'})
    assert json.loads(plan.query) == {'query': {'match_all': {}}, 'size': 10}
