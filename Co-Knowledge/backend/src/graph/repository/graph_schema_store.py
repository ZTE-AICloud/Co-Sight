"""``graph_schema`` 表（知识图谱模板）。

**这张表有三条与其它表不一样的规矩，改动前务必看清**：

1. **物理删除**：全库统一硬删除，不再有 ``is_enabled``。
2. 时间列统一为 ``created_at`` / ``updated_at timestamptz``，
   ``created_by`` / ``updated_by`` 记录操作人；``updated_at`` 由触发器自动刷新。
3. ``schema_obj`` 是 ``jsonb`` 类型。**两条写入路径用了不同的序列化器**，
   差别只是「null 字段留不留」。
   转成 jsonb 后键序不再保留；从接口看仍是解析后的结构体，语义不变。
"""

from __future__ import annotations

import json
from typing import Any, Optional

from infrastructure.db.kb import connection

from infrastructure.db.rows import rows as _rows

# 列清单（声明顺序，不带 ``schema_obj`` 的两条查询另有列单）
SCHEMA_COLUMNS = ('schema_id', 'schema_obj', 'schema_name', 'schema_desc', 'created_at',
                  'updated_at', 'created_by', 'updated_by', 'status')
# ``getSchemaListByCreateUserAndTenant`` 的列清单（**不含 schema_obj**）
LIST_COLUMNS = tuple(column for column in SCHEMA_COLUMNS if column != 'schema_obj')


def _parse_schema_obj(value):
    """``PgJsonbTypeHandler`` 读回来是 ``Map``。已经是 dict 就原样给。"""
    if value is None or isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None


def _normalize(row: Optional[dict]) -> Optional[dict]:
    if row is None:
        return None
    if 'schema_obj' in row:
        row['schema_obj'] = _parse_schema_obj(row['schema_obj'])
    return row


def get_schema_by_id(schema_id: str) -> Optional[dict]:
    """``SchemaDao.getSchemaById`` / ``SchemaDao2.selectById``。

    注意前者是 MP 的 ``selectOne``（无 ORDER BY、多行会抛异常），后者是裸
    ``SELECT * FROM graph_schema WHERE schema_id = ?``。主键唯一，两者等价。
    """
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT %s FROM graph_schema WHERE schema_id = %%s'
                % ', '.join(SCHEMA_COLUMNS), (schema_id,))
            rows = _rows(cursor)
    return _normalize(rows[0]) if rows else None


def get_schema_by_name(schema_name: str) -> Optional[dict]:
    """按名称取一行：``WHERE schema_name = ? LIMIT 1``（**有 LIMIT**）。

    ``schema_name`` 上没有唯一约束，所以理论上可能有多行 —— 取第一行且顺序不定。
    """
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT * FROM graph_schema WHERE schema_name = %s LIMIT 1', (schema_name,))
            rows = _rows(cursor)
    return _normalize(rows[0]) if rows else None


def is_schema_exist(schema_id: Optional[str], schema_name: Optional[str]) -> bool:
    """``SchemaDao.isSchemaExist``：``WHERE (schema_id = ? OR schema_name = ?)``。

    **两个条件各自只在非空时才加**；两个都为空时不带 WHERE（但调用点不会这样传）。
    """
    where, params = [], []
    if schema_id:
        where.append('schema_id = %s')
        params.append(schema_id)
    if schema_name:
        where.append('schema_name = %s')
        params.append(schema_name)
    sql = 'SELECT COUNT(*) FROM graph_schema'
    if where:
        sql += ' WHERE (' + ' OR '.join(where) + ')'
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return int(cursor.fetchone()[0]) > 0


def list_by_user(emp_no: Optional[str]) -> list[dict]:
    """``getSchemaListByCreateUserAndTenant``。

    ``emp_no`` 非空时按创建人过滤（本栈是单租户，没有租户条件）。

    **无分页** —— 这个接口没有 page/size，别自作主张加 LIMIT。
    """
    where, params = [], []
    if emp_no:
        where.append('created_by = %s')
        params.append(emp_no)
    sql = 'SELECT %s FROM graph_schema' % ', '.join(LIST_COLUMNS)
    if where:
        sql += ' WHERE (' + ' AND '.join(where) + ')'
    sql += ' ORDER BY created_at DESC'
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return _rows(cursor)


def insert_schema(schema_id: Optional[str], schema_name: str, schema_desc: str,
                  schema_obj: Any, created_by: Optional[str], status: int = 0) -> None:
    """插入模板行：显式写业务列，审计列取默认值。

    ⚠️ ``schema_id`` 传 None 时 PG 会报 **NOT NULL 违例**（23502）。
    ``POST /create`` 不传 ``schema_id`` 时就是这么坏的：它在 ``graphSchemaObj`` 上生成了 UUID，
    却把 **DTO 的** ``schemaId``（可能是 null）绑进 INSERT。
    这个行为要保持 —— 见服务层的说明。
    """
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                'INSERT INTO graph_schema (schema_id, schema_obj, schema_name, schema_desc, '
                'created_by, status) '
                'VALUES (%s, %s::jsonb, %s, %s, %s, %s)',
                (schema_id, _dump_schema_obj(schema_obj), schema_name, schema_desc,
                 created_by, status))


def delete_schema_by_id(schema_id: str) -> int:
    """**物理删除**。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM graph_schema WHERE schema_id = %s', (schema_id,))
            return cursor.rowcount


def update_schema(schema_id: str, schema_name: str, schema_desc: str, schema_obj: Any,
                  updated_by: Optional[str]) -> int:
    """按 id 更新模板行。

    ``created_at`` / ``created_by`` / ``status`` 在上层 untouched；
    ``updated_at`` 由触发器自动刷新。``updated_by`` 为 None 时写入空串。
    """
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                'UPDATE graph_schema SET schema_obj = %s::jsonb, schema_name = %s, '
                'schema_desc = %s, updated_by = %s WHERE schema_id = %s',
                (_dump_schema_obj(schema_obj), schema_name, schema_desc,
                 updated_by or '', schema_id))
            return cursor.rowcount


def _dump_schema_obj(value: Any) -> Optional[str]:
    """序列化成 PG ``jsonb`` 列接受的文本。

    字段顺序 = 声明顺序，dict 保序，
    所以只要**按声明顺序构造**就能对上。``ensure_ascii=False`` 让中文原样落库。
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)
