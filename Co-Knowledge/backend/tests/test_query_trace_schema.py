"""`t_query_trace` 的 DDL 快照/迁移注册/清理阈值一致性。"""
from __future__ import annotations

import re
from pathlib import Path

from chat import schema

REPO = Path(__file__).resolve().parents[2]
SCHEMA_SQL = REPO / 'deploy' / 'init' / 'pg' / '00-schema.sql'
BOOTSTRAP = REPO / 'tools' / 'verify' / 'verify-empty-bootstrap.sh'


def test_schema_constants_are_stable():
    assert schema.TABLE_NAME == 'chat_query_trace'
    assert schema.STATUS_VALUES == ('ok', 'error', 'client_disconnect')
    assert schema.COLUMN_NAMES[0] == 'trace_id'
    assert schema.COLUMN_NAMES[-1] == 'top_score'
    assert 'created_at' not in schema.COLUMN_NAMES
    assert len(schema.CREATE_INDEX_STATEMENTS) == len(schema.INDEX_NAMES) == 5


def test_sql_snapshot_mirrors_the_table_and_indexes():
    text = SCHEMA_SQL.read_text(encoding='utf-8')
    assert re.search(r'CREATE TABLE (?:IF NOT EXISTS )?public\.chat_query_trace', text)
    for index_name in schema.INDEX_NAMES:
        assert index_name in text
    for column in schema.COLUMN_NAMES:
        assert re.search(rf'\b{column}\b', text), column


def test_snapshot_table_count_is_22():
    text = SCHEMA_SQL.read_text(encoding='utf-8')
    tables = re.findall(r'^CREATE TABLE (?:IF NOT EXISTS )?public\.', text, re.MULTILINE)
    assert len(tables) == 22
    assert '22 张业务表' in text


def test_bootstrap_expects_22_tables():
    bootstrap = BOOTSTRAP.read_text(encoding='utf-8')
    assert '== "22"' in bootstrap
    assert '!= 22' in bootstrap
    # pg_stat_statements 会在 public 建视图；必须只数 BASE TABLE
    assert "table_type='BASE TABLE'" in bootstrap
