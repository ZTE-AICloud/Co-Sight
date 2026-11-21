"""契约 schema 与 OpenAPI / 实际 VO 的一致性回归。

这些断言只读 ``contracts/``，不依赖运行时应用；用来阻止手写 JSON Schema
再次落后于 FastAPI 契约或 VO 字段。
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / 'contracts'


def _schema(name: str) -> dict:
    return json.loads((CONTRACTS / 'schemas' / name).read_text(encoding='utf-8'))


def _rkb_openapi() -> dict:
    text = (CONTRACTS / 'openapi' / 'rkb-api.yaml').read_text(encoding='utf-8')
    return yaml.safe_load(text.split('\n', 1)[1])


def test_search_schema_matches_retrieval_request():
    search = _schema('search.json')['$defs']['SearchRequest']
    retrieval = _rkb_openapi()['components']['schemas']['RetrievalRequest']

    assert set(search['properties']) == set(retrieval['properties'])
    assert set(search['required']) == set(retrieval['required']) == {'question', 'bases'}

    search_base = search['properties']['bases']['items']
    retrieval_base = retrieval['properties']['bases']['items']
    assert set(search_base['properties']) == set(retrieval_base['properties'])
    assert set(search_base['required']) == set(retrieval_base['required']) == {
        'baseList',
        'priority',
    }
    assert {'top_k', 'score_threshold'} <= set(search_base['properties'])


def test_knowledge_base_schema_covers_vo_fields():
    props = set(_schema('knowledge-base.json')['properties'])
    vo_fields = {
        'id', 'pkId', 'name', 'headIcon', 'type', 'description', 'props',
        'esIndexName', 'embeddingModel', 'currentFileCount', 'fileCountLimit',
        'createdBy', 'createdDate', 'lastUpdatedBy', 'lastUpdatedDate',
        'fullName', 'fullNameEn', 'tableName', 'action', 'operatorId',
        'failReason', 'status', 'schemaName', 'schemaObj', 'process',
        'processDetailInfo', 'chunkCount',
    }
    assert vo_fields <= props, f'missing: {sorted(vo_fields - props)}'
    assert _schema('knowledge-base.json')['properties']['processDetailInfo']['type'] == [
        'string', 'null',
    ], 'processDetailInfo is produced by _localized_text/_localized_string_value (str)'


def _base_vo_keys(service: str) -> set[str]:
    """Return the literal keys of ``_base_vo`` in a backend service module.

    Reading the source instead of hand-copying the schema is the point: the
    previous list was copied from ``document.json``, so it happily asserted a
    ``kbId`` key the backend never emits (PR #75 review).
    """
    import ast

    source = ROOT / 'backend' / 'src' / 'knowledge_base' / 'service' / service
    tree = ast.parse(source.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == '_base_vo':
            for child in ast.walk(node):
                if isinstance(child, ast.Return) and isinstance(child.value, ast.Dict):
                    return {
                        key.value for key in child.value.keys
                        if isinstance(key, ast.Constant) and isinstance(key.value, str)
                    }
    raise AssertionError(f'_base_vo dict literal not found in {source}')


def test_document_schema_covers_vo_fields():
    props = set(_schema('document.json')['properties'])
    vo_fields = _base_vo_keys('directory_service.py') | {'chunkCount'}
    assert vo_fields <= props, f'missing: {sorted(vo_fields - props)}'
    # The backend emits ``kbaseId``; a ``kbId`` property would both miss the
    # required key and be rejected by ``additionalProperties: false``.
    assert 'kbaseId' in props and 'kbId' not in props
    schema = _schema('document.json')
    assert 'kbaseId' in schema['required']


def test_document_vo_validates_against_schema():
    import jsonschema

    schema = _schema('document.json')
    instance = {key: None for key in _base_vo_keys('directory_service.py')}
    instance.update({'id': 'f-1', 'kbaseId': 'kb-1', 'title': 'a.md', 'type': 'file',
                     'createdDate': '2026-10-05 04:49:42'})
    jsonschema.validate(instance, schema)


def test_timestamp_pattern_matches_backend_formatter():
    import ast
    import datetime

    import jsonschema

    source = ROOT / 'backend' / 'src' / 'knowledge_base' / 'service' / 'directory_service.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    fmt = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == '_DATE_FORMAT' for t in node.targets
        ):
            fmt = ast.literal_eval(node.value)
    assert fmt, '_DATE_FORMAT not found'
    rendered = datetime.datetime(2026, 10, 5, 4, 49, 42).strftime(fmt)
    for name in ('document.json', 'knowledge-base.json'):
        prop = _schema(name)['properties']['createdDate']
        assert 'format' not in prop, f'{name} must not claim RFC 3339 date-time'
        jsonschema.validate(rendered, {'type': 'string', 'pattern': prop['pattern']})


def test_external_agent_openapi_snapshot_present():
    snapshot = ROOT / 'docs' / 'external-api' / 'openapi' / 'agent-api.yaml'
    assert snapshot.exists(), f'{snapshot} 缺失；交付包无法导入 Dify/Coze'
    assert snapshot.read_text(encoding='utf-8').startswith('# 交付快照')
