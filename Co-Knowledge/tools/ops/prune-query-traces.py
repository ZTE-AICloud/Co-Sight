#!/usr/bin/env python3
"""清理 `public.chat_query_trace` 中超过保留期的记录（默认 30 天，分批删除）。

这是**宿主侧**工具（`tools/` 不在 RKB 运行镜像里）：

    python3 tools/ops/prune-query-traces.py --dry-run
    python3 tools/ops/prune-query-traces.py --apply --yes --older-than-days 30
    python3 tools/ops/prune-query-traces.py --verify

cron 示例（每天 03:17，按实际仓库路径/环境调整；宿主连接走 127.0.0.1）：

    17 3 * * * cd /path/to/ragstudio-opensource && \
      set -a && . deploy/.env && set +a && \
      RKB_DB_HOST=127.0.0.1 RKB_DB_PORT=5432 \
      python3 tools/ops/prune-query-traces.py --apply --yes --older-than-days 30 \
      >> /var/log/rkb-query-trace-prune.log 2>&1

连接参数优先 RKB_DB_*，缺失时回落 POSTGRES_*（宿主的 deploy/.env 通常只有后一组）。
`--apply` 必须同时给 `--yes`，且 `--older-than-days` 不能小于 1，避免误删当天数据。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'backend' / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chat.schema import COLUMN_NAMES, INDEX_NAMES, TABLE_NAME  # noqa: E402

DEFAULT_DB = 'rag_studio'
DEFAULT_DAYS = 30
DEFAULT_BATCH = 5000
REQUIRED_COLUMNS = {'id', 'created_at', *COLUMN_NAMES}


def connect(dbname: str):
    # 宿主 cron 通常只 source deploy/.env（POSTGRES_*），容器内才一定有 RKB_DB_*；
    # 这里按优先级回落，避免默认去连 postgresql 主机名。
    return psycopg2.connect(
        host=(os.environ.get('RKB_DB_HOST')
              or os.environ.get('POSTGRES_HOST')
              or '127.0.0.1'),
        port=os.environ.get('RKB_DB_PORT', os.environ.get('POSTGRES_PORT', '5432')),
        user=(os.environ.get('RKB_DB_USER')
              or os.environ.get('POSTGRES_USER')
              or 'rag'),
        password=(os.environ.get('RKB_DB_PASSWORD')
                  or os.environ.get('POSTGRES_PASSWORD')
                  or ''),
        dbname=dbname,
        connect_timeout=2,
    )


def verify(cur) -> bool:
    cur.execute(
        'SELECT column_name FROM information_schema.columns '
        "WHERE table_schema = 'public' AND table_name = %s",
        (TABLE_NAME,))
    columns = {row[0] for row in cur.fetchall()}
    if not columns:
        print(f'FAIL missing table {TABLE_NAME}')
        return False
    missing_columns = sorted(REQUIRED_COLUMNS - columns)
    if missing_columns:
        print(f'FAIL missing columns: {", ".join(missing_columns)}')
        return False
    cur.execute(
        'SELECT indexname FROM pg_indexes '
        "WHERE schemaname = 'public' AND tablename = %s",
        (TABLE_NAME,))
    indexes = {row[0] for row in cur.fetchall()}
    missing_indexes = sorted(set(INDEX_NAMES) - indexes)
    if missing_indexes:
        print(f'FAIL missing indexes: {", ".join(missing_indexes)}')
        return False
    print(f'verify: PASS (columns={len(columns)}, indexes={len(INDEX_NAMES)})')
    return True


def dry_run(cur, older_than_days: int) -> int:
    cur.execute(
        f'SELECT count(*), min(created_at), max(created_at) FROM {TABLE_NAME} '
        'WHERE created_at < now() - make_interval(days => %s)',
        (older_than_days,))
    count, oldest, newest = cur.fetchone()
    print(f'dry-run: {count} row(s) older than {older_than_days} day(s)'
          f'（range: {oldest} .. {newest}）')
    return int(count or 0)


def _delete_batch(cur, older_than_days: int, batch_size: int) -> int:
    cur.execute(
        f'WITH victims AS ('
        f'  SELECT id FROM {TABLE_NAME} '
        '   WHERE created_at < now() - make_interval(days => %s) '
        '   ORDER BY created_at, id LIMIT %s'
        ') '
        f'DELETE FROM {TABLE_NAME} t USING victims v '
        'WHERE t.id = v.id RETURNING t.id',
        (older_than_days, batch_size))
    return len(cur.fetchall())


def prune(conn, older_than_days: int, batch_size: int) -> int:
    total = 0
    while True:
        with conn.cursor() as cur:
            deleted = _delete_batch(cur, older_than_days, batch_size)
        conn.commit()
        total += deleted
        print(f'deleted batch: {deleted} (total={total})')
        if deleted < batch_size:
            return total


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dbname', default=DEFAULT_DB)
    parser.add_argument('--older-than-days', type=int, default=DEFAULT_DAYS)
    parser.add_argument('--batch-size', type=int, default=DEFAULT_BATCH)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--dry-run', action='store_true')
    group.add_argument('--apply', action='store_true')
    group.add_argument('--verify', action='store_true')
    parser.add_argument('--yes', action='store_true')
    args = parser.parse_args(argv)

    if args.apply and not args.yes:
        print('拒绝执行：--apply 必须同时给 --yes', file=sys.stderr)
        return 2
    if args.apply and args.older_than_days < 1:
        print('拒绝执行：--older-than-days 必须 >= 1', file=sys.stderr)
        return 2
    if args.batch_size < 1:
        print('拒绝执行：--batch-size 必须 >= 1', file=sys.stderr)
        return 2

    conn = connect(args.dbname)
    try:
        with conn.cursor() as cur:
            if args.verify:
                return 0 if verify(cur) else 1
            if not args.apply:
                dry_run(cur, args.older_than_days)
                return 0
        total = prune(conn, args.older_than_days, args.batch_size)
        print(f'applied: deleted {total} row(s) older than '
              f'{args.older_than_days} day(s)')
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
