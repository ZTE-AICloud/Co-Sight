#!/usr/bin/env python3
"""图谱**向量检索**端到端验收：写侧向量表 → 对外入口 → 种子召回 → 子图。

覆盖的是「图知识库到底能不能用」这条链：

1. ``graph_<uuid>_vector`` 存在且有 ``key_type='entity'`` 行（导入/抽图后**真的**
   写了向量，不是只把实体塞进 ``graph_<uuid>_vertex``）；
2. ``POST <RKB_PREFIX>/retrieval/graph``（经 nginx 的那条对外入口）返回 200 +
   检索结果对象（统一 REST 契约，无 ``code/data`` 信封）；
3. ``seed_entity_ids`` 非空 —— 证明向量召回命中，而不是空结果兜底；
4. 返回实体非空、``entity_count`` 与列表一致、所有种子都出现在实体里；
5. 若该库有 chunk 向量，``chunks`` 非空且 ``chunk_count`` 一致；没有则记 SKIP。

跑法（**容器内**；8091 未发布到宿主）::

    docker cp tools/verify/verify-graph-vector-retrieval.py <rkb>:/tmp/
    docker exec <rkb> python3 -u /tmp/verify-graph-vector-retrieval.py

也可以从宿主经 nginx 跑（此时无法读库，必须显式给 KB/模型/query）::

    RKB_GRAPH_TEST_KB=graph_<uuid> \
    RKB_GRAPH_TEST_EMBEDDING=Qwen3-Embedding-0.6B \
    RKB_GRAPH_TEST_QUERY='西湖一号站' \
    python3 tools/verify/verify-graph-vector-retrieval.py

可选环境变量：

* ``RKB_GRAPH_TEST_KB``          ``graph_<uuid>`` 或裸 ``<uuid>``；省略时自动挑一个
                                 「启用且有实体向量」的图库
* ``RKB_GRAPH_TEST_EMBEDDING``   覆盖 embedding 模型名（默认取 ``kb_kbase.embedding_model``）
* ``RKB_GRAPH_TEST_QUERY``       覆盖检索词（默认取向量表里的首条实体文本）
* ``RKB_GRAPH_RETRIEVE_URL``     默认 ``http://127.0.0.1:8091/api/co-knowledge/v1/retrieval/graph``

退出码：0 = 全绿（SKIP 不算失败）；1 = 有断言失败；2 = 环境不满足（找不到图库等）。
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE_RE = re.compile(r'^graph_[A-Za-z0-9_]{1,64}$')
DEFAULT_URL = 'http://127.0.0.1:8091/api/co-knowledge/v1/retrieval/graph'
SEED_K = 5
DEPTH = 1
TIMEOUT = 120

failures: list[str] = []
skips: list[str] = []


def check(name: str, condition: bool, detail: str = '') -> None:
    if condition:
        print(f'PASS {name}')
    else:
        print(f'FAIL {name}: {detail}')
        failures.append(name)


def skip(name: str, detail: str) -> None:
    print(f'SKIP {name}: {detail}')
    skips.append(name)


def post(url: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        method='POST',
        headers={
            'Content-Type': 'application/json',
            'X-Emp-No': 'admin',
            'Accept-Language': 'zh-CN',
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, json.loads(response.read() or b'{}')
    except urllib.error.HTTPError as error:
        raw = error.read()[:300].decode('utf-8', 'replace')
        return error.code, {'_http_body': raw}


def normalize_base(value: str) -> str:
    value = (value or '').strip()
    if value and not value.startswith('graph_'):
        value = f'graph_{value}'
    return value


def _connect():
    # 延迟 import：经 nginx 在宿主跑时不需要（也不会去连）业务库。
    from infrastructure.db.kb import connection

    return connection()


def discover_base() -> tuple[str, str, str]:
    """返回 ``(base, embedding_model, sample_text)``；找不到返回 ``('', '', '')``。"""
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT k.table_name, k.embedding_model
                FROM public.kb_kbase k
                JOIN pg_tables t
                  ON t.schemaname = 'kb_index'
                 AND t.tablename = k.table_name || '_vector'
                WHERE k.category = 10
                ORDER BY k.updated_at DESC NULLS LAST
                LIMIT 50
                """
            )
            candidates = cursor.fetchall()

            for table, model in candidates:
                if not table or not BASE_RE.match(table):
                    continue
                cursor.execute(
                    f"SELECT count(*) FROM kb_index.{table}_vector WHERE key_type = 'entity'")
                if cursor.fetchone()[0] == 0:
                    continue
                cursor.execute(
                    f"SELECT \"key\" FROM kb_index.{table}_vector "
                    "WHERE key_type = 'entity' AND \"key\" IS NOT NULL AND \"key\" <> '' "
                    'ORDER BY id LIMIT 1')
                row = cursor.fetchone()
                sample = (row[0] or '').strip() if row else ''
                return table, (model or '').strip(), sample

    return '', '', ''


def vector_stats(base: str) -> tuple[dict[str, int], int]:
    """返回 ``({key_type: rows}, chunk_rows)``；读不到库时返回空。"""
    table = f'kb_index.{base}_vector'
    with _connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'SELECT key_type, count(*) FROM {table} GROUP BY key_type')
            stats = {str(key_type): int(count) for key_type, count in cursor.fetchall()}

            chunk_table = f'kb_index.{base}_chunk'
            cursor.execute(
                "SELECT count(*) FROM pg_tables WHERE schemaname = 'kb_index' "
                "AND tablename = %s", (f'{base}_chunk',))
            chunk_rows = 0
            if cursor.fetchone()[0]:
                cursor.execute(f'SELECT count(*) FROM {chunk_table}')
                chunk_rows = int(cursor.fetchone()[0])
    return stats, chunk_rows


def main() -> int:
    base = normalize_base(os.environ.get('RKB_GRAPH_TEST_KB', ''))
    embedding = os.environ.get('RKB_GRAPH_TEST_EMBEDDING', '').strip()
    query = os.environ.get('RKB_GRAPH_TEST_QUERY', '').strip()
    url = os.environ.get('RKB_GRAPH_RETRIEVE_URL', DEFAULT_URL).strip() or DEFAULT_URL

    # 先校验再拼任何 SQL（表名只允许白名单字符）
    if base and not BASE_RE.match(base):
        print(f'非法图库基名: {base!r}', file=sys.stderr)
        return 2

    stats: dict[str, int] = {}
    chunk_rows = 0
    if not base:
        try:
            base, discovered_model, sample = discover_base()
            embedding = embedding or discovered_model
            query = query or sample
        except Exception as error:                                  # noqa: BLE001
            print(f'无法自动发现图谱库（{type(error).__name__}: {error}）', file=sys.stderr)
            print('请显式设置 RKB_GRAPH_TEST_KB / EMBEDDING / QUERY 后重试', file=sys.stderr)
            return 2
    else:
        try:
            embedding = embedding or ''
            if not query or not embedding:
                with _connect() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            'SELECT embedding_model FROM public.kb_kbase WHERE table_name = %s',
                            (base,))
                        row = cursor.fetchone()
                        embedding = embedding or ((row[0] or '').strip() if row else '')
                        if not query:
                            cursor.execute(
                                f"SELECT \"key\" FROM kb_index.{base}_vector "
                                "WHERE key_type = 'entity' AND \"key\" IS NOT NULL "
                                'AND "key" <> \'\' ORDER BY id LIMIT 1')
                            sample = cursor.fetchone()
                            query = (sample[0] or '').strip() if sample else ''
        except Exception as error:                                  # noqa: BLE001
            print(f'WARN 读库失败（{type(error).__name__}: {error}），只做接口断言',
                  file=sys.stderr)

    if not base or not BASE_RE.match(base):
        print(f'非法或缺失图库基名: {base!r}', file=sys.stderr)
        return 2
    if not embedding or not query:
        print('缺 embedding 模型名或检索词：设置 RKB_GRAPH_TEST_EMBEDDING / '
              'RKB_GRAPH_TEST_QUERY', file=sys.stderr)
        return 2

    print(f'base={base}\nembedding={embedding}\nquery={query[:120]!r}\nurl={url}\n')

    # 1) 写侧：向量表真的有 entity 行
    try:
        stats, chunk_rows = vector_stats(base)
        print(f'vector rows: {stats}; chunk rows: {chunk_rows}')
        check('vector table has entity rows', stats.get('entity', 0) > 0,
              f"stats={stats}")
    except Exception as error:                                      # noqa: BLE001
        skip('vector table stats', f'读不到业务库: {type(error).__name__}: {error}')

    # 2) 读侧：经对外入口调用
    payload = {
        'query': query,
        'embedding': embedding,
        'bases': [base],
        'scope': '',
        'seed_k': SEED_K,
        'depth': DEPTH,
        'limit': 100,
        'score': 0.0,
    }
    status, body = post(url, payload)
    check('retrieve HTTP 200', status == 200, f'status={status} body={body!r}')
    check('retrieve body is the result object',
          isinstance(body, dict) and 'base_results' in body, f'body={body!r}')

    data = body if isinstance(body, dict) else {}
    results = data.get('base_results') or []
    check('base_results length == 1', len(results) == 1,
          f'len={len(results)}')
    result = results[0] if results else {}

    seeds = result.get('seed_entity_ids') or []
    entities = result.get('entities') or []
    edges = result.get('edges') or []
    chunks = result.get('chunks') or {}

    check('vector recall produced seeds', len(seeds) > 0, f'seeds={seeds!r}')
    check('seed count within entity+edge top-k',
          len(seeds) <= SEED_K + 2 * SEED_K,
          f'seeds={len(seeds)} (seed_k={SEED_K}, entity 1x + edge 2 endpoints)')
    check('subgraph has entities', len(entities) > 0, 'entities=[]')
    check('entity_count matches list',
          result.get('entity_count') == len(entities),
          f"entity_count={result.get('entity_count')} len={len(entities)}")

    entity_ids = {str(entity.get('entity_id')) for entity in entities
                  if entity.get('entity_id') is not None}
    missing = [seed for seed in seeds if str(seed) not in entity_ids]
    check('all seeds are present in entities', not missing,
          f'missing={missing[:10]}')

    if chunk_rows > 0:
        check('chunks returned when chunk vectors exist', bool(chunks),
              f'chunk vector rows exist but chunks={len(chunks)}')
        check('chunk_count matches map', result.get('chunk_count') == len(chunks),
              f"chunk_count={result.get('chunk_count')} len={len(chunks)}")
    else:
        skip('chunk assertions', '该库没有 chunk 行/向量（抽图路径不产 document_chunk.jsonl）')

    print(f'\nseeds={len(seeds)} entities={len(entities)} edges={len(edges)} '
          f'chunks={len(chunks)}')
    if failures:
        print(f'\nsummary: failures={len(failures)} skips={len(skips)}')
        return 1
    print(f'\nsummary: PASS (skips={len(skips)})')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
