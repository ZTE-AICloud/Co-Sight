#!/usr/bin/env python3
"""端到端切分 A/B：同一批文档 → 两个知识库 → 同一组事实问答比检索命中。

**为什么不复用现成的 L1 基准**：``tools/rag-metrics`` 与 ``tools/bench`` 的口径
都是「一 passage = 一 chunk」，走 ``POST /chunks`` 手工灌切片 —— 切分被固定成
变量。要评估「解析 + 切分」本身的改动（哨兵、表格行、章节边界、PDF 行重建），
必须走真实的**文件上传**流水线。

用法::

    # A 侧：当前版本（容器里是新解析器）
    python3 tools/bench/run_chunking_ab.py --docs a.docx b.docx --tag new
    # B 侧：把容器换回上一版解析器后，跑同名库（--reuse-kb 复用已上传文档）
    python3 tools/bench/run_chunking_ab.py --docs a.docx b.docx --tag old
    # 对比
    python3 tools/bench/run_chunking_ab.py --compare \
        .metrics-data/bench/runs/chunking-old.json \
        .metrics-data/bench/runs/chunking-new.json

口径：

* **问题自动生成、确定性**（同一批文档每次生成同样的问题）：
  - docx 表格：``<首列值> 的<列名>是什么？`` → 该单元格内容；
  - docx / md 标题：``<标题> 的具体内容是什么？`` → 正文前 24 字。
* **coverage 与排序分开报**：先说答案在不在库里（切分有没有丢内容），
  再看排第几（排序质量）。只有 coverage 相同，hit@k 的差异才归因于切分边界。
* **污染度**：含内部哨兵（``table is find`` / ``table is finished``）的切片数，
  是「解析层把内部标记漏进检索正文」这类回归的直接判据。
* KB 名固定为 ``chunk-ab-<tag>``，重复跑会复用（已就绪的文档不重传）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'rag-metrics'))

from rkb_client import RkbClient, RkbError  # noqa: E402

from common import DEFAULT_BASE, RUNS_DIR, write_json  # noqa: E402

KS = (1, 5, 10)
HEADLINE = ('hit@1', 'hit@5', 'hit@10', 'mrr@10')
SENTINELS = ('table is find', 'table is finished')
MIN_ANSWER = 2
MAX_ANSWER = 60
SECTION_ANSWER_CHARS = 24


# ----------------------------------------------------------------------
# 问题生成（纯函数，可单测）
# ----------------------------------------------------------------------

def _clean(text: str) -> str:
    return ' '.join((text or '').split())


def questions_from_docx(path: str, table_limit: int = 40, section_limit: int = 15) -> List[Dict[str, str]]:
    from docx import Document

    document = Document(path)
    questions: List[Dict[str, str]] = []

    for table in document.tables:
        if not table.rows:
            continue
        header = [_clean(cell.text) for cell in table.rows[0].cells]
        if not header or not header[0]:
            continue
        for row in table.rows[1:]:
            cells = [_clean(cell.text) for cell in row.cells]
            # 行宽与表头不一致（合并 / 残表）时不造题，避免答案对不上列
            if len(cells) != len(header):
                continue
            subject = cells[0]
            if len(subject) < 2:
                continue
            for column in range(1, len(header)):
                attribute, value = header[column], cells[column]
                if not attribute or value == subject:
                    continue
                if not MIN_ANSWER <= len(value) <= MAX_ANSWER:
                    continue
                questions.append({'kind': 'table', 'q': f'{subject} 的{attribute}是什么？', 'a': value})
                if len(questions) >= table_limit:
                    break
            if len(questions) >= table_limit:
                break
        if len(questions) >= table_limit:
            break

    paragraphs = document.paragraphs
    for index, paragraph in enumerate(paragraphs):
        if not (paragraph.style.name or '').startswith('Heading'):
            continue
        heading = _clean(paragraph.text)
        if len(heading) < 4:
            continue
        body = ''
        for follow in paragraphs[index + 1:index + 4]:
            if (follow.style.name or '').startswith('Heading'):
                break
            text = _clean(follow.text)
            if len(text) >= 20:
                body = text
                break
        if not body:
            continue
        questions.append({'kind': 'section', 'q': f'{heading} 的具体内容是什么？',
                          'a': body[:SECTION_ANSWER_CHARS]})
        if len(questions) >= table_limit + section_limit:
            break
    return questions


def questions_from_md(path: str, section_limit: int = 30) -> List[Dict[str, str]]:
    lines = Path(path).read_text(encoding='utf-8', errors='replace').splitlines()
    questions: List[Dict[str, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r'^(#{1,6})\s+(.*)$', line.strip())
        if not match:
            continue
        heading = _clean(match.group(2))
        if len(heading) < 4:
            continue
        body = ''
        for follow in lines[index + 1:index + 4]:
            text = _clean(follow)
            if text.startswith('#'):
                break
            if len(text) >= 20:
                body = text
                break
        if not body:
            continue
        questions.append({'kind': 'section', 'q': f'{heading} 的具体内容是什么？',
                          'a': body[:SECTION_ANSWER_CHARS]})
        if len(questions) >= section_limit:
            break
    return questions


def build_questions(docs: Sequence[str], limit: Optional[int] = None) -> List[Dict[str, str]]:
    """按扩展名生成问题；未知格式跳过（记一行告警在调用方）。"""
    questions: List[Dict[str, str]] = []
    for path in docs:
        suffix = Path(path).suffix.lower()
        if suffix == '.docx':
            questions.extend(questions_from_docx(path))
        elif suffix in ('.md', '.markdown'):
            questions.extend(questions_from_md(path))
    if limit and len(questions) > limit:
        # 均匀抽样，保证确定性
        step = len(questions) / limit
        questions = [questions[int(index * step)] for index in range(limit)]
    return questions


# ----------------------------------------------------------------------
# 指标（纯函数，可单测）
# ----------------------------------------------------------------------

#: 产品会做、源文档不会做的标点归一（表格单元格里 ``。`` → ``；``）
_MATCH_TRANSLATION = str.maketrans({'。': '；', '．': '.', '（': '(', '）': ')', '，': ','})
#: 中文与中文标点旁边的空白不承载信息（产品会把单元格里的换行并成空格）
_CJK_ADJACENT_SPACE = re.compile(r'\s+(?=[一-鿿；，。、：（）])|(?<=[一-鿿；，。、：（）])\s+')


def normalize_for_match(text: str) -> str:
    """比子串之前先归一「空白 + 中文标点」。

    产品在表格单元格里把 ``。`` 换成 ``；``、把多段单元格的换行并成空格；
    源文档里一个单元格写成两段时，金标答案和切片正文只差一个空白 ——
    直接用原始字符串比会把这些判成「内容丢失」（实测 110 题里 6 个假阴性，
    实际一条内容都没丢）。英文词之间的空白保留，避免把相邻词误并。
    """
    text = re.sub(r'\s+', ' ', (text or '')).strip().translate(_MATCH_TRANSLATION)
    return _CJK_ADJACENT_SPACE.sub('', text)


def score_ranks(ranks: Sequence[Optional[int]]) -> Dict[str, float]:
    total = len(ranks) or 1
    metrics = {f'hit@{k}': sum(1 for rank in ranks if rank and rank <= k) / total for k in KS}
    metrics['mrr@10'] = sum(1.0 / rank for rank in ranks if rank and rank <= 10) / total
    metrics['miss'] = sum(1 for rank in ranks if not rank or rank > 10) / total
    return metrics


def compare_results(old: Dict[str, Any], new: Dict[str, Any]) -> List[str]:
    """两次结果的对比文本（表格 + 逐题排名变化）。"""
    lines: List[str] = []
    lines.append(f"文档: {', '.join(new.get('docs') or [])}")
    lines.append(f"切片数: 旧 {old.get('chunks')} → 新 {new.get('chunks')}")
    lines.append(f"答案覆盖率: 旧 {old.get('coverage')}/{old.get('questions')} → "
                 f"新 {new.get('coverage')}/{new.get('questions')}")
    lines.append(f"含哨兵切片: 旧 {old.get('contaminated')} → 新 {new.get('contaminated')}")
    lines.append('')
    lines.append('| 系统 | 指标 | 旧 | 新 | 变化 |')
    lines.append('|---|---|---|---|---|')
    for system in sorted(set(old.get('metrics') or {}) & set(new.get('metrics') or {})):
        for key in HEADLINE:
            before = (old['metrics'][system] or {}).get(key)
            after = (new['metrics'][system] or {}).get(key)
            if before is None or after is None:
                continue
            lines.append(f'| {system} | {key} | {before*100:.2f}% | {after*100:.2f}% '
                         f'| {(after-before)*100:+.2f} pp |')
    lines.append('')

    for system in sorted(set(old.get('details') or {}) & set(new.get('details') or {})):
        old_rows = {row['q']: row for row in old['details'][system]}
        new_rows = {row['q']: row for row in new['details'][system]}
        better = worse = same = 0
        changes = []
        for question, new_row in new_rows.items():
            old_row = old_rows.get(question)
            if not old_row:
                continue
            before, after = old_row.get('rank'), new_row.get('rank')
            if before == after:
                same += 1
                continue
            if (after or 99) < (before or 99):
                better += 1
            else:
                worse += 1
            changes.append((question, before, after))
        lines.append(f'{system}: 排名更好 {better}、更差 {worse}、持平 {same}')
        for question, before, after in changes[:8]:
            lines.append(f'  - 旧 {before or "未命中"} → 新 {after or "未命中"} | {question[:48]}')
        lines.append('')
    return lines


# ----------------------------------------------------------------------
# 跑一侧
# ----------------------------------------------------------------------

def ensure_kb(client: RkbClient, kb_name: str) -> str:
    existing = client.find_kb(kb_name)
    if existing:
        return existing['id']
    created = client.create_kb(kb_name, description='chunking A/B (run_chunking_ab.py)')
    return created['id']


def wait_chunks_stable(client: RkbClient, kb_id: str, timeout: int = 300) -> int:
    """解析完成后还在批量 embedding：切片数连续 3 次不变才算稳定。"""
    last, stable, deadline = -1, 0, time.time() + timeout
    while time.time() < deadline:
        page = client._request('GET', f'/knowledge-bases/{kb_id}/chunks?page=1&size=1') or {}
        total = page.get('total') or 0
        if total == last:
            stable += 1
            if stable >= 3:
                return total
        else:
            last, stable = total, 0
        time.sleep(3)
    return last


def list_chunk_texts(client: RkbClient, kb_id: str, page_size: int = 500) -> List[str]:
    texts: List[str] = []
    page = 1
    while True:
        payload = client._request(
            'GET', f'/knowledge-bases/{kb_id}/chunks?page={page}&size={page_size}') or {}
        items = payload.get('items') or []
        texts.extend(str(item.get('content') or '') for item in items)
        if not items or len(texts) >= (payload.get('total') or 0):
            return texts
        page += 1


def doc_text(doc: Dict[str, Any]) -> str:
    parts = []
    for key in ('content', 'supplement', 'text', 'contentExpand'):
        value = doc.get(key)
        if isinstance(value, str) and value:
            parts.append(value)
    return '\n'.join(parts)


def run_side(client: RkbClient, docs: Sequence[str], tag: str, top_k: int,
             systems: Sequence[str]) -> Dict[str, Any]:
    kb_name = f'chunk-ab-{tag}'
    kb_id = ensure_kb(client, kb_name)
    directory = client.default_directory(kb_id)

    existing = {row.get('title'): row for row in client.list_files(kb_id)}
    for path in docs:
        name = Path(path).name
        if (existing.get(name) or {}).get('status') == 1:
            continue
        client.upload_document(kb_id, directory, path)
    client.wait_for_file(kb_id, Path(docs[0]).name)
    for path in docs:
        client.wait_for_file(kb_id, Path(path).name)

    total = wait_chunks_stable(client, kb_id)
    chunk_texts = list_chunk_texts(client, kb_id)
    contaminated = sum(1 for text in chunk_texts if any(mark in text for mark in SENTINELS))

    questions = build_questions(docs)
    if not questions:
        raise RkbError('没有生成任何问题：请确认文档是 docx / md 且含标题或表格')
    normalized_chunks = [normalize_for_match(text) for text in chunk_texts]
    coverage = sum(1 for item in questions
                   if any(normalize_for_match(item['a']) in text for text in normalized_chunks))

    type_map = {'vector': 0, 'keyword': 1}
    metrics: Dict[str, Any] = {}
    details: Dict[str, Any] = {}
    for system in systems:
        ranks: List[Optional[int]] = []
        rows = []
        for item in questions:
            fetched = client.retrieve(kb_id, item['q'], type_map[system], top_k=top_k)
            answer = normalize_for_match(item['a'])
            rank = None
            for position, doc in enumerate(fetched, start=1):
                if answer in normalize_for_match(doc_text(doc)):
                    rank = position
                    break
            ranks.append(rank)
            rows.append({'q': item['q'], 'a': item['a'], 'kind': item['kind'], 'rank': rank})
        metrics[system] = score_ranks(ranks)
        details[system] = rows

    return {
        'tag': tag,
        'kb_id': kb_id,
        'kb_name': kb_name,
        'docs': [Path(path).name for path in docs],
        'chunks': total,
        'questions': len(questions),
        'coverage': coverage,
        'contaminated': contaminated,
        'metrics': metrics,
        'details': details,
        'config': {'top_k': top_k, 'systems': list(systems)},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--docs', nargs='+', default=[], help='参与评测的文档（docx / md）')
    parser.add_argument('--tag', default='current', help='本侧名字，KB 名为 chunk-ab-<tag>')
    parser.add_argument('--base-url', default=DEFAULT_BASE)
    parser.add_argument('--systems', default='vector,keyword')
    parser.add_argument('--top-k', type=int, default=10)
    parser.add_argument('--compare', nargs=2, metavar=('OLD', 'NEW'),
                        help='只做对比：两个结果 JSON 的路径')
    args = parser.parse_args()

    if args.compare:
        old = json.loads(Path(args.compare[0]).read_text(encoding='utf-8'))
        new = json.loads(Path(args.compare[1]).read_text(encoding='utf-8'))
        print('\n'.join(compare_results(old, new)))
        return

    if not args.docs:
        raise SystemExit('要么给 --docs，要么用 --compare OLD NEW')
    if not 1 <= args.top_k <= 80:
        raise SystemExit('--top-k 必须在 1..80')

    systems = [item.strip() for item in args.systems.split(',') if item.strip()]
    if not set(systems) <= {'vector', 'keyword'}:
        raise SystemExit(f'未知系统: {systems}')

    client = RkbClient(args.base_url)
    client.health()
    result = run_side(client, args.docs, args.tag, args.top_k, systems)

    out = RUNS_DIR / f'chunking-{args.tag}.json'
    write_json(out, result)
    print(f"kb={result['kb_id']} chunks={result['chunks']} "
          f"coverage={result['coverage']}/{result['questions']} "
          f"contaminated={result['contaminated']}")
    for system, values in result['metrics'].items():
        print(f"  {system}: " + ', '.join(f'{key}={value:.4f}' for key, value in values.items()))
    print(f'结果已写入 {out}')


if __name__ == '__main__':
    main()
