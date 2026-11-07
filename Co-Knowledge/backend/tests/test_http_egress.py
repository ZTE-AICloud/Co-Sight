"""出站代理策略单测（**不碰网络**）。

钉住一条规则：私网 / 回环 / 链路本地 / 容器短名 → 显式禁用代理；
公网地址 → 返回空映射，继续交给 ``NO_PROXY`` 等环境变量。

背景是实测回归：模型管理页注册 ``http://10.0.0.50:30804/...`` 后，
连接测试报 ``ProxyError ... ConnectionResetError(104)`` —— 请求被公司代理截走。
静态 ``NO_PROXY`` 不可能覆盖运行时新增的端点，所以策略必须落在代码里。
"""

import pytest
import requests

from infrastructure.http import egress


@pytest.mark.parametrize('host', [
    '10.0.0.50',      # RFC1918：实测被代理截走的那个端点
    '172.18.0.5',       # compose 网络
    '192.168.1.10',
    '127.0.0.1',
    'localhost',
    'MODEL-GATEWAY',    # 单标签 = compose 服务名（大小写不敏感）
    '::1',
    'fd00::1',          # IPv6 ULA
    '169.254.1.1',      # 链路本地
])
def test_private_hosts_are_treated_as_direct(host):
    assert egress.is_private_host(host) is True


@pytest.mark.parametrize('host', [
    '8.8.8.8',
    'llm.example.com',
    'api.example.com',
    '10.0.0.50.example.com',  # 只是长得像 IP 的域名
    '',
])
def test_public_or_unknown_hosts_keep_env_proxy_behavior(host):
    assert egress.is_private_host(host) is False


def test_request_proxies_disables_both_schemes_for_private_url():
    # http 与 https 都必须显式置 None：requests 只跳过值为 None 的键，
    # 漏掉一个就会把环境变量里的对应代理又合并回来。
    assert egress.request_proxies('http://10.0.0.50:30804/v1/chat/completions') == {
        'http': None, 'https': None,
    }


def test_request_proxies_returns_empty_for_public_url():
    assert egress.request_proxies('https://api.example.com/v1/chat/completions') == {}


def test_post_forwards_proxy_policy_and_keeps_other_kwargs(monkeypatch):
    seen = {}

    def fake_post(url, **kwargs):
        seen['url'] = url
        seen.update(kwargs)
        return 'response'

    monkeypatch.setattr(requests, 'post', fake_post)
    body = {'model': 'deepseek-chat'}
    assert egress.post('http://10.0.0.50:30804/v1/chat/completions',
                       json=body, timeout=30) == 'response'
    assert seen['url'].startswith('http://10.0.0.50:30804/')
    assert seen['json'] == body
    assert seen['timeout'] == 30
    assert seen['proxies'] == {'http': None, 'https': None}


def test_get_forwards_proxy_policy(monkeypatch):
    seen = {}

    def fake_get(url, **kwargs):
        seen.update(kwargs)
        return 'response'

    monkeypatch.setattr(requests, 'get', fake_get)
    assert egress.get('http://model-gateway:8000/models', timeout=3) == 'response'
    assert seen['proxies'] == {'http': None, 'https': None}


def test_explicit_proxies_from_caller_are_not_overridden(monkeypatch):
    """调用方显式传 proxies 时以调用方为准（本模块只兜默认值）。"""
    monkeypatch.setattr(requests, 'post', lambda url, **kwargs: kwargs.get('proxies'))
    explicit = {'http': 'http://user-proxy:3128'}
    assert egress.post('http://10.0.0.50:30804/v1', proxies=explicit) == explicit
