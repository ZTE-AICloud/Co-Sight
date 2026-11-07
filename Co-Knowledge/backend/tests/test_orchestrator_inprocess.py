"""编排 ↔ RKB 的进程内传输契约。

合并把编排对 RKB 的四条调用从 HTTP 换成进程内。风险不在「能不能跑通」，
而在**信封形状悄悄变了**：编排那四个客户端是 vendored 件，它们照旧按
「状态码 → 业务码 → 取 bo/data」解析；一旦这边少一个字段或多一层包装，
症状是「检索返回空、回答像兜底话术」，HTTP 200、日志无异常。

所以这里逐条钉住**客户端真正读的那些字段**（不是「响应大体正确」）。
"""

import pathlib

import pytest

from chat.adapters import rkb_inprocess
from workflow import runtime as flow_runtime
from shared.errors.api import KbValidationError

# 编排侧（同仓，服务根在 pythonpath 上）
from chat.gateways import rkb_transport

# ---------------------------------------------------------------------------
# 1) 检索
# ---------------------------------------------------------------------------


class _FakeRetrieve:
    def __init__(self, result):
        self._result = result
        self.calls = []

    def __call__(self, body):
        self.calls.append(body)
        return self._result


def test_retrieve_envelope_matches_kb_style(monkeypatch):
    """`bo` 是列表、`code.code` 是 '0000' —— 编排按这两条判成功。"""
    rows = [{'baseName': 'b', 'documents': []}]
    fake = _FakeRetrieve(rows)
    monkeypatch.setattr(rkb_inprocess.retrieve_service, 'retrieve', fake)

    resp = rkb_inprocess.post_retrieve({'question': 'x', 'bases': [{}], 'type': 0})

    assert resp.status_code == 200
    assert resp.json() == rows, '纯 REST 下 body 就是结果列表'


def test_retrieve_validation_error_becomes_non_success_envelope(monkeypatch):
    """校验失败在 HTTP 时代是 200 + `0004`，**不是** 4xx。

    编排据此走 `code != '0000'` → `request-knowledgebase-failed` 分支。
    若这里改成抛异常或返回 4xx，编排的行为就变了（错误键会换一个）。
    """
    def _raise(_body):
        raise KbValidationError('retrieve.question.required')

    monkeypatch.setattr(rkb_inprocess.retrieve_service, 'retrieve', _raise)

    resp = rkb_inprocess.post_retrieve({'bases': [{}]})

    assert resp.status_code == 422
    assert resp.json()['code'] == 'validation_failed'


def test_retrieve_unexpected_error_is_200_with_server_code(monkeypatch):
    def _boom(_body):
        raise RuntimeError('boom')

    monkeypatch.setattr(rkb_inprocess.retrieve_service, 'retrieve', _boom)
    resp = rkb_inprocess.post_retrieve({})

    assert resp.status_code == 500
    assert resp.json()['code'] == 'internal_error'


# ---------------------------------------------------------------------------
# 2) 知识库列表
# ---------------------------------------------------------------------------


def test_kbase_list_envelope_and_missing_table_name(monkeypatch):
    """`list_authority_kbases` 的 VO 不设 tableName 是**现存行为**。

    编排的 `invoke_list_vector_knowledge_bases` 只收 tableName → 恒为空 →
    抛 `knowledgebase-not-imported`。合并前后一致，这里钉住「不要顺手修好」。
    """
    monkeypatch.setattr(rkb_inprocess.kbase_service, 'list_authority_kbases',
                        lambda org_id=None: [{'name': 'kb1', 'id': 1, 'tableName': None}])

    payload = rkb_inprocess.get_kbase_list().json()

    assert payload == [{'name': 'kb1', 'id': 1, 'tableName': None}]


# ---------------------------------------------------------------------------
# 3) 图谱检索（成功体就是结果对象；失败是真实状态码 + problem）
# ---------------------------------------------------------------------------


def test_graph_retrieve_payload_is_the_plain_result(monkeypatch):
    # 注意补丁目标：`rkb_inprocess` 是**按名导入**该函数的，所以要补丁它自己模块里的
    # 那个绑定，补丁 gateway 模块属性无效（这正是「按名导入 vs 按模块引用」的经典差别）。
    monkeypatch.setattr(rkb_inprocess, 'retrieve_result_from_payload',
                        lambda payload, headers=None: {'nodes': []})

    response = rkb_inprocess.post_graph_retrieve({'question': 'q'})

    assert response.status_code == 200
    assert response.json() == {'nodes': []}


def test_graph_retrieve_failure_maps_to_problem(monkeypatch):
    from graph.service.graph_retrieve_gateway import GraphRetrieveError
    from shared.problem import UPSTREAM_UNAVAILABLE

    def _raise(payload, headers=None):
        raise GraphRetrieveError(UPSTREAM_UNAVAILABLE, 'embedding down')

    monkeypatch.setattr(rkb_inprocess, 'retrieve_result_from_payload', _raise)

    response = rkb_inprocess.post_graph_retrieve({'question': 'q'})

    assert response.status_code == 502
    assert response.json()['code'] == 'upstream_unavailable'
    assert response.json()['detail'] == 'embedding down'


def test_graph_retrieve_propagates_validation_error(monkeypatch):
    """入参不符合契约 → **原样抛**，由 transport 映射（对应 HTTP 时代的 422）。"""
    from pydantic import ValidationError

    def _raise(payload, headers=None):
        raise ValidationError.from_exception_data('GraphRetrieveDto', [])

    monkeypatch.setattr(rkb_inprocess, 'retrieve_result_from_payload', _raise)

    with pytest.raises(ValidationError):
        rkb_inprocess.post_graph_retrieve({'bad': 'shape'})


# ---------------------------------------------------------------------------
# 4) 画布配置
# ---------------------------------------------------------------------------


class _FakeFlowService:
    def __init__(self, canvas=None, error=None):
        self._canvas = canvas
        self._error = error
        self.scopes = []

    def get_flow_config(self, app_id, language):
        self.scopes.append('dev')
        if self._error:
            raise self._error
        return self._canvas

    def get_published_flow_config(self, app_id, language):
        self.scopes.append('published')
        if self._error:
            raise self._error
        return self._canvas


def test_flow_config_scope_selects_draft_or_published(monkeypatch):
    canvas = {'nodeConfigDTOList': [], 'otherNodeConfigList': [], 'version': 3}
    fake = _FakeFlowService(canvas=canvas)
    monkeypatch.setattr(flow_runtime, 'get_flow_service', lambda: fake)

    payload = rkb_inprocess.get_flow_config('wf1', scope='dev').json()
    assert fake.scopes == ['dev'], "scope='dev' 必须读草稿"
    assert payload == canvas

    rkb_inprocess.get_flow_config('wf1', scope='')
    assert fake.scopes[-1] == 'published', '默认必须读发布快照'


def test_flow_config_error_is_non_success_envelope(monkeypatch):
    """没有发布过 → 非 `0000` 信封 → 编排映射成 published-workflow-not-found。"""
    monkeypatch.setattr(flow_runtime, 'get_flow_service',
                        lambda: _FakeFlowService(error=RuntimeError('published.not.exist')))

    resp = rkb_inprocess.get_flow_config('wf1')

    assert resp.status_code == 500
    assert resp.json()['code'] == 'internal_error'


# ---------------------------------------------------------------------------
# 5) transport 的分派与失败形状
# ---------------------------------------------------------------------------


def test_transport_is_a_thin_facade_over_the_inprocess_surface(monkeypatch):
    """transport 的四个函数各自直通 `rkb_inprocess` 的对应入口。

    合并前它们拼 URL 再发 HTTP；现在按**逻辑名**直调 —— 所以这里断言的是
    「参数原样传到、返回值原样带回」，而不再有 URL 可断言。
    """
    seen = []

    monkeypatch.setattr(rkb_inprocess, 'post_retrieve', lambda body: seen.append(('retrieve', body)))
    monkeypatch.setattr(rkb_inprocess, 'get_kbase_list', lambda: seen.append(('kbase',)))
    monkeypatch.setattr(rkb_inprocess, 'get_flow_config',
                        lambda app_id, scope='': seen.append(('flow', app_id, scope)))
    monkeypatch.setattr(rkb_inprocess, 'post_graph_retrieve',
                        lambda body, headers=None: seen.append(('graph', body, headers)))

    rkb_transport.post_retrieve({'a': 1}, {'h': 'v'})
    rkb_transport.get_kbase_list()
    rkb_transport.get_flow_config('wf9', 'dev')
    rkb_transport.post_graph_retrieve({'q': 2}, {'h': 'v'})

    assert seen == [('retrieve', {'a': 1}), ('kbase',),
                    ('flow', 'wf9', 'dev'), ('graph', {'q': 2}, {'h': 'v'})]


def test_transport_imports_compat_lazily():
    """`chat.adapters.rkb_inprocess` 必须**惰性**导入。

    它拉起 RKB 的业务层（`store` → psycopg2）。编排独立跑单测的环境
    没有 psycopg2 —— 模块级导入会让整个测试收集失败（文档处理模块合并时踩过）。
    所以在**干净子进程**里只 import transport，断言不连带拉起 RKB 适配器。
    """
    import subprocess
    import sys

    code = (
        'import sys;'
        'from chat.gateways import rkb_transport;'
        "print('chat.adapters.rkb_inprocess' in sys.modules)"
    )
    service_root = pathlib.Path(__file__).resolve().parents[1]
    # 唯一 import 根是 src/。子进程不会继承 pytest 的 `pythonpath` 配置，
    # 所以把 cwd 指到 src/（`-c` 的 sys.path[0] = cwd）。
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                         cwd=str(service_root / 'src'))
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == 'False', '模块级 import 了 RKB 适配器 —— 编排独立跑单测会炸'


def test_inprocess_response_is_minimal_surface():
    """替身只保证 `.status_code` 与 `.json()`；别的属性要 AttributeError 而非给错值。"""
    resp = rkb_inprocess.InProcessResponse(200, {'a': 1})
    assert resp.status_code == 200 and resp.json() == {'a': 1}
    assert not hasattr(resp, 'text')
