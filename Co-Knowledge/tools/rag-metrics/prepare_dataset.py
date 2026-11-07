"""准备公开检索基准（首期：C-MTEB DuRetrieval）。

产物（默认 ``.metrics-data/<dataset>/``）：
* ``corpus.parquet``  —— ``id, text``
* ``queries.parquet`` —— ``id, text``
* ``qrels.parquet``   —— ``qid, pid, score``（二值 relevance）
* ``stats.json``      —— 复核过的规模/长度/覆盖统计，报告里直接引用

数据不入库（``.metrics-data/`` 已在 .gitignore），报告只写聚合指标。
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
from typing import Any, Dict

DATASETS = {
    'duretrieval': {
        'corpus': 'C-MTEB/DuRetrieval',
        'qrels': 'C-MTEB/DuRetrieval-qrels',
        'citation': 'C-MTEB / DuRetrieval (DuReader retrieval), https://huggingface.co/datasets/C-MTEB/DuRetrieval',
    },
    't2retrieval': {
        'corpus': 'C-MTEB/T2Retrieval',
        'qrels': 'C-MTEB/T2Retrieval-qrels',
        'citation': 'C-MTEB / T2Retrieval (T2Ranking), https://huggingface.co/datasets/C-MTEB/T2Retrieval',
    },
}


def _stats(corpus, queries, qrels) -> Dict[str, Any]:
    corpus_map = {row['id']: row['text'] for row in corpus}
    query_ids = {row['id'] for row in queries}
    qrels_list = list(qrels)
    qrels_qids = {row['qid'] for row in qrels_list}
    gold: Dict[str, set] = {}
    for row in qrels_list:
        gold.setdefault(row['qid'], set()).add(row['pid'])
    lengths = [len(text) for text in corpus_map.values()]
    ordered = sorted(lengths)
    missing_pids = {row['pid'] for row in qrels_list if row['pid'] not in corpus_map}
    return {
        'corpus_passages': len(corpus_map),
        'queries': len(query_ids),
        'qrels': len(qrels_list),
        'queries_with_qrels': len(qrels_qids),
        'queries_without_qrels': sorted(query_ids - qrels_qids)[:20],
        'gold_per_query_min': min(len(v) for v in gold.values()),
        'gold_per_query_median': statistics.median(len(v) for v in gold.values()),
        'gold_per_query_max': max(len(v) for v in gold.values()),
        'qrels_pids_missing_from_corpus': len(missing_pids),
        'passage_chars_min': min(lengths),
        'passage_chars_median': statistics.median(lengths),
        'passage_chars_p90': ordered[int(len(ordered) * 0.9)],
        'passage_chars_p99': ordered[int(len(ordered) * 0.99)],
        'passage_chars_max': max(lengths),
        'passage_chars_total': sum(lengths),
        'duplicate_passage_texts': len(lengths) - len(set(corpus_map.values())),
        'qrels_relevance_values': sorted({row['score'] for row in qrels_list}),
    }


def prepare(dataset: str, out_dir: str, cache_dir: str | None) -> Dict[str, Any]:
    from datasets import load_dataset

    spec = DATASETS[dataset]
    os.makedirs(out_dir, exist_ok=True)
    if cache_dir:
        os.environ.setdefault('HF_HOME', cache_dir)
    dataset_dict = load_dataset(spec['corpus'])
    corpus = dataset_dict['corpus']
    queries_ds = dataset_dict['queries']
    qrels_ds = load_dataset(spec['qrels'])['dev']

    corpus.to_parquet(os.path.join(out_dir, 'corpus.parquet'))
    queries_ds.to_parquet(os.path.join(out_dir, 'queries.parquet'))
    qrels_ds.to_parquet(os.path.join(out_dir, 'qrels.parquet'))

    stats = _stats(corpus, queries_ds, qrels_ds)
    stats['dataset'] = dataset
    stats['citation'] = spec['citation']
    stats['corpus_hub'] = spec['corpus']
    stats['qrels_hub'] = spec['qrels']
    with open(os.path.join(out_dir, 'stats.json'), 'w', encoding='utf-8') as handle:
        json.dump(stats, handle, ensure_ascii=False, indent=2)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', choices=sorted(DATASETS), default='duretrieval')
    parser.add_argument('--out', default='.metrics-data/duretrieval')
    parser.add_argument('--cache-dir', default='.metrics-data/hf-cache')
    args = parser.parse_args()
    stats = prepare(args.dataset, args.out, args.cache_dir)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
