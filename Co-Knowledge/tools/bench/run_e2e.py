#!/usr/bin/env python3
"""在已灌库的公开基准上跑产品端到端问答（工作流 ``POST /query``）。

用法::

    python3 tools/bench/run_e2e.py --dataset hotpotqa --kb-id <kb-id> \
        --workflow-id Bench_hotpotqa --limit 300 --workers 4

评分：SQuAD 规范化 EM / token F1 / 答案覆盖（gold 是否是预测的完整词序列）/
证据标题召回；长答案基准（CRUD-RAG）另用网关 judge 判正确性。
结果逐行落 ``results.jsonl``，默认断点续跑。
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from common import (DEFAULT_BASE, RUNS_DIR, BenchClient, GatewayJudge,
                    evidence_hit, is_refusal, load_manifest, mean_ci,
                    read_jsonl, sample_rows, score_answer, write_json)

EN_PROMPT = (
    'Answer the question using the context below. If the context is '
    'insufficient, use your own knowledge. Output only the final answer, with '
    'no explanation, citations, or extra sentences; if the answer is a list, '
    'separate items with commas.\n\nQuestion: {query_str}\nContext: {context_str}'
)
EN_STRICT_PROMPT = (
    'Answer the question using only the context below. If the context does not '
    'contain the answer, output exactly: I cannot answer. Output only the final '
    'answer, with no explanation, citations, or extra sentences; if the answer '
    'is a list, separate items with commas.\n\nQuestion: {query_str}\nContext: '
    '{context_str}'
)
ZH_PROMPT = (
    '请依据下面的上下文回答问题；如果上下文不足，可以结合你自己的知识。'
    '只输出最终答案，不要解释、不要引用；如果是列表，用逗号分隔。\n\n'
    '问题：{query_str}\n上下文：{context_str}'
)
ZH_STRICT_PROMPT = (
    '只能依据下面的上下文回答问题。上下文不足以回答时，只输出：无法回答。'
    '只输出最终答案，不要解释、不要引用；如果是列表，用逗号分隔。\n\n'
    '问题：{query_str}\n上下文：{context_str}'
)
ZH_LONG_PROMPT = (
    '请依据下面的上下文回答问题；允许完整陈述，但不要编造上下文之外的事实。'
    '信息不足时明确说明。\n\n问题：{query_str}\n上下文：{context_str}'
)


def _prompt(language: str, style: str, strict: bool = False) -> str:
    if language == 'zh':
        if style == 'long':
            return ZH_LONG_PROMPT
        return ZH_STRICT_PROMPT if strict else ZH_PROMPT
    return EN_STRICT_PROMPT if strict else EN_PROMPT


def _limited_queries(queries: Sequence[Dict[str, Any]], limit: Optional[int],
                     per_type: Optional[int]) -> List[Dict[str, Any]]:
    if per_type:
        buckets: Dict[str, List[Dict[str, Any]]] = {}
        for row in queries:
            buckets.setdefault(str(row.get('type') or ''), []).append(row)
        out: List[Dict[str, Any]] = []
        for type_name in sorted(buckets):
            out.extend(sample_rows(buckets[type_name], per_type, key='qid'))
        return out
    if limit:
        return sample_rows(queries, limit, key='qid')
    return list(queries)


def _query_one(client: BenchClient, workflow_id: str, row: Dict[str, Any],
               judge: Optional[GatewayJudge], style: str) -> Dict[str, Any]:
    started = time.perf_counter()
    error = None
    answer = ''
    context = ''
    items: List[Dict[str, Any]] = []
    timings: Dict[str, Any] = {}
    try:
        response = client.ask(workflow_id, str(row['question']))
        answer = response['answer']
        context = response['context']
        items = response['items']
        timings = response['timings']
    except Exception as exc:  # noqa: BLE001
        error = str(exc)[:300]
    elapsed = time.perf_counter() - started
    answers = row.get('answers') or []
    scores = score_answer(answer, answers) if answers and answer else {
        'em': 0.0, 'f1': 0.0, 'contains': 0.0}
    result = {
        'qid': str(row['qid']),
        'type': row.get('type'),
        'question': str(row['question']),
        'answers': answers,
        'prediction': answer,
        'elapsed_s': elapsed,
        'retrieval_items': len(items),
        'context_chars': len(context),
        'evidence_hit': evidence_hit(context, row.get('gold_titles') or []),
        'refusal': is_refusal(answer),
        'error': error,
        'timings': timings,
        **scores,
    }
    if style == 'long' and judge and not error:
        judged = judge.judge_correct(str(row['question']), answers, answer)
        result['judge_correct'] = judged['correct']
        result['judge_reason'] = judged['reason']
    return result


def aggregate(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    def collect(key: str) -> Dict[str, Any]:
        return mean_ci([row.get(key) for row in rows if row.get(key) is not None])

    by_type: Dict[str, Dict[str, Any]] = {}
    for type_name in sorted({str(row.get('type') or '') for row in rows}):
        subset = [row for row in rows if str(row.get('type') or '') == type_name]
        by_type[type_name] = {
            'n': len(subset),
            'em': collect_subset(subset, 'em'),
            'f1': collect_subset(subset, 'f1'),
            'contains': collect_subset(subset, 'contains'),
            'evidence_hit': collect_subset(subset, 'evidence_hit'),
            'refusal_rate': sum(1 for row in subset if row.get('refusal')) / max(len(subset), 1),
            'latency_mean_s': sum(row.get('elapsed_s') or 0 for row in subset) / max(len(subset), 1),
        }
        if any(row.get('judge_correct') is not None for row in subset):
            judged = [row for row in subset if row.get('judge_correct') is not None]
            by_type[type_name]['judge_accuracy'] = collect_subset(judged, 'judge_correct')
    latencies = [row.get('elapsed_s') or 0 for row in rows]
    return {
        'n': len(rows),
        'em': collect('em'),
        'f1': collect('f1'),
        'contains': collect('contains'),
        'evidence_hit': collect('evidence_hit'),
        'judge_accuracy': collect('judge_correct'),
        'refusal_rate': sum(1 for row in rows if row.get('refusal')) / max(len(rows), 1),
        'error_rate': sum(1 for row in rows if row.get('error')) / max(len(rows), 1),
        'latency_s': {
            'mean': sum(latencies) / max(len(latencies), 1),
            'p50': _percentile(latencies, 50),
            'p95': _percentile(latencies, 95),
            'max': max(latencies) if latencies else 0.0,
        },
        'by_type': by_type,
    }


def collect_subset(rows: Sequence[Dict[str, Any]], key: str) -> Dict[str, Any]:
    return mean_ci([row.get(key) for row in rows if row.get(key) is not None])


def _percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((pct / 100) * (len(ordered) - 1))))
    return float(ordered[index])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--kb-id', required=True)
    parser.add_argument('--workflow-id', default='')
    parser.add_argument('--workflow-name', default='')
    parser.add_argument('--base-url', default=DEFAULT_BASE)
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--per-type', type=int, default=None)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--language', choices=('en', 'zh'), default='en')
    parser.add_argument('--prompt-style', choices=('short', 'long'), default='short')
    parser.add_argument('--strict-grounding', action='store_true',
                        help='上下文不足时要求拒答；默认允许模型使用自身知识')
    parser.add_argument('--top-k', type=int, default=20)
    parser.add_argument('--rerank-top-n', type=int, default=8)
    parser.add_argument('--judge', action='store_true', help='长答案用网关 judge 判正确性')
    parser.add_argument('--judge-model', default='deepseek-chat.1-Flash')
    parser.add_argument('--qid-file', default='',
                        help='只跑文件里的 qid（每行一个；部分导入时用）')
    parser.add_argument('--out', default='')
    parser.add_argument('--no-resume', action='store_true')
    args = parser.parse_args()

    _, queries, _ = load_manifest(args.dataset)
    if args.qid_file:
        wanted = {line.strip() for line in Path(args.qid_file).read_text().splitlines()
                  if line.strip()}
        queries = [row for row in queries if str(row['qid']) in wanted]
    queries = _limited_queries(queries, args.limit, args.per_type)
    workflow_id = args.workflow_id or f'Bench_{args.dataset}'
    workflow_name = args.workflow_name or f'{args.dataset} benchmark'
    client = BenchClient(args.base_url)
    client.health()
    client.ensure_workflow(workflow_id, workflow_name, args.kb_id,
                           _prompt(args.language, args.prompt_style,
                                   args.strict_grounding),
                           top_k=args.top_k, rerank_top_n=args.rerank_top_n)
    judge = GatewayJudge(model=args.judge_model) if args.judge else None

    out_dir = Path(args.out) if args.out else RUNS_DIR / args.dataset / args.kb_id
    out_dir.mkdir(parents=True, exist_ok=True)
    result_path = out_dir / 'results.jsonl'
    done: Dict[str, Dict[str, Any]] = {}
    if result_path.exists() and not args.no_resume:
        for row in read_jsonl(result_path):
            done[str(row['qid'])] = row
    todo = [row for row in queries if str(row['qid']) not in done]
    print(f'workflow={workflow_id} queries={len(queries)} todo={len(todo)} '
          f'workers={args.workers}', flush=True)

    lock = threading.Lock()
    with result_path.open('a', encoding='utf-8') as handle:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(_query_one, client, workflow_id, row, judge,
                                   args.prompt_style): row for row in todo}
            for index, future in enumerate(as_completed(futures), start=1):
                row = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001
                    result = {'qid': str(row['qid']), 'type': row.get('type'),
                              'question': str(row['question']), 'error': str(exc)[:300],
                              'em': 0.0, 'f1': 0.0, 'contains': 0.0,
                              'evidence_hit': 0.0, 'refusal': False,
                              'elapsed_s': 0.0}
                with lock:
                    handle.write(json.dumps(result, ensure_ascii=False) + '\n')
                    handle.flush()
                if index % 20 == 0:
                    print(f'  {index}/{len(todo)}', flush=True)

    rows = read_jsonl(result_path)
    summary = {
        'config': {
            'dataset': args.dataset,
            'kb_id': args.kb_id,
            'workflow_id': workflow_id,
            'language': args.language,
            'prompt_style': args.prompt_style,
            'strict_grounding': args.strict_grounding,
            'top_k': args.top_k,
            'rerank_top_n': args.rerank_top_n,
            'judge_model': args.judge_model if args.judge else None,
            'queries_total': len(queries),
        },
        'aggregate': aggregate(rows),
    }
    write_json(out_dir / 'results.json', summary)
    print(json.dumps(summary['aggregate'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
