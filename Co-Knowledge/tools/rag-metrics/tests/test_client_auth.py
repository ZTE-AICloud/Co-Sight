"""评测客户端的本地账号适配（默认 AUTH_MODE=local）。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rkb_client import RkbClient, RkbError


def _response(status: int, cookie: str = 'session-token', code: str = '') -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.text = '{}'
    response.headers = {}
    response.cookies = {} if not cookie else {'ragstudio_session': cookie}
    response.json.return_value = {'code': code} if code else {}
    return response


def test_origin_keeps_port_by_default_and_can_drop_it():
    client = RkbClient('http://127.0.0.1:18080/api/co-knowledge/v1')
    assert client._origin() == 'http://127.0.0.1:18080'
    assert client._origin(with_port=False) == 'http://127.0.0.1'


def test_login_posts_credentials_to_auth_login():
    client = RkbClient('http://127.0.0.1/api/co-knowledge/v1',
                       username='u', password='p')
    session = MagicMock()
    session.post.return_value = _response(200)

    client._login(session)

    args, kwargs = session.post.call_args
    assert args[0] == 'http://127.0.0.1/api/co-knowledge/v1/auth/login'
    assert kwargs['json'] == {'username': 'u', 'password': 'p'}


def test_login_is_skipped_without_local_auth():
    client = RkbClient()
    # 404/405：端点不存在；409 auth_not_enabled：AUTH_MODE 不是 local。
    for status in (404, 405, 409):
        session = MagicMock()
        session.post.return_value = _response(status)
        client._login(session)          # 不抛异常


def test_login_falls_back_to_host_origin_after_csrf_rejection():
    # 自带 nginx 会把 Host 改写成不带端口的形式，带端口的 Origin 会被拒。
    client = RkbClient('http://127.0.0.1:18080/api/co-knowledge/v1')
    session = requests.Session()        # 要检查 headers 的写回，不能用 MagicMock
    rejected = _response(403, cookie='', code='csrf_rejected')
    accepted = _response(200)
    session.post = MagicMock(side_effect=[rejected, accepted])

    client._login(session)

    origins = [call.kwargs['headers']['Origin'] for call in session.post.call_args_list]
    assert origins == ['http://127.0.0.1:18080', 'http://127.0.0.1']
    # 后续 unsafe 请求要沿用登录成功的那个 Origin。
    assert session.headers['Origin'] == 'http://127.0.0.1'


def test_login_raises_on_rejected_credentials():
    client = RkbClient('http://127.0.0.1', username='u', password='wrong')
    session = MagicMock()
    session.post.return_value = _response(401)

    with pytest.raises(RkbError, match='登录失败 HTTP 401'):
        client._login(session)


def test_login_raises_when_cookie_missing():
    client = RkbClient()
    session = MagicMock()
    session.post.return_value = _response(200, cookie='')

    with pytest.raises(RkbError, match='未下发会话 Cookie'):
        client._login(session)


def test_login_raises_when_secure_cookie_is_set_over_http():
    client = RkbClient('http://127.0.0.1')
    session = MagicMock()
    response = _response(200)
    response.headers = {'Set-Cookie': 'ragstudio_session=x; Secure; HttpOnly'}
    session.post.return_value = response

    with pytest.raises(RkbError, match='Secure'):
        client._login(session)


def test_session_logs_in_once_and_reuses_the_thread_session():
    client = RkbClient('http://127.0.0.1:8091/api/co-knowledge/v1')
    client._login = MagicMock()

    first = client._session()
    second = client._session()

    assert first is second
    assert client._login.call_count == 1
    assert first.headers['Origin'] == 'http://127.0.0.1:8091'


def test_request_relogins_once_on_401():
    client = RkbClient()
    first, second = MagicMock(), MagicMock()
    first.request.return_value = _response(401)
    second.request.return_value = _response(200)
    client._session = MagicMock(side_effect=[first, second])

    assert client._request('GET', '/x') == {}
    assert first.request.call_count == 1
    assert second.request.call_count == 1
