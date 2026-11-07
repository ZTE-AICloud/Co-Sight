#!/usr/bin/env python3
"""清理三类任务表中已进入终态且超过保留期的历史行。

宿主侧工具：

    python3 tools/ops/prune-task-history.py --dry-run
    python3 tools/ops/prune-task-history.py --apply --yes --older-than-days 90

只删终态任务；PENDING/RUNNING/RETRY 永不删除。图谱抽取任务有
``fk_graph_extract_task_kbase``，但保留的是任务行，不影响 KB。
"""

from __future__ import annotations

import argparse
import os
import sys

import psycopg2

DEFAULT_DB = 'rag_studio'
DEFAULT_DAYS = 90
DEFAULT_BATCH = 2000

#: (table, terminal statuses, time column)
TASKS = (
    ('kb_import_task', ('COMPLETED', 'FAILED'), 'created_at'),
    ('graph_import_task', ('COMPLETED', 'COMPLETED_WITH_ERRORS', 'FAILED'), 'created_at'),
    ('graph_extract_task', ('SUCCESS', 'FAIL'), 'created_at'),
)


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


def where_clause(table: str, statuses: tuple[str, ...], time_col: str,
                 days: int) -> tuple[str, tuple]:
    placeholders = ','.join(['%s'] * len(statuses))
    return (f'status IN ({placeholders}) AND {time_col} < '
            'now() - make_interval(days => %s)', (*statuses, days))


def count_rows(cur, table, statuses, time_col, days) -> int:
    where, params = where_clause(table, statuses, time_col, days)
    cur.execute(f'SELECT count(*) FROM public.{table} WHERE {where}', params)
    return int(cur.fetchone()[0])


def delete_rows(cur, table, statuses, time_col, days, batch) -> int:
    where, params = where_clause(table, statuses, time_col, days)
    deleted = 0
    while True:
        cur.execute(f"""
            DELETE FROM public.{table}
            WHERE ctid IN (
                SELECT ctid FROM public.{table} WHERE {where} LIMIT %s
            )
        """, (*params, batch))
        if not cur.rowcount:
            break
        deleted += cur.rowcount
    return deleted


def verify(cur) -> bool:
    ok = True
    for table, statuses, time_col in TASKS:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
        """, (table,))
        columns = {row[0] for row in cur.fetchall()}
        missing = {'status', time_col} - columns
        if not columns or missing:
            print(f'FAIL {table}: missing {sorted(missing) or "table"}')
            ok = False
    if ok:
        print('PASS task history retention columns')
    return ok


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
            counts = {table: count_rows(cur, table, statuses, time_col,
                                        args.older_than_days)
                      for table, statuses, time_col in TASKS}
            for table, count in counts.items():
                print(f'[{args.dbname}] {table}: {count} terminal rows older '
                      f'than {args.older_than_days} days')
            if args.dry_run:
                print('dry-run：未删除。要清理请加 --apply --yes')
                return 0
            deleted = {}
            for table, statuses, time_col in TASKS:
                deleted[table] = delete_rows(cur, table, statuses, time_col,
                                             args.older_than_days, args.batch)
        conn.commit()
        for table, count in deleted.items():
            print(f'[{args.dbname}] deleted {count} rows from {table}')
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
