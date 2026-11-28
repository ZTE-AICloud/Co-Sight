"""数据源地址校验：SSRF 纵深防御的一层。"""

import ipaddress

import pytest

from text_to_sql import net_guard
from text_to_sql.errors import Text2SqlValidationError


def _resolver(*addresses):
    def resolve(_host):
        return [ipaddress.ip_address(item) for item in addresses]
    return resolve


@pytest.mark.parametrize('address', [
    '169.254.169.254',   # 云元数据
    '169.254.1.1',       # 链路本地
    '0.0.0.0',
    '224.0.0.1',         # 组播
    '240.0.0.1',         # 保留
    'fe80::1',
    'ff02::1',
])
def test_blocks_link_local_and_reserved(address):
    with pytest.raises(Text2SqlValidationError):
        net_guard.assert_host_allowed('ds.internal', resolver=_resolver(address))


@pytest.mark.parametrize('address', ['127.0.0.1', '::1', '::ffff:127.0.0.1',
                                     '10.1.2.3', '192.168.1.9',
                                     '172.16.0.5', 'fd00::1', '8.8.8.8'])
def test_allows_loopback_and_private_by_default(address):
    net_guard.assert_host_allowed('ds.internal', resolver=_resolver(address))


def test_ipv6_loopback_is_not_treated_as_reserved():
    """回归：``::1`` 落在 ``::/8``「保留」段，但它是回环，必须按回环处理。"""
    net_guard.assert_host_allowed('localhost', resolver=_resolver('::1'))


def test_private_can_be_blocked_by_environment(monkeypatch):
    monkeypatch.setattr(net_guard, '_BLOCK_PRIVATE', True)
    for address in ('127.0.0.1', '::1', '10.1.2.3', '192.168.1.9'):
        with pytest.raises(Text2SqlValidationError):
            net_guard.assert_host_allowed('ds.internal',
                                          resolver=_resolver(address))
    net_guard.assert_host_allowed('ds.internal', resolver=_resolver('8.8.8.8'))


def test_hostname_resolving_to_metadata_is_blocked():
    """域名指向元数据地址也要拦住，不能只看字面量。"""
    with pytest.raises(Text2SqlValidationError):
        net_guard.assert_host_allowed('metadata.example.com',
                                      resolver=_resolver('169.254.169.254'))


def test_unresolvable_host_is_left_to_connect_stage():
    net_guard.assert_host_allowed('no-such-host', resolver=lambda _host: [])


def test_empty_host_rejected():
    with pytest.raises(Text2SqlValidationError):
        net_guard.assert_host_allowed('', resolver=_resolver('8.8.8.8'))


def test_ipv6_brackets_are_stripped():
    with pytest.raises(Text2SqlValidationError):
        net_guard.assert_host_allowed('[fe80::1]', resolver=_resolver('fe80::1'))
