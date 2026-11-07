"""HTTP 小工具（精简版）。

下游是进程内检索，请求头只需要用户标识与语言。

2026-10 清理：删掉 `check_status_code_ok`（全仓零引用；本仓各客户端都直接内联
判断状态码并抛 `RagException`）。
"""
from urllib.parse import quote


def build_headers(header) -> dict:
    """构造调用检索的请求头。

    缺 `X-Emp-No` 时后端按默认用户处理（单用户模式），
    所以这里即使拿不到用户也不报错 —— 与「谁在调」这件事解耦。
    """
    headers = {'Content-Type': 'application/json'}
    if header is None:
        return headers
    emp_no = getattr(header, 'emp_no', '') or ''
    if emp_no:
        headers['X-Emp-No'] = emp_no
    org_id = getattr(header, 'org_id', '') or ''
    if org_id:
        headers['X-Org-Id'] = org_id
    language = getattr(header, 'language_option', '') or ''
    if language:
        headers['X-Lang-Id'] = language
    return headers


def escape(value: str) -> str:
    return quote(value) if isinstance(value, str) else value
