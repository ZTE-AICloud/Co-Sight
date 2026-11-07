"""Agent API Key 管理 CLI（在**容器内**运行）。

为什么放在 ``backend/src/agent_api/`` 而不是仓库根的 ``tools/``：
compose 的 build context 是 ``backend/``，``tools/`` 不会进运行镜像；而建 Key
需要与后端同一份 ``RKB_DB_*`` 环境与同一个 pepper，容器内执行最省事。

用法（容器内）::

    python3 -m agent_api.cli create --name dify-prod \\
        --scopes kb:list,kb:search,kb:answer \\
        --kb-ids 7ad5...,f2f2... --rate-limit 60
    python3 -m agent_api.cli list
    python3 -m agent_api.cli revoke --prefix ragk_a1b2c3d4e5
    python3 -m agent_api.cli enable  --prefix ragk_a1b2c3d4e5

明文只在 ``create`` 时打印一次；库里只存前缀与 HMAC 哈希。
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from agent import key_ops, keys, scopes, repository_pg as store_pg  # noqa: F401 — keys 是测试注入点
from agent.errors import AgentKeyStoreUnavailable

# argparse 默认值与测试引用的常量：
# 真值在 ``agent_api.scopes``，UI 管理接口与 CLI 共用，避免两份漂移。
DEFAULT_SCOPES = ','.join(scopes.DEFAULT_SCOPES)
KNOWN_SCOPES = scopes.KNOWN_SCOPES
KEY_PREFIX_RETRIES = scopes.KEY_PREFIX_RETRIES


def _parse_csv(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(',') if item.strip()]


def _parse_scopes(value: Optional[str]) -> list[str]:
    parsed = _parse_csv(value) or list(scopes.DEFAULT_SCOPES)
    unknown = [scope for scope in parsed if scope not in scopes.KNOWN_SCOPES]
    if unknown:
        raise SystemExit(
            f'未知 scope: {", ".join(unknown)}；可选: {", ".join(scopes.KNOWN_SCOPES)}')
    return parsed


def _parse_expires(value: Optional[str]):
    if not value:
        return None
    try:
        return key_ops.parse_expires(value)
    except ValueError as error:
        raise SystemExit(f'--expires 无法解析: {value!r}（用 YYYY-MM-DD 或 ISO 8601）') from error


def _pepper() -> str:
    pepper = (os.environ.get('RKB_AGENT_KEY_PEPPER') or '').strip()
    if not pepper:
        raise SystemExit(
            'RKB_AGENT_KEY_PEPPER 为空：拒绝创建 Key。'
            '请使用与后端相同的 pepper（生成方式：openssl rand -hex 32）。')
    return pepper


def _format_ts(value) -> str:
    if value is None:
        return '-'
    try:
        return value.strftime('%Y-%m-%d %H:%M:%S')
    except AttributeError:
        return str(value)


def _format_list(values) -> str:
    return ','.join(values or []) or '(all)'


def cmd_create(args) -> int:
    scope_list = _parse_scopes(args.scopes)
    kb_ids = _parse_csv(args.kb_ids)
    expires_at = _parse_expires(args.expires)
    if args.rate_limit < 0:
        raise SystemExit('--rate-limit 不能为负数（0 = 不限制）')
    pepper = _pepper()

    try:
        full_key, prefix = key_ops.create_key_record(
            name=args.name,
            description=(args.description or '').strip() or None,
            scopes_list=scope_list,
            kb_ids=kb_ids,
            rate_limit_per_min=args.rate_limit,
            expires_at=expires_at,
            created_by=args.created_by or os.environ.get('USER') or 'cli',
            pepper=pepper,
        )
    except key_ops.KeyAdminError as error:
        print(f'创建失败：{error.key}', file=sys.stderr)
        return 1

    print('created agent api key')
    print(f'  name:               {args.name}')
    print(f'  description:        {args.description or "-"}')
    print(f'  key_prefix:         {prefix}')
    print(f'  scopes:             {_format_list(scope_list)}')
    print(f'  kb_ids:             {_format_list(kb_ids)}')
    print(f'  rate_limit_per_min: {args.rate_limit}')
    print(f'  expires_at:         {_format_ts(expires_at)}')
    print()
    print('  public key (只显示这一次，请立即保存):')
    print(f'  {full_key}')
    return 0


def cmd_list(_args) -> int:
    rows = store_pg.list_keys()
    if not rows:
        print('no agent api keys')
        return 0
    headers = ('KEY_PREFIX', 'NAME', 'SCOPES', 'KB_IDS', 'RATE', 'ENABLED',
               'EXPIRES', 'LAST_USED')
    table = [headers]
    for row in rows:
        table.append((
            row.get('key_prefix') or '',
            row.get('name') or '',
            _format_list(row.get('scopes')),
            _format_list(row.get('kb_ids')),
            str(row.get('rate_limit_per_min', '')),
            'yes' if row.get('enabled') else 'no',
            _format_ts(row.get('expires_at')),
            _format_ts(row.get('last_used_at')),
        ))
    widths = [max(len(line[i]) for line in table) for i in range(len(headers))]
    for line in table:
        print('  '.join(cell.ljust(widths[i]) for i, cell in enumerate(line)))
    return 0


def _toggle(prefix: str, enabled: bool) -> int:
    changed = store_pg.set_enabled(prefix, enabled)
    if not changed:
        print(f'not found: {prefix}', file=sys.stderr)
        return 1
    print(f'{"enabled" if enabled else "disabled"}: {prefix}')
    return 0


def cmd_revoke(args) -> int:
    return _toggle(args.prefix, False)


def cmd_enable(args) -> int:
    return _toggle(args.prefix, True)


def cmd_disable(args) -> int:
    return _toggle(args.prefix, False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='python3 -m agent_api.cli',
        description='Knowledge Studio agent API key management')
    parser.add_argument('--dbname', default=None,
                        help='覆盖 RKB_DB_NAME（默认 rag_studio）')
    sub = parser.add_subparsers(dest='command', required=True)

    create = sub.add_parser('create', help='创建一把 Key（明文只输出一次）')
    create.add_argument('--name', required=True, help='用途名，如 dify-prod')
    create.add_argument('--description', default=None,
                        help='用途说明（选填，最多 200 字）')
    create.add_argument('--scopes', default=None,
                        help=f'逗号分隔；默认 {DEFAULT_SCOPES}；可选 {",".join(KNOWN_SCOPES)}')
    create.add_argument('--kb-ids', default=None,
                        help='逗号分隔的知识库 ID 白名单；留空 = 全部文档库')
    create.add_argument('--rate-limit', type=int, default=60,
                        help='每分钟请求上限；0 = 不限制')
    create.add_argument('--expires', default=None,
                        help='过期时间：YYYY-MM-DD 或 ISO 8601；留空 = 不过期')
    create.add_argument('--created-by', default=None)
    create.set_defaults(func=cmd_create)

    listing = sub.add_parser('list', help='列出 Key（不含明文/哈希）')
    listing.set_defaults(func=cmd_list)

    revoke = sub.add_parser('revoke', help='停用一把 Key（软删除）')
    revoke.add_argument('--prefix', required=True)
    revoke.set_defaults(func=cmd_revoke)

    enable = sub.add_parser('enable', help='重新启用一把 Key')
    enable.add_argument('--prefix', required=True)
    enable.set_defaults(func=cmd_enable)

    disable = sub.add_parser('disable', help='停用一把 Key')
    disable.add_argument('--prefix', required=True)
    disable.set_defaults(func=cmd_disable)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.dbname:
        os.environ['RKB_DB_NAME'] = args.dbname
    try:
        return args.func(args)
    except AgentKeyStoreUnavailable:
        print('Key 表不存在：请先完成数据库初始化（deploy/init/pg/00-schema.sql）',
              file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
