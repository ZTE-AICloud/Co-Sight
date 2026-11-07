"""按 PG 重建评测库的 ES 关键词索引（正文取 chunk 表）。

背景：``tools/verify/migrate-es-flat-schema.py`` 只从**向量表**取 ``text``。
新库向量表的 ``text`` 恒为 NULL，正文在 ``<table>_chunk``；直接用它重建会把
10 万条 ES 文档的 ``text`` 全丢成空，关键词路指标会掉到 ~1%。

本脚本是评测专用的修正版：
* ``text = COALESCE(vector.text, chunk.text)``；
* 手工切片的 chunk.text 是 ``【DURET-<pid>】\\n正文``，索引前剥掉标记；
* 用产品自己的 ``flat_document`` 生成 v2 文档，字段/mapping 与线上一致；
* 以 ``node_id`` 为 ``_id`` 覆盖写，可重复执行。

用法::

    python3 tools/rag-metrics/reindex_es.py --kb-id <kb-id> --dry-run
    python3 tools/rag-metrics/reindex_es.py --kb-id <kb-id> --apply
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Tuple

import psycopg2
import requests

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SRC = os.path.join(ROOT, 'backend', 'src')
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from retrieval.repository.vector_write_store import flat_document  # noqa: E402

MARKER_RE = re.compile(r'^【DURET-[0-9a-f]{32}】\n?')
KB_RE = re.compile(r'^[0-9a-f]{8,32}$')
BATCH = 500


def connect():
    return psycopg2.connect(
        host=os.environ.get('PGHOST', '127.0.0.1'),
        port=int(os.environ.get('PGPORT', '5432')),
        dbname=os.environ.get('PGDATABASE', 'rag_studio'),
        user=os.environ.get('PGUSER', 'rag'),
        # compose 默认值；生产请用 PGPASSWORD 覆盖。
        password=os.environ.get('PGPASSWORD', 'changeme'),
    )


def strip_marker(text: Any) -> Any:
    if text is None:
        return None
    return MARKER_RE.sub('', str(text), count=1)


def relation_map(conn, kb_id: str) -> Dict[str, str]:
    with conn.cursor() as cursor:
        cursor.execute(
            'SELECT node_id, directory_id FROM public.kb_node_relation WHERE kbase_id = %s',
            (kb_id,))
        relation: Dict[str, str] = {}
        for node_id, file_id in cursor.fetchall():
            if not node_id or not file_id:
                continue
            relation[node_id] = min(relation.get(node_id, file_id), file_id)
    return relation


def load_docs(conn, kb_id: str) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    table = f'doc_{kb_id}_vector'
    chunk = f'doc_{kb_id}_chunk'
    with conn.cursor() as cursor:
        cursor.execute('SELECT to_regclass(%s), to_regclass(%s)',
                       (f'kb_index."{table}"', f'kb_index."{chunk}"'))
        table_exists, chunk_exists = cursor.fetchone()
        if not table_exists:
            raise SystemExit(f'向量表不存在: {table}')
        if chunk_exists:
            sql = (
                'SELECT DISTINCT ON (v.node_id) '
                'v.node_id, v.text AS vector_text, v.source, '
                'v.content_expand, v.chunk_id, v.type, c.text AS chunk_text '
                f'FROM kb_index."{table}" v '
                f'LEFT JOIN kb_index."{chunk}" c ON v.content_expand = c.id '
                'WHERE v.node_id IS NOT NULL ORDER BY v.node_id, v.id DESC'
            )
        else:
            sql = (
                'SELECT DISTINCT ON (v.node_id) '
                'v.node_id, v.text AS vector_text, v.source, '
                'v.content_expand, v.chunk_id, v.type, NULL AS chunk_text '
                f'FROM kb_index."{table}" v '
                'WHERE v.node_id IS NOT NULL ORDER BY v.node_id, v.id DESC'
            )
        cursor.execute(sql)
        rows = cursor.fetchall()

    relation = relation_map(conn, kb_id)
    docs: List[Dict[str, Any]] = []
    stats = {'rows': len(rows), 'from_vector': 0, 'from_chunk': 0,
             'stripped_markers': 0, 'empty_text': 0, 'missing_file_id': 0}
    for (node_id, vector_text, source, content_expand,
         chunk_id, type_value, chunk_text) in rows:
        if vector_text is not None:
            text = vector_text
            stats['from_vector'] += 1
        else:
            text = chunk_text
            stats['from_chunk'] += 1
            cleaned = strip_marker(text)
            if cleaned != text:
                stats['stripped_markers'] += 1
            text = cleaned
        if text is None or not str(text).strip():
            stats['empty_text'] += 1
        file_id = relation.get(node_id)
        if file_id is None:
            stats['missing_file_id'] += 1
        docs.append(flat_document(node_id, file_id, text, {
            'source': source,
            'chunk_index': '',
            'content_expand': content_expand,
            'chunk_id': chunk_id,
            'type': type_value,
        }))
    return docs, stats


def apply_docs(es_url: str, index: str, docs: List[Dict[str, Any]]) -> None:
    for start in range(0, len(docs), BATCH):
        batch = docs[start:start + BATCH]
        lines = []
        for doc in batch:
            lines.append(json.dumps(
                {'index': {'_index': index, '_id': doc['node_id']}}, ensure_ascii=False))
            lines.append(json.dumps(doc, ensure_ascii=False))
        response = requests.post(
            f'{es_url}/{index}/_bulk',
            data=('\n'.join(lines) + '\n').encode('utf-8'),
            headers={'Content-Type': 'application/x-ndjson'}, timeout=120)
        response.raise_for_status()
        payload = response.json()
        if payload.get('errors'):
            failures = [
                item for item in payload.get('items') or []
                if ((item.get('index') or {}).get('status', 200) >= 300)
            ]
            raise SystemExit(f'bulk 失败: {failures[:3]}')
        if (start // BATCH) % 20 == 0:
            print(f'{min(start + BATCH, len(docs))}/{len(docs)} indexed', flush=True)
    requests.post(f'{es_url}/{index}/_refresh', timeout=120).raise_for_status()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--kb-id', required=True)
    parser.add_argument('--es-url', default='http://127.0.0.1:9200')
    parser.add_argument('--es-index', default=None,
                        help='默认 doc_<kb-id>')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not KB_RE.match(args.kb_id):
        raise SystemExit('kb-id 形态不合法')
    index = args.es_index or f'doc_{args.kb_id}'

    conn = connect()
    docs, stats = load_docs(conn, args.kb_id)
    conn.close()
    stats['index'] = index
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if args.dry_run or not args.apply:
        print('dry-run：未写入 ES')
        return
    apply_docs(args.es_url, index, docs)
    count = requests.get(f'{args.es_url}/{index}/_count', timeout=30).json()['count']
    with_text = requests.post(
        f'{args.es_url}/{index}/_count',
        json={'query': {'exists': {'field': 'text'}}}, timeout=30).json()['count']
    print(f'indexed {len(docs)} docs; ES count={count}; with text={with_text} '
          f'({with_text / max(len(docs), 1):.2%})')
    if docs and with_text < 0.9 * len(docs):
        raise SystemExit(
            'ES text 覆盖率不足 90%；reindex 很可能写丢了正文（检查 chunk 表与 COALESCE）')
    # 抽样确认 text 字段真的写进去了
    sample = requests.post(
        f'{args.es_url}/{index}/_search',
        json={'size': 1, 'query': {'exists': {'field': 'text'}}}, timeout=30).json()
    hits = ((sample.get('hits') or {}).get('hits')) or []
    if hits:
        print('sample:', {k: str(v)[:80] for k, v in hits[0]['_source'].items()})


if __name__ == '__main__':
    main()
