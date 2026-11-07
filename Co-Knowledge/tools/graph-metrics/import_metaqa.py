#!/usr/bin/env python3
"""把 prepare_metaqa.py 生成的 zip 导入成图谱知识库，并等到就绪。

幂等策略：

* 同 id 已存在且 ``status=5`` 且未传 ``--force`` → 跳过导入（直接复用）；
  这样样本题库可以反复跑指标，不会每次重建 13 万条边。
* ``--force`` → 先删库再导入；删库会连带清掉图存储表。

导入完成后的验收不是「状态码 200」，而是真的能检索出种子：
用 zip 里第一个实体做 query 调 ``POST /retrieval/graph``，``seed_entity_ids``
必须非空，否则按失败退出。
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

from graph_client import GraphClient, RkbError

DEFAULT_DATA = Path('.metrics-data/metaqa')


def read_zip_header(zip_path: Path) -> tuple[dict, dict, str, int, int]:
    with zipfile.ZipFile(zip_path) as archive:
        desc = json.loads(archive.read('desc.json'))
        schema = json.loads(archive.read('schema.json'))
        entity_lines = archive.read('entities.jsonl').decode('utf-8').splitlines()
        edge_lines = archive.read('edges.jsonl').decode('utf-8').splitlines()
        first_entity = json.loads(entity_lines[0]) if entity_lines else {}
    return (desc, schema, first_entity.get('entity_id', ''),
            len(entity_lines), len(edge_lines))


def import_metaqa(data_dir: Path, *, zip_path: Path | None = None,
                  kb_id: str = '', kb_name: str = '', embedding: str = '',
                  force: bool = False, timeout: int = 3600,
                  client: GraphClient | None = None) -> dict:
    stats_path = data_dir / 'stats.json'
    stats = json.loads(stats_path.read_text(encoding='utf-8')) \
        if stats_path.exists() else {}
    zip_path = zip_path or data_dir / 'metaqa-import.zip'
    if not zip_path.exists():
        raise RkbError(f'导入包不存在: {zip_path}；先跑 prepare_metaqa.py')

    desc, schema, first_entity, entity_count, edge_count = read_zip_header(zip_path)
    kb_id = kb_id or desc.get('id') or stats.get('kbase_id') or ''
    kb_name = kb_name or desc.get('name') or stats.get('kb_name') or ''
    embedding = embedding or desc.get('embedding') or stats.get('embedding') or ''
    if not kb_id:
        raise RkbError('缺 kbase id：重新跑 prepare_metaqa.py 或传 --kb-id')

    # 导入包 ``desc.id`` 是 ``graph_<16hex>``（表名形状）；知识库业务 id 是
    # 去掉前缀的 16 位十六进制，详情/删除/轮询都走后者。
    api_id = kb_id[6:] if kb_id.startswith('graph_') else kb_id
    client = client or GraphClient()
    existing = None
    try:
        existing = client.get_kb(api_id)
    except RkbError as error:
        if 'HTTP 404' not in str(error):
            raise

    # 同名库可能已经存在但 id 不同（导入接口按名字复用）：跟随真实 id，
    # 否则会对着一个永远不会出现的 id 轮询。
    same_name = client.find_kb(kb_name) if kb_name else None
    if same_name and same_name.get('id') and same_name['id'] != api_id:
        print(f'同名库已存在，改用实际 id {same_name["id"]}（请求 id {api_id}）')
        api_id = same_name['id']
        existing = client.get_kb(api_id)

    if existing and not force:
        status = existing.get('status')
        print(f'复用已有图谱库 {api_id}（status={status}）')
        if status != 5:
            existing = client.wait_ready(api_id, timeout=timeout)
        result = {'kb_id': api_id, 'table_name': existing.get('tableName'),
                  'status': existing.get('status'), 'reused': True,
                  'entities': entity_count, 'edges': edge_count,
                  'zip': str(zip_path)}
        (data_dir / 'imported.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8')
        return result

    if existing and force:
        print(f'--force：删除已有图谱库 {api_id}')
        client.delete_kb(api_id)

    print(f'导入 {zip_path} → kb={api_id} name={kb_name!r} embedding={embedding!r}')
    client.import_zip(zip_path)
    detail = client.wait_ready(api_id, timeout=timeout)
    table_name = detail.get('tableName') or f'graph_{api_id}'

    query = first_entity
    if query:
        result = client.retrieve_graph(table_name, query, embedding=embedding,
                                       seed_k=5, depth=1, limit=100)
        seeds = ((result.get('base_results') or [{}])[0] or {}).get('seed_entity_ids') or []
        if not seeds:
            raise RkbError(f'导入状态就绪，但检索不出种子（query={query!r}）')
        print(f'检索验收通过：query={query!r} seeds={len(seeds)}')

    result = {'kb_id': api_id, 'table_name': table_name,
              'status': detail.get('status'), 'reused': False,
              'entities': entity_count, 'edges': edge_count,
              'schema_edges': len(schema.get('edges') or []),
              'zip': str(zip_path)}
    (data_dir / 'imported.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=DEFAULT_DATA)
    parser.add_argument('--zip', type=Path)
    parser.add_argument('--kb-id', default='')
    parser.add_argument('--name', default='')
    parser.add_argument('--embedding', default='')
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--timeout', type=int, default=3600)
    args = parser.parse_args(argv)
    try:
        result = import_metaqa(
            args.data_dir, zip_path=args.zip, kb_id=args.kb_id,
            kb_name=args.name, embedding=args.embedding,
            force=args.force, timeout=args.timeout)
    except RkbError as error:
        print(f'FAIL {error}', file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
