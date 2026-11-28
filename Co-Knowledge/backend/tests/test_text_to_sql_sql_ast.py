"""SQL AST 校验：结构白名单的回归用例。

重点覆盖两类历史缺陷：
* **误杀**——多列 ``GROUP BY`` / ``ORDER BY`` 曾被逗号连接规则错误拒绝；
* **绕过**——``query_to_xml('...')`` 之类把 SQL 塞进字符串字面量的写法。
"""

import pytest

from text_to_sql import sql_ast
from text_to_sql.errors import SqlGuardError

SNAPSHOT = {
    'tables': [
        {
            'id': 't1', 'schema': 'public', 'name': 'order_info',
            'columns': [
                {'id': 'c1', 'name': 'order_id'},
                {'id': 'c2', 'name': 'user_id'},
                {'id': 'c3', 'name': 'pay_amount'},
                {'id': 'c4', 'name': 'status'},
                {'id': 'c5', 'name': 'create_time'},
            ],
        },
        {
            'id': 't2', 'schema': 'public', 'name': 'user_info',
            'columns': [
                {'id': 'c6', 'name': 'user_id'},
                {'id': 'c7', 'name': 'user_name'},
                {'id': 'c8', 'name': 'city_id'},
            ],
        },
        {
            'id': 't3', 'schema': 'public', 'name': 'region_info',
            'columns': [
                {'id': 'c9', 'name': 'city_id'},
                {'id': 'c10', 'name': 'city_name'},
            ],
        },
    ],
}


def _accept(sql):
    assert sql_ast.validate(sql, SNAPSHOT) == sql


def _reject(sql, code):
    with pytest.raises(SqlGuardError) as error:
        sql_ast.validate(sql, SNAPSHOT)
    assert error.value.code == code, error.value.message


# ---------------------------------------------------------------------------
# 应当通过
# ---------------------------------------------------------------------------
def test_accepts_single_table_select():
    _accept('SELECT order_id FROM public.order_info')


def test_accepts_multi_column_group_by_and_order_by():
    """回归：旧正则把 FROM 之后的任意逗号当成逗号连接，误杀了多列聚合。"""
    _accept('SELECT status, user_id, count(*) FROM public.order_info '
            'GROUP BY status, user_id')
    _accept('SELECT user_id, pay_amount FROM public.order_info '
            'ORDER BY user_id, pay_amount')
    _accept('SELECT status, count(*) AS n FROM public.order_info '
            'GROUP BY status ORDER BY n DESC, status')


def test_accepts_two_hop_join_with_two_column_group_by():
    _accept('SELECT r.city_name, o.status, count(*) AS n '
            'FROM public.order_info o '
            'JOIN public.user_info u ON u.user_id = o.user_id '
            'JOIN public.region_info r ON r.city_id = u.city_id '
            'GROUP BY r.city_name, o.status')


def test_accepts_cte_and_subquery():
    _accept('WITH paid AS (SELECT * FROM public.order_info WHERE status = 2) '
            'SELECT count(*) FROM paid')
    _accept('SELECT count(*) FROM (SELECT * FROM public.order_info) s')


def test_accepts_in_list_and_window_function():
    _accept('SELECT count(*) FROM public.order_info WHERE status IN (1, 2)')
    _accept('SELECT user_id, row_number() OVER (PARTITION BY user_id, status '
            'ORDER BY create_time) FROM public.order_info')


def test_accepts_set_operation():
    _accept('SELECT order_id FROM public.order_info '
            'UNION SELECT user_id FROM public.user_info')


def test_accepts_quoted_identifiers():
    _accept('SELECT "order_id" FROM "public"."order_info"')


def test_accepts_aggregate_and_scalar_functions():
    _accept('SELECT round(avg(pay_amount), 2), date_trunc(\'day\', create_time) '
            'FROM public.order_info GROUP BY date_trunc(\'day\', create_time)')


def test_accepts_cte_column_reference():
    _accept('WITH t AS (SELECT order_id, pay_amount FROM public.order_info) '
            'SELECT order_id FROM t')


# ---------------------------------------------------------------------------
# 应当拒绝：语句形态
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('sql', [
    'DELETE FROM public.order_info',
    'UPDATE public.order_info SET status = 1',
    'INSERT INTO public.order_info (order_id) VALUES (1)',
    'DROP TABLE public.order_info',
    'CREATE TABLE x (a int)',
    'TRUNCATE public.order_info',
    'SELECT 1; DROP TABLE public.order_info',
    'WITH x AS (DELETE FROM public.order_info RETURNING *) SELECT * FROM x',
])
def test_rejects_writes_and_multiple_statements(sql):
    _reject(sql, 'SQL_UNSAFE')


def test_rejects_locking_read_and_select_into():
    _reject('SELECT * FROM public.order_info FOR UPDATE', 'SQL_UNSAFE')
    _reject('SELECT * FROM public.order_info FOR SHARE', 'SQL_UNSAFE')
    _reject('SELECT order_id INTO TEMP z FROM public.order_info', 'SQL_UNSAFE')


def test_rejects_syntax_error():
    _reject('SELECT FROM WHERE', 'SQL_SYNTAX')


# ---------------------------------------------------------------------------
# 应当拒绝：表
# ---------------------------------------------------------------------------
def test_rejects_unknown_table():
    _reject('SELECT * FROM public.secret', 'SQL_TABLE_NOT_ALLOWED')
    _reject('SELECT * FROM secret', 'SQL_TABLE_NOT_ALLOWED')


def test_rejects_comma_join():
    _reject('SELECT * FROM public.order_info, public.user_info', 'SQL_UNSAFE')


def test_rejects_system_catalog():
    _reject('SELECT * FROM pg_catalog.pg_class', 'SQL_TABLE_NOT_ALLOWED')
    _reject('SELECT * FROM information_schema.tables', 'SQL_TABLE_NOT_ALLOWED')


def test_rejects_function_in_from():
    _reject('SELECT count(*) FROM generate_series(1, 10)', 'SQL_UNSAFE')


# ---------------------------------------------------------------------------
# 应当拒绝：字段
# ---------------------------------------------------------------------------
def test_rejects_unknown_column():
    _reject('SELECT no_such_column FROM public.order_info',
            'SQL_COLUMN_NOT_ALLOWED')
    _reject('SELECT o.no_such_column FROM public.order_info o',
            'SQL_COLUMN_NOT_ALLOWED')


def test_rejects_unknown_column_in_where_and_group_by():
    _reject('SELECT count(*) FROM public.order_info WHERE nope = 1',
            'SQL_COLUMN_NOT_ALLOWED')
    _reject('SELECT count(*) FROM public.order_info GROUP BY nope',
            'SQL_COLUMN_NOT_ALLOWED')


def test_accepts_same_name_column_when_qualified():
    """同名字段靠限定名消歧：city_id 同时属于 user_info 与 region_info。"""
    _accept('SELECT u.city_id, r.city_id FROM public.user_info u '
            'JOIN public.region_info r ON r.city_id = u.city_id')


# ---------------------------------------------------------------------------
# 应当拒绝：函数
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('sql', [
    "SELECT query_to_xml('SELECT count(*) FROM pg_catalog.pg_class', true, false, '')",
    "SELECT set_config('search_path', 'pg_catalog', false)",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT pg_sleep(5)",
    "SELECT current_setting('search_path')",
    "SELECT dblink('host=x', 'select 1')",
    "SELECT lo_export(1, '/tmp/x')",
])
def test_rejects_dangerous_functions(sql):
    _reject(sql, 'SQL_FUNCTION_NOT_ALLOWED')


def test_rejects_schema_qualified_function():
    _reject('SELECT pg_catalog.count(*) FROM public.order_info',
            'SQL_FUNCTION_NOT_ALLOWED')


def test_string_literal_is_never_treated_as_sql():
    """字面量里的表名/函数名不参与判定：它只是 A_Const。"""
    _accept("SELECT order_id FROM public.order_info "
            "WHERE status = 2 AND 'DROP TABLE x; pg_read_file' = 'DROP TABLE x; pg_read_file'")


# ---------------------------------------------------------------------------
# 非可加指标：去重计数不能再求和
# ---------------------------------------------------------------------------
def test_rejects_sum_over_distinct_aggregate():
    _reject('SELECT sum(count(DISTINCT user_id)) FROM public.order_info',
            'SQL_AGGREGATION_NOT_ALLOWED')


def test_accepts_distinct_count_alone_and_plain_sum():
    _accept('SELECT count(DISTINCT user_id) FROM public.order_info')
    _accept('SELECT sum(pay_amount) FROM public.order_info')
    # 比值形态合法：人均金额 = 总额 / 去重人数
    _accept('SELECT sum(pay_amount) / count(DISTINCT user_id) FROM public.order_info')
