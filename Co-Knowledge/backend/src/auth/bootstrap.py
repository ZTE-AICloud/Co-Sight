"""首次启动播种管理员账号。

只在 ``AUTH_MODE=local`` 且 ``auth_user`` 为空时执行一次。异常一律只记日志、
不阻断服务启动：数据库暂时不可用时，登录接口会回 503，运维仍能进容器
排查；把整个服务启不起来反而更难处理。

密码来源：``RKB_ADMIN_PASSWORD``；为空则生成随机值。密码写到
``RKB_ADMIN_PASSWORD_FILE``（默认 ``/data/rkb/initial-admin-password``，0600）。
首次登录后强制改密；改密成功会删除该文件（见 ``service._remove_bootstrap_password_file``）。
"""

from __future__ import annotations

import logging
import os
import secrets

from auth import repository as repo, service

log = logging.getLogger(__name__)

DEFAULT_ADMIN_USERNAME = 'admin'
DEFAULT_PASSWORD_FILE = '/data/rkb/initial-admin-password'


def _password_file_path() -> str:
    return (os.environ.get('RKB_ADMIN_PASSWORD_FILE')
            or DEFAULT_PASSWORD_FILE).strip()


def _write_password_file(path: str, password: str) -> bool:
    """0600 写入；失败返回 False（调用方决定是否把密码打到日志）。"""
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(password + '\n')
        os.chmod(path, 0o600)
        return True
    except OSError:
        return False


def ensure_initial_admin() -> bool:
    """返回是否真的创建了账号。"""
    if service.auth_mode() != 'local':
        return False

    try:
        if not repo.table_exists():
            log.error(
                'auth tables are missing; apply deploy/init/pg/00-schema.sql '
                'before enabling AUTH_MODE=local')
            return False
        if repo.count_users() > 0:
            return False
    except Exception:                                              # noqa: BLE001
        log.exception('auth bootstrap: cannot inspect account table')
        return False

    username = (os.environ.get('RKB_ADMIN_USERNAME')
                or DEFAULT_ADMIN_USERNAME).strip()
    configured = os.environ.get('RKB_ADMIN_PASSWORD') or ''
    generated = not configured
    password = configured or secrets.token_urlsafe(18)
    must_change = ((os.environ.get('RKB_ADMIN_MUST_CHANGE') or 'true')
                   .strip().lower() not in {'0', 'false', 'no', 'off'})

    if configured and len(configured) < 8:
        log.warning(
            'auth bootstrap: RKB_ADMIN_PASSWORD is shorter than 8 characters; '
            'it is accepted for the bootstrap admin only. Change it after first login.')

    try:
        service.create_user(
            username, password,
            display_name='Administrator',
            role='admin',
            must_change_password=must_change,
            # 运维显式提供的引导口令允许低于常规策略；生成的随机口令不需要。
            allow_weak_password=bool(configured),
        )
    except Exception:                                              # noqa: BLE001
        # 多副本同时启动时另一个实例可能已抢先插入；按“已存在”处理。
        log.exception('auth bootstrap: failed to create initial admin %s', username)
        return False

    path = _password_file_path()
    if _write_password_file(path, password):
        log.warning(
            'auth bootstrap: created initial admin %r; password written to %s%s',
            username, path, ' (change it on first login)' if must_change else '')
    elif generated:
        # 文件写不进去时，给一次“唯一可行的出口”；提示立刻改密。
        log.warning(
            'auth bootstrap: created initial admin %r with generated password %r; '
            'the password file %s is not writable — change it immediately',
            username, password, path)
    else:
        log.warning(
            'auth bootstrap: created initial admin %r from RKB_ADMIN_PASSWORD; '
            'password file %s is not writable', username, path)
    return True
