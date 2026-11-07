"""评测知识库的存储侧统计（报告附录用）。

只读，不写库。回答三个问题：
1. 向量行/切片行的规模与形态（普通行 text=NULL，LLM 优化行存正文）；
2. 是否存在删除切片后残留的孤儿向量行；
3. 实际导入的 pid 数，以及 qrels 覆盖率。

用法::

    python3 tools/rag-metrics/db_stats.py --kb-id <kb-id> \
        --data-dir .metrics-data/duretrieval --out .metrics-data/runs/<kb-id>/db-stats.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from typing import Any, Dict

import pandas as pd
import psycopg2

KB_ID_RE = re.compile(r'^[0-9a-f]{8,32}$')
MARKER_SQL = "substring({column} from '【DURET-([0-9a-f]{{32}})】')"


def connect():
    return psycopg2.connect(
        host=os.environ.get('PGHOST', '127.0.0.1'),
        port=int(os.environ.get('PGPORT', '5432')),
        dbname=os.environ.get('PGDATABASE', 'rag_studio'),
        user=os.environ.get('PGUSER', 'rag'),
        password=os.environ.get('PGPASSWORD', 'changeme'),
    )


def scalar(cursor, sql: str, params: Any = None) -> int:
    cursor.execute(sql, params)
    row = cursor.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--kb-id', required=True)
    parser.add_argument('--data-dir', default='.metrics-data/duretrieval')
    parser.add_argument('--es-index', default='',
                        help='可选：ES 索引名（kb_es_<kb-id>），用于核对关键词索引文档数')
    parser.add_argument('--es-url', default='http://127.0.0.1:9200')
    parser.add_argument('--out', default='')
    args = parser.parse_args()
    if not KB_ID_RE.match(args.kb_id):
        raise SystemExit('kb-id 形态不合法')
    vector = f'kb_index.doc_{args.kb_id}_vector'
    chunk = f'kb_index.doc_{args.kb_id}_chunk'

    stats: Dict[str, Any] = {'kb_id': args.kb_id, 'vector_table': vector, 'chunk_table': chunk}
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT to_regclass(%s), to_regclass(%s)', (vector, chunk))
            vector_exists, chunk_exists = cursor.fetchone()
            if not vector_exists:
                raise SystemExit(f'向量表不存在: {vector}')
            stats['chunk_table_exists'] = bool(chunk_exists)
            stats['vector_rows'] = scalar(cursor, f'SELECT count(*) FROM {vector}')
            stats['vector_text_null'] = scalar(
                cursor, f'SELECT count(*) FROM {vector} WHERE text IS NULL')
            stats['vector_text_present'] = stats['vector_rows'] - stats['vector_text_null']
            # 并发下写入可能留下 vector.text 有正文、但没有 chunk 行的行。
            stats['text_without_chunk_rows'] = stats['vector_text_present']
            stats['chunk_rows'] = (scalar(cursor, f'SELECT count(*) FROM {chunk}')
                                   if chunk_exists else 0)
            if chunk_exists:
                stats['orphan_vector_rows'] = scalar(
                    cursor,
                    f'SELECT count(*) FROM {vector} v LEFT JOIN {chunk} c '
                    'ON v.content_expand = c.id WHERE c.id IS NULL')
                stats['orphan_empty_content'] = scalar(
                    cursor,
                    f'SELECT count(*) FROM {vector} v LEFT JOIN {chunk} c '
                    'ON v.content_expand = c.id WHERE c.id IS NULL AND v.text IS NULL')
                stats['true_orphan_rows'] = stats['orphan_empty_content']
                # 有正文但 join 不到 chunk 行。
                stats['text_without_chunk_rows'] = max(
                    stats['orphan_vector_rows'] - stats['true_orphan_rows'], 0)
                stats['imported_pids'] = scalar(
                    cursor,
                    f'SELECT count(DISTINCT pid) FROM ('
                    f"  SELECT {MARKER_SQL.format(column='text')} AS pid FROM {chunk} "
                    f"  UNION ALL "
                    f"  SELECT {MARKER_SQL.format(column='content_expand')} AS pid FROM {vector}"
                    ' ) markers WHERE pid IS NOT NULL')
                # 同一 pid 的同一段正文出现多次 = 失败重试留下的重复切片。
                stats['duplicate_part_groups'] = scalar(
                    cursor,
                    f'SELECT count(*) FROM ('
                    f'  SELECT pid, body, count(*) AS c FROM ('
                    f"    SELECT {MARKER_SQL.format(column='text')} AS pid, text AS body "
                    f'    FROM {chunk} '
                    f'    UNION ALL '
                    f"    SELECT {MARKER_SQL.format(column='content_expand')} AS pid, "
                    f'           text AS body FROM {vector}'
                    '  ) parts WHERE pid IS NOT NULL GROUP BY pid, body HAVING count(*) > 1'
                    ' ) dup')
            else:
                stats['imported_pids'] = scalar(
                    cursor,
                    f"SELECT count(DISTINCT {MARKER_SQL.format(column='content_expand')}) "
                    f'FROM {vector}')

    if args.es_index:
        try:
            base = f'{args.es_url.rstrip("/")}/{args.es_index}/_count'
            with urllib.request.urlopen(base, timeout=10) as response:
                stats['es_docs'] = int(json.loads(response.read())['count'])
            request = urllib.request.Request(
                base,
                data=json.dumps({'query': {'exists': {'field': 'text'}}}).encode(),
                headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(request, timeout=10) as response:
                stats['es_docs_with_text'] = int(json.loads(response.read())['count'])
        except Exception as error:                                # noqa: BLE001
            stats['es_docs_error'] = str(error)[:200]

    qrels = pd.read_parquet(os.path.join(args.data_dir, 'qrels.parquet'))
    stats['qrels_pids_total'] = int(qrels['pid'].nunique())
    stats['qrels_rows'] = int(len(qrels))
    # coverage 的精确值由 run_retrieval_metrics.py 从 API 侧再算一遍；这里只给存储侧规模。

    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if args.out:
        os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
        with open(args.out, 'w', encoding='utf-8') as handle:
            json.dump(stats, handle, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:                                    # noqa: BLE001
        print(f'db_stats failed: {error}', file=sys.stderr)
        raise
