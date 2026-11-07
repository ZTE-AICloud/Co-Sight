#!/usr/bin/env python3
"""把多跳基准的「题目上下文」整理成图谱抽取上传文件。

输入是 `prepare.py` 产出的 ``corpus.jsonl/queries.jsonl``；只取指定 qid
（默认全部）的 ``context_pids``，按 ``--group-size`` 篇一个 txt，最多
``--max-files`` 个文件（产品单次上传上限 50）。

用法::

    python3 tools/bench/prepare_graph.py --dataset 2wiki \
        --out .metrics-data/bench/graph-2wiki --group-size 50
    python3 tools/bench/prepare_graph.py --dataset hotpotqa \
        --qid-file .metrics-data/bench/hotpotqa-e2e-qids.txt \
        --out .metrics-data/bench/graph-hotpotqa --group-size 40
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from common import load_manifest, write_json, write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--qid-file', default='')
    parser.add_argument('--group-size', type=int, default=50)
    parser.add_argument('--max-files', type=int, default=50)
    parser.add_argument('--limit-qids', type=int, default=None)
    args = parser.parse_args()

    corpus, queries, _ = load_manifest(args.dataset)
    if args.qid_file:
        wanted = {line.strip() for line in Path(args.qid_file).read_text().splitlines()
                  if line.strip()}
        queries = [row for row in queries if str(row['qid']) in wanted]
    if args.limit_qids:
        queries = queries[:args.limit_qids]
    by_pid = {row['pid']: row for row in corpus}
    selected: Dict[str, Dict[str, Any]] = {}
    for row in queries:
        for pid in row.get('context_pids') or row.get('gold_pids') or []:
            if pid in by_pid:
                selected[pid] = by_pid[pid]
    rows = [selected[pid] for pid in sorted(selected)]
    if not rows:
        raise SystemExit('没有可抽取的 context_pids；先重跑 prepare.py 生成该字段')

    group_size = args.group_size
    while (len(rows) + group_size - 1) // group_size > args.max_files:
        group_size += 10
    upload_dir = args.out / 'graph_upload'
    upload_dir.mkdir(parents=True, exist_ok=True)
    for old in upload_dir.glob('*.txt'):
        old.unlink()
    groups: List[Dict[str, Any]] = []
    for start in range(0, len(rows), group_size):
        chunk = rows[start:start + group_size]
        filename = f'graph-{start // group_size + 1:03d}.txt'
        body = '\n\n'.join(
            f'## {row["title"]}\n{row["text"]}' for row in chunk)
        (upload_dir / filename).write_text(body + '\n', encoding='utf-8')
        groups.append({'file': filename,
                       'pids': [row['pid'] for row in chunk],
                       'titles': [row['title'] for row in chunk]})
    write_jsonl(args.out / 'groups.jsonl', groups)
    # import_2wiki._wait_graph_ready 用它做「实体数是否明显偏低」的 sanity check
    write_jsonl(args.out / 'articles.jsonl', rows)
    write_json(args.out / 'manifest.json', {
        'dataset': args.dataset,
        'queries': len(queries),
        'passages': len(rows),
        'files': len(groups),
        'group_size': group_size,
        'qid_file': args.qid_file,
    })
    print(json.dumps({'dataset': args.dataset, 'queries': len(queries),
                      'passages': len(rows), 'files': len(groups),
                      'group_size': group_size}, ensure_ascii=False))


if __name__ == '__main__':
    main()
