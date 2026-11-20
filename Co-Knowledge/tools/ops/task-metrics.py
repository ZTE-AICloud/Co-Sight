#!/usr/bin/env python3
"""把统一任务表的观测值渲染成 Prometheus 文本格式。

宿主侧工具（配合 node_exporter textfile collector）::

    python3 tools/ops/task-metrics.py > /var/lib/node_exporter/textfile/task_center.prom

cron 示例（每分钟）::

    * * * * * /path/to/ragstudio/tools/ops/task-metrics.py \
      > /var/lib/node_exporter/textfile/task_center.prom

只读查询 ``task_center.task`` / ``task_center.task_attempt``，不修改任何数据。
"""

from __future__ import annotations

import argparse
import os
import sys

import psycopg2

DEFAULT_DB = 'rag_studio'


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


def _escape(value: str) -> str:
    return (str(value).replace('\\', '\\\\')
            .replace('"', '\\"').replace('\n', '\\n'))


def _labels(**labels: object) -> str:
    if not labels:
        return ''
    body = ','.join(f'{key}="{_escape(value)}"' for key, value in labels.items())
    return '{' + body + '}'


def _metric(lines: list[str], name: str, kind: str, help_text: str,
            samples: list[tuple[dict, float | int]]) -> None:
    lines.append(f'# HELP {name} {help_text}')
    lines.append(f'# TYPE {name} {kind}')
    for labels, value in samples:
        lines.append(f'{name}{_labels(**labels)} {value}')
    lines.append('')


def render(cur) -> str:
    lines: list[str] = []

    cur.execute(
        'SELECT task_type, lane, status, count(*) FROM task_center.task '
        'GROUP BY task_type, lane, status ORDER BY task_type, lane, status')
    _metric(
        lines, 'task_center_task_total', 'gauge',
        'Tasks by type, lane and status.',
        [({'task_type': task_type, 'lane': lane, 'status': status}, count)
         for task_type, lane, status, count in cur.fetchall()])

    cur.execute(
        "SELECT lane, count(*) FROM task_center.task "
        "WHERE status IN ('PENDING', 'RETRY') GROUP BY lane ORDER BY lane")
    queue = {lane: 0 for lane in ('file_import', 'graph_extract', 'graph_import')}
    queue.update({lane: count for lane, count in cur.fetchall()})
    _metric(
        lines, 'task_center_queue_depth', 'gauge',
        'Pending plus retry tasks per lane.',
        [({'lane': lane}, count) for lane, count in sorted(queue.items())])

    cur.execute(
        "SELECT COALESCE(extract(epoch FROM now() - min(created_at)), 0)::bigint "
        "FROM task_center.task WHERE status IN ('PENDING', 'RETRY')")
    oldest = int(cur.fetchone()[0] or 0)
    _metric(
        lines, 'task_center_oldest_pending_age_seconds', 'gauge',
        'Age in seconds of the oldest PENDING/RETRY task.',
        [({}, oldest)])

    cur.execute(
        "SELECT count(*) FROM task_center.task "
        "WHERE status = 'RUNNING' AND locked_until < now()")
    overdue = int(cur.fetchone()[0] or 0)
    _metric(
        lines, 'task_center_running_overdue', 'gauge',
        'RUNNING tasks whose lease has expired.',
        [({}, overdue)])

    cur.execute(
        'SELECT status, count(*) FROM task_center.task_attempt '
        'GROUP BY status ORDER BY status')
    attempts = {status: 0 for status in (
        'RUNNING', 'COMPLETED', 'COMPLETED_WITH_ERRORS', 'FAILED',
        'CANCELLED', 'LOST')}
    attempts.update({status: count for status, count in cur.fetchall()})
    _metric(
        lines, 'task_center_attempt_total', 'gauge',
        'Task execution attempts by final status.',
        [({'status': status}, count)
         for status, count in sorted(attempts.items())])

    return '\n'.join(lines).rstrip() + '\n'


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dbname', default=DEFAULT_DB)
    args = parser.parse_args(argv)

    conn = connect(args.dbname)
    try:
        with conn.cursor() as cur:
            sys.stdout.write(render(cur))
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
