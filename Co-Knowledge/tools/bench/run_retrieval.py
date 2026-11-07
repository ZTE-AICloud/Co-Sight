#!/usr/bin/env python3
"""在公开基准清单上跑产品 L1 检索指标（向量 / 关键词）。

用法::

    python3 tools/bench/run_retrieval.py --dataset beir-scifact \
        --kb-id <kb-id> --systems vector,keyword --top-k 80

口径与 ``tools/rag-metrics/run_retrieval_metrics.py`` 一致：
* 标记只用于展示（``supplement``），``content`` 是干净正文；
* 长 passage 的子片共享 pid，指标在 pid 级去重；
* 空结果重试一次，仍为空按 0 分计；连续 5 条错误即停；
* 未映射文档按「非相关、占一个排名位」保留，占比超阈值拒绝出报告。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from common import (DEFAULT_BASE, DEFAULT_EMBEDDING, RUNS_DIR, BenchClient,
                    bootstrap_ci, load_manifest, safe_pid,
                    split_parts, write_json)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'rag-metrics'))
from metrics import score_query  # noqa: E402

KS = [1, 3, 5, 10, 20, 50, 80]
HEADLINE = ['ndcg@10', 'recall@10', 'recall@80', 'mrr@10', 'hit@10',
            'precision@10', 'precision_retrieved@10']


def build_text_index(corpus: Sequence[Dict[str, Any]]) -> Tuple[Dict[str, List[str]],
                                                               Dict[str, List[str]]]:
    exact: Dict[str, List[str]] = {}
    normalized: Dict[str, List[str]] = {}
    for row in corpus:
        pid = safe_pid(row['pid'])
        title = str(row.get('title') or '').strip()
        text = str(row.get('text') or '')
        content = f'{title}\n{text}'.strip() if title else text
        for part in split_parts(content):
            for key, table in ((part, exact), (' '.join(part.split()), normalized)):
                pids = table.setdefault(key, [])
                if pid not in pids:
                    pids.append(pid)
    return exact, normalized


def doc_pids(doc: Dict[str, Any], prefix: str,
             text_index: Tuple[Dict[str, List[str]], Dict[str, List[str]]],
             marker: re.Pattern[str]) -> List[str]:
    content = doc.get('content') or ''
    match = marker.search(content)
    if match:
        return [match.group(1)]
    exact, normalized = text_index
    pids = exact.get(content)
    if pids:
        return list(pids)
    return list(normalized.get(' '.join(content.split())) or [])


def aggregate(per_query: Sequence[Dict[str, Any]], metric: str,
              exclude_empty: bool = False) -> Dict[str, Any]:
    values = [row['metrics'][metric] for row in per_query
              if metric in row.get('metrics', {})
              and (not exclude_empty or not row.get('empty'))]
    if not values:
        return {'n': 0}
    low, high = bootstrap_ci(values)
    return {
        'n': len(values),
        'mean': float(np.mean(values)),
        'std': float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
        'median': float(np.median(values)),
        'ci95_low': low,
        'ci95_high': high,
    }


def paired_diff(left: Dict[str, Any], right: Dict[str, Any],
                metric_names: Sequence[str]) -> Dict[str, Any]:
    left_map = {row['qid']: row for row in left['per_query']}
    right_map = {row['qid']: row for row in right['per_query']}
    common = sorted(qid for qid in set(left_map) & set(right_map)
                    if not left_map[qid].get('empty') and not right_map[qid].get('empty')
                    and not left_map[qid].get('error') and not right_map[qid].get('error'))
    out: Dict[str, Any] = {'n_pairs': len(common)}
    for metric in metric_names:
        pairs = [(left_map[qid]['metrics'][metric], right_map[qid]['metrics'][metric])
                 for qid in common
                 if metric in left_map[qid]['metrics']
                 and metric in right_map[qid]['metrics']]
        if not pairs:
            continue
        diffs = np.asarray([a - b for a, b in pairs], dtype=float)
        rng = np.random.default_rng(42)
        indices = rng.integers(0, diffs.size, size=(2000, diffs.size))
        means = diffs[indices].mean(axis=1)
        out[metric] = {
            'mean_diff': float(diffs.mean()),
            'ci95_low': float(np.percentile(means, 2.5)),
            'ci95_high': float(np.percentile(means, 97.5)),
        }
    return out


def failure_count(container: str) -> Optional[int]:
    if not container:
        return None
    try:
        output = subprocess.run(['docker', 'logs', container],
                                capture_output=True, text=True, timeout=120)
        text = (output.stdout or '') + (output.stderr or '')
        return text.count('retrieve failed, returning empty result')
    except Exception:  # noqa: BLE001
        return None


def run_system(client: BenchClient, kb_id: str, queries: Sequence[Dict[str, Any]],
               gold: Dict[str, Dict[str, float]], retrieve_type: int, top_k: int,
               text_index: Tuple[Dict[str, List[str]], Dict[str, List[str]]],
               marker: re.Pattern[str], ks: Sequence[int],
               max_unmapped_rate: float) -> Dict[str, Any]:
    per_query: List[Dict[str, Any]] = []
    started = time.time()
    consecutive_errors = 0
    for number, row in enumerate(queries, start=1):
        qid = str(row['qid'])
        question = str(row['question'])
        query_gold = gold.get(qid) or {}
        begin = time.perf_counter()
        error = None
        retried = False
        docs: List[Dict[str, Any]] = []
        try:
            docs = client.retrieve(kb_id, question, retrieve_type, top_k=top_k)
            if not docs:
                retried = True
                time.sleep(0.4)
                docs = client.retrieve(kb_id, question, retrieve_type, top_k=top_k)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)[:300]
        latency_ms = (time.perf_counter() - begin) * 1000
        groups: List[List[str]] = []
        seen: set[str] = set()
        unmapped = 0
        for rank, doc in enumerate(docs, start=1):
            pids = doc_pids(doc, '', text_index, marker)
            if not pids:
                unmapped += 1
                pids = [f'__unmapped__:{qid}:{rank}']
            kept = [pid for pid in pids if pid not in seen]
            for pid in kept:
                seen.add(pid)
            if kept:
                groups.append(kept)
        scores = score_query(groups, query_gold, ks)
        first_gold = next(
            (rank for rank, group in enumerate(groups, start=1)
             if any(pid in query_gold for pid in group)), None)
        per_query.append({
            'qid': qid,
            'question': question,
            'type': row.get('type'),
            'ranked': [pid for group in groups for pid in group],
            'metrics': scores,
            'gold_count': len(query_gold),
            'first_gold_rank': first_gold,
            'latency_ms': round(latency_ms, 2),
            'docs_returned': len(docs),
            'empty': len(docs) == 0,
            'retried_empty': retried,
            'error': error,
            'unmapped_docs': unmapped,
        })
        if error:
            consecutive_errors += 1
            if consecutive_errors >= 5:
                raise SystemExit(f'连续 {consecutive_errors} 条查询失败: {error}')
        else:
            consecutive_errors = 0
        if number % 200 == 0:
            print(f'  {number}/{len(queries)}', flush=True)
    latencies = [row['latency_ms'] for row in per_query]
    docs_returned = [row['docs_returned'] for row in per_query]
    total_docs = sum(docs_returned)
    unmapped_docs = sum(row['unmapped_docs'] for row in per_query)
    unmapped_rate = unmapped_docs / total_docs if total_docs else 0.0
    if unmapped_rate > max_unmapped_rate:
        raise SystemExit(f'未映射文档占比 {unmapped_rate:.1%} 超过 {max_unmapped_rate:.1%}')
    metric_names = sorted({name for row in per_query for name in row['metrics']})
    return {
        'retrieve_type': retrieve_type,
        'elapsed_seconds': round(time.time() - started, 1),
        'queries': len(per_query),
        'evaluated_queries': aggregate(per_query, 'ndcg@10', True).get('n', 0),
        'empty_responses': sum(1 for row in per_query if row['empty']),
        'empty_retried': sum(1 for row in per_query if row['retried_empty']),
        'error_responses': sum(1 for row in per_query if row.get('error')),
        'unmapped_docs': unmapped_docs,
        'unmapped_rate': round(unmapped_rate, 6),
        'docs_returned': {
            'min': int(min(docs_returned)) if docs_returned else 0,
            'median': float(np.median(docs_returned)) if docs_returned else 0.0,
            'max': int(max(docs_returned)) if docs_returned else 0,
            'mean': float(np.mean(docs_returned)) if docs_returned else 0.0,
        },
        'latency_ms': {
            'mean': float(np.mean(latencies)) if latencies else 0.0,
            'p50': float(np.percentile(latencies, 50)) if latencies else 0.0,
            'p95': float(np.percentile(latencies, 95)) if latencies else 0.0,
            'max': float(max(latencies)) if latencies else 0.0,
        },
        'metrics': {name: aggregate(per_query, name, True) for name in metric_names},
        'metrics_including_empty': {name: aggregate(per_query, name, False)
                                     for name in metric_names},
        'per_query': per_query,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True, help='清单目录名，如 beir-scifact')
    parser.add_argument('--kb-id', required=True)
    parser.add_argument('--base-url', default=DEFAULT_BASE)
    parser.add_argument('--systems', default='vector,keyword')
    parser.add_argument('--top-k', type=int, default=80)
    parser.add_argument('--query-limit', type=int, default=None)
    parser.add_argument('--marker-prefix', default='BENCH')
    parser.add_argument('--embedding-model', default=DEFAULT_EMBEDDING)
    parser.add_argument('--ef-search', default='')
    parser.add_argument('--product-version', default='')
    parser.add_argument('--log-container', default='rag-studio-rag-knowledge-base-1')
    parser.add_argument('--max-unmapped-rate', type=float, default=0.05)
    parser.add_argument('--require-gold-imported', action='store_true',
                        help='只评 gold 全部已导入的查询（部分导入时用）')
    parser.add_argument('--out', default='')
    args = parser.parse_args()
    if not 1 <= args.top_k <= 80:
        raise SystemExit('--top-k 必须在 1..80')
    ks = [k for k in KS if k <= args.top_k]

    corpus, queries, stats = load_manifest(args.dataset)
    if args.query_limit:
        queries = queries[:args.query_limit]
    client = BenchClient(args.base_url)
    client.health()
    detail = client.get_kb(args.kb_id)
    actual_model = (detail.get('embeddingModel') or '').strip()
    if actual_model and args.embedding_model and actual_model != args.embedding_model:
        raise SystemExit(f'KB embedding={actual_model} 与参数 {args.embedding_model} 不一致')
    marker = client.marker_regex(args.marker_prefix)
    if args.require_gold_imported:
        imported = client.existing_pids(args.kb_id, args.marker_prefix)
        before = len(queries)
        queries = [row for row in queries
                   if {safe_pid(pid) for pid in row.get('gold_pids') or []} <= imported]
        print(f'coverage filter: {len(queries)}/{before} queries with all gold imported')
    text_index = build_text_index(corpus)
    gold: Dict[str, Dict[str, float]] = {}
    for row in queries:
        scores = row.get('gold_scores') or {}
        gold[str(row['qid'])] = {
            safe_pid(pid): float(scores.get(pid, 1.0))
            for pid in row.get('gold_pids') or []
        }
    queries = [row for row in queries if gold.get(str(row['qid']))]
    systems = [item.strip() for item in args.systems.split(',') if item.strip()]
    type_map = {'vector': 0, 'keyword': 1}
    for system in systems:
        if system not in type_map:
            raise SystemExit(f'unknown system: {system}')

    result: Dict[str, Any] = {
        'config': {
            'dataset': args.dataset,
            'kb_id': args.kb_id,
            'systems': systems,
            'top_k': args.top_k,
            'ks': ks,
            'marker_prefix': args.marker_prefix,
            'embedding_model': actual_model or args.embedding_model,
            'ef_search': args.ef_search,
            'product_version': args.product_version,
            'base_url': args.base_url,
        },
        'dataset_stats': stats,
        'systems': {},
    }
    for system in systems:
        before = failure_count(args.log_container)
        print(f'== {system} ({len(queries)} queries) ==', flush=True)
        result['systems'][system] = run_system(
            client, args.kb_id, queries, gold, type_map[system], args.top_k,
            text_index, marker, ks, args.max_unmapped_rate)
        after = failure_count(args.log_container)
        if before is not None and after is not None:
            result['systems'][system]['retrieve_failed_log_lines'] = after - before
    if 'vector' in result['systems'] and 'keyword' in result['systems']:
        result['paired_diff'] = paired_diff(
            result['systems']['vector'], result['systems']['keyword'], HEADLINE)

    out = Path(args.out) if args.out else RUNS_DIR / args.dataset / args.kb_id
    os.makedirs(out, exist_ok=True)
    write_json(out / 'results.json', result)
    print(f'wrote {out / "results.json"}')


if __name__ == '__main__':
    main()
