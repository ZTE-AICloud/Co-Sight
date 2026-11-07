#!/usr/bin/env python3
"""把 prepare_graph.py 产出的上传文件抽成图谱库，并建/发布「文档+图谱」工作流。

复用 ``tools/graph-metrics/import_2wiki.py`` 的图谱创建/工作流逻辑，避免
复制一套产品调用。

用法::

    python3 tools/bench/import_graph.py \
        --graph-dir .metrics-data/bench/graph-2wiki \
        --graph-kb-name bench-2wiki-graph-v1 \
        --doc-kb-id 1671be88784461cc \
        --workflow-id Bench_2wiki_graph \
        --workflow-name "2Wiki graph benchmark" \
        --llm deepseek-chat --graph-workers 4
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'tools' / 'graph-metrics'))

import import_2wiki as wiki  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph-dir', type=Path, required=True)
    parser.add_argument('--graph-kb-name', required=True)
    parser.add_argument('--doc-kb-id', required=True)
    parser.add_argument('--workflow-id', required=True)
    parser.add_argument('--workflow-name', required=True)
    parser.add_argument('--llm', default='deepseek-chat')
    parser.add_argument('--extraction-profile', default='general_attributes',
                        help='general / general_attributes（日期、国家等属性）')
    parser.add_argument('--embedding', default='Qwen3-Embedding-0.6B')
    parser.add_argument('--rerank-model', default='Qwen3-Reranker-4B')
    parser.add_argument('--graph-workers', type=int, default=4)
    parser.add_argument('--base-url', default='http://127.0.0.1/api/co-knowledge/v1')
    parser.add_argument('--state', type=Path, default=None)
    args = parser.parse_args()

    state_path = args.state or (REPO / '.metrics-data' / 'bench'
                                / f'graph-{args.graph_kb_name}.json')
    state = wiki.State(state_path)
    client = wiki.RkbClient(args.base_url, timeout=180)
    client.health()
    existing = state.get('graph_kb_id')
    if existing:
        detail = client.get_kb(existing)
        if detail.get('status') == 5:
            graph_id = existing
            print(f'[graph] reuse ready kb={graph_id}')
        else:
            raise SystemExit(
                f'state 里的图谱库 {existing} 不是 ready（status={detail.get("status")}）；'
                '换名字或清理后重跑')
    else:
        data = {
            'name': args.graph_kb_name,
            'description': f'{args.graph_kb_name} benchmark graph',
            'category': 10,
            'props': {'embeddingModel': args.embedding},
            'operatorId': '-6',
            'coverFlag': True,
            'kwargs': {
                'llm': args.llm,
                'chunkSize': 1000,
                'overlap': 100,
                'maxWorkers': args.graph_workers,
                'extractionProfile': args.extraction_profile,
            },
        }
        created = client._request(
            'POST', '/graph-extractions',
            files=wiki._graph_upload_files(args.graph_dir),
            data={'data': json.dumps(data, ensure_ascii=False)}, retries=1)
        graph_id = created['id']
        state.update(graph_kb_id=graph_id)
        print(f'[graph] created kb={graph_id} profile={args.extraction_profile}')
    state.update(graph_stats=wiki._wait_graph_ready(
        client, graph_id, args.graph_dir))
    workflow_id = wiki.ensure_workflow(
        client, state, args.doc_kb_id, graph_id, args.llm,
        args.rerank_model, args.workflow_id, args.workflow_name)
    summary = {
        'graph_kb_id': graph_id,
        'workflow_id': workflow_id,
        'graph_stats': state.get('graph_stats'),
        'state': str(state_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
