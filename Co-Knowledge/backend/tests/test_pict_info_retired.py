"""``pict_info`` 图片能力已整体退役。

本测试锁定四件事，防止能力被「改名复活」或漏删建表通道：

1. 运行时源码不再出现 ``pict_info`` / ``kb_pict_info`` 字面量；
2. 切片展开列清单 ``EXPANDED_FIELDS`` 不含 ``pict_info``；
3. 动态表建表模板不再生成该列；
4. 静态 schema 快照与引导校验的表数已同步（含 ``agent_api_key_usage`` 调用计数表）。

本版本尚未发布，因此**不提供迁移脚本** —— 新装直接从快照得到新 schema。
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / 'backend' / 'src'
SCHEMA_SQL = REPO / 'deploy' / 'init' / 'pg' / '00-schema.sql'
BOOTSTRAP = REPO / 'tools' / 'verify' / 'verify-empty-bootstrap.sh'


def _source_files():
    return sorted(SRC.rglob('*.py'))


def test_runtime_source_has_no_pict_info_code_paths():
    """注释/历史说明可以提这个名字，但代码里不能再有引用。"""
    offenders = []
    for path in _source_files():
        text = path.read_text(encoding='utf-8')
        for lineno, line in enumerate(text.splitlines(), 1):
            if "'pict_info'" in line or '"pict_info"' in line:
                offenders.append(f'{path.relative_to(REPO)}:{lineno}')
        for snippet in ('INSERT INTO kb_pict_info', 'DELETE FROM kb_pict_info',
                        'FROM kb_pict_info', 'pict_info JSONB'):
            if snippet in text:
                offenders.append(f'{path.relative_to(REPO)}: {snippet}')
    assert offenders == [], f'仍有 pict_info 代码引用：{offenders}'


def test_expanded_fields_exclude_pict_info():
    from shared.chunk_schema import node_columns

    assert 'pict_info' not in node_columns.EXPANDED_FIELDS
    assert node_columns.EXPANDED_FIELDS == (
        'source', 'content_expand', 'chunk_id', 'type')


def test_dynamic_table_ddl_has_no_pict_info_column():
    from infrastructure.db import ddl

    assert 'pict_info' not in ddl._CREATE_VECTOR_TABLE
    assert 'pict_info' not in ddl._CREATE_CHUNK_TABLE


def test_chunk_ddl_keeps_source_index():
    from infrastructure.db import ddl

    for template in (ddl._CREATE_CHUNK_TABLE, ddl._CREATE_GRAPH_CHUNK_TABLE):
        assert '{table}_source_idx' in template


def test_schema_snapshot_drops_table_and_updates_count():
    text = SCHEMA_SQL.read_text(encoding='utf-8')

    assert 'kb_pict_info' not in text
    assert '23 张业务表' not in text
    assert '22 张业务表' in text
    assert len([
        line for line in text.splitlines() if line.startswith('CREATE TABLE ')
    ]) == 22


def test_unreleased_retirement_ships_without_migration():
    """新装即新 schema，不为存量数据背迁移脚本。"""
    assert not (REPO / 'tools' / 'migrate').exists()


def test_bootstrap_expectation_matches_new_table_count():
    text = BOOTSTRAP.read_text(encoding='utf-8')
    assert '== "22"' in text
    assert 'public=22' in text
