"""出站 HTTP 的代理策略：**私网地址一律直连**。

## 为什么需要这一层

容器会继承宿主的 ``http_proxy`` / ``https_proxy``（常见于企业内网部署）。
``NO_PROXY`` 只能列出**部署时已知**的主机（compose 里的 ``GENERATION_HOST`` /
``EMBEDDING_HOST`` / ``RERANK_HOST``），而模型管理页允许**运行时**注册任意端点 ——
静态名单必然漏掉新端点。症状是连接测试报::

    ProxyError: HTTPConnectionPool(host='proxy.example.com', port=80):
    Max retries exceeded ... (Caused by ProxyError('Unable to connect to proxy',
    ConnectionResetError(104, 'Connection reset by peer')))

看起来像「模型端点不可用」，实际是请求被代理截走了（实测 :444 的 10.x 端点）。

所以这里按**地址类型**兜底，而不是按主机名逐条配置：

* 回环 / RFC1918 / 链路本地 / IPv6 ULA / 单标签主机名（compose 服务名）
  → 显式禁用代理；
* 其它（公网）→ 交给环境变量，``NO_PROXY`` 里的内网域名照旧生效。

「单标签主机名」也算直连：容器网络里的服务名（``model-gateway`` 之类）不该走代理，
而公网域名至少有一个点。

## 用法

调用模型端点（用户可随时新增）的地方用 :func:`get` / :func:`post` 替掉
``requests.get`` / ``requests.post``；其余出站调用（内部服务）不受影响。
注入点（单测里的 ``http_get`` / ``http_post``）仍然优先，不经过本模块。
"""

from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlsplit

import requests

#: requests 的 ``proxies`` 语义：键存在且值为 ``None`` = 该协议**不走**代理。
_DIRECT: dict = {'http': None, 'https': None}


def is_private_host(host: str) -> bool:
    """``host`` 是否属于「应当直连」的地址（不依赖 DNS 解析）。"""
    host = (host or '').strip().strip('[]').lower().rstrip('.')
    if not host:
        return False
    if host == 'localhost' or host.endswith('.localhost'):
        return True
    if '.' not in host:
        # 单标签：compose 服务名 / 容器网络内的短名。公网域名至少有一个点。
        return True
    try:
        address = ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local


def request_proxies(url: str) -> dict:
    """给 ``requests`` 的 ``proxies=``：私网地址禁用代理，其它返回空（= 用环境变量）。"""
    host = urlsplit(url or '').hostname or ''
    return dict(_DIRECT) if is_private_host(host) else {}


def get(url: str, **kwargs):
    """``requests.get`` 的直连兜底版：私网地址强制绕过环境代理。"""
    kwargs.setdefault('proxies', request_proxies(url))
    return requests.get(url, **kwargs)


def post(url: str, **kwargs):
    """``requests.post`` 的直连兜底版：私网地址强制绕过环境代理。"""
    kwargs.setdefault('proxies', request_proxies(url))
    return requests.post(url, **kwargs)
