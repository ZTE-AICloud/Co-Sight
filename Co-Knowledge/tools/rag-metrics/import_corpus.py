"""把 DuRetrieval corpus 灌进一个专用知识库（一 passage = 一/多个 chunk）。

关键口径（报告里必须写清楚）：

* **embedding / 关键词索引用干净正文**（``content``），标记只放在 ``supplement``：
  实测向量路返回 supplement、关键词路返回 content —— 这样两条路都能映射回 pid，
  且标记不会污染向量与 BM25。
* 超长 passage 按 ``MAX_PART_CHARS`` 切成多个子片，共享同一个 pid 标记；
  检索指标在 pid 级去重（同一条 passage 的多个子片只算一次）。
* 容器文件（承载手工切片）自身会产出 1 个无标记 chunk；评测时按「必须含标记」
  过滤掉，数量占比 <0.1%。

用法::

    python3 tools/rag-metrics/import_corpus.py --limit 20          # 先测吞吐
    python3 tools/rag-metrics/import_corpus.py                     # 全量
    python3 tools/rag-metrics/import_corpus.py --resume            # 断点续灌
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple

import pandas as pd

from rkb_client import EMBEDDING_MODEL, RkbClient, display_text

MARKER_RE = re.compile(r'【DURET-([0-9a-f]{32})】')
MAX_PART_CHARS = 4000
SHARD_SIZE = 2500


def load_corpus(path: str, limit: int | None) -> List[Tuple[str, str]]:
    frame = pd.read_parquet(path)
    rows = [(str(row.id), str(row.text)) for row in frame.itertuples(index=False)]
    return rows[:limit] if limit else rows


def split_parts(text: str) -> List[str]:
    if len(text) <= MAX_PART_CHARS:
        return [text]
    return [text[start:start + MAX_PART_CHARS]
            for start in range(0, len(text), MAX_PART_CHARS)]


def existing_pids(client: RkbClient, kb_id: str) -> set[str]:
    found: set[str] = set()
    for row in client.list_chunks(kb_id):
        for field in ('supplement', 'content'):
            value = row.get(field) or ''
            match = MARKER_RE.search(value)
            if match:
                found.add(match.group(1))
                break
    return found


CONTAINER_TEXT = (
    '# DuRetrieval shard {index}\n\n'
    '本文件仅作为评测切片的容器，不参与检索评分。'
    'The container file is only a carrier for manually added chunks '
    'and is filtered out during metrics.\n'
)


def ensure_shard_files(client: RkbClient, kb_id: str, directory_id: str,
                       count: int) -> List[str]:
    """按 SHARD_SIZE 建/复用容器文件；resume 时不重复上传。

    复用只认 status=1 的行；失败行先删掉再重建（否则 resume 会一直撞同一个坏文件）。
    """
    existing = {row.get('title'): row for row in client.list_files(kb_id)}
    file_ids = []
    for index in range((count + SHARD_SIZE - 1) // SHARD_SIZE):
        name = f'duretrieval-shard-{index:03d}.md'
        row = existing.get(name)
        file_id = row.get('id') if row and row.get('status') == 1 else None
        if not file_id:
            if row and row.get('id'):
                client.delete_file(kb_id, row['id'])
            file_id = client.upload_container(
                kb_id, directory_id, name, CONTAINER_TEXT.format(index=index))
            # 容器自身会切出一小段无标记正文。**不删**：删除切片不会清掉向量行，
            # 会留下空正文的孤儿 doc（产品行为，已登记）；保留它并在评测里按
            # 「非语料、非相关」占位，更保守也更接近真实索引。
        file_ids.append(file_id)
    return file_ids


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1/api/co-knowledge/v1')
    parser.add_argument('--data-dir', default='.metrics-data/duretrieval')
    parser.add_argument('--kb-name', default='rag-eval-duretrieval-v1')
    parser.add_argument('--embedding-model', default=EMBEDDING_MODEL)
    parser.add_argument('--workers', type=int, default=12)
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--runs-dir', default='.metrics-data/runs')
    parser.add_argument('--resume', action='store_true',
                        help='保留已有 KB，跳过已导入 pid')
    args = parser.parse_args()

    client = RkbClient(args.base_url)
    client.health()
    if args.resume:
        kb = client.ensure_kb(args.kb_name, args.embedding_model)
    else:
        old = client.find_kb(args.kb_name)
        if old:
            raise SystemExit(f'KB 已存在: {old["id"]}；要复用请加 --resume')
        kb = client.create_kb(args.kb_name, args.embedding_model)
    kb_id = kb['id']
    directory_id = client.default_directory(kb_id)

    corpus = load_corpus(os.path.join(args.data_dir, 'corpus.parquet'), args.limit)
    already = existing_pids(client, kb_id) if args.resume else set()
    if already:
        print(f'resume: 已有 {len(already)} 个 pid，跳过')
    todo = [(pid, text) for pid, text in corpus if pid not in already]
    parts = ((pid, part) for pid, text in todo for part in split_parts(text))

    shard_files = ensure_shard_files(client, kb_id, directory_id, len(corpus))
    print(f'KB={kb_id} corpus={len(corpus)} todo={len(todo)} shards={len(shard_files)}')

    run_dir = os.path.join(args.runs_dir, kb_id)
    os.makedirs(run_dir, exist_ok=True)
    checkpoint_path = os.path.join(run_dir, 'imported.jsonl')
    started = time.time()
    done = 0
    failures: List[Dict[str, str]] = []
    part_list = list(parts)
    total_parts = len(part_list)
    print(f'parts={total_parts} workers={args.workers}')

    def add_one(item: Tuple[str, str]) -> Tuple[str, int]:
        pid, part = item
        # 按 pid 稳定分片到容器文件；fileId 只影响关系表归属，不参与检索指标。
        file_id = shard_files[int(pid, 16) % len(shard_files)]
        client.add_chunk(kb_id, file_id, part, display_text(pid, part))
        return pid, 1

    with open(checkpoint_path, 'a', encoding='utf-8') as checkpoint:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(add_one, item): item for item in part_list}
            for future in as_completed(futures):
                item = futures[future]
                try:
                    pid, _ = future.result()
                    checkpoint.write(json.dumps({'pid': pid}) + '\n')
                    checkpoint.flush()
                    done += 1
                except Exception as error:                      # noqa: BLE001
                    failures.append({'pid': item[0], 'error': str(error)[:500]})
                if done % 200 == 0 and done:
                    rate = done / max(time.time() - started, 1e-6)
                    print(f'{done}/{total_parts} parts, {rate:.1f} parts/s, '
                          f'failures={len(failures)}', flush=True)

    elapsed = time.time() - started
    summary = {
        'kb_id': kb_id,
        'kb_name': args.kb_name,
        'corpus_passages': len(corpus),
        'parts_attempted': total_parts,
        'parts_succeeded': done,
        'failures': failures[:50],
        'failure_count': len(failures),
        'elapsed_seconds': round(elapsed, 1),
        'parts_per_second': round(done / max(elapsed, 1e-6), 2),
    }
    with open(os.path.join(run_dir, 'import-summary.json'), 'w', encoding='utf-8') as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(f'{len(failures)} 个切片导入失败，见 {run_dir}/import-summary.json')


if __name__ == '__main__':
    main()
