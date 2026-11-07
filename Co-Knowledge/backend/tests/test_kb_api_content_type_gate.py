"""Content-Type 闸门的回归测试 —— kb_api 侧。

主题一句话：**「请求体 + Content-Type」这组输入在媒体类型层面的归宿固定**。
四类归宿：

- 媒体类型不合格（无 CT / text/plain / xml / octet-stream / text/json / 解析不出，
  以及「无 CT + 非空体」）→ 200 + **0005 + ``msg:null``**；
- form-urlencoded 体解不出、multipart 缺 boundary → 200 + **0001**；
- JSON 族（``application/json`` 任意大小写/参数、``application/*+json``）→ 放行，
  之后照常走 ``parse_json_body``：0 字节 / 字面量 ``null``（必填体）→ 0004
  ``Required request body is missing``；空白 / 畸形 / 非对象 → 0004
  ``RetCode.illegalArgument``；
- multipart 端点（``File(...)``/``Form(...)``）被非 multipart 调用 → 0001；
  ``/graph-extractions`` 端点内显式挡 → 0001，其更新端点（``PUT /knowledge-bases/
  {id}/graph``）先绑普通参数 → 0004。

判定表见 ``compat/kb_api/content_type.py`` 模块头。下面四份响应对照固定
（**无尾换行**）；断言直接比 ``response.content``。

跑法（服务目录下）::

    python -m pytest tests/test_kb_api_content_type_gate.py -q
"""


import pytest

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from shared.prefixes import RKB_PREFIX as KBASE_PREFIX
from http_api import register_rkb_api  # noqa: E402
from retrieval.service import retrieve_service  # noqa: E402
from graph.service import graph_export_service  # noqa: E402

# 旧契约（200 + 0005/0004/0001 信封）已改为真实状态码 + RFC 9457。
# 这里保留原变量名，值换成 (status, code)，下面的用例按「输入 → 归宿」逐格断言。
JAVA_0001_ZH = (400, 'malformed_request')          # 读体阶段失败
JAVA_0005_NULL = (415, 'unsupported_media_type')   # 媒体类型不受支持
JAVA_0004_MISSING = (400, 'malformed_request')     # 缺体 / null
JAVA_0004_ILLEGAL_ZH = (400, 'malformed_request')  # 畸形 JSON / 非对象
VALIDATION_FAILED = (422, 'validation_failed')     # 语义校验


@pytest.fixture()
def client(monkeypatch):
    """真实路由 + 桩掉各域业务函数 —— 本文件只考「到业务之前」的那几层。"""
    monkeypatch.setattr(retrieve_service, 'retrieve', lambda payload: {'echo': payload})
    monkeypatch.setattr(
        graph_export_service, 'export_graph',
        lambda payload: (str(payload).encode('utf-8'), 'graph.csv'))
    app = FastAPI()
    register_rkb_api(app)
    return TestClient(app, raise_server_exceptions=False)


#: 请求头缺席的哨兵（与「显式空串 CT」区分 —— 两者归宿相同，但都要覆盖到）
_ABSENT = object()


def _post(client, path, *, body=b'{}', ctype=_ABSENT, language='zh-CN'):
    headers = {'Accept-Language': language}
    if ctype is not _ABSENT:
        headers['Content-Type'] = ctype
    return client.post(f'{KBASE_PREFIX}{path}', content=body, headers=headers)


def _assert_envelope(response, expectation):
    status, code = expectation
    assert response.status_code == status, response.text
    assert response.headers['content-type'].startswith('application/problem+json')
    body = response.json()
    assert body['status'] == status
    assert body['code'] == code
    assert body['title'] and body['detail']
    assert body['type'] == 'urn:ragstudio:problem:' + code


# ----------------------------------------------------------------------
# ① 媒体类型不合格 → 0005 + msg:null
# ----------------------------------------------------------------------

#: 非 JSON 的媒体类型（含「缺席」与「空串」——classify 都解析不出媒体类型）
_NON_JSON_MEDIA_TYPES = [_ABSENT, '', 'text/plain', 'application/xml',
                         'application/octet-stream', 'text/json', 'not-a-media-type',
                         'application/json, text/plain']


@pytest.mark.parametrize('ctype', _NON_JSON_MEDIA_TYPES)
@pytest.mark.parametrize('body', [b'{}', b'{', b'\xff\xfe'])
def test_non_json_media_type_returns_0005_null(client, ctype, body):
    """``POST /retrieval`` 全矩阵：非 JSON 媒体类型 × 任意非空体 → 0005+null。"""
    _assert_envelope(_post(client, '/retrieval', body=body, ctype=ctype),
                     JAVA_0005_NULL)


@pytest.mark.parametrize('path', ['/retrieval', '/knowledge-bases',
                                  '/knowledge-bases/kb-x/directories',
                                  '/graph-schemas'])
@pytest.mark.parametrize('ctype', [_ABSENT, 'text/plain'])
def test_every_json_endpoint_rejects_non_json_media_type(client, path, ctype):
    """其余 JSON 端点同规则（逐个端点各取两格）—— 闸门是统一实现，端点面要逐个盖到。"""
    _assert_envelope(_post(client, path, body=b'{}', ctype=ctype), JAVA_0005_NULL)


def test_form_urlencoded_gate(client):
    """form-urlencoded：可解码 → 0005；解不出（转义坏 / 严格解码失败）→ 0001。

    逐格实测（base_form）：``a=1&b=2`` / UTF-8 中文 / 控制字节 /
    百分号编码的中文 → 0005；GBK 字节 / 孤立 ``\\x80`` / ``\\xff\\xfe`` / ``%FF`` /
    ``%E4%B`` / ``%zz`` → 0001。0 字节 → 0005（媒体类型判定先行）。
    """
    form = 'application/x-www-form-urlencoded'
    readable = ['a=1&b=2', '名字=中文'.encode('utf-8'), b'\x00\x01\x02', b'%E4%B8%AD', b'']
    for body in readable:
        _assert_envelope(_post(client, '/retrieval', body=body, ctype=form),
                         JAVA_0005_NULL)
    bad = ['名字=中文'.encode('gbk'), b'\x80', b'\xff\xfe', b'%FF', b'%E4%B', b'%zz']
    for body in bad:
        _assert_envelope(_post(client, '/retrieval', body=body, ctype=form),
                         JAVA_0001_ZH)


def test_multipart_on_json_endpoint(client):
    """multipart/* 打在 JSON 端点上：带 boundary → 0005；缺 boundary → 0001。"""
    with_boundary = 'multipart/form-data; boundary=XX'
    for body in (b'{}', b'junk', b'--XX--\r\n', b''):
        _assert_envelope(_post(client, '/retrieval', body=body, ctype=with_boundary),
                         JAVA_0005_NULL)
    for body in (b'{}', b''):
        _assert_envelope(_post(client, '/retrieval', body=body,
                               ctype='multipart/form-data'), JAVA_0001_ZH)


# ----------------------------------------------------------------------
# ② JSON 族放行 → 照常解析
# ----------------------------------------------------------------------

_JSON_MEDIA_TYPES = ['application/json', 'application/JSON', 'application/json;;',
                     'application/json; charset=utf-8', 'application/json;charset=gbk',
                     'application/merge-patch+json']


@pytest.mark.parametrize('ctype', _JSON_MEDIA_TYPES)
def test_json_family_passes_gate(client, ctype):
    """大小写 / 参数（含 ``;;`` 这种畸形参数段）/ ``+json`` 后缀都放行，业务照常跑到。"""
    response = _post(client, '/retrieval', body=b'{"question": "hi"}', ctype=ctype)
    assert response.status_code == 200
    assert response.json() == {'echo': {'question': 'hi'}}


@pytest.mark.parametrize('ctype', [_ABSENT, '', 'application/json',
                                   'application/json; charset=utf-8', 'application/JSON'])
def test_zero_byte_body_on_required_endpoint_returns_0004_missing(client, ctype):
    """0 字节 + （能放行的）CT → ``@RequestBody`` 必填判定 → 0004 missing。"""
    for path in ('/retrieval', '/knowledge-bases', '/graph-schemas'):
        _assert_envelope(_post(client, path, body=b'', ctype=ctype),
                         JAVA_0004_MISSING)


def test_literal_null_and_whitespace(client):
    """字面量 ``null`` / 空白体在 JSON 族下的两个不同归宿。"""
    _assert_envelope(_post(client, '/retrieval', body=b'null',
                           ctype='application/json'), JAVA_0004_MISSING)
    _assert_envelope(_post(client, '/retrieval', body=b'  ',
                           ctype='application/json'), JAVA_0004_ILLEGAL_ZH)
    _assert_envelope(_post(client, '/retrieval', body=b'  ', ctype=_ABSENT),
                     JAVA_0005_NULL)


@pytest.mark.parametrize('body', [b'{', b'[]', b'[1,2]', b'1', b'"x"', b','])
def test_malformed_or_non_object_json_returns_0004_illegal(client, body):
    """畸形 JSON 与非对象体（数组/数字/字符串）→ 0004 illegalArgument。"""
    _assert_envelope(_post(client, '/retrieval', body=body, ctype='application/json'),
                     JAVA_0004_ILLEGAL_ZH)


# ----------------------------------------------------------------------
# ③ 必填体端点：0 字节 / null → 0004 missing
# ----------------------------------------------------------------------

_REQUIRED_BODY_ENDPOINTS = [
    ('POST', '/knowledge-bases'),
    ('POST', '/knowledge-bases/kb-x/directories'),
    ('PATCH', '/knowledge-bases/kb-x'),
    ('POST', '/knowledge-bases/kb-x/chunks'),
    ('POST', '/retrieval'),
    ('POST', '/graph-schemas'),
    ('PATCH', '/graph-schemas/schema-1'),
    ('POST', '/knowledge-bases/kb-x/graph/query'),
    ('POST', '/knowledge-bases/kb-x/graph/entities'),
    ('PATCH', '/knowledge-bases/kb-x/graph/entities/entity-1'),
    ('POST', '/knowledge-bases/kb-x/graph/edges'),
    ('PATCH', '/knowledge-bases/kb-x/graph/edges/edge-1'),
    ('PUT', '/operators/1/visibility'),
]


@pytest.mark.parametrize('method,path', _REQUIRED_BODY_ENDPOINTS)
@pytest.mark.parametrize('body', [b'', b'null'])
def test_required_body_endpoints_reject_empty_body(client, method, path, body):
    """声明了必填 JSON 体的端点：缺体 → 0004 missing（与 ``@RequestBody`` 同规则）。"""
    response = client.request(method, f'{KBASE_PREFIX}{path}', content=body,
                              headers={'Accept-Language': 'zh-CN',
                                       'Content-Type': 'application/json'})
    _assert_envelope(response, JAVA_0004_MISSING)


# ----------------------------------------------------------------------
# ④ 导出：新动词下的解析规则
# ----------------------------------------------------------------------


def test_graph_export_is_a_get_download(client):
    """``GET /knowledge-bases/{id}/graph/export`` → 文件流，不再是 POST + JSON 体。"""
    response = client.get(f'{KBASE_PREFIX}/knowledge-bases/kb-1/graph/export')
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/octet-stream'
    assert response.headers['content-disposition'].startswith(
        "attachment; filename*=utf-8''")
    assert response.content == b"{'kbId': 'kb-1'}"


# ----------------------------------------------------------------------
# ⑤ multipart 端点：非 multipart 的 CT → 0001
# ----------------------------------------------------------------------

_MULTIPART_ENDPOINTS = [
    '/knowledge-bases/kb-x/documents',
    '/operators',
    '/graph-imports',
    '/graph-schemas/import',
]


@pytest.mark.parametrize('path', _MULTIPART_ENDPOINTS)
@pytest.mark.parametrize('ctype', [_ABSENT, 'text/plain', 'application/json'])
def test_multipart_endpoint_wrong_content_type_returns_0001(client, path, ctype):
    """4 条 multipart 端点 × 3 种「非 multipart」CT（含缺席）→ 200 + 0001。"""
    _assert_envelope(_post(client, path, body=b'{}', ctype=ctype), JAVA_0001_ZH)


def test_graph_extractions_inline_guard(client):
    """``POST /graph-extractions``（手工 ``request.form()``）→ 端点内显式挡 0001。"""
    for ctype in (_ABSENT, 'text/plain', 'application/json'):
        _assert_envelope(_post(client, '/graph-extractions', body=b'{}', ctype=ctype),
                         JAVA_0005_NULL)


def test_graph_update_binds_params_first(client):
    """``PUT /knowledge-bases/{id}/graph``：普通参数先绑 → 缺 data 等 → 0004。"""
    for ctype in (_ABSENT, 'text/plain', 'application/json'):
        headers = {'Accept-Language': 'zh-CN'}
        if ctype is not _ABSENT:
            headers['Content-Type'] = ctype
        response = client.put(f'{KBASE_PREFIX}/knowledge-bases/kb-1/graph',
                              content=b'{}', headers=headers)
        _assert_envelope(response, VALIDATION_FAILED)


# ----------------------------------------------------------------------
# ⑥ GET 不在闸门范围（别扩大打击面）
# ----------------------------------------------------------------------


def test_get_requests_not_gated(client):
    """GET 带任何 Content-Type 都不参与判定（例如 GET /operators/types 带 text/plain → 0000）。"""
    response = client.get(f'{KBASE_PREFIX}/operators/types',
                          headers={'Content-Type': 'text/plain'})
    assert response.status_code == 200
    assert isinstance(response.json(), list)
