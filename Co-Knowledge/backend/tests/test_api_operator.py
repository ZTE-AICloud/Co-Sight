"""NL2API：spec 知识、URL 拼接边界、四段流程。"""

import json

import pytest

from api_operator import knowledge as spec_knowledge
from api_operator.operator import Nl2ApiOperator
from knowledge_engine.operator import OperatorError, QueryOperator

SPEC = {
    'openapi': '3.0.0',
    'info': {'title': '订单服务', 'description': '查询订单'},
    'servers': [{'url': 'https://api.example.com'}],
    'paths': {
        '/orders/{orderId}': {
            'get': {
                'operationId': 'getOrder',
                'summary': '按订单号查询订单详情',
                'parameters': [
                    {'name': 'orderId', 'in': 'path', 'required': True},
                    {'name': 'verbose', 'in': 'query', 'required': False},
                ],
            }
        },
        '/orders': {
            'get': {
                'operationId': 'listOrders',
                'summary': '按城市列出订单',
                'parameters': [
                    {'name': 'city', 'in': 'query', 'required': False},
                ],
            }
        },
    },
}


def _operator(call, captured=None, response=None):
    def http_call(**kwargs):
        if captured is not None:
            captured.append(kwargs)
        return response or {'status': 200, 'json': {'items': [1]}}

    return Nl2ApiOperator(llm=lambda **kwargs: call, spec_loader=lambda key: SPEC,
                          http_call=http_call)


def test_implements_the_operator_protocol():
    assert isinstance(_operator({}), QueryOperator)
    assert _operator({}).name == 'nl2api'


def test_spec_becomes_api_and_endpoint_objects():
    objects = spec_knowledge.build_objects('orders', SPEC)
    assert {item.object_type for item in objects} == {'API', 'ENDPOINT'}
    endpoints = {item.object_key for item in objects if item.object_type == 'ENDPOINT'}
    assert 'GET /orders/{orderId}' in endpoints


def test_full_flow_builds_url_and_executes():
    captured = []
    operator = _operator({'method': 'GET', 'path': '/orders/{orderId}',
                          'pathParams': {'orderId': 'A-1'},
                          'query': {'verbose': '1'}}, captured=captured)
    params = {'spec': SPEC, 'api': 'orders'}
    context = operator.retrieve('订单 A-1 的详情', datasource_id='orders',
                                params={'spec': SPEC})
    plan = operator.plan('订单 A-1 的详情', context, params=params)
    validated = operator.validate(plan, params=params)
    assert validated.details['url'] == 'https://api.example.com/orders/A-1'

    result = operator.execute(validated, params=params)
    assert result.extra['status'] == 200
    assert captured[0]['url'] == 'https://api.example.com/orders/A-1'
    assert captured[0]['params'] == {'verbose': '1'}


@pytest.mark.parametrize('call,code', [
    ({'method': 'DELETE', 'path': '/orders'}, 'API_ENDPOINT_NOT_ALLOWED'),
    ({'method': 'GET', 'path': '/admin/secret'}, 'API_ENDPOINT_NOT_ALLOWED'),
    ({'method': 'GET', 'path': '/orders', 'query': {'password': 'x'}},
     'API_PARAM_NOT_ALLOWED'),
    ({'method': 'GET', 'path': '/orders/{orderId}'}, 'API_PARAM_MISSING'),
    ({'method': 'GET', 'path': '/orders/{orderId}',
      'pathParams': {'orderId': '../admin'}}, 'API_PARAM_NOT_ALLOWED'),
])
def test_validate_rejects_out_of_spec_calls(call, code):
    operator = _operator(call)
    plan = operator.plan('x', operator.retrieve('x', datasource_id='orders',
                                                params={'spec': SPEC}),
                         params={'spec': SPEC, 'api': 'orders'})
    with pytest.raises(OperatorError) as error:
        operator.validate(plan, params={'spec': SPEC, 'api': 'orders'})
    assert error.value.code == code


def test_missing_spec_is_an_operator_error():
    operator = Nl2ApiOperator(llm=lambda **kwargs: {}, spec_loader=lambda key: {})
    with pytest.raises(OperatorError) as error:
        operator.retrieve('x', datasource_id='nope', params={})
    assert error.value.code == 'API_SPEC_NOT_FOUND'


def test_plan_round_trips_json():
    operator = _operator({'method': 'GET', 'path': '/orders',
                          'query': {'city': '西安市'}})
    context = operator.retrieve('西安的订单', datasource_id='orders',
                                params={'spec': SPEC})
    plan = operator.plan('西安的订单', context, params={'spec': SPEC})
    assert json.loads(plan.query)['query'] == {'city': '西安市'}
    assert plan.language == 'http'
