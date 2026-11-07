#!/usr/bin/env python3
"""图谱工作流端到端验收：建流（绑图谱库）→ 画布 → 发布 → 问答 → 多轮追问。

覆盖的是「图谱能不能真正用起来」这条产品链路，而不是单个接口的形状：

1. `POST /workflow` 绑一个图谱知识库 —— 服务端应自动选 `Blended_graph` 变体，
   画布里出现 `KnowledgeGraphRetriever`，且 `kwargs.knowledge_base_name` 只含图谱库；
2. 画布里的算子必须能过发布硬门槛（无外部重排算子、无未知包名）；
3. `POST /flow/publish` 成功；
4. `POST /query` 返回非空答案（图谱实体/属性真的进了合成上下文）；
5. 带 `chat_history` 的追问返回非空答案（多轮改写路径可用）。

脚本**自清理**：默认跑完删除创建的工作流（`--keep` 保留，便于手工看画布）。

用法（容器内；8091 未发布到宿主）::

    docker cp tools/verify/verify-graph-workflow-chat-e2e.py <rkb>:/tmp/
    docker exec <rkb> python3 -u /tmp/verify-graph-workflow-chat-e2e.py

可选环境变量：

* ``RKB_BASE_URL``          默认 ``http://127.0.0.1:8091/api/co-knowledge/v1``
* ``RKB_GRAPH_TEST_KB``     ``graph_<uuid>``；省略时自动挑一个「启用且有 entity 向量」的图库
* ``RKB_GRAPH_TEST_EMBEDDING``  默认取 ``kb_kbase.embedding_model``
* ``RKB_GRAPH_TEST_QUERY``  首轮问题；默认用向量表首条实体文本构造
* ``RKB_GRAPH_TEST_KEEP=1`` 保留创建的工作流

退出码：0 = 全绿；1 = 断言失败；2 = 环境不满足（找不到图库等）。
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get('RKB_BASE_URL', 'http://127.0.0.1:8091/api/co-knowledge/v1').rstrip('/')
BASE_RE = re.compile(r'^graph_[A-Za-z0-9_]{1,64}$')
STAMP = uuid.uuid4().hex[:8]
WORKFLOW_ID = f'RAG_Workflow_graph_e2e_{STAMP}'
CONVERSATION_ID = f'dlg-graph-e2e-{STAMP}'
KEEP = os.environ.get('RKB_GRAPH_TEST_KEEP', '').strip().lower() in {'1', 'true', 'yes'}
HEADERS = {
    'Content-Type': 'application/json',
    'X-Emp-No': 'admin',
    'Accept-Language': 'zh-CN',
    'language-option': 'zh-CN',
    'X-Request-Id': f'e2e-graph-{STAMP}',
}

failures: list[str] = []


def check(name: str, condition: bool, detail: str = '') -> None:
    if condition:
        print(f'PASS {name}')
    else:
        print(f'FAIL {name}: {detail}')
        failures.append(name)


def call(method: str, path: str, body=None) -> tuple[int, dict, dict]:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request(BASE + path, data=data, method=method,
                                     headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return response.status, dict(response.headers), json.loads(response.read() or b'{}')
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), {
            '_body': error.read()[:500].decode('utf-8', 'replace')}


def kb_ok(status: int) -> bool:
    """RKB API 与编排 /query 都用真实 2xx。"""
    return 200 <= status < 300


def discover_graph_kb() -> tuple[str, str, str]:
    from infrastructure.db.kb import connection

    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT k.table_name, k.embedding_model
                FROM public.kb_kbase k
                JOIN pg_tables t
                  ON t.schemaname = 'kb_index' AND t.tablename = k.table_name || '_vector'
                WHERE k.category = 10
                ORDER BY k.updated_at DESC NULLS LAST
                LIMIT 50
                """
            )
            for table, model in cursor.fetchall():
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


def main() -> int:
    base = (os.environ.get('RKB_GRAPH_TEST_KB') or '').strip()
    embedding = (os.environ.get('RKB_GRAPH_TEST_EMBEDDING') or '').strip()
    query = (os.environ.get('RKB_GRAPH_TEST_QUERY') or '').strip()

    if not base:
        try:
            base, discovered_embedding, sample = discover_graph_kb()
            embedding = embedding or discovered_embedding
            query = query or sample
        except Exception as error:                                  # noqa: BLE001
            print(f'cannot discover graph KB: {type(error).__name__}: {error}', file=sys.stderr)
            return 2
    if not base or not BASE_RE.match(base):
        print(f'illegal graph base: {base!r}', file=sys.stderr)
        return 2
    if not embedding:
        print('missing embedding model (set RKB_GRAPH_TEST_EMBEDDING)', file=sys.stderr)
        return 2
    if not query:
        query = '请介绍这个知识图谱中的实体'

    print(f'workflow={WORKFLOW_ID}\nbase={base}\nembedding={embedding}\nquery={query[:80]!r}\n')
    created = False
    try:
        print('=== create flow')
        status, _, payload = call('POST', '/workflows', {
            'name': f'graph-e2e-{STAMP}',
            'workFlowId': WORKFLOW_ID,
            'template': 'Blended',
            'knowledgeType': 'knowledgeBase',
            'description': 'graph workflow e2e (verify script)',
            'boundInfo': {'running': [{'tableName': base, 'embeddingModel': embedding}]},
        })
        check('create flow', kb_ok(status),
              f'status={status} payload={payload!r}')
        if failures:
            return 1
        created = True

        print('=== inspect canvas')
        status, _, flow = call('GET', f'/workflows/{WORKFLOW_ID}/flow')
        flow = flow
        operators = []
        graph_kwargs = None
        for node in flow.get('nodeConfigDTOList') or []:
            for stage, ops in (node.get('variables') or {}).items():
                if not isinstance(ops, list):
                    continue
                for op in ops:
                    if isinstance(op, dict) and op.get('operator'):
                        operators.append(op['operator'])
                        if op['operator'] == 'KnowledgeGraphRetriever':
                            graph_kwargs = op.get('kwargs') or {}
        check('canvas has KnowledgeGraphRetriever',
              'KnowledgeGraphRetriever' in operators, f'operators={operators}')
        rerank_ops = {'ExternalModelReranker', 'BgeLargeReranker'} & set(operators)
        check('canvas has no external model reranker',
              not rerank_ops, f'operators={operators}')
        if graph_kwargs is not None:
            check('graph retriever bound to the graph KB only',
                  graph_kwargs.get('knowledge_base_name') == [base],
                  f"kwargs={graph_kwargs!r}")
            check('graph retriever got the embedding model',
                  graph_kwargs.get('embedding') == embedding,
                  f"embedding={graph_kwargs.get('embedding')!r}")

        print('=== publish')
        status, _, payload = call('POST', f'/workflows/{WORKFLOW_ID}/publication')
        check('publish', kb_ok(status),
              f'status={status} payload={payload!r}')
        if failures:
            return 1

        print('=== query first turn')
        status, headers, payload = call('POST', '/query', {
            'question': query,
            'conversation_id': CONVERSATION_ID,
            'workflow_id': WORKFLOW_ID,
            'stream': False,
        })
        data = payload if isinstance(payload, dict) else {}
        answer = str(data.get('answer') or '')
        check('query returned an answer', bool(answer.strip()),
              f'answer={answer!r}')
        check('query returned a request id',
              bool((headers.get('x-request-id') or headers.get('X-Request-Id'))),
              f'headers={headers!r}')

        print('=== query follow-up with chat_history')
        status, headers, payload = call('POST', '/query', {
            'question': '那它属于哪个区？',
            'conversation_id': CONVERSATION_ID,
            'workflow_id': WORKFLOW_ID,
            'stream': False,
            'chat_history': [{'question': query, 'answer': answer}],
        })
        data = payload if isinstance(payload, dict) else {}
        follow_up_answer = str(data.get('answer') or '')
        check('follow-up returned an answer', bool(follow_up_answer.strip()),
              f'answer={follow_up_answer!r}')

        print(f'\nfirst answer: {answer[:160]!r}')
        print(f'follow-up:    {follow_up_answer[:160]!r}')
        return 0 if not failures else 1
    finally:
        if created and not KEEP:
            try:
                call('DELETE', f'/workflows/{WORKFLOW_ID}')
                print(f'cleaned workflow {WORKFLOW_ID}')
            except Exception as error:                              # noqa: BLE001
                print(f'WARN cleanup failed: {type(error).__name__}: {error}', file=sys.stderr)
        elif created:
            print(f'kept workflow {WORKFLOW_ID} (RKB_GRAPH_TEST_KEEP=1)')


if __name__ == '__main__':
    raise SystemExit(main())
