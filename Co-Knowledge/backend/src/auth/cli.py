"""账号管理 CLI（在**容器内**运行）。

与 ``agent/cli.py`` 同一形态：真正的实现在领域包里，``tools/user-admin.py``
只是宿主侧的 sys.path 包装。容器内推荐：

    python3 -m auth.cli create --username alice --display-name 张三 --generate
    python3 -m auth.cli list
    python3 -m auth.cli reset-password --username alice --generate
    python3 -m auth.cli disable --username alice
    python3 -m auth.cli enable  --username alice
    python3 -m auth.cli delete  --username alice --yes

密码只在 ``--generate``/创建时打印一次；库里只存 scrypt 哈希。
表不存在时先完成数据库初始化（``deploy/init/pg/00-schema.sql``）。
"""

from __future__ import annotations

import argparse
import secrets
import sys

import psycopg2
from psycopg2 import errors as pg_errors

from auth import repository as repo, service
from auth.errors import AuthError, AuthStoreUnavailable
from shared.problem import ProblemSpec, generic_detail, title_for


def _print_auth_error(error: AuthError) -> None:
    spec = ProblemSpec(error.status, error.problem_code,
                       title_for(error.problem_code))
    print(f'{error.problem_code}: {generic_detail(spec, "zh")}', file=sys.stderr)


def _run(action):
    try:
        return action()
    except AuthStoreUnavailable:
        print('账号表不存在：请先完成数据库初始化（deploy/init/pg/00-schema.sql）',
              file=sys.stderr)
        return None
    except pg_errors.UniqueViolation:
        print('用户名或邮箱已存在', file=sys.stderr)
        return None
    except AuthError as error:
        _print_auth_error(error)
        return None
    except psycopg2.Error as error:
        print(f'数据库错误: {error}', file=sys.stderr)
        return None


def _password(value: str | None, generate: bool) -> tuple[str, bool]:
    """返回 ``(password, generated)``；``--generate`` 优先于 ``--password``。"""
    if value and not generate:
        return value, False
    return secrets.token_urlsafe(18), True


def _cmd_create(args) -> int:
    password, generated = _password(args.password, args.generate)
    user = _run(lambda: service.create_user(
        args.username, password,
        display_name=args.display_name,
        email=args.email,
        role=args.role,
        must_change_password=args.must_change,
    ))
    if user is None:
        return 1
    print(f'created: {user.username} ({user.role})')
    if generated:
        print(f'password: {password}')
    return 0


def _cmd_list(_args) -> int:
    users = _run(repo.list_users)
    if users is None:
        return 1
    if not users:
        print('(no accounts)')
        return 0
    print(f'{"username":<24} {"role":<6} {"enabled":<8} {"must_change":<12} '
          f'{"last_login":<26} display_name')
    for row in users:
        print(f'{str(row.get("username") or ""):<24} '
              f'{str(row.get("role") or ""):<6} '
              f'{str(bool(row.get("enabled"))):<8} '
              f'{str(bool(row.get("must_change_password"))):<12} '
              f'{str(row.get("last_login_at") or "-"):<26} '
              f'{row.get("display_name") or ""}')
    return 0


def _cmd_reset_password(args) -> int:
    password, generated = _password(args.password, args.generate)
    user = _run(lambda: service.reset_password(
        args.username, password,
        must_change_password=not args.no_must_change,
    ))
    if user is None:
        return 1
    print(f'password reset: {user.username}')
    if generated:
        print(f'password: {password}')
    if not args.no_must_change:
        print('must_change_password: true')
    return 0


def _cmd_set_enabled(args, enabled: bool) -> int:
    user = _run(lambda: service.set_enabled(args.username, enabled))
    if user is None:
        return 1
    print(f'{"enabled" if enabled else "disabled"}: {user.username}')
    return 0


def _cmd_delete(args) -> int:
    if not args.yes:
        print('拒绝执行：delete 必须同时给 --yes', file=sys.stderr)
        return 2

    def _delete():
        service.delete_user(args.username)
        return True

    result = _run(_delete)
    if result is None:
        return 1
    print(f'deleted: {args.username}')
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='python3 -m auth.cli',
        description='Knowledge Studio 本地账号管理')
    sub = parser.add_subparsers(dest='command', required=True)

    create = sub.add_parser('create', help='新建账号')
    create.add_argument('--username', required=True)
    create.add_argument('--password', default='')
    create.add_argument('--generate', action='store_true')
    create.add_argument('--display-name', default='')
    create.add_argument('--email', default='')
    create.add_argument('--role', default='user', choices=('user', 'admin'))
    create.add_argument('--must-change', action='store_true')
    create.set_defaults(func=_cmd_create)

    listing = sub.add_parser('list', help='列出账号')
    listing.set_defaults(func=_cmd_list)

    reset = sub.add_parser('reset-password', help='重置口令并撤销全部会话')
    reset.add_argument('--username', required=True)
    reset.add_argument('--password', default='')
    reset.add_argument('--generate', action='store_true')
    reset.add_argument('--no-must-change', action='store_true')
    reset.set_defaults(func=_cmd_reset_password)

    disable = sub.add_parser('disable', help='禁用账号并撤销会话')
    disable.add_argument('--username', required=True)
    disable.set_defaults(func=lambda args: _cmd_set_enabled(args, False))

    enable = sub.add_parser('enable', help='启用账号')
    enable.add_argument('--username', required=True)
    enable.set_defaults(func=lambda args: _cmd_set_enabled(args, True))

    delete = sub.add_parser('delete', help='删除账号及其会话')
    delete.add_argument('--username', required=True)
    delete.add_argument('--yes', action='store_true')
    delete.set_defaults(func=_cmd_delete)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
