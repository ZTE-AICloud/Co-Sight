"""前缀收敛后的路由归属与异常通道。

收敛把三族路由折进同一个前缀，由此产生两类**只在同前缀下才存在**的静默故障：

1. **兜底路由吃掉编排的 `/query`**。kb_api 兼容层带一条
   ``@router.api_route('/{unknown_path:path}')``，同前缀下它会接住任何它没定义的路径。
   注册顺序错了（编排在 kb_api **之后**）时，提问会拿到 ``0005 + msg:null`` 信封
   —— HTTP 200、不抛异常、日志里也没有错误，只是「回答不对」。

2. **编排的 422 被 kb 的校验处理器接管**。前端 ``streamPost`` 与工具脚本读的是
   FastAPI 默认的 ``{"detail": ...}``；被接管会变成 kb 的 ``0004`` 信封，形状完全不同。

两条都不会让既有测试变红，所以在这里显式钉住。
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from http_api import register_rkb_api
from shared.prefixes import RKB_PREFIX
from chat.router import register_query_api


def _app_in_production_order() -> FastAPI:
    """按 `src/app.py` 的**真实顺序**装配：编排 → flow → kb（kb 的兜底必须最后）。"""
    app = FastAPI()
    register_query_api(app, RKB_PREFIX)
    register_rkb_api(app)
    return app


def test_query_is_owned_by_orchestration_not_the_kb_catch_all():
    """`<prefix>/query` 必须命中编排 handler，而不是 kb 的兜底。

    判据用「空 body」这条：kb 的兜底路由对任何路径都回 **200 + 0005 信封**，
    而编排自己的 FastAPI 校验会回 **422**。所以 422 本身就是归属证据
    （这也是为什么不能只看「有没有报错」—— 兜底那条连状态码都是 200）。
    """
    client = TestClient(_app_in_production_order())

    response = client.post(f'{RKB_PREFIX}/query', json={})

    assert response.status_code == 422, \
        f'没落到编排的校验上（疑似被 kb 兜底接走）：{str(response.json())[:200]}'
    assert not isinstance(response.json().get('code'), dict)


def test_valid_query_reaches_the_orchestration_handler(monkeypatch):
    """正向：入参合法时确实进编排的 handler（而不是停在某个兜底上）。"""
    import chat.app as app_module

    class _FakeEngine:
        def query(self, question):
            class _R:
                response = '答案'
            return _R()

    monkeypatch.setattr(app_module.rag, 'build_query_engine',
                        lambda rag_request, headers, *a, **kw: _FakeEngine())

    client = TestClient(_app_in_production_order())
    body = client.post(f'{RKB_PREFIX}/query',
                       json={'question': '知识库怎么用？', 'conversation_id': 'd-prefix-1'}).json()

    assert body.get('answer') == '答案', f'编排没处理这条请求：{str(body)[:200]}'
    assert 'code' not in body


def test_query_traces_route_is_not_swallowed_by_kb_catch_all(monkeypatch):
    """`<prefix>/query-traces` 必须在 kb 兜底之前注册（GET 不是 kb 的 0005 信封）。"""
    from chat import trace_service

    monkeypatch.setattr(trace_service, 'list_traces', lambda **kwargs: ([], 0))

    response = TestClient(_app_in_production_order()).get(f'{RKB_PREFIX}/query-traces')

    assert response.status_code == 200
    assert response.json()['total'] == 0
    assert not isinstance(response.json().get('code'), dict)


def test_kb_family_still_owns_its_own_paths():
    """同一前缀下 kb 家族的路由照旧（收敛不能把它们的归属改掉）。"""
    client = TestClient(_app_in_production_order())

    health = client.get(f'{RKB_PREFIX}/health')
    assert health.status_code == 200
    assert health.text.strip() == 'ok', 'kb 的 /health 是纯文本 ok（契约与 verify 脚本按它读）'


def test_orchestration_422_is_a_problem_response():
    """编排的入参错误也走统一契约：422 + problem+json，不是旧信封。"""
    client = TestClient(_app_in_production_order())

    response = client.post(f'{RKB_PREFIX}/query', json={'question': '只有问题'})

    assert response.status_code == 422
    assert response.headers['content-type'].startswith('application/problem+json')
    body = response.json()
    assert body['code'] == 'validation_failed'
    assert not isinstance(body.get('code'), dict)


def test_unknown_path_under_prefix_still_falls_into_kb_catch_all():
    """反向哨兵：兜底还在 —— 别把 carve-out 做成「整条前缀都不接管」。"""
    client = TestClient(_app_in_production_order())

    response = client.get(f'{RKB_PREFIX}/definitely-not-a-route')
    body = response.json()

    assert response.status_code == 404, 'kb 兜底路由消失了，若是有意为之请更新本用例'
    assert body['code'] == 'not_found'
