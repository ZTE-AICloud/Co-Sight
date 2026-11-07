"""kb_api 兼容层骨架的测试。

覆盖三件必须锁死的事：健康端点的**纯文本**形态（不是信封）、
对外契约信封的**形状**、以及连接库名的窄开关语义。

不依赖 DB / 网络：健康检查是纯文本，信封是纯函数，库名是环境变量。
``compat.kb_api.db`` 的池子是函数内延迟 import，所以 import 本模块不会连 PG。

跑法（服务目录下）::

    python -m pytest tests/test_kb_api_skeleton.py -q
"""

import json

import pytest

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import workflow as flow_api  # noqa: E402
from infrastructure.db import kb as kb_db  # noqa: E402
from infrastructure.http import kb_responses as responses  # noqa: E402
from shared.errors import api as kb_errors  # noqa: E402
from shared.prefixes import RKB_PREFIX as KBASE_PREFIX
from http_api import register_rkb_api
from shared.prefixes import RKB_PREFIX  # noqa: E402


@pytest.fixture()
def client():
    app = FastAPI()
    register_rkb_api(app)
    return TestClient(app)


# ----------------------------------------------------------------------
# 健康检查：对外契约返回的是**纯文本 ok**，不是信封
# （`contracts/openapi/rkb-api.yaml` 记的是 text/plain 示例 ok；
#   compose 的健康检查与 README 的最小链路验证都按它读。）
# ----------------------------------------------------------------------


def test_health_returns_plain_text_ok(client):
    response = client.get(f'{KBASE_PREFIX}/health')

    assert response.status_code == 200
    assert response.text == 'ok'
    assert response.headers['content-type'].startswith('text/plain')


# 健康检查只有唯一端点 `<prefix>/health`；
# `/health/readiness` 与 `/health/msb` 别名不存在。


# ----------------------------------------------------------------------
# 响应信封：形状必须与 flow_api 完全一致（两套兼容层不能漂移）
# ----------------------------------------------------------------------


def test_success_is_plain_json_body():
    """成功响应不再包 ``{code,bo,other}``，body 就是资源本身。"""
    response = responses.success({'id': 'kb-1'})

    assert response.status_code == 200
    assert json.loads(response.body) == {'id': 'kb-1'}


def test_none_becomes_204_no_content():
    assert responses.no_content().status_code == 204
    assert responses.no_content().body == b''


def test_error_is_problem_json_with_real_status():
    """业务错误 → 真实 4xx/5xx + RFC 9457 problem+json。"""
    response = responses.error(kb_errors.KbApiError('kbase.not.exist'), 'zh')

    assert response.status_code == 404
    assert response.headers['content-type'].startswith('application/problem+json')
    payload = json.loads(response.body)
    assert payload['code'] == 'knowledge_base_not_found'
    assert payload['status'] == 404
    assert payload['detail'] == '知识库不存在'
    assert payload['type'] == 'urn:ragstudio:problem:knowledge_base_not_found'


def test_validation_error_uses_422():
    response = responses.error(kb_errors.KbValidationError('request.invalid'), 'zh')

    assert response.status_code == 422
    assert json.loads(response.body)['code'] == 'validation_failed'


def test_key_and_flow_error_mappings_are_shared():
    """kb 与 flow 共用同一张 key→problem 映射，不再各维护一套数字码。"""
    from shared.problem import resolve_problem

    assert resolve_problem(key='kbase.not.exist').status == 404
    assert resolve_problem(key='workflow.not.exist').status == 404
    assert resolve_problem(key='validation_failed').status == 400


def test_public_prefix_is_shared_by_all_three_families():
    """kb / flow / 编排三族**共用**同一个对外前缀。

    共用同一个前缀是设计意图，**且三族的路径不冲突**
    （kb_api ∩ flow_api = 空，编排只有 /query）。
    只有这一条对外前缀，不存在原生前缀。
    """
    assert KBASE_PREFIX == RKB_PREFIX


# ----------------------------------------------------------------------
# 连接库名：窄开关，默认值必须指向本服务的业务库
# ----------------------------------------------------------------------


def test_kbase_db_name_defaults_to_rag_studio():
    """默认 `rag_studio`（知识库业务库），不是 RKB 自己的 `rag_knowledge_base`。

    默认值给错的表现是「表不存在」这类误导性报错 —— 因为 RKB 自有库里根本没有
    ``kb_kbase``/``t_directory``。锁死它。
    """
    import os

    saved = os.environ.pop(kb_db.ENV_DB_NAME, None)
    try:
        assert kb_db.get_kbase_db_name() == 'rag_studio'
    finally:
        if saved is not None:
            os.environ[kb_db.ENV_DB_NAME] = saved


def test_kbase_db_name_is_overridable(monkeypatch):
    monkeypatch.setenv(kb_db.ENV_DB_NAME, 'rag_studio_shadow')

    assert kb_db.get_kbase_db_name() == 'rag_studio_shadow'


def test_kbase_db_name_treats_blank_as_unset(monkeypatch):
    """留空回落默认值。"""

    monkeypatch.setenv(kb_db.ENV_DB_NAME, '   ')

    assert kb_db.get_kbase_db_name() == 'rag_studio'


# ----------------------------------------------------------------------
# 与既有兼容层共存
# ----------------------------------------------------------------------


def test_kb_api_coexists_with_flow_api():
    """两个兼容层挂在同一个 app 上互不影响（装配顺序见 src/app.py）。

    只查路由表、不发请求：flow 的业务端点要连库，这里要验的是「两份注册互不覆盖」，
    不该依赖 PG 是否可达。
    """
    app = FastAPI()
    flow_api.register_flow_api(app)
    register_rkb_api(app)
    client = TestClient(app)

    assert client.get(f'{KBASE_PREFIX}/health').status_code == 200
    from route_helpers import route_paths

    registered = set(route_paths(app))
    assert f'{KBASE_PREFIX}/health' in registered
    assert f'{RKB_PREFIX}/workflows' in registered


# ----------------------------------------------------------------------
# 服务器错误（0001）
# ----------------------------------------------------------------------


def test_server_error_is_500_problem():
    response = responses.server_error('zh')

    assert response.status_code == 500
    payload = json.loads(response.body)
    assert payload['code'] == 'internal_error'
    assert payload['status'] == 500
    assert payload['detail'] == '服务器内部错误，请稍后重试'


def test_server_error_never_leaks_store_detail():
    """存储层的原始错误（含表名/主机/连接信息）不能出现在响应体里。

    ``KbStoreError.detail`` 是给日志与排障用的，目前没有任何序列化出口 ——
    这条测试是「一直保持没有」的守卫：将来谁把 detail 塞进信封，它会红。
    """
    from shared.errors.api import KbStoreError

    raw = 'relation "kb_kbase" does not exist (host=postgresql user=rag db=rag_studio)'
    assert KbStoreError(KbStoreError.DB_ERROR, raw).detail == raw  # 异常本身仍然带着它

    body = responses.server_error('zh').body.decode('utf-8')
    assert 'kb_kbase' not in body
    assert 'postgresql' not in body
    assert 'rag_studio' not in body


# ----------------------------------------------------------------------
# 文案渲染
# ----------------------------------------------------------------------


@pytest.mark.parametrize('raw, expected', [
    # **不是「zh 开头即中文」**：只有 zh_CN 有专属 properties，其余语言都回落到
    # 服务端默认 locale(en_US)。
    ('zh-CN', 'zh'),
    ('zh-cn', 'zh'),      # HTTP 标签大小写不敏感
    ('zh_CN', 'zh'),
    ('zh', 'en'),         # ← 反直觉但实测如此
    ('zh-TW', 'en'),
    ('en-US', 'en'),
    ('de', 'en'),
    ('', 'en'),
    (None, 'en'),
    ('*', 'zh'),          # Tomcat 解析出空语言 → 取基础包，本项目的基础包是中文
])
def test_normalize_language(raw, expected):
    from shared.i18n.messages import normalize_language

    assert normalize_language(raw) == expected


@pytest.mark.parametrize('header, expected', [
    ('zh-CN,zh;q=0.9,en;q=0.8', 'zh'),   # 浏览器实际发的形态
    ('en-US,zh-CN;q=0.9', 'en'),         # 按 q 值取主标签，不是「出现即命中」
    ('zh-CN;q=0.1,en;q=0.9', 'en'),
    ('', 'en'),
    (None, 'en'),
])
def test_preferred_tag_uses_quality_values(header, expected):
    """``Accept-Language`` 的主标签按 q 值取；归一化后对上表的 ``zh``/``en``。"""
    from infrastructure.http.identity import _preferred_tag
    from shared.i18n.messages import normalize_language

    assert normalize_language(_preferred_tag(header)) == expected


def test_language_returns_normalized_value():
    """``identity.language`` 的返回值**已经归一化** —— 调用方不必再猜手上是原始标签还是结果。

    这条约束很要紧：原始标签 ``zh`` 归一化后是 ``en``，两者同名不同义。
    """
    from infrastructure.http.identity import language

    class _Req:
        def __init__(self, header):
            self.headers = {} if header is None else {'accept-language': header}

    assert language(_Req('zh-CN,zh;q=0.9')) == 'zh'
    assert language(_Req('zh')) == 'en'
    assert language(_Req(None)) == 'en'


def test_render_falls_back_to_key_for_unknown_message():
    """未知文案键回落成键名 —— 排障时能立刻看出是哪个键缺了，而不是看到一句空话。"""
    from shared.i18n.messages import render

    assert render('no.such.key', 'zh') == 'no.such.key'


def test_render_survives_argument_count_mismatch(monkeypatch):
    """占位符个数对不上是编码错误：返回带占位符的原文案，不要抛异常盖掉真实错误。"""
    from shared.i18n import messages as messages

    monkeypatch.setitem(messages.MESSAGES, 'test.placeholder', {'zh': '值 {0} 与 {1}', 'en': 'x'})

    assert messages.render('test.placeholder', 'zh', 'only-one') == '值 {0} 与 {1}'


# ----------------------------------------------------------------------
# 连接的事务语义
# ----------------------------------------------------------------------


class _FakeConn:
    """假连接：只记录被调用过的生命周期方法。"""

    def __init__(self, calls, rollback_error=None):
        self.calls = calls
        self.rollback_error = rollback_error

    def commit(self):
        self.calls.append('commit')

    def rollback(self):
        self.calls.append('rollback')
        if self.rollback_error:
            raise self.rollback_error

    def close(self):
        self.calls.append('close')


@pytest.fixture()
def fake_pool(monkeypatch):
    """把 ``kb_db._get_pool`` 换成假的连接池（不连库）。"""
    calls = []

    class _FakePool:
        def getconn(self):
            calls.append(('getconn',))
            return _FakeConn(calls)

        def putconn(self, conn, close=False):
            calls.append(('putconn', close))

    def install(rollback_error=None):
        pool = _FakePool()
        if rollback_error is not None:

            def getconn():
                calls.append(('getconn',))
                return _FakeConn(calls, rollback_error)

            pool.getconn = getconn
        monkeypatch.setattr(kb_db, '_get_pool', lambda _dbname: pool)
        return calls

    return install


def test_connection_commits_on_success(fake_pool):
    """正常退出必须 commit。

    psycopg2 默认 ``autocommit=False``，而连接是裸 ``psycopg2.connect`` ——
    不 commit 就 close 是**隐式回滚**，写入会静默丢失，且不报任何错。
    """
    calls = fake_pool()

    with kb_db.connection() as conn:
        assert isinstance(conn, _FakeConn)

    assert calls == [('getconn',), 'commit', ('putconn', False)]


def test_connection_rolls_back_and_reraises_on_error(fake_pool):
    calls = fake_pool()

    with pytest.raises(RuntimeError, match='boom'):
        with kb_db.connection():
            raise RuntimeError('boom')

    assert calls == [('getconn',), 'rollback', ('putconn', False)]


def test_rollback_failure_does_not_mask_original_error(fake_pool):
    """回滚本身失败（连接已被对端断开/关闭）不能顶掉原始异常，否则真正的错因就丢了。"""
    fake_pool(rollback_error=RuntimeError('connection already closed'))

    with pytest.raises(RuntimeError, match='boom'):
        with kb_db.connection():
            raise RuntimeError('boom')


def test_broken_connection_is_closed_not_returned_to_pool(monkeypatch):
    """连接已断（closed != 0）时必须 putconn(close=True)，不能放回池。"""
    calls = []

    class _BrokenConn(_FakeConn):
        closed = 1

    class _Pool:
        def getconn(self):
            return _BrokenConn(calls)

        def putconn(self, conn, close=False):
            calls.append(('putconn', close))

    monkeypatch.setattr(kb_db, '_get_pool', lambda _dbname: _Pool())

    with kb_db.connection():
        pass

    assert calls == ['commit', ('putconn', True)]


def test_commit_failure_destroys_connection(monkeypatch):
    """commit 失败时连接事务已不可用，必须销毁而不是放回池。"""
    calls = []

    class _CommitFailConn(_FakeConn):
        def commit(self):
            calls.append('commit')
            raise RuntimeError('commit boom')

    class _Pool:
        def getconn(self):
            return _CommitFailConn(calls)

        def putconn(self, conn, close=False):
            calls.append(('putconn', close))

    monkeypatch.setattr(kb_db, '_get_pool', lambda _dbname: _Pool())

    with pytest.raises(RuntimeError, match='commit boom'):
        with kb_db.connection():
            pass

    assert calls == ['commit', ('putconn', True)]
