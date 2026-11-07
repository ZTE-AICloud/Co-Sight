"""``PgFlowStore`` 自建表兜底的单测。

``deploy/init/pg`` 不存在，``flow_*`` 三张表不能假设环境里已经存在。
这里钉两件事：

1. ``_ensure_schema`` 把 ``FLOW_SCHEMA_STATEMENTS`` 全部执行一次并立即提交；
2. 每进程只建一次（第二次调用不再执行 DDL）。
"""

import workflow.repository_pg as store_pg


class _Cursor:
    def __init__(self, executed):
        self._executed = executed

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql, params=None):
        self._executed.append(sql)


class _Conn:
    def __init__(self, executed):
        self._executed = executed
        self.commits = 0

    def cursor(self):
        return _Cursor(self._executed)

    def commit(self):
        self.commits += 1


def test_ensure_schema_executes_all_statements_and_commits(monkeypatch):
    # Arrange
    monkeypatch.setattr(store_pg, '_schema_ready', False)
    executed = []
    conn = _Conn(executed)
    store = store_pg.PgFlowStore()

    # Act
    store._ensure_schema(conn)

    # Assert
    assert executed == list(store_pg.FLOW_SCHEMA_STATEMENTS)
    assert conn.commits == 1


def test_like_pattern_escapes_wildcards():
    """列表搜索把 ``%`` / ``_`` 当字面量：搜 ``wf_1`` 不能把 ``wf21`` 带出来。"""
    assert store_pg._like_pattern('wf_1') == '%wf\\_1%'
    assert store_pg._like_pattern('50%') == '%50\\%%'
    assert store_pg._like_pattern('a\\b') == '%a\\\\b%'


def test_ensure_schema_is_idempotent_per_process(monkeypatch):
    # Arrange
    monkeypatch.setattr(store_pg, '_schema_ready', False)
    executed = []
    conn = _Conn(executed)
    store = store_pg.PgFlowStore()
    store._ensure_schema(conn)

    # Act
    store._ensure_schema(conn)

    # Assert：第二次一条 DDL 都不该再跑
    assert executed == list(store_pg.FLOW_SCHEMA_STATEMENTS)
    assert conn.commits == 1
