#!/usr/bin/env python3
"""建「仅文档」「仅图谱」两个对照工作流，用于量化图谱对端到端问答的增益。

复用 ``import_2wiki.py`` 的同一套检索 / 重排 / 提示词参数，唯一差别是 ``boundInfo``：

* 仅文档 → 只绑文档库，服务端选 ``Blended``（无 ``KnowledgeGraphRetriever``）
* 仅图谱 → 只绑图谱库，服务端选 ``Blended_graph``（无文档向量 / 关键词检索）

两个工作流都发布，并写出 ``state-doconly.json`` / ``state-graphonly.json``，
交给 ``run_2wiki_e2e.py --state ...`` 跑同一批题。

跑法（先有 ``import_2wiki.py`` 建好的两个知识库）::

    python3 tools/graph-metrics/make_ablation_workflows.py \
        --doc-kb-id ddf25d25f1b5ea70 --graph-kb-id 33aae56a8680ddab
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from graph_client import RkbClient, RkbError

DEFAULT_BASE = 'http://127.0.0.1/api/co-knowledge/v1'
DEFAULT_RERANK_MODEL = 'Qwen3-Reranker-4B'
DEFAULT_GRAPH_DEPTH = 3
ANSWER_PROMPT = (
    'Answer the question using the context below. If the context is insufficient, '
    'use your own knowledge. Output only the final answer, with no explanation, '
    'citations, or extra sentences; if the answer is a list, separate items with '
    'commas.\n\nQuestion: {query_str}\nContext: {context_str}'
)


def _bound_item(detail: dict) -> dict:
    return {
        'name': detail.get('name'),
        'type': detail.get('type') or 'document',
        'tableName': detail.get('tableName'),
        'embeddingModel': detail.get('embeddingModel') or 'Qwen3-Embedding-0.6B',
        'category': 10,
    }


def _patch_flow(flow: dict, rerank_model: str, graph_depth: int) -> int:
    """与 ``import_2wiki.ensure_workflow`` 同一套参数（保持对照公平）。"""
    changed = 0
    for node in flow.get('nodeConfigDTOList') or []:
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
                        kwargs['depth'] = graph_depth
                        kwargs['top_k'] = 30
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
    return changed


def ensure_workflow(client: RkbClient, workflow_id: str, name: str,
                    kb_ids: list[str], rerank_model: str,
                    graph_depth: int) -> None:
    try:
        client._request('GET', f'/workflows/{workflow_id}/flow')
        print(f'[flow] reuse workflow={workflow_id}')
    except RkbError:
        bound = {'running': [_bound_item(client.get_kb(kb)) for kb in kb_ids],
                 'dev': []}
        client._request('POST', '/workflows', json_body={
            'name': name,
            'workFlowId': workflow_id,
            'template': 'Blended',
            'knowledgeType': 'knowledgeBase',
            'description': '2WikiMultiHopQA graph ablation',
            'boundInfo': bound,
        }, retries=1)
        print(f'[flow] created workflow={workflow_id} '
              f'bound={[item["name"] for item in bound["running"]]}')

    flow = client._request('GET', f'/workflows/{workflow_id}/flow')
    changed = _patch_flow(flow, rerank_model, graph_depth)
    client._request('PUT', f'/workflows/{workflow_id}/flow', json_body=flow)
    client._request('POST', f'/workflows/{workflow_id}/publication', json_body={})
    print(f'[flow] saved and published workflow={workflow_id} changes={changed}')

    flow = client._request('GET', f'/workflows/{workflow_id}/flow')
    operators = []
    for node in flow.get('nodeConfigDTOList') or []:
        variables = node.get('variables') or {}
        for stage in ('retriever', 'postretriever', 'responsesynthesizer'):
            for operator in variables.get(stage) or []:
                operators.append(operator.get('operator'))
    print(f'[flow] operators={operators}')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default=DEFAULT_BASE)
    parser.add_argument('--doc-kb-id', required=True)
    parser.add_argument('--graph-kb-id', required=True)
    parser.add_argument('--doc-workflow-id', default='RAG_Workflow_2wiki_doconly')
    parser.add_argument('--graph-workflow-id', default='RAG_Workflow_2wiki_graphonly')
    parser.add_argument('--rerank-model', default=DEFAULT_RERANK_MODEL)
    parser.add_argument('--graph-depth', type=int, default=DEFAULT_GRAPH_DEPTH)
    parser.add_argument('--state-dir', type=Path, default=Path('.metrics-data/2wiki'))
    args = parser.parse_args()

    client = RkbClient(args.base_url)
    client.health()
    ensure_workflow(client, args.doc_workflow_id,
                    '2WikiMultiHopQA E2E (docs only)', [args.doc_kb_id],
                    args.rerank_model, args.graph_depth)
    ensure_workflow(client, args.graph_workflow_id,
                    '2WikiMultiHopQA E2E (graph only)', [args.graph_kb_id],
                    args.rerank_model, args.graph_depth)

    args.state_dir.mkdir(parents=True, exist_ok=True)
    (args.state_dir / 'state-doconly.json').write_text(json.dumps({
        'doc_kb_id': args.doc_kb_id,
        'workflow_id': args.doc_workflow_id,
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (args.state_dir / 'state-graphonly.json').write_text(json.dumps({
        'graph_kb_id': args.graph_kb_id,
        'workflow_id': args.graph_workflow_id,
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
