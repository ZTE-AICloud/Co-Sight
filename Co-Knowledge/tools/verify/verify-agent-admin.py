#!/usr/bin/env python3
"""Agent Key 管理接口 + 真实 Agent 调用的端到端验收。

覆盖链路：UI 管理接口建 Key → 用 Key 调 REST → 停用（401）→ 启用（200）→
编辑 → 删除（401）。脚本自己清理临时 Key，不依赖任何已有 Key。

推荐在容器内跑（与后端同网络）：

    docker compose -f deploy/docker-compose.yml exec -T rag-knowledge-base \
      python3 - < tools/verify/verify-agent-admin.py

也可在宿主直接跑（需要 requests）：

    python3 tools/verify/verify-agent-admin.py \
      --base-url http://<host>/api/co-knowledge/v1

环境变量：
- ``RKB_BASE_URL``        默认 ``http://127.0.0.1/api/co-knowledge/v1``
- ``RKB_GATEWAY_TOKEN``   可选，写成 ``X-Auth-Token``（AUTH_MODE=gateway 时）
- ``RKB_EMP_NO``          可选，写成 ``X-Emp-No``（记录 created_by）

注意：管理接口是纯 JSON + problem（真实状态码）；Agent 接口用真实 HTTP
状态码。两者不要混着判断。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any, Optional

import requests

failures: list[str] = []
warnings: list[str] = []
skips: list[str] = []


def check(name: str, condition: bool, detail: str = '') -> None:
    if condition:
        print(f'PASS {name}')
    else:
        print(f'FAIL {name}: {detail}')
        failures.append(name)


def skip(name: str, detail: str) -> None:
    print(f'SKIP {name}: {detail}')
    skips.append(name)


def warn(name: str, detail: str) -> None:
    print(f'WARN {name}: {detail}')
    warnings.append(name)


class Client:
    def __init__(self, base: str, admin_path: str) -> None:
        self.base = base.rstrip('/')
        self.admin = (admin_path or f'{self.base}/agent-keys').rstrip('/')
        self.headers = {
            'Accept': 'application/json',
            'Accept-Language': 'zh-CN',
            'Content-Type': 'application/json',
        }
        token = (os.environ.get('RKB_GATEWAY_TOKEN') or '').strip()
        if token:
            self.headers['X-Auth-Token'] = token
        emp = (os.environ.get('RKB_EMP_NO') or '').strip()
        if emp:
            self.headers['X-Emp-No'] = emp

    def admin_request(self, method: str, path: str = '',
                      payload: Optional[dict] = None) -> tuple[str, str, dict, Any]:
        response = requests.request(method, f'{self.admin}{path}',
                                    headers=self.headers, json=payload, timeout=30)
        try:
            body = response.json()
        except ValueError:
            return 'http_error', f'HTTP {response.status_code}: {response.text[:200]}', {}, response
        # 纯 REST + RFC 9457 problem
        if 200 <= response.status_code < 300:
            return '0000', '', body, response
        if isinstance(body, dict):
            return str(body.get('code') or 'http_error'), str(body.get('detail') or ''), None, response
        return 'http_error', f'HTTP {response.status_code}: {response.text[:200]}', None, response

    def agent_list(self, key: str) -> requests.Response:
        return requests.get(f'{self.base}/agent/knowledge-bases',
                            headers={'Authorization': f'Bearer {key}',
                                     'Accept': 'application/json'},
                            timeout=30)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Agent key admin e2e verification')
    parser.add_argument('--base-url', default=os.environ.get('RKB_BASE_URL')
                        or 'http://127.0.0.1/api/co-knowledge/v1')
    parser.add_argument('--admin-path', default=None,
                        help='管理接口完整前缀；默认 <base-url>/agent-keys')
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = Client(args.base_url, args.admin_path)

    status_code, status_message, status, _ = client.admin_request('GET', '/status')
    if status_code != '0000':
        print(f'FAIL status: {status_code} {status_message}', file=sys.stderr)
        return 2

    if status.get('adminEnabled') is not True:
        print('SKIP 后续用例：密钥管理接口已被服务端关闭 '
              '(RKB_AGENT_KEY_ADMIN_ENABLED=false)')
        return 0

    check('status.keyStoreAvailable', status.get('keyStoreAvailable') is True,
          '请先完成数据库初始化（deploy/init/pg/00-schema.sql）')
    check('status.pepperConfigured', status.get('pepperConfigured') is True,
          'RKB_AGENT_KEY_PEPPER 为空，无法创建 Key')
    if failures:
        return 1

    api_ready = bool(status.get('apiEnabled') and status.get('restEnabled'))
    if not api_ready:
        skip('agent 调用链', 'RKB_AGENT_API_ENABLED/REST_ENABLED 未开启')

    name = f'verify-admin-{int(time.time())}'
    prefix = None
    plaintext = None

    try:
        code, message, bo, _ = client.admin_request('POST', '', {
            'name': name,
            'scopes': ['kb:list'],
            'kbIds': [],
            'rateLimitPerMin': 60,
            'expiresAt': None,
        })
        check('create', code == '0000', f'{code} {message}')
        if code != '0000':
            return 1

        bo = bo or {}
        plaintext = bo.get('plaintextKey') or ''
        key_info = bo.get('key') or {}
        prefix = key_info.get('keyPrefix') or ''
        check('create.plaintextKey', plaintext.startswith('ragk_'), '<redacted>')
        check('create.keyPrefix', bool(prefix) and prefix.startswith('ragk_'), prefix)

        code, message, listing, _ = client.admin_request('GET', '?keyword=' + name)
        rows = (listing or {}).get('items') or []
        check('list.contains_new_key', code == '0000' and any(
            row.get('keyPrefix') == prefix for row in rows), f'{code} {message}')
        serialized = str(listing or {})
        check('list.no_plaintext', plaintext not in serialized, 'list leaked plaintext')
        check('list.no_hash', 'key_hash' not in serialized and 'keyHash' not in serialized,
              'list leaked key hash')

        if api_ready:
            response = client.agent_list(plaintext)
            check('agent.enabled.200', response.status_code == 200,
                  f'HTTP {response.status_code}: {response.text[:200]}')

        code, message, updated, _ = client.admin_request(
            'PATCH', f'/{prefix}', {'enabled': False})
        check('disable', code == '0000' and (updated or {}).get('enabled') is False,
              f'{code} {message}')
        if api_ready:
            response = client.agent_list(plaintext)
            check('agent.disabled.401', response.status_code == 401,
                  f'HTTP {response.status_code}: {response.text[:200]}')

        code, message, updated, _ = client.admin_request(
            'PATCH', f'/{prefix}', {'enabled': True})
        check('enable', code == '0000' and (updated or {}).get('enabled') is True,
              f'{code} {message}')
        if api_ready:
            response = client.agent_list(plaintext)
            check('agent.enabled_again.200', response.status_code == 200,
                  f'HTTP {response.status_code}: {response.text[:200]}')

        code, message, updated, _ = client.admin_request(
            'PATCH', f'/{prefix}', {
                'scopes': ['kb:list', 'kb:search'],
                'rateLimitPerMin': 10,
            })
        updated = updated or {}
        check('update', code == '0000'
              and updated.get('scopes') == ['kb:list', 'kb:search']
              and updated.get('rateLimitPerMin') == 10,
              f'{code} {message} {updated}')

        code, message, _bo, _ = client.admin_request('POST', '', {
            'name': f'{name}-past',
            'scopes': ['kb:list'],
            'expiresAt': '2000-01-01',
        })
        check('validation.past_expiry', code == '0004', f'{code} {message}')

        code, message, _bo, _ = client.admin_request('POST', '', {
            'name': f'{name}-scope',
            'scopes': ['nope'],
        })
        check('validation.unknown_scope', code == '0004', f'{code} {message}')

        code, message, _bo, _ = client.admin_request('DELETE', f'/{prefix}')
        check('delete', code == '0000', f'{code} {message}')
        prefix = None
        if api_ready:
            response = client.agent_list(plaintext)
            check('agent.deleted.401', response.status_code == 401,
                  f'HTTP {response.status_code}: {response.text[:200]}')
    finally:
        if prefix:
            client.admin_request('DELETE', f'/{prefix}')

    print()
    print(f'summary: failures={len(failures)} warnings={len(warnings)} '
          f'skips={len(skips)}')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
