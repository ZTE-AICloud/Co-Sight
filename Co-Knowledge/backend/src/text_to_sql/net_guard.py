"""数据源地址的出站校验。

Text2SQL 的数据源由用户填写 ``host:port``，连接由**服务端**发起。若不加限制，
一条 ``POST /datasources`` 就能让后端去连内网任意端口（SSRF）。这里的取舍是：

* 链路本地（含 ``169.254.169.254`` 云元数据）、未指定、组播、保留地址
  **一律拒绝**——正常业务数据源不会在这些地址上；
* 回环与 RFC1918 私网**默认放行**：本产品的部署形态就是「后端与库同机或同内网」，
  一刀切禁掉等于禁用功能。需要更严时设
  ``RKB_TEXT2SQL_BLOCK_PRIVATE_HOSTS=1``（此时回环与私网一并拒绝）；
* 主机名先解析再判定，避免 ``localhost`` 或指向元数据地址的域名绕过；
  解析失败不阻断（交给连接阶段报错），只对解析出的地址负责。

已知边界：DNS 解析与真正连接之间存在 TOCTOU 窗口（rebinding）。本模块是
纵深防御的一层，主要控制仍是「数据源写操作限管理员」。
"""

from __future__ import annotations

import ipaddress
import os
import socket
from typing import Iterable

from text_to_sql.errors import Text2SqlValidationError

IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

_BLOCK_PRIVATE = os.environ.get(
    'RKB_TEXT2SQL_BLOCK_PRIVATE_HOSTS', '').strip().lower() in {'1', 'true', 'yes', 'on'}


def assert_host_allowed(host: str, *, resolver=None) -> None:
    """``host`` 指向禁止的地址时抛 :class:`Text2SqlValidationError`。"""
    target = (host or '').strip().strip('[]')
    if not target:
        raise Text2SqlValidationError('host 不能为空')
    addresses = list(_resolve(target, resolver))
    if not addresses:
        return
    blocked = [str(address) for address in addresses
               if _is_blocked(address, block_private=_BLOCK_PRIVATE)]
    if blocked:
        raise Text2SqlValidationError(
            f'不允许连接该地址（{blocked[0]}）；数据源不能指向链路本地、'
            '云元数据或保留地址')


def _resolve(host: str, resolver) -> Iterable[IpAddress]:
    if resolver is None:
        try:
            infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        except (socket.gaierror, UnicodeError, OSError):
            return []
        result = []
        for info in infos:
            try:
                result.append(ipaddress.ip_address(info[4][0]))
            except ValueError:
                continue
        return result
    return resolver(host)


def _is_blocked(address: IpAddress, *, block_private: bool) -> bool:
    # 回环必须先判：Python 的 ipaddress 把 IPv6 的 ``::1`` 归进 ``::/8``「保留」段，
    # 先按 is_reserved 判会把回环一起拒掉（``localhost`` 解析出 ``::1`` 时直接报错）。
    if address.is_loopback:
        return block_private
    # 任何配置下都拒绝：链路本地（含云元数据 169.254.169.254）、组播、未指定、保留。
    if (address.is_link_local or address.is_multicast
            or address.is_unspecified or address.is_reserved):
        return True
    # RFC1918 / ULA 属于本产品的常规部署形态（后端与库同机/同内网），默认放行；
    # 收紧由 RKB_TEXT2SQL_BLOCK_PRIVATE_HOSTS 控制。
    if block_private and address.is_private:
        return True
    return False
