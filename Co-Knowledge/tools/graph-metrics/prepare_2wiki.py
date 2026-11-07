#!/usr/bin/env python3
"""把 2WikiMultiHopQA 的 dev 集转成端到端评测语料。

数据源用 HuggingFace 镜像 ``voidful/2WikiMultihopQA`` 的 ``dev.json``：官方 test
集在几个镜像里 ``answer`` 为空，dev 集带标准答案与 supporting facts，量级相同
（12,576 题），因此端到端评测用 dev。

产物（默认 ``.metrics-data/2wiki/data``）：

* ``questions.jsonl`` —— 分层抽样的题目：``qid/type/question/answer/gold_titles``
* ``articles.jsonl``  —— 去重后的文章：``aid/title/text``（文档库逐篇一个切片）
* ``graph_upload/*.txt`` —— 抽图上传文件（每文件最多 ``--group-size`` 篇，
  图谱库单次上传上限 50 个文件）
* ``groups.jsonl``    —— 上传文件 → 文章标题的映射
* ``manifest.json``   —— 本次抽样与语料统计

跑法::

    python3 tools/graph-metrics/prepare_2wiki.py \
        --input .metrics-data/2wiki/raw/dev_voidful.json \
        --out .metrics-data/2wiki/data --per-type 25
"""

from __future__ import annotations

import argparse
import collections
import json
import random
from pathlib import Path

DEFAULT_INPUT = Path('.metrics-data/2wiki/raw/dev_voidful.json')
DEFAULT_OUT = Path('.metrics-data/2wiki/data')
TYPES = ('bridge_comparison', 'comparison', 'compositional', 'inference')
MAX_UPLOAD_FILES = 50


def _safe_filename(index: int) -> str:
    return f'article-{index:05d}.txt'


def article_text(title: str, sentences: list[str]) -> str:
    return title + '\n' + ' '.join(str(s).strip() for s in sentences if str(s).strip())


def load_rows(path: Path) -> list[dict]:
    with path.open(encoding='utf-8') as handle:
        rows = json.load(handle)
    if not isinstance(rows, list):
        raise SystemExit(f'{path} 不是 JSON 数组')
    return rows


def sample(rows: list[dict], per_type: int, seed: int) -> list[dict]:
    """``per_type <= 0`` 表示该题型全量，不做随机抽样。"""
    by_type: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        if row.get('answer') and row.get('type') in TYPES:
            by_type[row['type']].append(row)
    rng = random.Random(seed)
    picked: list[dict] = []
    for type_name in TYPES:
        pool = by_type.get(type_name) or []
        if per_type <= 0:
            picked.extend(pool)
            continue
        if len(pool) < per_type:
            raise SystemExit(f'{type_name} 只有 {len(pool)} 题，不够 {per_type} 题')
        picked.extend(rng.sample(pool, per_type))
    picked.sort(key=lambda row: (TYPES.index(row['type']), row['_id']))
    return picked


def build_articles(rows: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """按标题去重；同一标题多次出现时取句子更多的那份。"""
    by_title: dict[str, list[str]] = {}
    for row in rows:
        for title, sentences in row['context']:
            title = str(title).strip()
            sentences = [str(s) for s in (sentences or [])]
            if not title:
                continue
            previous = by_title.get(title)
            if previous is None or len(' '.join(sentences)) > len(' '.join(previous)):
                by_title[title] = sentences
    articles = [
        {'aid': _safe_filename(index), 'title': title,
         'text': article_text(title, sentences)}
        for index, (title, sentences) in enumerate(sorted(by_title.items()), start=1)
    ]
    title_to_aid = {article['title']: article['aid'] for article in articles}
    return articles, title_to_aid


def write_graph_upload(out_dir: Path, articles: list[dict],
                       group_size: int) -> list[dict]:
    groups = []
    upload_dir = out_dir / 'graph_upload'
    upload_dir.mkdir(parents=True, exist_ok=True)
    for start in range(0, len(articles), group_size):
        chunk = articles[start:start + group_size]
        filename = f'graph-{start // group_size + 1:03d}.txt'
        body = '\n\n'.join(
            f'## {article["title"]}\n'
            + article['text'].split('\n', 1)[-1]
            for article in chunk)
        (upload_dir / filename).write_text(body + '\n', encoding='utf-8')
        groups.append({'file': filename,
                       'titles': [article['title'] for article in chunk]})
    if len(groups) > MAX_UPLOAD_FILES:
        raise SystemExit(
            f'抽图上传文件 {len(groups)} 个，超过单次上限 {MAX_UPLOAD_FILES}；'
            f'请增大 --group-size')
    with (out_dir / 'groups.jsonl').open('w', encoding='utf-8') as handle:
        for group in groups:
            handle.write(json.dumps(group, ensure_ascii=False) + '\n')
    return groups


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=DEFAULT_INPUT)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--per-type', type=int, default=25,
                        help='每种题型的抽样数（默认 25，共 100 题；<=0 = 该题型全量）')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--group-size', type=int, default=20,
                        help='每个抽图上传文件包含的文章数')
    args = parser.parse_args()

    rows = load_rows(args.input)
    picked = sample(rows, args.per_type, args.seed)
    articles, title_to_aid = build_articles(picked)
    args.out.mkdir(parents=True, exist_ok=True)

    questions = []
    for index, row in enumerate(picked, start=1):
        gold_titles = []
        for title, _sentence_index in row.get('supporting_facts') or []:
            title = str(title).strip()
            if title and title not in gold_titles:
                gold_titles.append(title)
        context_titles = [str(title).strip() for title, _ in row['context']]
        questions.append({
            'qid': str(row['_id']),
            'index': index,
            'type': row['type'],
            'question': str(row['question']).strip(),
            'answer': str(row['answer']).strip(),
            'gold_titles': gold_titles,
            'gold_aids': [title_to_aid[title] for title in gold_titles
                          if title in title_to_aid],
            'context_titles': context_titles,
        })

    with (args.out / 'questions.jsonl').open('w', encoding='utf-8') as handle:
        for question in questions:
            handle.write(json.dumps(question, ensure_ascii=False) + '\n')
    with (args.out / 'articles.jsonl').open('w', encoding='utf-8') as handle:
        for article in articles:
            handle.write(json.dumps(article, ensure_ascii=False) + '\n')

    groups = write_graph_upload(args.out, articles, args.group_size)
    manifest = {
        'source': str(args.input),
        'seed': args.seed,
        'per_type': args.per_type,
        'question_count': len(questions),
        'type_counts': dict(collections.Counter(q['type'] for q in questions)),
        'article_count': len(articles),
        'graph_upload_files': len(groups),
        'gold_titles_missing': sorted({
            title for q in questions for title in q['gold_titles']
            if title not in title_to_aid
        }),
    }
    (args.out / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
