"""上传链「错误通道」的测试。

主题一句话：**异常也必须走业务信封** —— HTTP 200 + ``code.code``，与对外契约一致。
两条通道：

- 通道 1：metadata 非法 JSON / 非对象 → ``ExceptionAdvice`` 0001；
  不能是裸 500 ``text/plain``。
- 通道 2：multipart 解析失败（空 multipart / 缺 boundary）→ 0001；
  不能是 400 ``{"detail": ...}``。

跑法（服务目录下）::

    python -m pytest tests/test_kb_api_upload_error_channel.py -q
"""

import io

import pytest

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from shared.prefixes import RKB_PREFIX as KBASE_PREFIX
from http_api import register_rkb_api  # noqa: E402
from knowledge_base.service import file_service  # noqa: E402

KB = 'kbid-error-channel'  # 业务函数被桩掉，不需要真实库


def _multipart(parts, boundary='kbtestbnd'):
    """最小 multipart 编码器：``(name, value)`` 文本部件 / ``(name, bytes, filename)`` 文件部件。"""
    out = io.BytesIO()
    for part in parts:
        name, value = part[0], part[1]
        filename = part[2] if len(part) > 2 else None
        if filename is None:
            out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
                      f'\r\n\r\n'.encode())
            out.write(value if isinstance(value, bytes) else value.encode())
        else:
            out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
                      f'filename="{filename}"\r\nContent-Type: application/octet-stream'
                      f'\r\n\r\n'.encode())
            out.write(value if isinstance(value, bytes) else value.encode())
        out.write(b'\r\n')
    out.write(f'--{boundary}--\r\n'.encode())
    return out.getvalue(), f'multipart/form-data; boundary={boundary}'


@pytest.fixture()
def client(monkeypatch):
    """真实路由 + 桩掉文件域业务函数 —— 只考「到业务之前的错误通道」，单测不连库。"""
    monkeypatch.setattr(
        file_service, 'upload_files',
        lambda uploaded, metadata, kbase_id, emp_no, **kwargs:
        {item.filename: 'fid-' + item.filename for item in uploaded})
    app = FastAPI()
    register_rkb_api(app)
    return TestClient(app, raise_server_exceptions=False)


def _post(client, path, *, body=None, ctype=None, language='zh-CN'):
    headers = {'Accept-Language': language}
    if ctype:
        headers['Content-Type'] = ctype
    return client.post(f'{KBASE_PREFIX}{path}', content=body, headers=headers)


# ----------------------------------------------------------------------
# 通道 1：metadata 非法 JSON / 非对象 → 0001（不是 500，也不是 0004）
# ----------------------------------------------------------------------


def test_invalid_metadata_json_returns_0001_envelope(client):
    """``/file/upload`` 的 metadata 非法 JSON → 200 + 0001/RetCode.ServerError。"""
    body, ctype = _multipart([('metadata', '{not-json'), ('files', b'# hi\n', 'a.md')])

    response = _post(client, f'/knowledge-bases/{KB}/documents', body=body, ctype=ctype)

    assert response.status_code == 400
    body = response.json()
    assert body['code'] == 'malformed_request'
    assert body['detail'] == '请求格式不合法，请检查后重试'


@pytest.mark.parametrize('metadata', ['null', '[]', '123', '"x"'])
def test_non_object_metadata_returns_0001_envelope(client, metadata):
    """合法 JSON 但不是对象：``null`` 触发 NPE、其余触发解析异常，都是 0001。"""
    body, ctype = _multipart([('files', b'# hi\n', 'a.md'), ('metadata', metadata)])

    response = _post(client, f'/knowledge-bases/{KB}/documents', body=body, ctype=ctype)

    assert response.status_code == 400
    assert response.json()['code'] == 'malformed_request'


@pytest.mark.parametrize('metadata', ['', ' ', '{}'])
def test_empty_or_valid_metadata_still_reaches_service(client, metadata):
    """空串 / 纯空白 / 正常对象不走 0001 通道 —— 解析层放行，语义归 service（0005 一族）。"""
    body, ctype = _multipart([('files', b'# hi\n', 'a.md'), ('metadata', metadata)])

    response = _post(client, f'/knowledge-bases/{KB}/documents', body=body, ctype=ctype)

    assert response.status_code == 200
    assert response.json() == {'a.md': 'fid-a.md'}


# ----------------------------------------------------------------------
# 通道 2：multipart 解析失败 → 0001（不是 400 detail）
# ----------------------------------------------------------------------


def test_empty_multipart_returns_0001_envelope(client):
    """空 multipart（只有结束边界）：python-multipart 抛 MultipartParseError → 0001。"""
    body, ctype = _multipart([])

    response = _post(client, f'/knowledge-bases/{KB}/documents', body=body, ctype=ctype)

    assert response.status_code == 400
    body = response.json()
    assert body['code'] == 'malformed_request'
    assert body['detail'] == '请求格式不合法，请检查后重试'


def test_no_boundary_multipart_returns_0001_envelope(client):
    """声明 multipart 但没有 boundary：Starlette 转成 400 HTTPException → 0001。"""
    response = _post(client, f'/knowledge-bases/{KB}/documents', body=b'garbage',
                     ctype='multipart/form-data')

    assert response.status_code == 400
    assert response.json()['code'] == 'malformed_request'


def test_server_error_message_follows_accept_language(client):
    """文案随 Accept-Language —— en 与其他语言同一套契约。"""
    body, ctype = _multipart([])

    response = _post(client, f'/knowledge-bases/{KB}/documents', body=body, ctype=ctype,
                     language='en-US')

    assert response.status_code == 400
    assert response.json()['detail'] == 'Malformed request; check the request and retry'


# ----------------------------------------------------------------------
# 非回归：别的状态码 / 别的端点的行为不能被这两个兜底处理器带跑
# ----------------------------------------------------------------------


def test_kb_unknown_path_keeps_catch_all_envelope(client):
    """kb 前缀下的未知路径走**兜底路由**（200 + 0005 无文案，见 router.py 的兜底路由注释），
    不是 HTTPException 场景 —— 确认新挂的处理器没有改动这条既有行为。"""
    response = client.get(f'{KBASE_PREFIX}/file/noSuchRoute')

    assert response.status_code == 404
    assert response.json()['code'] == 'not_found'


def test_non_kb_404_keeps_fastapi_default():
    """非 kb 前缀的 404 走 FastAPI 默认处理器（新处理器只拦 400）。"""
    app = FastAPI()
    register_rkb_api(app)
    native = TestClient(app, raise_server_exceptions=False)

    response = native.get('/native/missing')

    assert response.status_code == 404
    assert response.json() == {'detail': 'Not Found'}


def test_non_kb_path_400_keeps_fastapi_default():
    """非 kb 前缀的 400 **不**换信封（flow_api / RKB 自有端点不受影响）。"""
    app = FastAPI()

    @app.get('/native/boom')
    def native_boom():
        raise HTTPException(status_code=400, detail='native detail')

    register_rkb_api(app)
    native = TestClient(app, raise_server_exceptions=False)

    response = native.get('/native/boom')

    assert response.status_code == 400
    assert response.json() == {'detail': 'native detail'}


def test_readonly_endpoint_validation_still_0004(client):
    """只读端点缺必填 query 参数 → 400 malformed_request（文案走 i18n 键）。"""
    response = client.get(f'{KBASE_PREFIX}/operators/template',
                          headers={'Accept-Language': 'zh-CN'})

    assert response.status_code == 400
    body = response.json()
    assert body['code'] == 'malformed_request'
    assert body['detail'] == '参数不合法，请检查后重试'
