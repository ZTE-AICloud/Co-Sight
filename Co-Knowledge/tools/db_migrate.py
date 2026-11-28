#!/usr/bin/env python3
"""SQL 迁移编排：`deploy/init/pg/*.sql` 的可重复执行入口。

为什么需要它：那批文件原本只挂在 PostgreSQL 的 ``docker-entrypoint-initdb.d``
上，**只在空数据卷执行一次**。已有部署要升级只能照文档手工 psql，既没有
「执行过哪些」的记录，也没法判断某个文件是否已经跑过。

这里用一张 ``public.init_sql_migration`` 表记录「文件名 + 内容 sha256 + 时间」：

    python3 tools/db_migrate.py --status      # 看哪些已应用、哪些待应用
    python3 tools/db_migrate.py --apply       # 应用待执行的（改过内容的会报错）
    python3 tools/db_migrate.py --baseline    # 只登记不执行（给 init 建好的库补账）
    python3 tools/db_migrate.py --check       # CI 用：有待应用即退出码 1

连接信息只认 ``RKB_DB_*``（与应用同一口径）。``*.sh`` 授权脚本不在此执行，
``--status`` 会把它们列出来提醒单独跑。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
MIGRATION_DIR = ROOT / 'deploy' / 'init' / 'pg'
TABLE = 'public.init_sql_migration'

_CREATE_TABLE = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    filename   TEXT PRIMARY KEY,
    checksum   TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def connection():
    return psycopg2.connect(
        host=(os.environ.get('RKB_DB_HOST') or '').strip() or None,
        port=(os.environ.get('RKB_DB_PORT') or '').strip() or None,
        dbname=(os.environ.get('RKB_DB_NAME') or '').strip() or 'rag_studio',
        user=(os.environ.get('RKB_DB_USER') or '').strip() or None,
        password=os.environ.get('RKB_DB_PASSWORD', ''),
        connect_timeout=8,
    )


def migration_files() -> list[Path]:
    return sorted(path for path in MIGRATION_DIR.glob('*.sql'))


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def applied(conn) -> dict[str, str]:
    with conn.cursor() as cursor:
        cursor.execute(_CREATE_TABLE)
        cursor.execute(f'SELECT filename, checksum FROM {TABLE}')
        return {row[0]: row[1] for row in cursor.fetchall()}


def record(conn, path: Path) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            f'INSERT INTO {TABLE} (filename, checksum) VALUES (%s, %s) '
            'ON CONFLICT (filename) DO UPDATE SET checksum = EXCLUDED.checksum, '
            'applied_at = now()', (path.name, checksum(path)))


def run_sql(conn, path: Path) -> None:
    """执行一个迁移文件。

    文件里自己带 ``BEGIN/COMMIT`` 的直接交给服务端；没有的补一层事务，
    避免出现「一半语句成功、一半失败」的中间态。
    """
    sql = path.read_text(encoding='utf-8')
    has_transaction = any(line.strip().upper() in ('BEGIN;', 'BEGIN')
                          for line in sql.splitlines()[:20])
    with conn.cursor() as cursor:
        if has_transaction:
            cursor.execute(sql)
        else:
            cursor.execute('BEGIN')
            try:
                cursor.execute(sql)
                cursor.execute('COMMIT')
            except Exception:
                cursor.execute('ROLLBACK')
                raise


def report(conn) -> tuple[list[Path], list[Path]]:
    done = applied(conn)
    pending, drifted = [], []
    for path in migration_files():
        if path.name not in done:
            pending.append(path)
        elif done[path.name] != checksum(path):
            drifted.append(path)
    return pending, drifted


def main() -> int:
    parser = argparse.ArgumentParser(description='SQL 迁移编排')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--status', action='store_true')
    group.add_argument('--apply', action='store_true')
    group.add_argument('--baseline', action='store_true')
    group.add_argument('--check', action='store_true')
    args = parser.parse_args()

    conn = connection()
    conn.autocommit = True
    try:
        pending, drifted = report(conn)
        if args.status or args.check:
            for path in migration_files():
                state = ('pending' if path in pending else
                         'changed' if path in drifted else 'applied')
                print(f'{state:8s} {path.name}')
            shells = sorted(p.name for p in MIGRATION_DIR.glob('*.sh'))
            if shells:
                print('\n需要单独执行的授权脚本（以部署账号运行）：')
                for name in shells:
                    print(f'  {name}')
            return 1 if (args.check and pending) else 0

        if args.baseline:
            for path in pending:
                record(conn, path)
                print(f'baseline {path.name}')
            return 0

        if drifted:
            print('以下迁移在应用后被修改过，请新建文件而不是改旧文件：', file=sys.stderr)
            for path in drifted:
                print(f'  {path.name}', file=sys.stderr)
            return 2

        for path in pending:
            print(f'apply {path.name} ...', flush=True)
            try:
                run_sql(conn, path)
            except psycopg2.Error as error:
                print(f'apply {path.name} FAILED: '
                      f'{str(error).strip().splitlines()[0]}', file=sys.stderr)
                return 3
            record(conn, path)
            print(f'apply {path.name} ok')
        if not pending:
            print('没有待应用的迁移')
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    sys.exit(main())
