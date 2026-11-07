"""从 L1 向量结果生成 LLMReranker 的候选输入（JSONL）。

候选 = 向量路 top-N 的 pid（来自 `7774-tuned/results.json` 的 `ranked`），
正文取 DuRetrieval corpus；超过 ``--max-chars`` 截断，避免 rerank prompt 超长。
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Dict, List

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--results', default='.metrics-data/runs/7774-tuned/results.json')
    parser.add_argument('--data-dir', default='.metrics-data/duretrieval')
    parser.add_argument('--out', default='.metrics-data/rerank/candidates-top50.jsonl')
    parser.add_argument('--candidate-k', type=int, default=50)
    parser.add_argument('--max-chars', type=int, default=4000)
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--sample-every', type=int, default=None,
                        help='等距抽样：每 N 条取 1 条（覆盖全难度，避免只测前几条简单 query）')
    parser.add_argument('--keyword-k', type=int, default=0,
                        help='>0 时把关键词路 top-K 并进候选（候选并集，交给 reranker 统一排序）')
    args = parser.parse_args()

    corpus = {str(pid): str(text) for pid, text in
              pd.read_parquet(os.path.join(args.data_dir, 'corpus.parquet'))
              .itertuples(index=False)}
    with open(args.results, encoding='utf-8') as handle:
        results = json.load(handle)
    sys_rows = results['systems']['vector']['per_query']
    if args.sample_every:
        sys_rows = sys_rows[::args.sample_every]
    if args.limit:
        sys_rows = sys_rows[:args.limit]

    keyword_rows = {}
    if args.keyword_k:
        keyword_rows = {row['qid']: row
                        for row in results['systems'].get('keyword', {}).get('per_query', [])}

    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    written = 0
    with open(args.out, 'w', encoding='utf-8') as out:
        for row in sys_rows:
            pids: List[str] = list(row['ranked'][:args.candidate_k])
            if args.keyword_k:
                for pid in keyword_rows.get(row['qid'], {}).get('ranked', [])[:args.keyword_k]:
                    if pid not in pids:
                        pids.append(pid)
            candidates: List[Dict[str, str]] = []
            seen = set()
            for pid in pids:
                if pid in seen or pid not in corpus:
                    continue
                seen.add(pid)
                candidates.append({'pid': pid, 'text': corpus[pid][:args.max_chars]})
            if not candidates:
                continue
            out.write(json.dumps({
                'qid': row['qid'],
                'question': row['question'],
                'candidates': candidates,
            }, ensure_ascii=False) + '\n')
            written += 1
    print(f'wrote {written} queries -> {args.out}')


if __name__ == '__main__':
    main()
