"""Cross-encoder rerank 消融（Qwen3-Reranker-4B，Cohere/Jina 风格 /v1/rerank）。

输入：``prepare_rerank_input.py`` 生成的 JSONL（query + top-N 候选）。
输出：JSONL（reranked pids + 指标 + 延迟）。

端点契约（vLLM）::

    POST /v1/rerank
    {"model": "Qwen3-Reranker-4B", "query": "...", "documents": ["...", ...]}
    -> {"results": [{"index": 0, "relevance_score": 0.99}, ...]}

与 ``rerank_llm.py`` 的区别：这里走真正的 cross-encoder，一次请求处理全部候选，
没有 reasoning/选择式丢文档的问题；指标同样只看最终 top_n（默认 10）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from metrics import score_query  # noqa: E402

KS = [1, 3, 5, 10]


def load_gold(path: str) -> Dict[str, set]:
    import pandas as pd
    qrels = pd.read_parquet(path)
    gold: Dict[str, set] = {}
    for row in qrels.itertuples(index=False):
        gold.setdefault(str(row.qid), set()).add(str(row.pid))
    return gold


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='.metrics-data/rerank/candidates-top50.jsonl')
    parser.add_argument('--output', default='.metrics-data/rerank/cross-top10.jsonl')
    parser.add_argument('--qrels', default='.metrics-data/duretrieval/qrels.parquet')
    parser.add_argument('--endpoint', default='http://127.0.0.1:8003/v1/rerank')
    parser.add_argument('--model', default='Qwen3-Reranker-4B')
    parser.add_argument('--top-n', type=int, default=10)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--timeout', type=int, default=120)
    parser.add_argument('--limit', type=int, default=None)
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    done = set()
    if os.path.isfile(args.output):
        with open(args.output, encoding='utf-8') as handle:
            for line in handle:
                try:
                    done.add(json.loads(line)['qid'])
                except Exception:                                  # noqa: BLE001
                    continue
        print(f'resume: {len(done)} queries already done')

    rows = []
    with open(args.input, encoding='utf-8') as handle:
        for line in handle:
            item = json.loads(line)
            if item['qid'] in done:
                continue
            rows.append(item)
            if args.limit and len(rows) >= args.limit:
                break
    print(f'rerank {len(rows)} queries, model={args.model}, top_n={args.top_n}, '
          f'workers={args.workers}')

    gold = load_gold(args.qrels)
    started = time.time()
    finished = 0

    def post(item: Dict[str, Any]) -> Dict[str, Any]:
        candidates = item['candidates']
        documents = [candidate['text'] for candidate in candidates]
        # 内部端点直连；不要走宿主代理（no_proxy 里的 10.*.*.* 对 Python 无效）。
        begin = time.perf_counter()
        response = requests.post(
            args.endpoint,
            json={'model': args.model, 'query': item['question'], 'documents': documents},
            timeout=args.timeout,
            proxies={'http': None, 'https': None},
        )
        latency = (time.perf_counter() - begin) * 1000
        response.raise_for_status()
        payload = response.json()
        results = payload.get('results') or []
        ranked = sorted(results, key=lambda row: row.get('relevance_score') or 0.0,
                        reverse=True)
        returned: List[str] = []
        for row in ranked[:args.top_n]:
            index = row.get('index')
            if isinstance(index, int) and 0 <= index < len(candidates):
                pid = candidates[index]['pid']
                if pid not in returned:
                    returned.append(pid)
        query_gold = gold.get(str(item['qid']), set())
        scores = score_query(returned, {pid: 1.0 for pid in query_gold}, KS)
        return {
            'qid': item['qid'],
            'question': item['question'],
            'returned': returned,
            'metrics': scores,
            'candidate_count': len(candidates),
            'returned_count': len(returned),
            'latency_ms': round(latency, 2),
        }

    with open(args.output, 'a', encoding='utf-8') as out:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(post, item) for item in rows]
            for future in as_completed(futures):
                try:
                    record = future.result()
                except Exception as error:                        # noqa: BLE001
                    print(f'query failed: {error}', flush=True)
                    continue
                out.write(json.dumps(record, ensure_ascii=False) + '\n')
                out.flush()
                finished += 1
                if finished % 50 == 0:
                    rate = finished / max(time.time() - started, 1e-6)
                    print(f'{finished}/{len(rows)} queries, {rate:.2f} q/s', flush=True)

    print(f'wrote {finished} records to {args.output}')


if __name__ == '__main__':
    main()
