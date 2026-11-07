#!/usr/bin/env python3
"""把公开基准清单灌进一个专用知识库（一 passage = 一/多个 chunk）。

用法::

    python3 tools/bench/import.py --dataset beir-scifact \
        --kb-name bench-scifact-v1 --prefix SCIFACT --workers 16
"""

from __future__ import annotations

import argparse
import json

from common import (DEFAULT_BASE, DEFAULT_EMBEDDING, BenchClient, load_manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--kb-name', required=True)
    parser.add_argument('--prefix', required=True,
                        help='切片标记前缀（大写字母/数字），如 SCIFACT')
    parser.add_argument('--base-url', default=DEFAULT_BASE)
    parser.add_argument('--embedding-model', default=DEFAULT_EMBEDDING)
    parser.add_argument('--keyword-analyzer', default='',
                        help='english / ik_smart / standard；空 = 产品按语言推断')
    parser.add_argument('--workers', type=int, default=16)
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--no-resume', action='store_true')
    args = parser.parse_args()
    corpus, _, stats = load_manifest(args.dataset)
    if args.limit:
        corpus = corpus[:args.limit]
    client = BenchClient(args.base_url)
    client.health()
    summary = client.import_corpus(
        args.kb_name, corpus, args.prefix, workers=args.workers,
        embedding_model=args.embedding_model, resume=not args.no_resume,
        keyword_analyzer=args.keyword_analyzer)
    summary['dataset'] = args.dataset
    summary['dataset_stats'] = stats
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary['failure_count']:
        raise SystemExit(f'{summary["failure_count"]} parts failed; '
                         f'see .metrics-data/bench/runs/{summary["kb_id"]}/import-summary.json')


if __name__ == '__main__':
    main()
