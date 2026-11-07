#!/usr/bin/env python3
"""准备 MetaQA 图谱检索评测数据：下载 → 校验 → 转成图谱导入包。

产物（默认 ``.metrics-data/metaqa/``，已 gitignore）：

* ``raw/``           上游原始文件（kb.txt + 三个 hop 的 qa_test.txt）
* ``questions.jsonl`` 每题一行：hop / qid / question / topic / answers
* ``metaqa-import.zip`` ``/graph-imports`` 可直接上传的包
* ``stats.json``      规模与环境摘要

上游镜像：https://huggingface.co/datasets/camazlucas/MetaQA
（原始发布在 Google Drive，HF 镜像是逐字节副本；本脚本只取 vanilla 文本与 kb.txt）

KB 转换口径（写进报告时保持一致）：

* 一个实体 = KB 里出现过的 subject/object；``entity_id`` 就是实体名，
  和 MetaQA 自带的答案标注同一命名空间，不做任何消歧。
* 实体类型统一为 ``Entity``：MetaQA 的实体类型是隐含的（movie/actor/...），
  强行推断会把「演员也导演过电影」这类实体拆成两个 ID，反而破坏多跳。
* 9 个关系映射成只含字母的 PascalCase 边类型：schema 校验器要求
  ``^[A-Za-z]*$``，``directed_by`` 这种名字不能直接用。
* 边 ID 用 ``r<行号>``，重复导入时按 edge_id 幂等跳过。
"""
from __future__ import annotations

import argparse
import json
import random
import re
import secrets
import sys
from pathlib import Path
from typing import Iterable

import requests

HF_BASE = 'https://huggingface.co/datasets/camazlucas/MetaQA/resolve/main'
RAW_FILES = (
    'kb/kb.txt',
    '1-hop/vanilla/qa_test.txt',
    '2-hop/vanilla/qa_test.txt',
    '3-hop/vanilla/qa_test.txt',
)
HOPS = ('1-hop', '2-hop', '3-hop')
DEFAULT_OUT = Path('.metrics-data/metaqa')
DEFAULT_EMBEDDING = 'Qwen3-Embedding-0.6B'
DEFAULT_KB_NAME = 'MetaQA-Benchmark-v1'
ENTITY_TYPE = 'Entity'
BRACKET_RE = re.compile(r'\[([^\]]+)\]')


# ----------------------------------------------------------------------
# 下载
# ----------------------------------------------------------------------


def download(url: str, target: Path, *, timeout: int = 300) -> None:
    """下载到临时文件再原子替换；已存在且非空则跳过。"""
    if target.exists() and target.stat().st_size > 0:
        print(f'skip {target} ({target.stat().st_size} bytes)')
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + '.part')
    with requests.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with tmp.open('wb') as handle:
            for chunk in response.iter_content(chunk_size=1 << 20):
                if chunk:
                    handle.write(chunk)
    tmp.replace(target)
    print(f'downloaded {target} ({target.stat().st_size} bytes)')


def ensure_raw(data_dir: Path) -> None:
    for relative in RAW_FILES:
        download(f'{HF_BASE}/{relative}', data_dir / 'raw' / relative)


# ----------------------------------------------------------------------
# 解析
# ----------------------------------------------------------------------


def parse_kb(path: Path) -> list[tuple[str, str, str]]:
    """``subject|relation|object`` 每行一条；空行跳过，字段数不是 3 直接报错。"""
    triples: list[tuple[str, str, str]] = []
    with path.open(encoding='utf-8') as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.rstrip('\n')
            if not line.strip():
                continue
            parts = line.split('|')
            if len(parts) != 3:
                raise ValueError(f'{path}:{line_no}: 期望 3 个字段，实际 {len(parts)}')
            triples.append((parts[0], parts[1], parts[2]))
    return triples


def parse_questions(path: Path, hop: str) -> list[dict]:
    """``question \\t answer1|answer2``；题目里的 ``[实体]`` 是标注的 topic entity。"""
    rows: list[dict] = []
    with path.open(encoding='utf-8') as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.rstrip('\n')
            if not line.strip():
                continue
            parts = line.split('\t')
            if len(parts) != 2:
                raise ValueError(f'{path}:{line_no}: 期望 2 个字段，实际 {len(parts)}')
            question, answers = parts
            topics = BRACKET_RE.findall(question)
            rows.append({
                'hop': hop,
                'qid': f'{hop}-{line_no}',
                'question': question,
                'topic': topics[0] if topics else '',
                'answers': [answer for answer in answers.split('|') if answer],
            })
    return rows


def relation_to_type(relation: str) -> str:
    """``directed_by`` → ``DirectedBy``；schema 只接受纯字母的类型名。"""
    mapped = ''.join(part.capitalize() for part in relation.split('_'))
    if not mapped.isalpha():
        raise ValueError(f'关系名无法映射成纯字母类型: {relation!r}')
    return mapped


def strip_brackets(question: str) -> str:
    """检索时去掉标注括号，但保留实体原文。"""
    return BRACKET_RE.sub(lambda match: match.group(1), question)


# ----------------------------------------------------------------------
# 导入包
# ----------------------------------------------------------------------


def build_schema(relations: Iterable[str], schema_name: str = 'MetaQA') -> dict:
    edge_types = sorted({relation_to_type(relation) for relation in relations})
    return {
        'schema_id': 'metaqa',
        'schema_name': schema_name,
        'schema_desc': 'MetaQA WikiMovies KB',
        'entities': [{
            'entity_type': ENTITY_TYPE,
            'entity_desc': 'MetaQA entity',
            'properties': [{
                'name': 'name',
                'type': 'STRING',
                'desc': 'entity name',
                'is_primary': True,
                'is_embedding': True,
                'is_index': False,
            }],
        }],
        'edges': [{
            'edge_type': edge_type,
            'edge_desc': edge_type,
            'direction': 'one-way',
            'source_entity': ENTITY_TYPE,
            'target_entity': ENTITY_TYPE,
            'properties': [],
        } for edge_type in edge_types],
    }


def build_zip(out_zip: Path, triples: list[tuple[str, str, str]], *,
              kb_name: str, embedding: str, kbase_id: str,
              schema_name: str = 'MetaQA') -> dict:
    """生成 ``desc.json`` / ``schema.json`` / ``entities.jsonl`` / ``edges.jsonl``。"""
    entities = sorted({value for triple in triples for value in (triple[0], triple[2])})
    relations = sorted({relation for _, relation, _ in triples})
    schema = build_schema(relations, schema_name)
    desc = {
        'name': kb_name,
        'id': kbase_id,
        'embedding': embedding,
        'desc': f'MetaQA benchmark: {len(triples)} triples / {len(entities)} entities',
    }
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_zip.with_suffix(out_zip.suffix + '.part')
    import zipfile

    with zipfile.ZipFile(tmp, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        _writestr(archive, 'desc.json', json.dumps(desc, ensure_ascii=False, indent=2))
        _writestr(archive, 'schema.json', json.dumps(schema, ensure_ascii=False, indent=2))
        _writestr(archive, 'entities.jsonl', ''.join(
            json.dumps({
                'entity_type': ENTITY_TYPE,
                'entity_id': name,
                'properties': {'name': name},
            }, ensure_ascii=False) + '\n'
            for name in entities))
        _writestr(archive, 'edges.jsonl', ''.join(
            json.dumps({
                'edge_id': f'r{line_no}',
                'source_id': source,
                'target_id': target,
                'edge_type': relation_to_type(relation),
                'properties': {},
            }, ensure_ascii=False) + '\n'
            for line_no, (source, relation, target) in enumerate(triples, 1)))
    tmp.replace(out_zip)
    return {
        'zip': str(out_zip),
        'zip_bytes': out_zip.stat().st_size,
        'entities': len(entities),
        'edges': len(triples),
        'edge_types': [edge['edge_type'] for edge in schema['edges']],
    }


def _writestr(archive, name: str, text: str) -> None:
    archive.writestr(name, text.encode('utf-8'))


def make_kbase_id(rng: random.Random | None = None) -> str:
    """``graph_`` + 16 位十六进制（导入接口对 id 长度的硬约束）。"""
    if rng is None:
        return 'graph_' + secrets.token_hex(8)
    return 'graph_' + ''.join(rng.choice('0123456789abcdef') for _ in range(16))


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------


def prepare(data_dir: Path, *, limit_triples: int = 0, kb_name: str,
            embedding: str, kbase_id: str = '') -> dict:
    ensure_raw(data_dir)
    triples = parse_kb(data_dir / 'raw/kb/kb.txt')
    if limit_triples > 0:
        triples = triples[:limit_triples]

    questions: list[dict] = []
    for hop in HOPS:
        questions.extend(parse_questions(data_dir / 'raw' / hop / 'vanilla/qa_test.txt', hop))
    with (data_dir / 'questions.jsonl').open('w', encoding='utf-8') as handle:
        for row in questions:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')

    existing_stats: dict = {}
    stats_path = data_dir / 'stats.json'
    if stats_path.exists():
        try:
            existing_stats = json.loads(stats_path.read_text(encoding='utf-8'))
        except ValueError:
            existing_stats = {}
    if (not kbase_id and existing_stats.get('kbase_id')
            and existing_stats.get('kb_name') == kb_name
            and existing_stats.get('embedding') == embedding):
        kbase_id = existing_stats['kbase_id']
    kbase_id = kbase_id or make_kbase_id()
    built = build_zip(data_dir / 'metaqa-import.zip', triples,
                      kb_name=kb_name, embedding=embedding, kbase_id=kbase_id)
    relations: dict[str, int] = {}
    for _, relation, _ in triples:
        relations[relation] = relations.get(relation, 0) + 1
    stats = {
        'kbase_id': kbase_id,
        'kb_name': kb_name,
        'embedding': embedding,
        **built,
        'relations': dict(sorted(relations.items())),
        'questions': {
            hop: sum(1 for row in questions if row['hop'] == hop) for hop in HOPS
        },
        'questions_with_topic': sum(1 for row in questions if row['topic']),
        'multi_answer': sum(1 for row in questions if len(row['answers']) > 1),
    }
    (data_dir / 'stats.json').write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--limit-triples', type=int, default=0,
                        help='只取前 N 条三元组（冒烟用；0 = 全量）')
    parser.add_argument('--kb-name', default=DEFAULT_KB_NAME)
    parser.add_argument('--embedding', default=DEFAULT_EMBEDDING)
    parser.add_argument('--kbase-id', default='',
                        help='复跑时固定 graph_<16hex>；缺省随机生成')
    args = parser.parse_args(argv)
    stats = prepare(args.out, limit_triples=args.limit_triples,
                    kb_name=args.kb_name, embedding=args.embedding,
                    kbase_id=args.kbase_id)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
