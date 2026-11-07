"""Content-Type 闸门的回归测试 —— flow_api 侧。

flow 与 kb 共用同一张判定表（``compat/kb_api/content_type.py`` 模块头），
差别只在**生效范围**：

- 只对唯一前缀 ``/api/co-knowledge/v1`` 生效；
- 新路径把工作流 id 放进路径，没有「缺 appId」这一层 query 绑定。

下面用到的四份原文（0005+null / 0004 missing / 0004 illegalArgument zh）
是契约原文，必须与 kb 侧保持一致。

跑法（服务目录下）::

    python -m pytest tests/test_flow_api_content_type_gate.py -q
"""


from shared.prefixes import RKB_PREFIX as KB_SERVICE_PREFIX  # noqa: E402

JAVA_0001_ZH = (400, 'malformed_request')
JAVA_0005_NULL = (415, 'unsupported_media_type')
JAVA_0004_MISSING = (400, 'malformed_request')
JAVA_0004_ILLEGAL_ZH = (400, 'malformed_request')

#: 请求头缺席的哨兵（与「显式空串 CT」区分）
_ABSENT = object()


def _request(client, method, path, *, body=b'{}', ctype=_ABSENT, language='zh-CN'):
    headers = {'Accept-Language': language}
    if ctype is not _ABSENT:
        headers['Content-Type'] = ctype
    return client.request(method, f'{KB_SERVICE_PREFIX}{path}', content=body,
                          headers=headers)


def _post(client, path, *, body=b'{}', ctype=_ABSENT, language='zh-CN'):
    return _request(client, 'POST', path, body=body, ctype=ctype, language=language)


def _assert_envelope(response, expectation):
    status, code = expectation
    assert response.status_code == status, response.text
    assert response.headers['content-type'].startswith('application/problem+json')
    body = response.json()
    assert body['status'] == status and body['code'] == code


# ----------------------------------------------------------------------
# POST /workflows/{id}/validate：必填体
# ----------------------------------------------------------------------

_NON_JSON_MEDIA_TYPES = [_ABSENT, 'text/plain', 'application/xml',
                         'application/x-www-form-urlencoded', 'application/octet-stream']


def test_precheck_non_json_media_type_returns_0005_null(client):
    """非 JSON 媒体类型（含「缺席」）→ 0005+null（body 非空；可解码的 form 体也算）。"""
    for ctype in _NON_JSON_MEDIA_TYPES:
        _assert_envelope(_post(client, '/workflows/nosuch/validate', body=b'{}',
                               ctype=ctype), JAVA_0005_NULL)


def test_precheck_zero_byte_with_content_type_returns_0005_null(client):
    """CT 在（text/plain）时媒体类型判定先行：0 字节体也 0005（不是 missing）。"""
    _assert_envelope(_post(client, '/workflows/nosuch/validate', body=b'',
                           ctype='text/plain'), JAVA_0005_NULL)


def test_precheck_zero_byte_or_null_required_body_returns_0004_missing(client):
    """CT 可放行（缺失 / json）时轮到必填判定：0 字节 / 字面量 null → 0004 missing。"""
    for ctype in (_ABSENT, 'application/json', 'application/json; charset=utf-8'):
        _assert_envelope(_post(client, '/workflows/nosuch/validate', body=b'',
                               ctype=ctype), JAVA_0004_MISSING)
    _assert_envelope(_post(client, '/workflows/nosuch/validate', body=b'null',
                           ctype='application/json'), JAVA_0004_MISSING)


def test_precheck_malformed_json_returns_0004_illegal(client):
    """JSON 族放行后解析失败 → 0004 illegalArgument（随语言，zh-CN 出中文）。"""
    _assert_envelope(_post(client, '/workflows/nosuch/validate', body=b'{',
                           ctype='application/json'), JAVA_0004_ILLEGAL_ZH)


def test_precheck_form_undecodable_returns_0001(client):
    """form-urlencoded 体解不出 → 0001（实测：flow-precheck EU/EB + form → 0001）。"""
    _assert_envelope(_post(client, '/workflows/nosuch/validate', body=b'\xff\xfe',
                           ctype='application/x-www-form-urlencoded'), JAVA_0001_ZH)


def test_precheck_json_body_reaches_business(client):
    """放行格：合法 JSON 对象照常进业务（不存在的 workflow → 0005「工作流 … 不存在」）。"""
    response = _post(client, '/workflows/nosuch/validate', body=b'{}',
                     ctype='application/json')
    assert response.status_code == 404
    body = response.json()
    assert body['code'] == 'workflow_not_found'
    assert body['detail'] == '知识检索 nosuch 不存在'


# ----------------------------------------------------------------------
# PATCH /workflows/{id}：必填体，无 query 参数
# ----------------------------------------------------------------------


def test_workflow_update_gate(client):
    """非 JSON / 缺 CT + 非空体 → 0005+null；form 可解码体同样 0005+null。"""
    for ctype in (_ABSENT, 'text/plain', 'application/x-www-form-urlencoded',
                  'application/octet-stream'):
        _assert_envelope(_request(client, 'PATCH', '/workflows/w-1', body=b'{}',
                                  ctype=ctype), JAVA_0005_NULL)


def test_workflow_update_required_body_and_parse(client):
    """0 字节 → 0004 missing；json + 畸形体 → 0004 illegalArgument；
    form 体解不出 → 0001。"""
    _assert_envelope(_request(client, 'PATCH', '/workflows/w-1', body=b'',
                              ctype='application/json'), JAVA_0004_MISSING)
    _assert_envelope(_request(client, 'PATCH', '/workflows/w-1', body=b'{',
                              ctype='application/json'), JAVA_0004_ILLEGAL_ZH)
    _assert_envelope(_request(client, 'PATCH', '/workflows/w-1', body=b'\xff\xfe',
                              ctype='application/x-www-form-urlencoded'), JAVA_0001_ZH)


# ----------------------------------------------------------------------
# GET /workflows/knowledge-bases：只读，没有请求体闸门
# ----------------------------------------------------------------------


def test_workflow_knowledge_bases_is_a_get(client):
    """知识库下拉改为 GET + 查询参数；带任何 Content-Type 都不参与闸门判定。"""
    response = client.get(f'{KB_SERVICE_PREFIX}/workflows/knowledge-bases',
                          headers={'Content-Type': 'text/plain'})
    assert response.status_code == 200
    assert set(response.json()) == {'running', 'dev'}
