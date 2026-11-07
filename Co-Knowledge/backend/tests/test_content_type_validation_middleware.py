"""``ContentTypeValidationMiddleware`` 与业务前缀的回归测试。

中间件的规则是「POST 只允许 json/form/multipart」，命中就回 **415 裸 JSON**
（``{"code": -1, "message": "Unsupported Content-Type: ..."}``）。但
``/api/co-knowledge/v1`` 下的请求体语义由路由层按方法参数绑定方式接管；
中间件在路由之前截成 415 会让这些端点永远出不了正常响应。
本文件钉三件事：

- 业务前缀的 POST 带 text/plain **不再** 415，而是走到路由层、回业务信封；
- 非兼容前缀（RKB 自有契约）保持原行为：POST text/plain → 415；
- ``_route_path`` 剥掉网关 ``root_path``（中间件跑在路由之前，拿不到 ``scope['route']``）。

跑法（服务目录下）::

    python -m pytest tests/test_content_type_validation_middleware.py -q
"""


import pytest

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from starlette.requests import Request  # noqa: E402

from infrastructure.http.middleware.content_type_validation import (  # noqa: E402
    ContentTypeValidationMiddleware,
)
from shared.prefixes import RKB_PREFIX as KBASE_PREFIX
from http_api import register_rkb_api  # noqa: E402
from retrieval.service import retrieve_service as retrieve_service  # noqa: E402


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(retrieve_service, 'retrieve', lambda payload: {'echo': payload})
    app = FastAPI()
    register_rkb_api(app)

    @app.post('/api/other/v1/native-echo')
    async def native_echo():
        return {'ok': True}

    app.add_middleware(ContentTypeValidationMiddleware)
    return TestClient(app, raise_server_exceptions=False)


def test_compat_prefix_text_plain_reaches_router_level_gate(client):
    """修复前：415 裸 JSON；修复后：路由层闸门按媒体类型判 → 200 + 0005+null。"""
    response = client.post(f'{KBASE_PREFIX}/retrieval', content=b'{}',
                           headers={'Content-Type': 'text/plain'})
    assert response.status_code == 415
    assert response.json()['code'] == 'unsupported_media_type'


def test_compat_prefix_absent_content_type_not_gated_by_middleware(client):
    """无 Content-Type 的 POST 同样要走到路由层（结果可能是 0005 或 0004 missing）。"""
    response = client.post(f'{KBASE_PREFIX}/retrieval', content=b'{}')
    assert response.status_code == 415
    assert response.json()['code'] == 'unsupported_media_type'


def test_flow_prefix_text_plain_not_gated_by_middleware(client):
    """flow 的兼容前缀也在放行名单里（未注册路由 → 404，但**不是** 415）。"""
    from shared.prefixes import RKB_PREFIX

    response = client.post(RKB_PREFIX + '/flow/preCheck',
                           content=b'{}', headers={'Content-Type': 'text/plain'})
    assert response.status_code != 415


def test_non_compat_endpoint_text_plain_still_415(client):
    """非兼容前缀不在放行名单：POST + text/plain → 415（老行为原样保留）。"""
    response = client.post('/api/other/v1/native-echo', content=b'{}',
                           headers={'Content-Type': 'text/plain'})
    assert response.status_code == 415
    assert response.json()['code'] == -1


def test_non_compat_endpoint_json_passes(client):
    response = client.post('/api/other/v1/native-echo', content=b'{}',
                           headers={'Content-Type': 'application/json'})
    assert response.status_code == 200
    assert response.json() == {'ok': True}


def test_route_path_strips_gateway_root_path():
    """网关前缀（``root_path``）下兼容前缀判定不能失准 —— 中间件手工剥前缀。"""
    middleware = ContentTypeValidationMiddleware(app=None)
    request = Request({
        'type': 'http', 'method': 'POST', 'path': '/gateway' + KBASE_PREFIX + '/kbase/retrieve',
        'root_path': '/gateway', 'headers': [],
    })
    assert middleware._route_path(request) == KBASE_PREFIX + '/kbase/retrieve'
    assert middleware._is_route_validated_prefix(middleware._route_path(request)) is True
    # 网关前缀下的「非兼容路径」剥掉 root_path 后也不能被误放行
    native = Request({
        'type': 'http', 'method': 'POST', 'path': '/gateway/api/other/v1/x',
        'root_path': '/gateway', 'headers': [],
    })
    assert middleware._route_path(native) == '/api/other/v1/x'
    assert middleware._is_route_validated_prefix(middleware._route_path(native)) is False
