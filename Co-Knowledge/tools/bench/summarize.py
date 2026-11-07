#!/usr/bin/env python3
"""把 ``.metrics-data/bench/runs`` 下的结果汇总成 Markdown 表。

不读原始数据、不访问产品；只做结果文件的归一化展示，方便写报告时对数。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from common import RUNS_DIR


def _pct(value: Optional[float]) -> str:
    return f'{value * 100:.2f}' if isinstance(value, (int, float)) else '-'


def _fmt(value: Any, digits: int = 2) -> str:
    if isinstance(value, (int, float)):
        return f'{value:.{digits}f}'
    return '-'


def load(path: Path) -> Dict[str, Any]:
    with path.open(encoding='utf-8') as handle:
        return json.load(handle)


def retrieval_rows(path: Path) -> List[List[str]]:
    data = load(path)
    config = data.get('config', {})
    stats = data.get('dataset_stats', {})
    rows = []
    for system, item in (data.get('systems') or {}).items():
        metrics = item.get('metrics') or {}
        rows.append([
            config.get('dataset', path.parent.parent.name),
            config.get('embedding_model', ''),
            system,
            _pct((metrics.get('ndcg@10') or {}).get('mean')),
            _pct((metrics.get('recall@10') or {}).get('mean')),
            _pct((metrics.get('recall@80') or {}).get('mean')),
            _pct((metrics.get('mrr@10') or {}).get('mean')),
            _fmt((item.get('latency_ms') or {}).get('p95'), 1),
            str(item.get('empty_responses', '')),
            _pct(item.get('unmapped_rate')),
            f"{stats.get('corpus_passages', '')}/{stats.get('queries', '')}",
        ])
    return rows


def e2e_rows(path: Path) -> List[List[str]]:
    data = load(path)
    config = data.get('config', {})
    agg = data.get('aggregate') or {}
    rows = [[
        config.get('dataset', path.parent.parent.name),
        config.get('language', ''),
        str(agg.get('n', '')),
        _pct((agg.get('em') or {}).get('mean')),
        _pct((agg.get('f1') or {}).get('mean')),
        _pct((agg.get('contains') or {}).get('mean')),
        _pct((agg.get('evidence_hit') or {}).get('mean')),
        _pct((agg.get('judge_accuracy') or {}).get('mean')),
        _pct(agg.get('refusal_rate')),
        _fmt((agg.get('latency_s') or {}).get('mean'), 2),
        str(data.get('config', {}).get('workflow_id', '')),
    ]]
    for type_name, item in (agg.get('by_type') or {}).items():
        rows.append([
            f'  └ {type_name}',
            '',
            str(item.get('n', '')),
            _pct((item.get('em') or {}).get('mean')),
            _pct((item.get('f1') or {}).get('mean')),
            _pct((item.get('contains') or {}).get('mean')),
            _pct((item.get('evidence_hit') or {}).get('mean')),
            _pct((item.get('judge_accuracy') or {}).get('mean')),
            _pct(item.get('refusal_rate')),
            _fmt(item.get('latency_mean_s'), 2),
            '',
        ])
    return rows


def context_rows(path: Path) -> List[List[str]]:
    data = load(path)
    config = data.get('config') or {}
    metrics = data.get('metrics') or data.get('overall') or {}
    rows = [[
        config.get('mode') or path.parent.parent.name,
        config.get('model', ''),
        str(data.get('n', '')),
        json.dumps(metrics, ensure_ascii=False),
        str(config.get('noise_rate', '')),
    ]]
    for type_name, item in (data.get('by_type') or {}).items():
        rows.append([
            f'  └ {type_name}', '', str(item.get('n', '')),
            json.dumps({k: v for k, v in item.items() if k != 'n'}, ensure_ascii=False),
            '',
        ])
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs-dir', type=Path, default=RUNS_DIR)
    args = parser.parse_args()
    groups: Dict[str, List[List[str]]] = {
        'retrieval': [], 'e2e': [], 'context': []}
    seen = set()
    for path in sorted(args.runs_dir.rglob('results.json')):
        if path in seen:
            continue
        seen.add(path)
        try:
            data = load(path)
        except Exception:  # noqa: BLE001
            continue
        if 'systems' in data:
            groups['retrieval'].extend(retrieval_rows(path))
        elif 'aggregate' in data:
            groups['e2e'].extend(e2e_rows(path))
        elif 'metrics' in data or 'overall' in data:
            groups['context'].extend(context_rows(path))
    print('## L1 retrieval\n')
    print('| dataset | embedding | system | nDCG@10 | Recall@10 | Recall@80 | MRR@10 | P95 ms | empty | unmapped | corpus/queries |')
    print('|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|')
    for row in groups['retrieval']:
        print('| ' + ' | '.join(row) + ' |')
    print('\n## E2E\n')
    print('| dataset | lang | n | EM | F1 | contains | evidence | judge | refusal | latency s | workflow |')
    print('|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|')
    for row in groups['e2e']:
        print('| ' + ' | '.join(row) + ' |')
    print('\n## Context QA\n')
    print('| dataset | model | n | metrics | noise |')
    print('|---|---|---:|---|---:|')
    for row in groups['context']:
        print('| ' + ' | '.join(row) + ' |')


if __name__ == '__main__':
    main()
