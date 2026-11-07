"""连续斜杠折叠（容忍路径里的空段）。

背景：``GET <RKB_PREFIX>//operator/template/download?operatorType=text_split``
必须返回真 ZIP，``///`` 也一样；Starlette 精确匹配会落兜底 0005。
web 的 ``api/operator.js`` 正是发双斜杠的 —— 不折叠，「下载模板」就是死的。

跑法::

    python -m pytest tests/test_path_normalization.py -q
"""


from fastapi import FastAPI
from fastapi.testclient import TestClient

from http_api import register_rkb_api  # noqa: E402
from infrastructure.http.path_normalization import CollapseDuplicateSlashesMiddleware  # noqa: E402


def _app(with_middleware: bool) -> TestClient:
    app = FastAPI()
    if with_middleware:
        app.add_middleware(CollapseDuplicateSlashesMiddleware)
    register_rkb_api(app)
    return TestClient(app)


# ``GET /operators/types``：纯静态端点（不碰库/文件），用来隔离路由行为
from shared.prefixes import RKB_PREFIX  # noqa: E402

TYPES = RKB_PREFIX + '/operators/types'


def test_double_slash_without_middleware_falls_into_catch_all():
    """对照组：不装中间件时，``//`` 命中兜底 → 0005（就是浏览器 E2E 看到的症状）。"""
    response = _app(with_middleware=False).get(RKB_PREFIX + '//operators/types')
    assert response.status_code == 404
    assert response.json()['code'] == 'not_found'


def test_double_slash_hits_the_real_route_with_middleware():
    response = _app(with_middleware=True).get(RKB_PREFIX + '//operators/types')
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_triple_slash_also_collapses():
    """``///`` 也必须能匹配（AntPathMatcher 丢空段）。"""
    response = _app(with_middleware=True).get(RKB_PREFIX + '///operators/types')
    assert response.status_code == 200


def test_single_slash_untouched():
    response = _app(with_middleware=True).get(TYPES)
    assert response.status_code == 200


def test_unit_scope_rewriting():
    """纯 ASGI 层：看下游收到的 scope（path 与 raw_path 都折叠，query 不动）。"""
    import asyncio

    seen = {}

    async def downstream(scope, receive, send):
        seen['path'] = scope['path']
        seen['raw_path'] = scope.get('raw_path')
        seen['query_string'] = scope['query_string']

    middleware = CollapseDuplicateSlashesMiddleware(downstream)
    scope = {'type': 'http', 'path': '//a///b', 'raw_path': b'//a///b?x=1',
             'query_string': b'x=1'}
    asyncio.run(middleware(scope, None, None))
    assert seen['path'] == '/a/b'
    assert seen['raw_path'] == b'/a/b?x=1'
    assert seen['query_string'] == b'x=1'


def test_unit_scope_untouched_when_no_duplicates():
    import asyncio

    seen = {}

    async def downstream(scope, receive, send):
        seen['scope'] = scope

    middleware = CollapseDuplicateSlashesMiddleware(downstream)
    scope = {'type': 'http', 'path': '/a/b/', 'raw_path': b'/a/b/'}
    asyncio.run(middleware(scope, None, None))
    # 单个尾斜杠**不动**（/kbase/ 那条的差异是另一回事，见模块头注释）
    assert seen['scope'] is scope
