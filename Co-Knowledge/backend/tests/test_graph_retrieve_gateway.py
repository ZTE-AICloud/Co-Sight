"""``graph/service/graph_retrieve_gateway.py``：检索结果的成功/失败契约。

``POST /retrieval/graph`` 遵循统一 REST 契约：
* 成功返回检索结果对象**本身**；
* 失败抛 :class:`GraphRetrieveError`，携带 problem 规格 + 本地化 detail，
  HTTP 侧映射真实状态码 + ``application/problem+json``，进程内侧映射同形 dict。
"""
from __future__ import annotations

import pytest

from graph.models.graph_retrieve_dto import GraphRetrieveDto
from shared.errors.exception import EMException
from graph.service import graph_retrieve_gateway as gateway


class _Headers:
    def __init__(self, language='zh'):
        self._language = language

    def get_language_option(self):
        return self._language


def _dto():
    return GraphRetrieveDto(query='q', embedding='e', bases=['graph_kb_1'])


def _fake_service(monkeypatch, result=None, error=None):
    class _Service:
        def retrieve_graph(self, retrieve_dto, http_headers):
            if error is not None:
                raise error
            return result

    monkeypatch.setattr(gateway, 'GraphQueryService', _Service)


def test_success_returns_the_result_object_without_an_envelope(monkeypatch):
    result = {'base_results': [{'base': 'graph_kb_1'}], 'base_count': 1}
    _fake_service(monkeypatch, result=result)

    assert gateway.retrieve_result(_dto(), _Headers('zh')) == result


def test_business_error_maps_to_a_problem_spec(monkeypatch):
    _fake_service(monkeypatch, error=EMException('database-operation-failed'))

    with pytest.raises(gateway.GraphRetrieveError) as excinfo:
        gateway.retrieve_result(_dto(), _Headers('zh'))

    error = excinfo.value
    assert error.spec.status == 500
    assert error.spec.code == 'internal_error'
    assert '失败' in error.detail or '错误' in error.detail


def test_embedding_failure_is_an_upstream_problem(monkeypatch):
    _fake_service(monkeypatch, error=EMException('embedding-service-error'))

    with pytest.raises(gateway.GraphRetrieveError) as excinfo:
        gateway.retrieve_result(_dto(), _Headers('en'))

    assert excinfo.value.spec.status == 502
    assert excinfo.value.spec.code == 'upstream_unavailable'


def test_unexpected_error_is_internal_error(monkeypatch):
    _fake_service(monkeypatch, error=RuntimeError('boom'))

    with pytest.raises(gateway.GraphRetrieveError) as excinfo:
        gateway.retrieve_result(_dto(), _Headers('en'))

    assert excinfo.value.spec.status == 500
    assert excinfo.value.spec.code == 'internal_error'
    assert excinfo.value.detail == 'Internal server error; try again later'


def test_unknown_business_code_falls_back_to_internal_error():
    assert gateway.graph_problem_spec('something-new').code == 'internal_error'
