#!/usr/bin/env python3
"""检查 2Wiki 图谱导入包的规模、连通性与 gold 证据覆盖。

用法::

    python3 tools/graph-metrics/analyze_2wiki_graph.py \
        --graph-zip .metrics-data/2wiki/graph-v2/graph.zip \
        --data-dir .metrics-data/2wiki/data \
        --dev-json .metrics-data/2wiki/raw/dev_voidful.json

指标：
* 实体/边数、度分布、孤立点、连通分量；
* gold evidence 实体覆盖率、直接边覆盖率、≤4 跳路径覆盖率；
* 按关系类型拆分的边覆盖；
* gold answer 作为实体存在的比例。
"""

from __future__ import annotations

import argparse
import collections
import io
import json
import re
import string
import zipfile
from pathlib import Path

DEFAULT_DATA = Path('.metrics-data/2wiki/data')
DEFAULT_DEV = Path('.metrics-data/2wiki/raw/dev_voidful.json')
MONTHS = {name.lower(): index for index, name in enumerate(
    ('January', 'February', 'March', 'April', 'May', 'June', 'July',
     'August', 'September', 'October', 'November', 'December'), start=1)}

#: 2Wiki 的 country evidence 常用国籍形容词（American）而不是国家名
#: （United States）；覆盖统计要把两者归一，否则会低估图谱。
COUNTRY_ALIASES = {
    'american': 'united states', 'u.s.': 'united states', 'usa': 'united states',
    'us': 'united states', 'united states of america': 'united states',
    'british': 'united kingdom', 'english': 'united kingdom',
    'scottish': 'united kingdom', 'welsh': 'united kingdom',
    'great britain': 'united kingdom', 'britain': 'united kingdom',
    'east german': 'germany', 'west german': 'germany', 'german': 'germany',
    'east germany': 'germany', 'west germany': 'germany',
    'swedish': 'sweden', 'russian': 'russia', 'soviet': 'russia',
    'soviet union': 'russia', 'ussr': 'russia',
    'kenyan': 'kenya', 'indian': 'india', 'french': 'france',
    'italian': 'italy', 'spanish': 'spain', 'canadian': 'canada',
    'australian': 'australia', 'japanese': 'japan', 'chinese': 'china',
    'irish': 'ireland', 'dutch': 'netherlands', 'polish': 'poland',
    'portuguese': 'portugal', 'brazilian': 'brazil', 'mexican': 'mexico',
}


def country_key(value: str) -> str:
    text = str(value or '').strip().lower()
    return COUNTRY_ALIASES.get(text, text)


def parse_date(value: str):
    """把常见日期写法归一成 (Y, M, D)；只有年份时 M/D=0。"""
    text = str(value).strip()
    match = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})(?:\s+\d{1,2}:\d{2}:\d{2})?$', text)
    if match:
        return int(match.group(1)), int(match.group(2)), int(match.group(3))
    match = re.match(r'^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$', text)
    if match and match.group(2).lower() in MONTHS:
        return int(match.group(3)), MONTHS[match.group(2).lower()], int(match.group(1))
    match = re.match(r'^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$', text)
    if match and match.group(1).lower() in MONTHS:
        return int(match.group(3)), MONTHS[match.group(1).lower()], int(match.group(2))
    match = re.match(r'^(\d{4})$', text)
    if match:
        return int(match.group(1)), 0, 0
    return None


def norm(name: str) -> str:
    text = str(name).lower()
    text = re.sub(r'\([^)]*\)', ' ', text)
    text = ''.join(' ' if char in string.punctuation else char for char in text)
    return ' '.join(text.split())


def load_zip(path: Path):
    archive = zipfile.ZipFile(io.BytesIO(path.read_bytes()))
    entities = [json.loads(line) for line in
                archive.read('entities.jsonl').decode('utf-8').splitlines() if line.strip()]
    edges = [json.loads(line) for line in
             archive.read('edges.jsonl').decode('utf-8').splitlines() if line.strip()]
    return entities, edges


def build_graph(entities, edges):
    id_name = {entity['entity_id']: (entity.get('properties') or {}).get('entity_name', '')
               for entity in entities}
    name_ids = collections.defaultdict(set)
    for entity_id, name in id_name.items():
        name_ids[norm(name)].add(entity_id)
    adjacency = collections.defaultdict(set)
    for edge in edges:
        source, target = edge.get('source_id'), edge.get('target_id')
        if source in id_name and target in id_name:
            adjacency[source].add(target)
            adjacency[target].add(source)
    return id_name, name_ids, adjacency


def ids_for(name: str, name_ids) -> set[str]:
    key = norm(name)
    found = set(name_ids.get(key, ()))
    if found or len(key) < 6:
        return found
    for candidate, ids in name_ids.items():
        if len(candidate) >= 6 and (key in candidate or candidate in key):
            found |= ids
    return found


def path_within(adjacency, sources: set[str], targets: set[str], max_depth: int = 4):
    if sources & targets:
        return 0
    frontier, seen = set(sources), set(sources)
    for depth in range(1, max_depth + 1):
        nxt = set()
        for node in frontier:
            for neighbour in adjacency[node]:
                if neighbour in targets:
                    return depth
                if neighbour not in seen:
                    seen.add(neighbour)
                    nxt.add(neighbour)
        frontier = nxt
        if not frontier:
            break
    return None


def graph_structure(id_name, adjacency) -> dict:
    degrees = {node: len(adjacency[node]) for node in id_name}
    values = sorted(degrees.values())
    seen, components = set(), []
    for node in id_name:
        if node in seen:
            continue
        stack, size = [node], 0
        seen.add(node)
        while stack:
            current = stack.pop()
            size += 1
            for neighbour in adjacency[current]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        components.append(size)
    return {
        'entities': len(id_name),
        'edges': sum(values) // 2,
        'isolated': sum(1 for value in values if value == 0),
        'degree_le_1': sum(1 for value in values if value <= 1),
        'degree_p50': values[len(values) // 2] if values else 0,
        'degree_p90': values[int(len(values) * 0.9)] if values else 0,
        'degree_max': values[-1] if values else 0,
        'components': len(components),
        'largest_component': max(components) if components else 0,
    }


def evidence_coverage(questions, dev_by_id, id_name, name_ids, adjacency) -> dict:
    entity_hit = entity_total = edge_hit = edge_total = path_questions = 0
    semantic_hit = 0
    by_relation = collections.defaultdict(lambda: [0, 0])
    answers = 0
    for question in questions:
        evidences = dev_by_id[question['qid']].get('evidences') or []
        any_path = False
        for subject, relation, obj in evidences:
            entity_total += 2
            subject_ids, object_ids = ids_for(subject, name_ids), ids_for(obj, name_ids)
            entity_hit += bool(subject_ids) + bool(object_ids)
            edge_total += 1
            relation_key = str(relation).lower()
            by_relation[relation_key][1] += 1
            is_country = relation_key in (
                'country of citizenship', 'country of origin', 'country')
            if subject_ids:
                direct = bool(object_ids) and any(
                    target in object_ids
                    for source in subject_ids for target in adjacency[source])
                if not direct and is_country:
                    # American -> United States；East Germany -> Germany
                    gold_country = country_key(obj)
                    direct = any(
                        country_key(id_name.get(target, '')) == gold_country
                        for source in subject_ids
                        for target in adjacency[source])
                semantic = direct
                if not semantic:
                    gold_date = parse_date(obj)
                    if gold_date:
                        # 日期写法可能不同（ISO vs "9 September 1992"），
                        # 只要主体连到语义相同的日期实体就算覆盖。
                        semantic = any(
                            parse_date(id_name.get(target, '')) == gold_date
                            for source in subject_ids
                            for target in adjacency[source])
                if direct:
                    edge_hit += 1
                if semantic:
                    semantic_hit += 1
                    by_relation[str(relation).lower()][0] += 1
                    any_path = True
                elif object_ids and path_within(adjacency, subject_ids, object_ids) is not None:
                    any_path = True
        path_questions += any_path
        answer_key = norm(question['answer'])
        answers += any(
            answer_key == key or (len(answer_key) >= 6 and
                                  (answer_key in key or key in answer_key))
            for key in name_ids)
    return {
        'entity_coverage': entity_hit / entity_total if entity_total else 0,
        'edge_coverage': edge_hit / edge_total if edge_total else 0,
        'edge_coverage_semantic': semantic_hit / edge_total if edge_total else 0,
        'path_coverage': path_questions / len(questions) if questions else 0,
        'answer_entity_coverage': answers / len(questions) if questions else 0,
        'relations': {relation: {'hit': value[0], 'total': value[1]}
                      for relation, value in sorted(by_relation.items(),
                                                    key=lambda item: -item[1][1])},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph-zip', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, default=DEFAULT_DATA)
    parser.add_argument('--dev-json', type=Path, default=DEFAULT_DEV)
    parser.add_argument('--out', type=Path, default=None)
    args = parser.parse_args()

    entities, edges = load_zip(args.graph_zip)
    id_name, name_ids, adjacency = build_graph(entities, edges)
    questions = [json.loads(line) for line in
                 (args.data_dir / 'questions.jsonl').open(encoding='utf-8') if line.strip()]
    dev_by_id = {row['_id']: row for row in json.loads(args.dev_json.read_text())}
    report = {
        'graph_zip': str(args.graph_zip),
        'structure': graph_structure(id_name, adjacency),
        'coverage': evidence_coverage(questions, dev_by_id, id_name, name_ids, adjacency),
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text + '\n', encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
