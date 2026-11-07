"""空卷启动资产的形状测试。

这些不是逻辑测试，而是防止三件事再发生：

1. 默认 compose 忘了挂 ``deploy/init/pg``；
2. schema 快照丢了核心表或 ``kb_index`` schema；
3. E2E 又单独维护一份 schema（两套快照漂移）。

跑法::

    python -m pytest tests/test_bootstrap_assets.py -q
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCHEMA = REPO / 'deploy' / 'init' / 'pg' / '00-schema.sql'
COMPOSE = REPO / 'deploy' / 'docker-compose.yml'
E2E_COMPOSE = REPO / 'deploy' / 'docker-compose.e2e.yml'


def test_schema_snapshot_exists_and_has_core_objects():
    text = SCHEMA.read_text(encoding='utf-8')
    assert 'CREATE SCHEMA IF NOT EXISTS kb_index' in text
    for table in ('kb_kbase', 'kb_directory', 'kb_node_relation', 'operator',
                  'graph_schema', 'graph_registry'):
        assert f'CREATE TABLE public.{table}' in text
    assert 'kb_kbase_kbase_id_uidx' in text
    assert 'kb_node_relation_kbase_node_uidx' in text
    assert 'CREATE TABLE public.chat_query_trace' in text
    assert 'idx_chat_query_trace_created' in text
    assert 'CREATE TABLE public.agent_api_key_usage' in text
    assert 'idx_agent_api_key_usage_usage_date' in text


def test_default_compose_mounts_init_pg():
    text = COMPOSE.read_text(encoding='utf-8')
    assert './init/pg:/docker-entrypoint-initdb.d:ro' in text


def test_e2e_compose_no_longer_owns_a_schema_copy():
    text = E2E_COMPOSE.read_text(encoding='utf-8')
    assert 'e2e/fixtures/db/schema.sql' not in text
    assert 'docker-entrypoint-initdb.d' not in text
