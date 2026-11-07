"""``/chunk`` 那一族的 SQL。

三张表的分工（都在 ``kb_index`` 这个 schema 下，**除关系表外都按库动态建**）：

================================  ==========================================
``kb_index.<table>``              向量索引表：``id / text / node_id / embedding`` + 5 个展开列
``kb_index.<table>_chunk``        切片表（``VectorChunkPO``）：带 ``source``/``text``/``chunk_order``
``public.kb_node_relation`` 关系表：``id / kbase_id / directory_id / node_id``
================================  ==========================================

``content_expand`` 存的是 **chunkId**，真实补充内容在 chunk 表的 ``text``；
读的时候要按 chunkId 取正文，否则 ``supplement`` 会返回一串 uuid。
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from infrastructure.db.kb import connection
from shared.chunk_schema import node_columns
from shared.chunk_schema.vector import to_vector_literal
from infrastructure.db.ddl import table_exists
from infrastructure.db import identifiers
from infrastructure.db.identifiers import SCHEMA, validate_identifier

from infrastructure.db.rows import rows as _rows

RELATION_TABLE = 'public.kb_node_relation'

# ``metadata_`` 那个 JSON 列已展开成 5 个物理列（见 ``node_columns.py``）。
# 查询用这份列清单取回来，再由 ``_with_metadata`` 拼回 ``metadata`` dict ——
# **调用方看到的接口不变**（仍拿 ``row['metadata']``），改的只是存储形态。
_METADATA_SELECT = ', '.join(node_columns.EXPANDED_FIELDS)
#: 文档库 chunk 表没有 ``content_expand``（正文就在本行 ``text``）。
_CHUNK_METADATA_SELECT = ', '.join(
    name for name in node_columns.EXPANDED_FIELDS if name != 'content_expand')


def _with_metadata(rows: list[dict]) -> list[dict]:
    """给每行补一个 ``metadata`` dict（由展开列拼回）。

    只收**非 NULL** 的列 —— 与 JSON 时代"键不存在就不出现"的语义对齐；
    这样 ``to_search_doc`` 透给前端的键集与改造前逐键相同。
    """
    for row in rows:
        row['metadata'] = node_columns.metadata_from_row(row)
    return rows


# ----------------------------------------------------------------------
# 库/表名
# ----------------------------------------------------------------------


def vector_table_name(kbase: dict) -> str:
    """``建索引表名``：**先取 ``kb_kbase.table_name``**，空了才回退。

    文档库是 ``doc_<kbaseId>_vector``，图谱库是 ``graph_<kbaseId>``。
    回退分支只在 ``table_name`` 为空时才走到。
    """
    table = (kbase.get('table_name') or '').strip()
    if table:
        return table
    return identifiers.doc_vector_table(str(kbase['kbase_id']))


def chunk_table_name(kbase: dict) -> str:
    """文档库去掉 ``_vector`` 换 ``_chunk``。"""
    return identifiers.chunk_table_for(vector_table_name(kbase))


# ----------------------------------------------------------------------
# 向量索引表
# ----------------------------------------------------------------------


def index_from_sql(kbase: dict) -> tuple[str, str]:
    """向量索引查询的 ``FROM`` 子句与正文表达式。

    普通行 ``vector.text`` 为 NULL，正文取 ``chunk.text``；LLM 优化行把生成的问题
    写进 ``vector.text``，必须优先保留（否则正文会被切片正文覆盖），所以用
    ``COALESCE(idx.text, chunk.text)``。
    """
    table = vector_table_name(kbase)
    validate_identifier(table)
    chunk_table = chunk_table_name(kbase)
    validate_identifier(chunk_table)
    from_sql = (f'{SCHEMA}.{table} AS idx'
                f' LEFT JOIN {SCHEMA}.{chunk_table} AS chunk '
                'ON idx.content_expand = chunk.id')
    return from_sql, 'COALESCE(idx.text, chunk.text)'


def index_select_sql(kbase: dict) -> tuple[str, str]:
    """``(FROM 子句, SELECT 列)``；列名保持裸名，供 ``_with_metadata`` 拼回。"""
    from_sql, text_expr = index_from_sql(kbase)
    meta = ', '.join(f'idx.{name}' for name in node_columns.EXPANDED_FIELDS)
    return from_sql, f'idx.id, {text_expr} AS text, idx.node_id, {meta}'


def query_by_node_id(kbase: dict, node_id: str) -> Optional[dict]:
    """``queryByNodeId``：``node_id`` 命中一条即回（MP 的 ``selectOne`` 取第一行）。"""
    from_sql, select = index_select_sql(kbase)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'SELECT {select} FROM {from_sql} WHERE idx.node_id = %s LIMIT 1',
                (node_id,),
            )
            rows = _with_metadata(_rows(cursor))
    return rows[0] if rows else None


def query_page_by_keyword(kbase: dict, keyword: Optional[str], current_page: int,
                          page_size: int) -> tuple[list[dict], int]:
    """``queryPageByKeyword``：**按 id 倒序**分页；关键字用 ``LIKE``（不是 ILIKE）。

    ⚠️ 与 :func:`count_by_file` 的 ``ILIKE`` **不一致**，别顺手统一 ——
    统一了大小写敏感的那批就对不上。

    ``totalCount`` 用 ``Page.getTotal()``，也就是**同样的 where 条件**下的总条数。
    """
    from_sql, select = index_select_sql(kbase)
    _, text_expr = index_from_sql(kbase)
    where, params = '', []
    if keyword:
        where = f' WHERE {text_expr} LIKE %s'
        params.append(f'%{keyword}%')
    offset = max(current_page - 1, 0) * page_size
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f'SELECT count(*) FROM {from_sql}{where}', params)
            total = int(cursor.fetchone()[0])
            cursor.execute(
                f'SELECT {select} FROM {from_sql}{where} '
                'ORDER BY idx.id DESC LIMIT %s OFFSET %s',
                params + [page_size, offset],
            )
            rows = _with_metadata(_rows(cursor))
    return rows, total


def update_index(kbase: dict, index_id: int, text: str, metadata: dict,
                 embedding: list[float]) -> None:
    """``更新索引``：``text`` / ``embedding`` / 4 个展开列一起写。"""

    table = vector_table_name(kbase)
    validate_identifier(table)
    cols = node_columns.columns_from_metadata(metadata)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'UPDATE {SCHEMA}.{table} SET text = %s, embedding = %s::vector, '
                'source = %s, content_expand = %s, '
                'chunk_id = %s, type = %s WHERE id = %s',
                (text, to_vector_literal(embedding),
                 cols['source'], cols['content_expand'],
                 cols['chunk_id'], cols['type'], index_id),
            )


def insert_index(kbase: dict, rows: list[dict]) -> None:
    """``batchInsert``：``(text, metadata_, node_id, embedding)`` 四列。

    ``id`` 是 ``GENERATED BY DEFAULT AS IDENTITY``，不写。
    """

    if not rows:
        return
    table = vector_table_name(kbase)
    validate_identifier(table)

    sql = (f'INSERT INTO {SCHEMA}.{table} (text, node_id, embedding, '
           'source, content_expand, chunk_id, type) '
           'VALUES (%s, %s, %s::vector, %s, %s, %s, %s)')
    with connection() as conn:
        with conn.cursor() as cursor:
            params = []
            for row in rows:
                cols = node_columns.columns_from_metadata(row['metadata'])
                params.append((
                    row['text'], row['node_id'],
                    to_vector_literal(row['embedding']),
                    cols['source'], cols['content_expand'],
                    cols['chunk_id'], cols['type'],
                ))
            cursor.executemany(sql, params)


def delete_by_node_ids(kbase: dict, node_ids: Iterable[str]) -> None:
    """``deleteByNodeIds``：按 ``node_id`` 删向量索引行。"""
    ids = list(node_ids)
    if not ids:
        return
    table = vector_table_name(kbase)
    validate_identifier(table)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'DELETE FROM {SCHEMA}.{table} WHERE node_id = ANY(%s)', (ids,))


def delete_chunk_by_id(kbase: dict, chunk_id: str) -> int:
    """删除切片表的一行。返回删除行数。"""
    table = chunk_table_name(kbase)
    validate_identifier(table)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'DELETE FROM {SCHEMA}.{table} WHERE id = %s', (chunk_id,))
            return cursor.rowcount


def _file_join(kbase: dict) -> tuple[str, str]:
    """``/chunk/file`` 的 ``(JOIN 子句, 正文表达式)``。

    ``VEC_CHUNK.text`` 普通行为 NULL，正文在 ``CHUNK.text``；LLM 优化行优先。
    """
    table = vector_table_name(kbase)
    validate_identifier(table)
    chunk_table = chunk_table_name(kbase)
    validate_identifier(chunk_table)
    join = (f'INNER JOIN {SCHEMA}.{table} AS VEC_CHUNK '
            'ON REL.NODE_ID = VEC_CHUNK.NODE_ID'
            f' LEFT JOIN {SCHEMA}.{chunk_table} AS CHUNK '
            'ON VEC_CHUNK.content_expand = CHUNK.id')
    return join, 'COALESCE(VEC_CHUNK.text, CHUNK.text)'


def count_by_file(kbase: dict, file_id: Optional[str],
                  keyword: Optional[str]) -> int:
    """``getCount``：**关系表 inner join 向量表**，关键字用 ``ILIKE``。"""
    join, text_expr = _file_join(kbase)
    sql = (f'SELECT count(VEC_CHUNK.id) FROM {RELATION_TABLE} AS REL '
           f'{join} WHERE ')
    params: list[Any] = []
    if file_id:
        sql += 'REL.directory_id = %s'
        params.append(file_id)
    else:
        sql += '1=1'
    if keyword:
        # ⚠️ 字面 ``%`` 必须写成 ``%%``：psycopg2 把裸 ``%`` 当占位符语法解析，
        # 它数出的占位符比参数多 → **IndexError: list index out of range**。
        sql += " AND " + text_expr + " ILIKE '%%' || %s || '%%'"
        params.append(keyword)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return int(cursor.fetchone()[0])


def count_all(kbase: dict) -> int:
    """整库切片总数：与 ``GET /chunks`` 列表的 ``total`` 同口径。

    数的是**向量索引行数**（``query_page_by_keyword`` 里那条 count 的 from 子句），
    不是关系表行数 —— 两边必须一致，否则详情页的角标会和翻页总数打架。
    向量表还没建（新建未处理）返回 0：这不是错误，是「还没有切片」。
    """
    table = vector_table_name(kbase)
    if not table_exists(table):
        return 0
    from_sql, _ = index_from_sql(kbase)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f'SELECT count(*) FROM {from_sql}')
            return int(cursor.fetchone()[0])


def count_by_files(kbase: dict, file_ids: list[str]) -> dict[str, int]:
    """批量版 :func:`count_by_file`：一次 ``GROUP BY`` 返回 ``{directory_id: count}``。

    文档列表页每行要显示「N 个切片」；逐个文件各查一次是 N+1 条 1 行请求，
    这里用一条 SQL 把整页的计数取回来。只统计文件列表传进来的 id。
    """
    if not file_ids:
        return {}
    join, _ = _file_join(kbase)
    sql = (f'SELECT REL.directory_id, count(VEC_CHUNK.id) '
           f'FROM {RELATION_TABLE} AS REL {join} '
           'WHERE REL.directory_id = ANY(%s) '
           'GROUP BY REL.directory_id')
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, (list(file_ids),))
            return {str(file_id): int(count)
                    for file_id, count in cursor.fetchall()}


def list_by_file(kbase: dict, file_id: Optional[str], keyword: Optional[str],
                 current_page: int, page_size: int, chunk_id_asc: bool = False) -> list[dict]:
    """``getListByFileId``：``(chunk_id, directory_id, text, metadata)``，按 ``REL.id`` **倒序**。

    ⚠️ 别被 XML 里那句 ``<if test="chunkIdAsc == false">desc</if>`` 骗了 ——
    DAO 调用时传的就是 **``false``**，条件成立，实际是 ``ORDER BY REL.id desc``
    （实测：同一批切片在这里是「后加的在前」，与 ``/chunk`` 列表同向）。

    文档预览要看「原文顺序」，显式传 ``chunk_id_asc=True`` 走升序；
    默认值不变，切片管理页仍按倒序分页。
    """
    join, text_expr = _file_join(kbase)
    # ⚠️ 展开列必须**加前缀别名**：``REL.id AS chunk_id`` 与向量表的 ``chunk_id`` 列同名，
    #    不加前缀会互相覆盖（前者是 API 里的 chunkId，后者是切片序号，含义完全不同）。
    sql = (f'SELECT REL.id AS chunk_id, REL.directory_id AS directory_id, '
           f'{text_expr} AS text, '
           f'VEC_CHUNK.source AS meta_source, '
           f'VEC_CHUNK.content_expand AS meta_content_expand, '
           f'VEC_CHUNK.chunk_id AS meta_chunk_id, VEC_CHUNK.type AS meta_type '
           f'FROM {RELATION_TABLE} AS REL {join} WHERE ')
    params: list[Any] = []
    if file_id:
        sql += 'REL.directory_id = %s'
        params.append(file_id)
    else:
        sql += '1=1'
    if keyword:
        # ⚠️ 字面 ``%`` 必须写成 ``%%``：psycopg2 把裸 ``%`` 当占位符语法解析，
        # 它数出的占位符比参数多 → **IndexError: list index out of range**。
        sql += " AND " + text_expr + " ILIKE '%%' || %s || '%%'"
        params.append(keyword)
    sql += f" ORDER BY REL.id {'ASC' if chunk_id_asc else 'DESC'} LIMIT %s OFFSET %s"
    params.extend([page_size, max(current_page - 1, 0) * page_size])
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            rows = _rows(cursor)
    for row in rows:                       # 展开列是 meta_ 前缀的，单独拼回 metadata
        row['metadata'] = node_columns.metadata_from_row(row, prefix='meta_')
        for name in node_columns.EXPANDED_FIELDS:
            row.pop('meta_' + name, None)
    return rows


# ----------------------------------------------------------------------
# 切片表
# ----------------------------------------------------------------------


def query_by_chunk_ids(kbase: dict, chunk_ids: list[str]) -> list[dict]:
    """``queryByChunkIds``：按切片 id 取回正文与元数据（文档库活列）。"""
    if not chunk_ids:
        return []
    table = chunk_table_name(kbase)
    validate_identifier(table)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'SELECT id, kb_id, text, {_CHUNK_METADATA_SELECT}, '
                f'created_at, updated_at '
                f'FROM {SCHEMA}.{table} WHERE id = ANY(%s)',
                (chunk_ids,),
            )
            return _with_metadata(_rows(cursor))


def update_chunk_text(kbase: dict, chunk_id: str, text: str, metadata: dict) -> None:
    """``updateChunkMetadata``：只改 ``text`` 与元数据列；``updated_at`` 由触发器刷新。

    ⚠️ **不写 ``source`` 列**：chunk 表本来就有 ``source`` 列（文件名的权威位置），
    而原 JSON 时代的 ``metadata.source`` 只是它的副本（实测逐行相同）。这里若按
    ``columns_from_metadata`` 一并写，调用方传 ``{}`` 时就会把文件名清成 NULL。
    """
    table = chunk_table_name(kbase)
    validate_identifier(table)
    cols = node_columns.columns_from_metadata(metadata)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'UPDATE {SCHEMA}.{table} SET text = %s, '
                'chunk_id = %s, type = %s WHERE id = %s',
                (text, cols['chunk_id'], cols['type'], chunk_id),
            )


def insert_chunk(kbase: dict, chunk_id: str, kbase_id: str, source: Optional[str],
                 text: Optional[str]) -> None:
    """新增切片那一行的插入。

    展开成列之后**不写 metadata 那几列**（全为 NULL），语义等价。
    """
    table = chunk_table_name(kbase)
    validate_identifier(table)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'INSERT INTO {SCHEMA}.{table} (id, kb_id, source, text) '
                'VALUES (%s, %s, %s, %s) '
                'ON CONFLICT (id) DO NOTHING',
                (chunk_id, kbase_id, source, text),
            )


# ----------------------------------------------------------------------
# 关系表
# ----------------------------------------------------------------------


def select_relation_by_id(chunk_id: int, kbase_id: str) -> Optional[dict]:
    """``selectByIdAndKbaseIdExist``：按主键 + 库查关系行（找不到回 null）。

    ⚠️ 调用方拿它**直接用**（不判空）—— 找不到就是 NPE。
    """
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'SELECT id, kbase_id, directory_id, node_id FROM {RELATION_TABLE} '
                'WHERE id = %s AND kbase_id = %s LIMIT 1',
                (chunk_id, kbase_id),
            )
            rows = _rows(cursor)
    return rows[0] if rows else None


def select_relations_by_node_ids(node_ids: Iterable[str],
                                 kbase_id: Optional[str] = None) -> list[dict]:
    """``selectByNodeIds`` 的两个重载：带不带 ``kbase_id``。"""
    ids = list(node_ids)
    if not ids:
        return []
    sql = (f'SELECT id, kbase_id, directory_id, node_id FROM {RELATION_TABLE} '
           'WHERE node_id = ANY(%s)')
    params: list[Any] = [ids]
    if kbase_id:
        sql += ' AND kbase_id = %s'
        params.append(kbase_id)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return _rows(cursor)


def delete_relation(chunk_id: int) -> None:
    """``deleteById``（关系表的主键）。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f'DELETE FROM {RELATION_TABLE} WHERE id = %s', (chunk_id,))
