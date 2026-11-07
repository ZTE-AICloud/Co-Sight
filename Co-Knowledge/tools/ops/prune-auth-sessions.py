#!/usr/bin/env python3
"""清理 `public.auth_session` 中已过期/已撤销且超过保留期的会话。

宿主侧工具（`tools/` 不在 RKB 运行镜像里）：

    python3 tools/ops/prune-auth-sessions.py --dry-run
    python3 tools/ops/prune-auth-sessions.py --apply --yes --older-than-days 30

保留期从「过期或撤销时刻」起算；未过期且未撤销的活跃会话永不删除。
`--apply` 必须同时给 `--yes`，且 `--older-than-days` 不能小于 1。
"""

from __future__ import annotations

import argparse
import os
import sys

import psycopg2

DEFAULT_DB = 'rag_studio'
DEFAULT_DAYS = 30
DEFAULT_BATCH = 5000
TABLE = 'auth_session'


def connect(dbname: str):
    return psycopg2.connect(
        host=(os.environ.get('RKB_DB_HOST')
              or os.environ.get('POSTGRES_HOST') or '127.0.0.1'),
        port=os.environ.get('RKB_DB_PORT', os.environ.get('POSTGRES_PORT', '5432')),
        user=(os.environ.get('RKB_DB_USER')
              or os.environ.get('POSTGRES_USER') or 'rag'),
        password=(os.environ.get('RKB_DB_PASSWORD')
                  or os.environ.get('POSTGRES_PASSWORD') or ''),
        dbname=dbname,
        connect_timeout=2,
    )


def where_clause(days: int) -> tuple[str, tuple]:
    return ("""
        COALESCE(revoked_at, expires_at) < now() - make_interval(days => %s)
    """, (days,))


def count_rows(cur, days: int) -> int:
    where, params = where_clause(days)
    cur.execute(f'SELECT count(*) FROM public.{TABLE} WHERE {where}', params)
    return int(cur.fetchone()[0])


def delete_rows(cur, days: int, batch: int) -> int:
    where, params = where_clause(days)
    deleted = 0
    while True:
        cur.execute(f"""
            DELETE FROM public.{TABLE}
            WHERE ctid IN (
                SELECT ctid FROM public.{TABLE}
                WHERE {where}
                LIMIT %s
            )
        """, (*params, batch))
        if not cur.rowcount:
            break
        deleted += cur.rowcount
    return deleted


def verify(cur) -> bool:
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
    """, (TABLE,))
    columns = {row[0] for row in cur.fetchall()}
    missing = {'expires_at', 'revoked_at'} - columns
    if not columns or missing:
        print(f'FAIL {TABLE}: missing {sorted(missing) or "table"}')
        return False
    print(f'PASS {TABLE} retention columns')
    return True


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dbname', default=DEFAULT_DB)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--dry-run', action='store_true')
    group.add_argument('--apply', action='store_true')
    group.add_argument('--verify', action='store_true')
    parser.add_argument('--yes', action='store_true')
    parser.add_argument('--older-than-days', type=int, default=DEFAULT_DAYS)
    parser.add_argument('--batch', type=int, default=DEFAULT_BATCH)
    args = parser.parse_args(argv)

    if args.older_than_days < 1:
        print('拒绝执行：--older-than-days 必须 >= 1', file=sys.stderr)
        return 2
    if args.apply and not args.yes:
        print('拒绝执行：--apply 必须同时给 --yes', file=sys.stderr)
        return 2

    conn = connect(args.dbname)
    try:
        with conn.cursor() as cur:
            if args.verify:
                return 0 if verify(cur) else 1
            rows = count_rows(cur, args.older_than_days)
            print(f'[{args.dbname}] {TABLE}: {rows} rows older than '
                  f'{args.older_than_days} days')
            if args.dry_run:
                print('dry-run：未删除。要清理请加 --apply --yes')
                return 0
            deleted = delete_rows(cur, args.older_than_days, args.batch)
        conn.commit()
        print(f'[{args.dbname}] deleted {deleted} rows from {TABLE}')
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
