import re
import urllib.parse
from http.cookies import SimpleCookie

from infrastructure.http.request_headers import EMRequestHeaders


def get_mode(http_headers):
    mode = http_headers.get('mode')
    return mode if mode else '0'


def build_http_headers(http_headers):
    qa_request_headers = EMRequestHeaders()
    qa_request_headers.set_username(get_user_name(http_headers))
    qa_request_headers.set_tenant_id(get_tenant_id(http_headers))
    qa_request_headers.set_language_option(get_language_option(http_headers))
    qa_request_headers.set_client_ip(get_client_ip(http_headers))
    qa_request_headers.set_connect_mode(get_http_header_value_by_name(http_headers, 'Z-CONNECT-MODE'))
    qa_request_headers.set_transaction_id(get_http_header_value_by_name(http_headers, 'TransactionID'))
    qa_request_headers.set_mode(get_mode(http_headers))
    qa_request_headers.set_cookie(get_cookie(http_headers))
    return qa_request_headers


def get_language_option(http_headers):
    language_option = get_http_header_value_by_name(http_headers, 'language-option')
    return 'zh' if language_option and language_option.lower().startswith('zh') else 'en'


def get_user_name(http_headers):
    username = get_http_header_value_by_name(http_headers, 'username')
    return decode_url_unicode(username)


def get_tenant_id(http_headers):
    tenant_id = get_http_header_value_by_name(http_headers, 'tenant-id')
    if tenant_id:
        return tenant_id
    cookie = get_cookie(http_headers)
    if cookie:
        c = SimpleCookie()
        c.load(cookie)
        if 'tenantId' in c:
            return c['tenantId'].value
    return ''


def get_client_ip(http_headers):
    client_ip = get_http_header_value_by_name(http_headers, 'X-Forwarded-For')
    if not client_ip:
        return get_http_header_value_by_name(http_headers, 'client-ip')
    return client_ip


def get_cookie(http_headers):
    return get_http_header_value_by_name(http_headers, 'Cookie')


def get_http_header_value_by_name(http_headers, header_name):
    header_value = http_headers.get(header_name)
    return header_value if header_value else ''


def is_success(status_code):
    return 200 <= int(status_code) < 300


def decode_url_unicode(s):
    decoded = urllib.parse.unquote(s)
    decoded = re.sub(r'%u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), decoded)
    return urllib.parse.unquote(decoded)
