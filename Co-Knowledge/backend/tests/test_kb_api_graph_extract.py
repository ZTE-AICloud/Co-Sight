"""抽图任务查询（``GET /graph/task/{id}`` / ``GET /graph/task/{id}``）的测试。

两个端点**逐字节相同**（同一份控制器代码），所以服务层只有一个函数 —— 这里也顺带钉住
「别把它实现成两套」。真实的双向对拍在 ``tools/verify/verify-graph-task-diff.py``。

跑法::

    python -m pytest tests/test_kb_api_graph_extract.py -q
"""


import pytest

# ----------------------------------------------------------------------
# 抽图任务查询（``GET /graph/task/{id}`` 与 ``GET /graph/task/{id}``）
# ----------------------------------------------------------------------


def test_task_id_blank_is_0004():
    from shared.errors.api import KbValidationError
    from graph.service import graph_extract_service as extract

    for bad in (None, '', '   '):
        with pytest.raises(KbValidationError) as caught:
            extract._validate_task_id(bad)
        assert caught.value.key == 'graph.extract.taskid.empty'
        assert caught.value.code == '0004'


def test_task_id_over_50_is_0004_with_length():
    """超长回 **0004** 且文案带当前长度 —— 与「不存在」是两条不同的键。"""
    from shared.errors.api import KbValidationError
    from graph.service import graph_extract_service as extract

    extract._validate_task_id('a' * 50)          # 恰好 50 合法
    with pytest.raises(KbValidationError) as caught:
        extract._validate_task_id('a' * 51)
    assert caught.value.key == 'graph.extract.taskid.length.exceed'
    assert caught.value.args == (51,)


def test_task_dates_use_jackson_format():
    """日期格式固定为 ``yyyy-MM-dd HH:mm:ss``；null 保持 null。"""
    from datetime import datetime
    from graph.service import graph_extract_service as extract

    assert extract._format_date(datetime(2026, 10, 12, 10, 0, 0)) == '2026-10-12 10:00:00'
    assert extract._format_date(None) is None


def test_task_status_constants_are_strings():
    """``status`` 列存的是**字符串**枚举，不是那个 int。"""
    from graph.repository import graph_extract_store as store

    assert (store.STATUS_INIT, store.STATUS_RUNNING, store.STATUS_SUCCESS,
            store.STATUS_FAIL) == ('INIT', 'RUNNING', 'SUCCESS', 'FAIL')


def test_graph_progress_writes_are_scoped_to_graph_kbases():
    """抽图进度/失败原因只写图谱库（``category = 10``）。

    文档库的库行状态恒为 0（文档进度记在 ``kb_directory`` 行上）。抽图状态一旦写进
    文档库，重新解析文档也不会复原 —— 库会一直停在「生成失败」。
    """
    from ingestion.service.operator import graph_extract_service as service

    assert 'category = 10' in service.UPDATE_STATUS_SQL
    assert 'category = 10' in service.UPDATE_FAIL_REASON_SQL


def test_extract_task_table_is_singular():
    """表是 ``graph_extract_task``（单数），与 ``graph_import_tasks``（复数）不是一套。"""
    from graph.repository import graph_extract_store as store

    assert store.TABLE == 'graph_extract_task'


def test_store_columns_exist_in_init_schema():
    """``store.COLUMNS`` 的每一列都必须出现在 init schema 的同名建表块里。

    回归：代码里的 ``start_time/finish_time`` 改成 ``started_at/finished_at`` 时，
    库表与 ``deploy/init/pg/00-schema.sql`` 必须同步。
    后果不是「慢」而是**任务行永远停在 INIT**：``update_task_status`` 第一次写
    ``started_at`` 就 UndefinedColumn，异常处理里写 ``finished_at`` 再炸一次，
    失败态也落不了库。前端只能看到「已创建」。
    """
    import re
    from pathlib import Path

    from graph.repository import graph_extract_store as store

    schema_sql = (Path(__file__).resolve().parents[2]
                  / 'deploy' / 'init' / 'pg' / '00-schema.sql')
    text = schema_sql.read_text(encoding='utf-8')
    block = re.search(
        r'CREATE TABLE (?:IF NOT EXISTS )?public\.graph_extract_task \((.*?)\n\);',
        text, re.S)
    assert block, 'graph_extract_task missing from the init schema snapshot'
    columns = set(re.findall(r'^\s*([a-z_][a-z0-9_]*)\s+\w', block.group(1), re.M))
    assert set(store.COLUMNS) <= columns, sorted(set(store.COLUMNS) - columns)
    # 这两列是本次回归的当事人：写死了才拦得住下次再顺手改名
    assert 'start_time' in store.COLUMNS and 'finish_time' in store.COLUMNS
