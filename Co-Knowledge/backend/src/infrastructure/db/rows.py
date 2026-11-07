"""接口层共享工具：把 DB-API 游标结果转换成 dict 列表。

psycopg2 裸游标的 ``fetchall()`` 返回元组；接口层各 store 需要按列名取值。
这里只做一件事：按 ``cursor.description`` 配列名，避免各文件重复实现。
"""


def rows(cursor) -> list[dict]:
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]
