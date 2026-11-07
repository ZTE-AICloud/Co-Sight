"""按「语料应有子片 vs 库里已有子片」补齐导入缺口。

为什么需要它：`import_corpus.py` 以 **pid** 做断点续灌；一条长 passage 切成多个
子片时，只要有一个子片成功，`--resume` 就会把整个 pid 当成已完成，失败/漏掉的
子片永远不会补。本脚本按**子片正文**逐条对账，缺哪片补哪片，因此也能补齐
「整个 pid 都没导入」的情况。

用法::

    python3 tools/rag-metrics/repair_parts.py --kb-id <kb-id>

只做新增（chunk/add），不删除、不改已有切片；重复执行是幂等的（缺片集合为空即退出）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple

import pandas as pd

from import_corpus import split_parts
from rkb_client import RkbClient, display_text

MARKER_RE = re.compile(r'【DURET-([0-9a-f]{32})】')


def part_of(row: dict) -> Tuple[str, str] | None:
    """从 chunk 列表行还原 (pid, 干净子片正文)。"""
    content = row.get('content') or ''
    supplement = row.get('supplement') or ''
    pid = None
    for value in (supplement, content):
        match = MARKER_RE.search(value)
        if match:
            pid = match.group(1)
            break
    if not pid:
        return None
    # content 可能带标记，先剥掉。
    text = MARKER_RE.sub('', content).lstrip('\n')
    if not text:
        text = MARKER_RE.sub('', supplement).lstrip('\n')
    return pid, text


def existing_parts(client: RkbClient, kb_id: str) -> Dict[str, set]:
    parts: Dict[str, set] = {}
    for row in client.list_chunks(kb_id):
        parsed = part_of(row)
        if not parsed:
            continue
        pid, text = parsed
        parts.setdefault(pid, set()).add(text)
    return parts


def container_file(client: RkbClient, kb_id: str, directory_id: str) -> str:
    for row in client.list_files(kb_id):
        title = row.get('title') or ''
        if title.startswith('duretrieval-shard-') and row.get('status') == 1:
            return row['id']
    return client.upload_container(
        kb_id, directory_id, 'duretrieval-repair.md',
        '# DuRetrieval repair\n\n本文件承载补录切片，不参与检索评分。\n')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1/api/co-knowledge/v1')
    parser.add_argument('--data-dir', default='.metrics-data/duretrieval')
    parser.add_argument('--kb-id', required=True)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--limit', type=int, default=None,
                        help='只对账前 N 条语料（小样本 KB 必须传，避免把全量灌进去）')
    parser.add_argument('--runs-dir', default='.metrics-data/runs')
    parser.add_argument('--force', action='store_true',
                        help='KB 规模明显小于语料时仍继续（默认拒绝）')
    args = parser.parse_args()

    client = RkbClient(args.base_url)
    client.health()
    kb = client.get_kb(args.kb_id)
    directory_id = client.default_directory(args.kb_id)
    file_id = container_file(client, args.kb_id, directory_id)
    corpus = pd.read_parquet(os.path.join(args.data_dir, 'corpus.parquet'))
    if args.limit:
        corpus = corpus.head(args.limit)
    existing = existing_parts(client, args.kb_id)
    if len(corpus) > 2 * max(len(existing), 1) and not args.force:
        raise SystemExit(
            f'语料 {len(corpus)} 条，但 KB 只有 {len(existing)} 个 pid；'
            '看起来是按部分语料建的库。请加 --limit，或确认 kb-id 后加 --force')

    missing: List[Tuple[str, str]] = []
    incomplete_pids = 0
    for pid, text in corpus.itertuples(index=False):
        pid = str(pid)
        expected = split_parts(str(text))
        have = existing.get(pid, set())
        gaps = [part for part in expected if part not in have]
        if gaps:
            incomplete_pids += 1
            missing.extend((pid, part) for part in gaps)

    print(f'KB={args.kb_id} pids={len(corpus)} incomplete={incomplete_pids} '
          f'missing_parts={len(missing)}')
    failures = []
    done = 0

    def add(item: Tuple[str, str]) -> None:
        pid, part = item
        client.add_chunk(args.kb_id, file_id, part, display_text(pid, part))

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(add, item) for item in missing]
        for future in as_completed(futures):
            try:
                future.result()
                done += 1
            except Exception as error:                            # noqa: BLE001
                failures.append(str(error)[:300])
            if done % 100 == 0 and done:
                print(f'{done}/{len(missing)} repaired', flush=True)

    summary = {
        'kb_id': args.kb_id,
        'kb_name': kb.get('name'),
        'pids': len(corpus),
        'incomplete_pids': incomplete_pids,
        'missing_parts': len(missing),
        'repaired_parts': done,
        'failure_count': len(failures),
        'failures': failures[:20],
    }
    run_dir = os.path.join(args.runs_dir, args.kb_id)
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, 'repair-summary.json'), 'w', encoding='utf-8') as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(f'{len(failures)} 个补录切片失败')


if __name__ == '__main__':
    main()
