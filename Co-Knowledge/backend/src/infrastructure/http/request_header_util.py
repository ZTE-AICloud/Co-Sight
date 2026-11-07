from fastapi import HTTPException
from starlette.datastructures import Headers

from infrastructure.logging.logutil import log
from infrastructure.http.cookies import get_cookie_value


def get_auth_name(headers):
    """取当前用户名：**只认 `username` 头**。

    :raises Exception: 头里没有 `username` —— 调用方（app.py 的几处归属字段）按原样处理
    """
    try:
        username = _get_http_header_value_by_name(headers, 'username')
        if len(username) != 0:
            return username
        raise Exception('query auth name empty')
    except Exception as e:
        log.exception(e)
        log.info('query auth name failed')
        raise e


def _check_forgerydefense(request_headers: Headers) -> None:
    if _get_http_header_value_by_name(request_headers, 'z-extent'):
        if 'forgerydefense' not in request_headers.keys():
            raise HTTPException(status_code=403, detail="Authentication failed")

        cookie = _get_http_header_value_by_name(request_headers, 'cookie')
        cookies_value = get_cookie_value(cookie, 'forgerydefense') or ''

        head_value = request_headers.get('forgerydefense', '')
        if head_value != cookies_value:
            raise HTTPException(status_code=403, detail="Authentication failed")


def _get_http_header_value_by_name(http_headers, header_name):
    header_value = http_headers.get(header_name)
    return header_value if header_value else ''
