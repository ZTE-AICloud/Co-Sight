"""``PgModelStore`` 的**行映射**守卫 —— 一个单测替身天然掩盖的缺陷类。

内存 store 的 ``list_records()`` 直接返回 :class:`ModelRecord` 对象，于是所有用例
都绕过「数据库的一行怎么变成 ModelRecord」这一步。首次真部署时那里就炸了：

    TypeError: tuple indices must be integers or slices, not str

（psycopg2 的裸游标 ``fetchall()`` 给的是**元组**，而映射代码按列名取字段。）
**单测全绿、真机必炸** —— 所以这里用假游标把那条路径单独压一遍。

不连库：``_connect`` 换成一个返回假连接的桩，游标只实现 ``execute`` / ``fetchall`` /
``fetchone`` / ``description`` —— 正好是 psycopg2 侧被用到的全部接口。

跑法（服务目录下）::

    python -m pytest tests/test_model_repository_pg_mapping.py -q
"""



from model import crypto  # noqa: E402
from model.repository_pg import (  # noqa: E402
    _COLUMNS,
    PgModelStore,
    _rows,
    _update_params,
)

def _column_names_from_select(columns_sql: str) -> list:
    """从 SELECT 列表里取**别名**（= 游标 description 会给的名字）。

    不能按逗号裸切：``to_char(create_time, 'YYYY-MM-DD HH24:MI:SS') AS create_time``
    内部就有逗号 —— 真按逗号切会把 `'YYYY-MM-DD HH24:MI:SS') AS create_time` 当成一列。
    这里按括号深度切，再取 ``AS`` 后面的名字。
    """
    names, depth, current = [], 0, ''
    for char in columns_sql:
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        if char == ',' and depth == 0:
            names.append(current)
            current = ''
        else:
            current += char
    names.append(current)

    resolved = []
    for chunk in names:
        chunk = ' '.join(chunk.split())
        if not chunk:
            continue
        resolved.append(chunk.split(' AS ')[-1].strip() if ' AS ' in chunk else chunk)
    return resolved


#: ``_COLUMNS`` 里列出的列名，按同样顺序 —— 假游标的 description 就用它
COLUMN_NAMES = _column_names_from_select(_COLUMNS)


def _row_values(overrides=None):
    """一行数据（与 COLUMN_NAMES 同序）。"""
    base = {
        'model_id': 'id-1', 'model_kind': 'llm', 'model_name': 'deepseek-chat',
        'display_name': 'DeepSeek Chat', 'api_model': '', 'base_url': 'http://gw/v1',
        'api_key': crypto.encrypt('sk-secret'), 'chat_path': '', 'embeddings_path': '', 'models_path': '/models',
        'rerank_path': '', 'dimension': None, 'max_tokens': 8192, 'temperature': 0.01,
        'timeout': 180, 'is_reasoning': True,
        'thinking_mode': 'preset', 'thinking_preset': 'qwen-vllm',
        'thinking_payload': {'chat_template_kwargs': {'enable_thinking': False}},
        'is_default': True, 'enabled': True,
        'source': 'env', 'remark': '', 'created_by': 'admin',
        'created_at': '2026-10-15 13:00:00', 'updated_at': '2026-10-15 13:00:00',
    }
    base.update(overrides or {})
    return base


def _to_tuple(row: dict, columns: list) -> tuple:
    """用例里写的是 dict，但游标必须按列序吐**元组**。

    ⚠️ 这一步不是多余的：替身要是直接回 dict，``dict(zip(columns, row))`` 会拿列名去配
    **字典的键**（都是字符串），于是 ``temperature`` 变成一个字符串再被 ``float()`` 炸掉 ——
    测试会指出一个假的问题。替身必须与真 psycopg2 的返回类型一致，否则测的是替身。
    """
    return tuple(row.get(name) for name in columns)


class _FakeCursor:
    """只实现被用到的四个接口；**返回元组**，与真 psycopg2 一致。"""

    def __init__(self, rows, columns, writes):
        self._rows = [_to_tuple(row, columns) for row in rows]
        self._columns = columns
        self._writes = writes
        self.description = [(name,) for name in columns]

    def execute(self, sql, params=()):
        self._writes.append((sql, params))

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


def _store(rows=None, overrides=None, columns=None):
    writes = []
    cursor = _FakeCursor(rows if rows is not None else [_row_values(overrides)],
                         columns if columns is not None else COLUMN_NAMES, writes)
    store = PgModelStore()
    store._connect = lambda: _FakeConn(cursor)
    store._ensure_schema = lambda conn: None       # 建表不在本用例范围
    # 读路径的明文修复会额外发 SQL；本组用例只钉行映射。
    store._maybe_encrypt_plaintext_keys = lambda: None
    return store, writes


# ---------------------------------------------------------------------------
# 行 → ModelRecord
# ---------------------------------------------------------------------------
def test_rows_helper_turns_tuples_into_dicts():
    """这条就是当初漏掉的那一步。"""
    class _Cursor:
        description = [('a',), ('b',)]
        def fetchall(self):
            return [(1, 2), (3, 4)]

    assert _rows(_Cursor()) == [{'a': 1, 'b': 2}, {'a': 3, 'b': 4}]


def test_list_records_maps_every_column():
    store, _ = _store()
    record = store.list_records('llm')[0]

    assert record.model_id == 'id-1'
    assert record.model_kind == 'llm'
    assert record.model_name == 'deepseek-chat'
    assert record.display_name == 'DeepSeek Chat'
    assert record.base_url == 'http://gw/v1'
    assert record.api_key == 'sk-secret'
    assert record.models_path == '/models'
    assert record.max_tokens == 8192
    assert record.temperature == 0.01
    assert record.timeout == 180
    assert record.is_reasoning is True
    assert record.thinking_mode == 'preset'
    assert record.thinking_preset == 'qwen-vllm'
    assert record.thinking_payload == {'chat_template_kwargs': {'enable_thinking': False}}
    assert record.is_default is True
    assert record.enabled is True
    assert record.source == 'env'
    assert record.created_at == '2026-10-15 13:00:00'


def test_nullable_columns_become_none_or_empty():
    store, _ = _store(overrides={
        'display_name': None, 'api_model': None, 'api_key': None, 'chat_path': None,
        'embeddings_path': None, 'models_path': None, 'rerank_path': None,
        'dimension': None, 'max_tokens': None, 'temperature': None, 'timeout': None,
        'remark': None, 'created_by': None})
    record = store.list_records()[0]

    assert record.display_name == '' and record.api_model == '' and record.api_key == ''
    assert record.dimension is None and record.max_tokens is None
    assert record.temperature is None and record.timeout is None
    assert record.created_by == ''
    # 空覆盖值仍然走标准默认路径（不是「路径为空」）
    assert record.path_for('chat') == '/chat/completions'


def test_get_record_returns_none_on_empty_result():
    store, _ = _store(rows=[])
    assert store.get_record('nope') is None


def test_list_records_commits_and_closes():
    """提交语义：不 commit 的写入会被 psycopg2 的隐式回滚吃掉（本仓踩过）。"""
    writes = []
    cursor = _FakeCursor([_row_values()], COLUMN_NAMES, writes)
    conn = _FakeConn(cursor)
    store = PgModelStore()
    store._connect = lambda: conn
    store._ensure_schema = lambda c: None
    store._maybe_encrypt_plaintext_keys = lambda: None

    store.list_records()
    assert conn.commits == 1


# ---------------------------------------------------------------------------
# 写路径的参数顺序
# ---------------------------------------------------------------------------
def test_update_params_do_not_carry_source_or_creator():
    """改一行不该把它变成「用户自己登记的」（source/creator 是审计字段）。

    ``_UPDATE_SQL`` 的占位符个数与 ``_update_params`` 必须一致 —— 少一个就是
    psycopg2 的 "not enough arguments"（真机才炸的那类）。
    """
    store, _ = _store()
    record = store.list_records()[0]
    params = _update_params(record)

    assert record.source not in params, 'source 不在 UPDATE 的参数里'
    # 写路径落库的是密文；明文绝不能出现在参数里。
    assert 'sk-secret' not in params
    assert any(str(value).startswith(crypto.PREFIX) for value in params)
    assert params[-1] == record.model_id, '最后一param 是 WHERE 条件'


def test_number_of_placeholders_matches_update_params():
    from model.repository_pg import _UPDATE_SQL
    store, _ = _store()
    record = store.list_records()[0]
    assert _UPDATE_SQL.count('%s') == len(_update_params(record))


def test_number_of_placeholders_matches_insert_params():
    from model.repository_pg import _INSERT_SQL, _insert_params
    store, _ = _store()
    record = store.list_records()[0]
    assert _INSERT_SQL.count('%s') == len(_insert_params(record))


def test_select_columns_match_every_persisted_record_field():
    """忘把新字段加进 ``_COLUMNS`` 时，占位符数量测试仍然是绿的。

    这条用 dataclass 字段做**完整集合**对账（``origin`` 是非持久化字段，排除），
    新加持久化字段而漏改 SQL 会在这里红。
    """
    from dataclasses import fields

    from model.models import ModelRecord

    persisted = {field.name for field in fields(ModelRecord)} - {'origin'}
    assert set(COLUMN_NAMES) == persisted


def test_create_table_includes_the_thinking_columns():
    from model.repository_pg import SCHEMA_STATEMENTS

    joined = ' '.join(SCHEMA_STATEMENTS).lower()
    assert 'create table if not exists model_registry' in joined
    for column in ('thinking_mode', 'thinking_preset', 'thinking_payload'):
        assert column in joined
    assert 'thinking_disabled' not in joined


def test_jsonb_payload_is_passed_as_json_text():
    """psycopg2 不能直接适配 dict；写路径必须给 ``%s::jsonb`` 文本。"""
    from model.repository_pg import _insert_params, _update_params

    store, _ = _store()
    record = store.list_records()[0]

    for params in (_insert_params(record), _update_params(record)):
        assert any(isinstance(value, str) and 'enable_thinking' in value
                   for value in params), params
