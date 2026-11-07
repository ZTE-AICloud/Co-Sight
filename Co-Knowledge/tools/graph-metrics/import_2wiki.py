#!/usr/bin/env python3
"""导入 2WikiMultiHopQA 端到端评测资源：文档库 + 图谱库 + 已发布工作流。

前置：``prepare_2wiki.py`` 已生成 ``questions.jsonl/articles.jsonl/graph_upload/``。

流程与断点：

1. **文档库**：逐篇文章作为手工切片写入一个容器文件；切片 ``supplement`` 带
   ``【2WIKI-<aid>】`` 标记，重跑时按标记跳过已导入文章。
2. **图谱库**：把 ``graph_upload/*.txt`` 交给产品的通用抽图算子
   （``operatorId=-6``，LLM 用模型注册表里的 ``deepseek-chat-1``），
   轮询知识库状态到 5；成功后校验 entity/edge 数不为 0。
3. **工作流**：建 ``Blended`` 流并绑定两个库（自动切 ``Blended_normal_graph``），
   把图谱检索 ``depth`` 改成 3（多跳题），保存并发布。

状态写在 ``--state``（默认 ``.metrics-data/2wiki/state.json``），每一步成功后才落盘。

跑法::

    python3 tools/graph-metrics/import_2wiki.py
    python3 tools/graph-metrics/import_2wiki.py --resume
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from graph_client import RkbClient, RkbError

DEFAULT_BASE = 'http://127.0.0.1/api/co-knowledge/v1'
DEFAULT_DATA = Path('.metrics-data/2wiki/data')
DEFAULT_STATE = Path('.metrics-data/2wiki/state.json')
DEFAULT_EMBEDDING = 'Qwen3-Embedding-0.6B'
DOC_KB_NAME = '2wiki-e2e-docs-v1'
GRAPH_KB_NAME = '2wiki-e2e-graph-v1'
WORKFLOW_ID = 'RAG_Workflow_2wiki'
MARKER = '【2WIKI-{}】'
GRAPH_OPERATOR_ID = '-6'
EXTRACT_LLM = 'deepseek-chat'
RERANK_MODEL = 'Qwen3-Reranker-4B'
STATUS_READY = 5
STATUS_FAILED = 103
GRAPH_DEPTH = 3
EXTRACT_PROFILE = 'general'
ANSWER_PROMPT = (
    'Answer the question using the context below. If the context is insufficient, '
    'use your own knowledge. Output only the final answer, with no explanation, '
    'citations, or extra sentences. Use the answer as it appears in the context; '
    'do not add country, state, province, or honorific qualifiers that are not in '
    'the context. For "when" questions, prefer the year when the context gives a '
    'year. If the answer is a list, separate items with commas.\n\n'
    'Question: {query_str}\nContext: {context_str}'
)


class State:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def update(self, **values):
        with self.lock:
            self.data.update(values)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2) + '\n',
                encoding='utf-8')


def _items(payload) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return list(payload.get('items') or payload.get('data') or [])
    return []


def ensure_model(client: RkbClient, kind: str, name: str, flag: str) -> None:
    """抽图/重排模型要在注册表里找得到，否则运行很久才落「生成失败」。"""
    payload = client._request(
        'GET', f'/models?kind={kind}&currentPage=1&pageSize=100') or {}
    names = {row.get('modelName') for row in _items(payload)}
    if name not in names:
        raise RkbError(
            f'模型 {name} 不在模型注册表（kind={kind}）；请先在「模型管理」注册，'
            f'或用 {flag} 指定已有模型（当前：{sorted(filter(None, names))}）')


def find_kb(client: RkbClient, name: str) -> dict | None:
    payload = client._request(
        'GET', '/knowledge-bases?page=1&size=500&keyword=') or {}
    for row in _items(payload):
        if row.get('name') == name:
            return row
    return None


def ensure_doc_kb(client: RkbClient, state: State, kb_name: str,
                  embedding: str) -> str:
    existing = find_kb(client, kb_name)
    if existing:
        detail = client.get_kb(existing['id'])
        if detail.get('embeddingModel') and detail['embeddingModel'] != embedding:
            raise RkbError(
                f'同名知识库 {kb_name} 的 embedding 是 {detail["embeddingModel"]}，'
                f'不是 {embedding}；换一个 --doc-kb-name')
        kb_id = existing['id']
        print(f'[docs] reuse kb={kb_id}')
    else:
        created = client._request('POST', '/knowledge-bases', json_body={
            'name': kb_name,
            'description': '2WikiMultiHopQA end-to-end docs',
            'props': {'embeddingModel': embedding},
        })
        kb_id = created['id']
        print(f'[docs] created kb={kb_id}')
    state.update(doc_kb_id=kb_id)
    return kb_id


def wait_file_ready(client: RkbClient, kb_id: str, filename: str,
                    timeout: int = 180) -> str:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        payload = client._request(
            'GET', f'/knowledge-bases/{kb_id}/documents?page=1&size=100') or {}
        for row in _items(payload):
            if row.get('title') == filename:
                last = row
                if row.get('status') == 1:
                    return row['id']
                if row.get('status') == 2:
                    raise RkbError(
                        f'容器文件导入失败: {row.get("failReason") or row.get("errorMsg")}')
        time.sleep(2)
    raise RkbError(f'容器文件 {filename} 未就绪: {last}')


def ensure_container(client: RkbClient, kb_id: str) -> str:
    name = '2wiki-corpus-container.md'
    payload = client._request(
        'GET', f'/knowledge-bases/{kb_id}/documents?page=1&size=100') or {}
    for row in _items(payload):
        if row.get('title') == name:
            if row.get('status') == 1:
                return row['id']
            if row.get('status') == 2:
                raise RkbError(
                    f'容器文件导入失败: {row.get("failReason") or row.get("errorMsg")}')
            return wait_file_ready(client, kb_id, name)
    directories = []
    deadline = time.time() + 30
    while time.time() < deadline:
        directories = client._request(
            'GET', f'/knowledge-bases/{kb_id}/directories?type=folder&sort=true') or []
        if directories:
            break
        time.sleep(1)
    if not directories:
        raise RkbError(f'知识库 {kb_id} 30s 内没有默认目录，无法上传容器文件')
    directory_id = directories[0]['id']
    metadata = {
        'kType': 'document', 'directoryId': directory_id, 'coverFlag': True,
        'splitType': 'system', 'parseOperator': {},
        'splitOperator': {'md': {
            'operatorId': -1, 'fileFormat': 'md',
            'args': [
                {'argName': 'maxWordCount', 'argType': 'int', 'defaultValue': 512},
                {'argName': 'overlap', 'argType': 'int', 'defaultValue': 128},
            ],
        }},
    }
    response = client._request(
        'POST', f'/knowledge-bases/{kb_id}/documents',
        files={'files': (name, b'# 2WikiMultiHopQA container\n\nplaceholder',
                         'text/markdown')},
        data={'metadata': json.dumps(metadata, ensure_ascii=False)})
    file_id = (response or {}).get(name)
    if not file_id:
        raise RkbError(f'上传响应缺少 {name}: {response}')
    return wait_file_ready(client, kb_id, name)


def existing_aids(client: RkbClient, kb_id: str) -> set[str]:
    found: set[str] = set()
    page = 1
    while True:
        payload = client._request(
            'GET', f'/knowledge-bases/{kb_id}/chunks?page={page}&size=500') or {}
        rows = _items(payload)
        if not rows:
            break
        for row in rows:
            supplement = row.get('supplement') or ''
            start = supplement.find('【2WIKI-')
            if start < 0:
                continue
            end = supplement.find('】', start)
            if end > start:
                found.add(supplement[start + len('【2WIKI-'):end])
        total = int(payload.get('total') or 0)
        if page * 500 >= total:
            break
        page += 1
    return found


def import_documents(client: RkbClient, state: State, data_dir: Path,
                     kb_name: str, embedding: str, workers: int = 8) -> str:
    kb_id = ensure_doc_kb(client, state, kb_name, embedding)
    file_id = ensure_container(client, kb_id)
    articles = [json.loads(line) for line in
                (data_dir / 'articles.jsonl').open(encoding='utf-8') if line.strip()]
    done = existing_aids(client, kb_id)
    todo = [article for article in articles if article['aid'] not in done]
    print(f'[docs] kb={kb_id} articles={len(articles)} done={len(done)} todo={len(todo)}')

    def add(article: dict) -> None:
        content = article['text']
        client._request(
            'POST', f'/knowledge-bases/{kb_id}/chunks',
            json_body={'documentId': file_id, 'content': content,
                       'supplement': MARKER.format(article['aid']) + content},
            retries=3)

    failures = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(add, article): article for article in todo}
        for completed, future in enumerate(as_completed(futures), start=1):
            try:
                future.result()
            except Exception as error:                              # noqa: BLE001
                failures.append({'aid': futures[future]['aid'], 'error': str(error)[:300]})
            if completed % 100 == 0:
                print(f'[docs] {completed}/{len(todo)} failures={len(failures)}')
    if failures:
        raise RkbError(f'{len(failures)} 个切片导入失败: {failures[:3]}')
    state.update(docs_imported=len(articles))
    print(f'[docs] done kb={kb_id} chunks={len(articles)}')
    return kb_id


def _graph_upload_files(data_dir: Path) -> list[tuple[str, bytes]]:
    upload_dir = data_dir / 'graph_upload'
    files = []
    for path in sorted(upload_dir.glob('*.txt')):
        files.append(('file', (path.name, path.read_bytes(), 'text/plain')))
    if not files:
        raise RkbError(f'{upload_dir} 下没有上传文件')
    return files


def _export_graph_zip(client: RkbClient, kb_id: str) -> bytes:
    """导出已有图谱库的 zip（desc/schema/entities/edges/document_chunk）。"""
    url = f'{client.base_url}/knowledge-bases/{kb_id}/graph/export'
    response = client._session().get(url, timeout=client.timeout)
    if response.status_code != 200 or not response.content.startswith(b'PK'):
        raise RkbError(
            f'导出图谱失败 HTTP {response.status_code}: {response.text[:200]}')
    return response.content


def _rewrite_graph_zip(content: bytes, name: str, embedding: str) -> bytes:
    """改 desc.json 的库名/embedding，并去掉 id，让导入建一个新库。"""
    import io
    import zipfile

    source = zipfile.ZipFile(io.BytesIO(content))
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename.endswith('desc.json'):
                desc = json.loads(data)
                desc.pop('id', None)
                desc['name'] = name
                desc['embedding'] = embedding
                desc['desc'] = '2WikiMultiHopQA graph re-imported for embedding variant'
                data = json.dumps(desc, ensure_ascii=False, indent=2).encode('utf-8')
            elif info.filename.endswith('document_chunk.jsonl'):
                # 导出把 spilt_type 写进了 type（字符串），导入侧要求
                # graph_<id>_chunk.type 是 smallint。这里归一成 0，
                # 原始 spilt_type 保留；属于导出→导入的已知不对称。
                lines = []
                for line in data.decode('utf-8').splitlines():
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    if not isinstance(record.get('type'), int):
                        record['spilt_type'] = record.get('type')
                        record['type'] = 0
                    lines.append(json.dumps(record, ensure_ascii=False))
                data = ('\n'.join(lines) + '\n').encode('utf-8')
            elif info.filename.endswith('schema.json'):
                # 导出包里的 schema_obj 可能没有 entity_desc / edge_desc，
                # 但导入校验要求非空；补默认描述，保证导出→导入可往返。
                schema = json.loads(data)
                for entity in schema.get('entities') or []:
                    entity.setdefault('entity_desc',
                                      entity.get('entity_type') or 'Entity')
                for edge in schema.get('edges') or []:
                    edge.setdefault('edge_desc', edge.get('edge_type') or 'Relation')
                data = json.dumps(schema, ensure_ascii=False, indent=2).encode('utf-8')
            target.writestr(info, data)
    return out.getvalue()


def _import_graph_zip(client: RkbClient, content: bytes, name: str) -> str:
    """POST /graph-imports（202 空体），再按库名找新库 id。"""
    client._request(
        'POST', '/graph-imports',
        files={'file': (f'{name}.zip', content, 'application/zip')}, retries=1)
    deadline = time.time() + 120
    while time.time() < deadline:
        row = find_kb(client, name)
        if row:
            return row['id']
        time.sleep(1)
    raise RkbError(f'图谱导入后 120s 内没有出现知识库 {name}')


def _wait_graph_ready(client: RkbClient, graph_id: str, data_dir: Path) -> dict:
    # 全量 54957 篇/约 2.7 万 chunk 的抽图可能需要 1-2 天；后台沙箱
    # 由 OPERATOR_GRAPH_EXTRACT_TIMEOUT_SECONDS 放大，这里等 3 天。
    deadline = time.time() + 259200
    last = None
    while True:
        detail = client.get_kb(graph_id)
        status = detail.get('status')
        process = detail.get('process')
        if (status, process) != last:
            print(f'[graph] kb={graph_id} status={status} process={process}')
            last = (status, process)
        if status == STATUS_READY:
            break
        if status == STATUS_FAILED or status in (101, 102, 103, 104):
            raise RkbError(f'图谱构建失败 kb={graph_id}: {detail.get("failReason")}')
        if time.time() >= deadline:
            raise RkbError(f'图谱构建超时 kb={graph_id}（最后状态 {status}）')
        time.sleep(5)

    graph = client._request(
        'GET', f'/knowledge-bases/{graph_id}/graph?page=1&size=5') or {}
    stats = graph.get('stats') or {}
    if not stats.get('entityCount') or not stats.get('edgeCount'):
        raise RkbError(f'图谱为空 kb={graph_id}: {stats}')
    article_count = sum(1 for line in
                        (data_dir / 'articles.jsonl').open(encoding='utf-8')
                        if line.strip())
    if stats['entityCount'] < article_count * 0.5:
        print(f'[graph] WARNING 实体数 {stats["entityCount"]} 明显低于文章数 '
              f'{article_count}；请查容器日志后再解读指标')
    return stats


def ensure_graph_kb(client: RkbClient, state: State, data_dir: Path, llm: str,
                    kb_name: str, embedding: str,
                    source_graph_kb: str = '',
                    graph_zip: Path | None = None,
                    graph_workers: int = 4,
                    extraction_profile: str = EXTRACT_PROFILE) -> str:
    graph_id = state.get('graph_kb_id')
    if graph_id:
        detail = client.get_kb(graph_id)
        if detail.get('status') == STATUS_READY:
            print(f'[graph] reuse ready kb={graph_id}')
            stats = (client._request(
                'GET', f'/knowledge-bases/{graph_id}/graph?page=1&size=5') or {}
                     ).get('stats') or {}
            state.update(graph_stats=stats)
            return graph_id
        print(f'[graph] resume kb={graph_id} status={detail.get("status")}')
    elif graph_zip:
        print(f'[graph] import zip {graph_zip} as {kb_name} ({embedding})')
        graph_id = _import_graph_zip(client, Path(graph_zip).read_bytes(), kb_name)
        print(f'[graph] imported kb={graph_id}')
        state.update(graph_kb_id=graph_id)
    elif source_graph_kb:
        print(f'[graph] export source kb={source_graph_kb} -> re-import as '
              f'{kb_name} ({embedding})')
        content = _export_graph_zip(client, source_graph_kb)
        content = _rewrite_graph_zip(content, kb_name, embedding)
        graph_id = _import_graph_zip(client, content, kb_name)
        print(f'[graph] imported kb={graph_id}')
        state.update(graph_kb_id=graph_id)
    else:
        data = {
            'name': kb_name,
            'description': '2WikiMultiHopQA end-to-end graph',
            'category': 10,
            'props': {'embeddingModel': embedding},
            'operatorId': GRAPH_OPERATOR_ID,
            'coverFlag': True,
            'kwargs': {'llm': llm, 'chunkSize': 1000, 'overlap': 100,
                       'maxWorkers': graph_workers,
                       'extractionProfile': extraction_profile},
        }
        created = client._request(
            'POST', '/graph-extractions', files=_graph_upload_files(data_dir),
            data={'data': json.dumps(data, ensure_ascii=False)}, retries=1)
        graph_id = created['id']
        print(f'[graph] created kb={graph_id}')
        state.update(graph_kb_id=graph_id)

    stats = _wait_graph_ready(client, graph_id, data_dir)
    state.update(graph_stats=stats)
    print(f'[graph] ready kb={graph_id} stats={stats}')
    return graph_id


def _bound_item(detail: dict) -> dict:
    return {
        'name': detail.get('name'),
        'type': detail.get('type') or 'document',
        'tableName': detail.get('tableName'),
        'embeddingModel': detail.get('embeddingModel') or DEFAULT_EMBEDDING,
        'category': 10,
    }


def ensure_workflow(client: RkbClient, state: State, doc_kb_id: str,
                    graph_kb_id: str, llm: str, rerank_model: str,
                    workflow_id: str, workflow_name: str,
                    include_edge_facts: bool = False) -> str:
    workflow_id = state.get('workflow_id') or workflow_id
    try:
        existing = client._request('GET', f'/workflows/{workflow_id}/flow')
        print(f'[flow] reuse workflow={workflow_id}')
    except RkbError:
        doc_detail = client.get_kb(doc_kb_id)
        graph_detail = client.get_kb(graph_kb_id)
        bound = {'running': [_bound_item(doc_detail), _bound_item(graph_detail)],
                 'dev': []}
        client._request('POST', '/workflows', json_body={
            'name': workflow_name,
            'workFlowId': workflow_id,
            'template': 'Blended',
            'knowledgeType': 'knowledgeBase',
            'description': '2WikiMultiHopQA end-to-end benchmark',
            'boundInfo': bound,
        }, retries=1)
        print(f'[flow] created workflow={workflow_id}')
        existing = client._request('GET', f'/workflows/{workflow_id}/flow')

    changed = 0
    for node in existing.get('nodeConfigDTOList') or []:
        copies = [node.get('variables')]
        data = node.get('data')
        if isinstance(data, dict):
            copies.append(data.get('variables'))
        for variables in copies:
            if not isinstance(variables, dict):
                continue
            for stage in ('retriever', 'postretriever', 'responsesynthesizer'):
                for operator in variables.get(stage) or []:
                    kwargs = operator.setdefault('kwargs', {})
                    name = operator.get('operator') or ''
                    if name == 'KnowledgeGraphRetriever':
                        kwargs['depth'] = GRAPH_DEPTH
                        kwargs['top_k'] = 30
                        kwargs['include_edge_facts'] = bool(include_edge_facts)
                        changed += 1
                    elif name == 'VectorRetriever':
                        for info in kwargs.get('knowledge_info_list') or []:
                            info['top_k'] = 15
                            info['score'] = 0.2
                        changed += 1
                    elif name == 'KeywordRetriever':
                        kwargs['top_k'] = 15
                        changed += 1
                    elif name in ('RagSimpleSummarizer', 'SimpleSummarizer'):
                        for config in kwargs.get('generator-config') or []:
                            config['prompt'] = ANSWER_PROMPT
                            config['no_context_prompt'] = ANSWER_PROMPT
                        changed += 1
                    elif name in ('LLMReranker', 'BgeLargeReranker', 'ExternalModelReranker'):
                        # 生成式重排（LLMReranker）单次 5–20s；专用 0.6B
                        # cross-encoder 实测 30 条候选 ~0.1s，故切到注册表里的
                        # Qwen3-Reranker-4B。
                        operator['operator'] = 'ExternalModelReranker'
                        operator['package'] = \
                            'core.rag.post_retriever.external_model_reranker'
                        kwargs.clear()
                        kwargs.update({
                            'model': rerank_model,
                            'top_n': 5,
                            'score': -100,
                            'desc_info': operator.get('desc_info') or
                                         'Rerank retrieved nodes',
                        })
                        changed += 1
    client._request('PUT', f'/workflows/{workflow_id}/flow', json_body=existing)
    client._request('POST', f'/workflows/{workflow_id}/publication', json_body={})
    state.update(workflow_id=workflow_id, flow_changes=changed)
    print(f'[flow] saved and published workflow={workflow_id} changes={changed}')
    return workflow_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default=DEFAULT_BASE)
    parser.add_argument('--data-dir', type=Path, default=DEFAULT_DATA)
    parser.add_argument('--state', type=Path, default=DEFAULT_STATE)
    parser.add_argument('--llm', default=EXTRACT_LLM,
                        help='抽图模型（须在模型注册表里，默认 deepseek-chat）')
    parser.add_argument('--rerank-model', default=RERANK_MODEL,
                        help='重排模型（注册表 kind=rerank，默认 Qwen3-Reranker-4B）')
    parser.add_argument('--embedding', default=DEFAULT_EMBEDDING,
                        help='向量模型（注册表 kind=embedding，默认 Qwen3-Embedding-0.6B）')
    parser.add_argument('--doc-kb-name', default=DOC_KB_NAME)
    parser.add_argument('--graph-kb-name', default=GRAPH_KB_NAME)
    parser.add_argument('--workflow-id', default=WORKFLOW_ID)
    parser.add_argument('--workflow-name', default='2WikiMultiHopQA E2E')
    parser.add_argument('--source-graph-kb', default='',
                        help='从已有图谱库导出并换 embedding 重新导入（跳过 LLM 抽图）')
    parser.add_argument('--graph-zip', type=Path, default=None,
                        help='直接导入预生成的图谱 zip（跳过抽图/导出）')
    parser.add_argument('--workers', type=int, default=8,
                        help='文档切片并发；高维 embedding 建议 4（连接池有限）')
    parser.add_argument('--graph-workers', type=int, default=4,
                        help='在线抽图 chunk 并发（算子 kwargs.maxWorkers，默认 4）')
    parser.add_argument('--extraction-profile', default=EXTRACT_PROFILE,
                        choices=('general', 'general_attributes'),
                        help='抽图模式（通用 / 通用+属性，默认 general）')
    parser.add_argument('--edge-facts', action='store_true',
                        help='图谱检索把 seed 直接边/邻居属性边附进 chunk 正文')
    args = parser.parse_args()

    client = RkbClient(args.base_url)
    client.health()
    ensure_model(client, 'llm', args.llm, '--llm')
    ensure_model(client, 'rerank', args.rerank_model, '--rerank-model')
    ensure_model(client, 'embedding', args.embedding, '--embedding')
    state = State(args.state)

    doc_kb_id = import_documents(client, state, args.data_dir,
                                 args.doc_kb_name, args.embedding, args.workers)
    graph_kb_id = ensure_graph_kb(client, state, args.data_dir, args.llm,
                                  args.graph_kb_name, args.embedding,
                                  args.source_graph_kb, args.graph_zip,
                                  args.graph_workers, args.extraction_profile)
    workflow_id = ensure_workflow(client, state, doc_kb_id, graph_kb_id,
                                  args.llm, args.rerank_model,
                                  args.workflow_id, args.workflow_name,
                                  args.edge_facts)
    print(json.dumps({
        'doc_kb_id': doc_kb_id,
        'graph_kb_id': graph_kb_id,
        'workflow_id': workflow_id,
        'embedding': args.embedding,
        'state': str(args.state),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
