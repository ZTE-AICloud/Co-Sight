"""对比 L1 基线（向量 top-10）与 rerank 输出的检索指标。

支持 cross-encoder（rerank_cross.py）和 LLM reranker（rerank_llm.py）两种 JSONL；
后者多一个 ``fallback`` 字段，会额外给出 fallback 子集的统计。
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List

import numpy as np

METRICS = ('ndcg@10', 'recall@10', 'mrr@10', 'hit@10')


def bootstrap_ci(values: np.ndarray, resamples: int = 2000,
                 seed: int = 42) -> List[float]:
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, values.size, size=(resamples, values.size))
    means = values[indices].mean(axis=1)
    return [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]


def summarize(baseline: Dict[str, dict], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    row_by_qid = {row['qid']: row for row in rows}
    qids = [qid for qid in row_by_qid if qid in baseline]
    out: Dict[str, Any] = {'n': len(qids)}
    for metric in METRICS:
        base = np.array([baseline[qid]['metrics'].get(metric, 0.0) for qid in qids])
        reranked = np.array([row_by_qid[qid]['metrics'].get(metric, 0.0) for qid in qids])
        diff = reranked - base
        out[metric] = {
            'baseline': float(base.mean()) if base.size else None,
            'rerank': float(reranked.mean()) if reranked.size else None,
            'diff': float(diff.mean()) if diff.size else None,
            'ci95_low': bootstrap_ci(diff)[0] if diff.size else None,
            'ci95_high': bootstrap_ci(diff)[1] if diff.size else None,
            'wins': int((diff > 1e-12).sum()),
            'ties': int((np.abs(diff) <= 1e-12).sum()),
            'losses': int((diff < -1e-12).sum()),
        }
    out['latency_ms'] = {
        'mean': float(np.mean([row.get('latency_ms', 0) for row in rows])) if rows else 0.0,
        'p50': float(np.percentile([row.get('latency_ms', 0) for row in rows], 50)) if rows else 0.0,
        'p95': float(np.percentile([row.get('latency_ms', 0) for row in rows], 95)) if rows else 0.0,
    }
    out['returned_mean'] = float(np.mean([row.get('returned_count', 0) for row in rows])) if rows else 0.0
    if any('fallback' in row for row in rows):
        fallback = [row for row in rows if row.get('fallback')]
        non_fallback = [row for row in rows if not row.get('fallback')]
        out['fallback'] = len(fallback)
        out['fallback_rate'] = len(fallback) / max(len(rows), 1)
        # 只有「部分 fallback」时才需要子集统计；全成功/全 fallback 会自我递归。
        if 0 < len(non_fallback) < len(rows):
            out['non_fallback'] = summarize(baseline, non_fallback)
    return out


def markdown(summary: Dict[str, Any], title: str) -> str:
    lines = [f'## {title}', '',
             '| 指标 | 基线（向量 top-10） | rerank top-10 | 差值 [95% CI] | 胜/平/负 |',
             '|---|---:|---:|---:|---:|']
    for metric in METRICS:
        row = summary[metric]
        lines.append(
            f'| {metric} | {row["baseline"] * 100:.2f}% | {row["rerank"] * 100:.2f}% | '
            f'{row["diff"] * 100:+.2f} pp [{row["ci95_low"] * 100:+.2f}, '
            f'{row["ci95_high"] * 100:+.2f}] | '
            f'{row["wins"]}/{row["ties"]}/{row["losses"]} |')
    latency = summary['latency_ms']
    lines.extend(['',
                  f'- 查询数：{summary["n"]}；平均返回 {summary["returned_mean"]:.2f} 条；'
                  f'延迟 mean/p50/p95 = {latency["mean"]:.1f}/{latency["p50"]:.1f}/{latency["p95"]:.1f} ms。'])
    if 'fallback' in summary:
        suffix = (f'；非 fallback 子集 n={summary["non_fallback"]["n"]}'
                  if 'non_fallback' in summary else '')
        lines.append(f'- fallback：{summary["fallback"]} 条'
                     f'（{summary["fallback_rate"]:.1%}）{suffix}。')
    return '\n'.join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', required=True,
                        help='L1 的 results.json（含 per_query.metrics 与 ranked）')
    parser.add_argument('--rerank', required=True, help='rerank JSONL')
    parser.add_argument('--out-json', default='')
    parser.add_argument('--out-md', default='')
    parser.add_argument('--title', default='rerank 对照')
    args = parser.parse_args()

    with open(args.baseline, encoding='utf-8') as handle:
        baseline = {row['qid']: row for row in json.load(handle)['systems']['vector']['per_query']}
    rows = [json.loads(line) for line in open(args.rerank, encoding='utf-8') if line.strip()]
    summary = summarize(baseline, rows)
    text = markdown(summary, args.title)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.out_json:
        os.makedirs(os.path.dirname(args.out_json) or '.', exist_ok=True)
        with open(args.out_json, 'w', encoding='utf-8') as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
    if args.out_md:
        os.makedirs(os.path.dirname(args.out_md) or '.', exist_ok=True)
        with open(args.out_md, 'w', encoding='utf-8') as handle:
            handle.write(text + '\n')


if __name__ == '__main__':
    main()
