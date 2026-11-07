"""在已灌好的知识库上跑 L1 检索指标。

用法::

    python3 tools/rag-metrics/run_retrieval_metrics.py \
        --kb-id <kb-id> --systems vector,keyword --top-k 80 \
        --out .metrics-data/runs/<kb-id>

判据：
* 所有 gold pid 必须已导入（``--strict-coverage`` 时缺失即失败）；
* 记录空结果率与「未映射文档」数；
* 回传 per-query 明细，报告只做聚合与 worst-N 展示。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from import_corpus import split_parts
from metrics import score_query
from rkb_client import RkbClient

MARKER_RE = re.compile(r'【DURET-([0-9a-f]{32})】')
KS = [1, 3, 5, 10, 20, 50, 80]
HEADLINE = ['ndcg@10', 'recall@10', 'recall@80', 'mrr@10', 'hit@10',
            'precision@10', 'precision_retrieved@10']


def load_frame(path: str) -> pd.DataFrame:
    return pd.read_parquet(path)


def build_text_index(
        corpus: pd.DataFrame) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """part 文本 → pid 列表（原始 + 空白归一两份索引）。

    同一段文本可能对应多个 pid（长 passage 的子片恰好等于另一条 passage 的全文，
    或语料本身有重复正文）。检索器无法区分它们，所以**映射到全部 pid**；
    指标在 pid 级去重，不会重复计分。
    """
    index: Dict[str, List[str]] = {}
    normalized: Dict[str, List[str]] = {}
    for pid, text in corpus.itertuples(index=False):
        pid = str(pid)
        for part in split_parts(str(text)):
            for key, table in ((part, index), (' '.join(part.split()), normalized)):
                pids = table.setdefault(key, [])
                if pid not in pids:
                    pids.append(pid)
    collisions = sum(1 for pids in index.values() if len(pids) > 1)
    if collisions:
        print(f'INFO text→pid 多义 {collisions} 组（映射到全部 pid）')
    return index, normalized


def doc_pids(doc: Dict[str, Any],
             text_index: Tuple[Dict[str, List[str]], Dict[str, List[str]]]) -> List[str]:
    content = doc.get('content') or ''
    match = MARKER_RE.search(content)
    if match:
        return [match.group(1)]
    exact, normalized = text_index
    pids = exact.get(content)
    if pids:
        return list(pids)
    return list(normalized.get(' '.join(content.split())) or [])


def bootstrap_ci(values: Sequence[float], resamples: int = 2000,
                 seed: int = 42) -> Tuple[float, float]:
    array = np.asarray(values, dtype=float)
    if array.size == 0:
        return (float('nan'), float('nan'))
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, array.size, size=(resamples, array.size))
    means = array[indices].mean(axis=1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def aggregate(per_query: List[Dict[str, Any]], metric: str,
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
        'p10': float(np.percentile(values, 10)),
        'p90': float(np.percentile(values, 90)),
        'ci95_low': low,
        'ci95_high': high,
    }


def log_failure_count(container: str) -> Optional[int]:
    if not container:
        return None
    try:
        output = subprocess.run(
            ['docker', 'logs', container], capture_output=True, text=True, timeout=60)
        text = (output.stdout or '') + (output.stderr or '')
        return text.count('retrieve failed, returning empty result')
    except Exception:                                            # noqa: BLE001
        return None


def run_system(client: RkbClient, kb_id: str, queries: pd.DataFrame,
               gold: Dict[str, set], retrieve_type: int, top_k: int,
               text_index: Tuple[Dict[str, List[str]], Dict[str, List[str]]],
               ks: Sequence[int], max_unmapped_rate: float = 0.05) -> Dict[str, Any]:
    per_query: List[Dict[str, Any]] = []
    started = time.time()
    consecutive_errors = 0
    for number, row in enumerate(queries.itertuples(index=False), start=1):
        qid, question = str(row.id), str(row.text)
        query_gold = gold.get(qid) or set()
        begin = time.perf_counter()
        error = None
        retried_empty = False
        docs: List[Dict[str, Any]] = []
        try:
            docs = client.retrieve(kb_id, question, retrieve_type, top_k=top_k)
            if not docs:
                # 服务端把检索异常吞成空结果；空结果也可能是真实的「没命中」。
                # 重试一次：能把并发/瞬时故障与真实空结果分开；仍为空则按 0 分计。
                retried_empty = True
                time.sleep(0.5)
                docs = client.retrieve(kb_id, question, retrieve_type, top_k=top_k)
        except Exception as exc:                                  # noqa: BLE001
            error = str(exc)[:300]
        latency_ms = (time.perf_counter() - begin) * 1000
        groups: List[List[str]] = []
        seen = set()
        unmapped = 0
        for rank, doc in enumerate(docs, start=1):
            pids = doc_pids(doc, text_index)
            if not pids:
                # 容器文件自带的正文 / 删除切片后残留的向量行：不是语料，但确实占了
                # 一个排名位。用伪 pid 占位（永远不会命中 gold），比直接过滤更保守。
                unmapped += 1
                pids = [f'__unmapped__:{qid}:{rank}']
            kept = [pid for pid in pids if pid not in seen]
            for pid in kept:
                seen.add(pid)
            if kept:
                groups.append(kept)
        scores = score_query(groups, {pid: 1.0 for pid in query_gold}, ks)
        first_gold_rank = next(
            (rank for rank, group in enumerate(groups, start=1)
             if any(pid in query_gold for pid in group)), None)
        per_query.append({
            'qid': qid,
            'question': question,
            'ranked': [pid for group in groups for pid in group],
            'metrics': scores,
            'gold_count': len(query_gold),
            'first_gold_rank': first_gold_rank,
            'latency_ms': round(latency_ms, 2),
            'docs_returned': len(docs),
            'empty': len(docs) == 0,
            'retried_empty': retried_empty,
            'error': error,
            'unmapped_docs': unmapped,
        })
        if error:
            consecutive_errors += 1
            if consecutive_errors >= 5:
                raise SystemExit(
                    f'连续 {consecutive_errors} 条查询失败，停止（最后一条: {error}）')
        else:
            consecutive_errors = 0
        if number % 200 == 0:
            print(f'  {number}/{len(queries)} queries', flush=True)

    latencies = [row['latency_ms'] for row in per_query]
    doc_counts = [row['docs_returned'] for row in per_query]
    total_docs = sum(doc_counts)
    unmapped_docs = sum(row['unmapped_docs'] for row in per_query)
    unmapped_rate = unmapped_docs / total_docs if total_docs else 0.0
    if unmapped_rate > max_unmapped_rate:
        raise SystemExit(
            f'未映射文档占比 {unmapped_rate:.1%} 超过阈值 {max_unmapped_rate:.1%}；'
            '映射链路可能失效，拒绝出报告')
    metric_names = sorted({name for row in per_query for name in row['metrics']})
    metrics_valid = {name: aggregate(per_query, name, exclude_empty=True)
                     for name in metric_names}
    metrics_all = {name: aggregate(per_query, name, exclude_empty=False)
                   for name in metric_names}
    if not metrics_valid.get('ndcg@10', {}).get('n'):
        raise SystemExit('没有任何有效查询可用于聚合（全部为空/失败）')
    return {
        'retrieve_type': retrieve_type,
        'elapsed_seconds': round(time.time() - started, 1),
        'queries': len(per_query),
        'evaluated_queries': metrics_valid.get('ndcg@10', {}).get('n', 0),
        'empty_responses': sum(1 for row in per_query if row['empty']),
        'empty_retried': sum(1 for row in per_query if row['retried_empty']),
        'error_responses': sum(1 for row in per_query if row.get('error')),
        'unmapped_docs': unmapped_docs,
        'unmapped_rate': round(unmapped_rate, 6),
        'docs_returned': {
            'min': int(min(doc_counts)) if doc_counts else 0,
            'median': float(np.median(doc_counts)) if doc_counts else 0.0,
            'max': int(max(doc_counts)) if doc_counts else 0,
            'mean': float(np.mean(doc_counts)) if doc_counts else 0.0,
        },
        'latency_ms': {
            'mean': float(np.mean(latencies)) if latencies else 0.0,
            'p50': float(np.percentile(latencies, 50)) if latencies else 0.0,
            'p95': float(np.percentile(latencies, 95)) if latencies else 0.0,
            'max': float(max(latencies)) if latencies else 0.0,
        },
        # headline 用「剔除空结果」的有效查询；同时保留把空结果按 0 分的保守口径。
        'metrics': metrics_valid,
        'metrics_including_empty': metrics_all,
        'per_query': per_query,
    }


def paired_diff(left: Dict[str, Any], right: Dict[str, Any],
                metrics: Iterable[str]) -> Dict[str, Any]:
    left_map = {row['qid']: row for row in left['per_query']}
    right_map = {row['qid']: row for row in right['per_query']}
    common = sorted(qid for qid in set(left_map) & set(right_map)
                    if not left_map[qid].get('empty') and not right_map[qid].get('empty')
                    and not left_map[qid].get('error') and not right_map[qid].get('error'))
    out: Dict[str, Any] = {'n_pairs': len(common)}
    for metric in metrics:
        pairs = [(left_map[qid]['metrics'][metric], right_map[qid]['metrics'][metric])
                 for qid in common
                 if metric in left_map[qid]['metrics'] and metric in right_map[qid]['metrics']]
        if not pairs:
            continue
        diffs = np.array([a - b for a, b in pairs], dtype=float)
        rng = np.random.default_rng(42)
        indices = rng.integers(0, diffs.size, size=(2000, diffs.size))
        means = diffs[indices].mean(axis=1)
        out[metric] = {
            'mean_diff': float(diffs.mean()),
            'ci95_low': float(np.percentile(means, 2.5)),
            'ci95_high': float(np.percentile(means, 97.5)),
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1/api/co-knowledge/v1')
    parser.add_argument('--data-dir', default='.metrics-data/duretrieval')
    parser.add_argument('--kb-id', required=True)
    parser.add_argument('--systems', default='vector,keyword')
    parser.add_argument('--top-k', type=int, default=80)
    parser.add_argument('--query-limit', type=int, default=None)
    parser.add_argument('--out', required=True)
    parser.add_argument('--product-version', default='')
    parser.add_argument('--embedding-model', default='Qwen3-Embedding-0.6B')
    parser.add_argument('--ef-search', default='',
                        help='测量时使用的 hnsw.ef_search（记录进报告；实际设置由部署侧完成）')
    parser.add_argument('--log-container', default='',
                        help='可选：docker 容器名，用于统计 retrieve 静默失败次数')
    parser.add_argument('--strict-coverage', action='store_true')
    parser.add_argument('--max-unmapped-rate', type=float, default=0.05,
                        help='未映射文档占比超过该值即拒绝出报告（默认 5%%）')
    args = parser.parse_args()
    if not 1 <= args.top_k <= 80:
        raise SystemExit('--top-k 必须在 1..80（产品 RetrieveDTO 上限 80）')
    ks = [k for k in KS if k <= args.top_k]
    if not ks:
        raise SystemExit('--top-k 必须至少为 1')

    corpus = load_frame(os.path.join(args.data_dir, 'corpus.parquet'))
    queries = load_frame(os.path.join(args.data_dir, 'queries.parquet'))
    qrels = load_frame(os.path.join(args.data_dir, 'qrels.parquet'))
    if args.query_limit:
        queries = queries.head(args.query_limit)

    client = RkbClient(args.base_url)
    client.health()
    kb_detail = client.get_kb(args.kb_id)
    actual_model = (kb_detail.get('embeddingModel') or '').strip()
    if actual_model and args.embedding_model and actual_model != args.embedding_model:
        raise SystemExit(
            f'KB 实际 embedding 模型是 {actual_model}，与参数 {args.embedding_model} 不一致')
    if actual_model:
        args.embedding_model = actual_model
    imported = {
        pid
        for row in client.list_chunks(args.kb_id)
        for field in ('supplement', 'content')
        for pid in MARKER_RE.findall(row.get(field) or '')
    }
    gold: Dict[str, set] = {}
    for row in qrels.itertuples(index=False):
        if row.pid in imported:
            gold.setdefault(str(row.qid), set()).add(str(row.pid))
    missing_qrels = {row.pid for row in qrels.itertuples(index=False)} - imported
    coverage = {
        'imported_pids': len(imported),
        'qrels_pids_total': len({row.pid for row in qrels.itertuples(index=False)}),
        'qrels_pids_missing': len(missing_qrels),
        'queries_with_gold_after_restrict': len(gold),
    }
    print(json.dumps(coverage, ensure_ascii=False))
    if args.strict_coverage and missing_qrels:
        raise SystemExit(f'{len(missing_qrels)} 个 qrels pid 未导入，拒绝出报告')

    queries = queries[queries['id'].astype(str).isin(gold.keys())]
    text_index = build_text_index(corpus)
    systems = [item.strip() for item in args.systems.split(',') if item.strip()]
    type_map = {'vector': 0, 'keyword': 1}

    result: Dict[str, Any] = {
        'config': {
            'kb_id': args.kb_id,
            'systems': systems,
            'top_k': args.top_k,
            'ks': ks,
            'product_version': args.product_version,
            'embedding_model': args.embedding_model,
            'ef_search': args.ef_search,
            'base_url': args.base_url,
            'strict_coverage': args.strict_coverage,
        },
        'coverage': coverage,
        'systems': {},
    }
    stats_path = os.path.join(args.data_dir, 'stats.json')
    if os.path.isfile(stats_path):
        with open(stats_path, encoding='utf-8') as handle:
            result['dataset_stats'] = json.load(handle)

    for system in systems:
        if system not in type_map:
            raise SystemExit(f'unknown system: {system}')
        before = log_failure_count(args.log_container)
        print(f'== {system} ({len(queries)} queries) ==')
        result['systems'][system] = run_system(
            client, args.kb_id, queries, gold, type_map[system],
            args.top_k, text_index, ks, args.max_unmapped_rate)
        after = log_failure_count(args.log_container)
        if before is not None and after is not None:
            result['systems'][system]['retrieve_failed_log_lines'] = after - before
        if system == 'vector' and str(args.ef_search).strip().isdigit():
            ef_search = int(str(args.ef_search).strip())
            median = result['systems'][system]['docs_returned']['median']
            if ef_search >= args.top_k and median < args.top_k:
                raise SystemExit(
                    f'向量路返回深度中位 {median} < top_k {args.top_k}；'
                    f'ef_search={ef_search} 可能未生效，拒绝出报告')

    if 'vector' in result['systems'] and 'keyword' in result['systems']:
        result['paired_diff'] = paired_diff(
            result['systems']['vector'], result['systems']['keyword'], HEADLINE)

    os.makedirs(args.out, exist_ok=True)
    output_path = os.path.join(args.out, 'results.json')
    with open(output_path, 'w', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(f'wrote {output_path}')


if __name__ == '__main__':
    main()
