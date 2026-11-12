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
        'processDetailInfo',
    }
    assert vo_fields <= props, f'missing: {sorted(vo_fields - props)}'


def test_document_schema_covers_vo_fields():
    props = set(_schema('document.json')['properties'])
    vo_fields = {
        'id', 'kbId', 'title', 'parentId', 'parentPath', 'canSpread', 'type',
        'createdBy', 'createdDate', 'lastUpdatedBy', 'lastUpdatedDate',
        'fileSize', 'status', 'kType', 'errorMsg', 'childList', 'props',
        'fileFrom', 'failReason', 'idChain',
    }
    assert vo_fields <= props, f'missing: {sorted(vo_fields - props)}'


def test_external_agent_openapi_snapshot_present():
    snapshot = ROOT / 'docs' / 'external-api' / 'openapi' / 'agent-api.yaml'
    assert snapshot.exists(), f'{snapshot} 缺失；交付包无法导入 Dify/Coze'
    assert snapshot.read_text(encoding='utf-8').startswith('# 交付快照')
