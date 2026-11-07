"""异步端点（``ok_status=202``）返回 ``None`` 时仍须是 202 Accepted。

``dispatch_sync`` 不能把「``ok_status == 204`` **或** 返回值 ``None``」并成同一支
—— ``POST /graph-imports``、``PUT /knowledge-bases/{id}/graph`` 的服务层正常返回
None 表示「已受理、后台执行」，若并成同一支会实际回 204，与 OpenAPI 契约（202）和
``docs/api-reference.md``（「成功 202」）不一致；客户端据此无法区分「已受理」和
「无内容」。
"""

import json

from starlette.requests import Request

from infrastructure.http.rkb_support import dispatch_sync


def make_request(method='POST', path='/api/co-knowledge/v1/graph-imports'):
    return Request({
        'type': 'http',
        'method': method,
        'path': path,
        'headers': [],
        'query_string': b'',
        'client': ('127.0.0.1', 12345),
    })


def test_none_result_with_202_returns_accepted():
    response = dispatch_sync(make_request(), b'', lambda _payload: None, ok_status=202)

    assert response.status_code == 202
    assert json.loads(response.body) == {'accepted': True}


def test_none_result_with_default_status_returns_204():
    response = dispatch_sync(make_request(), b'', lambda _payload: None)

    assert response.status_code == 204


def test_explicit_204_still_wins_over_a_result():
    response = dispatch_sync(make_request(), b'', lambda _payload: {'ignored': True},
                             ok_status=204)

    assert response.status_code == 204
