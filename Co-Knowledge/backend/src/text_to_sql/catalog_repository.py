"""关联 / 枚举 / 指标的 PostgreSQL 实现。

所有写操作都在一个事务里：先锁 datasource 行，再改行、改依赖、递增
``config_revision``。依赖表没有 ON DELETE CASCADE，删除顺序由本模块保证。
"""

from __future__ import annotations

import psycopg2
import psycopg2.extras

from text_to_sql.db import transaction as _transaction
from text_to_sql.errors import Text2SqlConflict, Text2SqlNotFound

_TS = "'YYYY-MM-DD HH24:MI:SS'"

_SELECT_RELATION = f"""
SELECT r.id, r.datasource_id, r.source_table_id, r.target_table_id,
       r.relation_name, r.relation_type, r.cardinality, r.description,
       r.enabled, r.verified, r.verified_by,
       to_char(r.verified_at, {_TS}) AS verified_at,
       st.schema_name || '.' || st.table_name AS source_table,
       tt.schema_name || '.' || tt.table_name AS target_table,
       to_char(r.created_at, {_TS}) AS created_at,
       to_char(r.updated_at, {_TS}) AS updated_at
FROM text2sql.t2s_relation r
JOIN text2sql.t2s_table st ON st.id = r.source_table_id
JOIN text2sql.t2s_table tt ON tt.id = r.target_table_id
WHERE r.datasource_id = %s
"""

_SELECT_VALUE = f"""
SELECT v.id, v.datasource_id, v.column_id, v.raw_value, v.value_type,
       v.business_name, v.aliases, v.description, v.source_type, v.enabled,
       c.column_name, t.schema_name || '.' || t.table_name AS table_name,
       to_char(v.created_at, {_TS}) AS created_at,
       to_char(v.updated_at, {_TS}) AS updated_at
FROM text2sql.t2s_value v
JOIN text2sql.t2s_column c ON c.id = v.column_id
JOIN text2sql.t2s_table t ON t.id = c.table_id
WHERE v.datasource_id = %s
"""

_SELECT_METRIC = f"""
SELECT m.id, m.datasource_id, m.base_table_id, m.metric_key, m.business_name,
       m.business_description, m.aliases, m.expression_sql, m.filter_definition,
       m.time_column_id, m.unit, m.business_timezone, m.aggregation_behavior,
       m.attribution_description, m.status, m.verified_by,
       to_char(m.verified_at, {_TS}) AS verified_at,
       t.schema_name || '.' || t.table_name AS base_table,
       tc.column_name AS time_column,
       to_char(m.created_at, {_TS}) AS created_at,
       to_char(m.updated_at, {_TS}) AS updated_at
FROM text2sql.t2s_metric m
JOIN text2sql.t2s_table t ON t.id = m.base_table_id
LEFT JOIN text2sql.t2s_column tc ON tc.id = m.time_column_id
WHERE m.datasource_id = %s
"""


def _lock_datasource(cursor, datasource_id: str) -> bool:
    cursor.execute(
        'SELECT id FROM text2sql.t2s_datasource '
        'WHERE id = %s AND deleted_at IS NULL FOR UPDATE', (datasource_id,))
    return cursor.fetchone() is not None


def _bump_revision(cursor, datasource_id: str) -> None:
    cursor.execute(
        'UPDATE text2sql.t2s_datasource '
        'SET config_revision = config_revision + 1 WHERE id = %s',
        (datasource_id,))


def _table_belongs(cursor, datasource_id: str, table_id: str) -> bool:
    cursor.execute(
        'SELECT 1 FROM text2sql.t2s_table '
        'WHERE id = %s AND datasource_id = %s AND missing_since IS NULL',
        (table_id, datasource_id))
    return cursor.fetchone() is not None


def _column_belongs(cursor, datasource_id: str, column_id: str,
                    table_id: str | None = None) -> bool:
    if table_id is None:
        cursor.execute(
            'SELECT 1 FROM text2sql.t2s_column '
            'WHERE id = %s AND datasource_id = %s AND missing_since IS NULL',
            (column_id, datasource_id))
    else:
        cursor.execute(
            'SELECT 1 FROM text2sql.t2s_column '
            'WHERE id = %s AND datasource_id = %s AND table_id = %s '
            'AND missing_since IS NULL',
            (column_id, datasource_id, table_id))
    return cursor.fetchone() is not None


# ---------------------------------------------------------------------------
# 关联
# ---------------------------------------------------------------------------
def list_relations(datasource_id: str) -> list[dict]:
    with _transaction() as cursor:
        cursor.execute(_SELECT_RELATION + ' ORDER BY st.schema_name, st.table_name, r.relation_name',
                       (datasource_id,))
        relations = [dict(item) for item in cursor.fetchall()]
        cursor.execute(
            """
            SELECT rc.relation_id, rc.ordinal_position,
                   sc.id AS source_column_id, sc.column_name AS source_column_name,
                   tc.id AS target_column_id, tc.column_name AS target_column_name
              FROM text2sql.t2s_relation_column rc
              JOIN text2sql.t2s_column sc ON sc.id = rc.source_column_id
              JOIN text2sql.t2s_column tc ON tc.id = rc.target_column_id
             WHERE rc.datasource_id = %s
             ORDER BY rc.relation_id, rc.ordinal_position
            """, (datasource_id,))
        pairs: dict[str, list[dict]] = {}
        for item in cursor.fetchall():
            pairs.setdefault(str(item['relation_id']), []).append(dict(item))
    for relation in relations:
        relation['column_pairs'] = pairs.get(str(relation['id']), [])
    return relations


def get_relation(datasource_id: str, relation_id: str) -> dict | None:
    for relation in list_relations(datasource_id):
        if str(relation['id']) == str(relation_id):
            return relation
    return None


def create_relation(datasource_id: str, fields: dict) -> str:
    with _transaction() as cursor:
        if not _lock_datasource(cursor, datasource_id):
            raise Text2SqlNotFound('数据源不存在或已删除')
        if not _table_belongs(cursor, datasource_id, fields['source_table_id']):
            raise Text2SqlNotFound('源数据表不存在')
        if not _table_belongs(cursor, datasource_id, fields['target_table_id']):
            raise Text2SqlNotFound('目标数据表不存在')
        for source_column, target_column in fields['column_pairs']:
            if not _column_belongs(cursor, datasource_id, source_column,
                                   fields['source_table_id']):
                raise Text2SqlNotFound('关联列不属于源数据表')
            if not _column_belongs(cursor, datasource_id, target_column,
                                   fields['target_table_id']):
                raise Text2SqlNotFound('关联列不属于目标数据表')
        try:
            cursor.execute(
                """
                INSERT INTO text2sql.t2s_relation
                    (datasource_id, source_table_id, target_table_id,
                     relation_name, relation_type, cardinality, description, enabled)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (datasource_id, fields['source_table_id'], fields['target_table_id'],
                 fields['relation_name'], fields.get('relation_type') or 'MANUAL',
                 fields['cardinality'],
                 fields.get('description') or '', fields.get('enabled', True)))
        except psycopg2.errors.UniqueViolation as error:
            raise Text2SqlConflict('该源表下已存在同名关联') from error
        relation_id = cursor.fetchone()['id']
        _insert_pairs(cursor, datasource_id, relation_id, fields['source_table_id'],
                      fields['target_table_id'], fields['column_pairs'])
        _bump_revision(cursor, datasource_id)
    return str(relation_id)


def update_relation(datasource_id: str, relation_id: str,
                    fields: dict) -> bool:
    with _transaction() as cursor:
        if not _lock_datasource(cursor, datasource_id):
            raise Text2SqlNotFound('数据源不存在或已删除')
        cursor.execute(
            'SELECT id, relation_type, source_table_id, target_table_id '
            'FROM text2sql.t2s_relation WHERE id = %s AND datasource_id = %s',
            (relation_id, datasource_id))
        current = cursor.fetchone()
        if current is None:
            return False
        assignments: list[str] = []
        params: list = []
        for key, column in (('cardinality', 'cardinality'),
                            ('description', 'description'),
                            ('enabled', 'enabled')):
            if key in fields:
                assignments.append(f'{column} = %s')
                params.append(fields[key])
        if assignments:
            params.extend([relation_id, datasource_id])
            cursor.execute(
                f"UPDATE text2sql.t2s_relation SET {', '.join(assignments)} "
                'WHERE id = %s AND datasource_id = %s', params)
        if fields.get('column_pairs') is not None:
            if current['relation_type'] != 'MANUAL':
                raise Text2SqlConflict('外键关联的列对由结构扫描维护，不能手工修改')
            cursor.execute(
                'DELETE FROM text2sql.t2s_relation_column WHERE relation_id = %s',
                (relation_id,))
            _insert_pairs(cursor, datasource_id, relation_id,
                          current['source_table_id'], current['target_table_id'],
                          fields['column_pairs'])
        _bump_revision(cursor, datasource_id)
    return True


def delete_relation(datasource_id: str, relation_id: str) -> bool:
    with _transaction() as cursor:
        if not _lock_datasource(cursor, datasource_id):
            raise Text2SqlNotFound('数据源不存在或已删除')
        cursor.execute(
            'SELECT id FROM text2sql.t2s_relation WHERE id = %s AND datasource_id = %s',
            (relation_id, datasource_id))
        if cursor.fetchone() is None:
            return False
        cursor.execute(
            'DELETE FROM text2sql.t2s_relation_column WHERE relation_id = %s',
            (relation_id,))
        cursor.execute(
            'DELETE FROM text2sql.t2s_relation WHERE id = %s AND datasource_id = %s',
            (relation_id, datasource_id))
        _bump_revision(cursor, datasource_id)
    return True


def verify_relation(datasource_id: str, relation_id: str, actor: str,
                    verified: bool) -> bool:
    with _transaction() as cursor:
        if not _lock_datasource(cursor, datasource_id):
            raise Text2SqlNotFound('数据源不存在或已删除')
        cursor.execute(
            """
            UPDATE text2sql.t2s_relation
               SET verified = %s,
                   verified_by = CASE WHEN %s THEN %s ELSE NULL END,
                   verified_at = CASE WHEN %s THEN now() ELSE NULL END
             WHERE id = %s AND datasource_id = %s
            RETURNING id
            """,
            (verified, verified, actor or None, verified, relation_id, datasource_id))
        if cursor.fetchone() is None:
            return False
        _bump_revision(cursor, datasource_id)
    return True


def _insert_pairs(cursor, datasource_id: str, relation_id: str,
                  source_table_id: str, target_table_id: str,
                  pairs: list[tuple[str, str]]) -> None:
    seen_source: set[str] = set()
    seen_target: set[str] = set()
    for ordinal, (source_column, target_column) in enumerate(pairs, start=1):
        if source_column in seen_source or target_column in seen_target:
            raise Text2SqlConflict('关联列对不能重复')
        seen_source.add(source_column)
        seen_target.add(target_column)
        cursor.execute(
            """
            INSERT INTO text2sql.t2s_relation_column
                (relation_id, datasource_id, source_table_id, target_table_id,
                 ordinal_position, source_column_id, target_column_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (relation_id, datasource_id, source_table_id, target_table_id,
             ordinal, source_column, target_column))


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------
def list_values(datasource_id: str, column_id: str | None = None) -> list[dict]:
    with _transaction() as cursor:
        sql = _SELECT_VALUE + ' AND (%s IS NULL OR v.column_id = %s) ORDER BY t.table_name, c.column_name, v.raw_value'
        cursor.execute(sql, (datasource_id, column_id, column_id))
        return [dict(item) for item in cursor.fetchall()]


def get_value(datasource_id: str, value_id: str) -> dict | None:
    for item in list_values(datasource_id):
        if str(item['id']) == str(value_id):
            return item
    return None


def create_value(datasource_id: str, fields: dict) -> str:
    with _transaction() as cursor:
        if not _lock_datasource(cursor, datasource_id):
            raise Text2SqlNotFound('数据源不存在或已删除')
        if not _column_belongs(cursor, datasource_id, fields['column_id']):
            raise Text2SqlNotFound('字段不存在')
        cursor.execute(
            'SELECT id, enabled FROM text2sql.t2s_value '
            'WHERE column_id = %s AND raw_value = %s FOR UPDATE',
            (fields['column_id'], fields['raw_value']))
        existing = cursor.fetchone()
        if existing is not None:
            if existing['enabled']:
                raise Text2SqlConflict('该字段下已存在相同的枚举值')
            # 删除是软删除：重新添加同一取值时直接恢复并覆盖业务名称/同义词。
            cursor.execute(
                """
                UPDATE text2sql.t2s_value
                   SET value_type = %s, business_name = %s, aliases = %s,
                       description = %s, source_type = %s, enabled = TRUE,
                       updated_at = now()
                 WHERE id = %s
                """,
                (fields['value_type'], fields.get('business_name'),
                 fields.get('aliases') or [], fields.get('description') or '',
                 fields.get('source_type') or 'MANUAL', existing['id']))
            value_id = existing['id']
        else:
            try:
                cursor.execute(
                    """
                    INSERT INTO text2sql.t2s_value
                        (datasource_id, column_id, raw_value, value_type, business_name,
                         aliases, description, source_type, enabled)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (datasource_id, fields['column_id'], fields['raw_value'],
                     fields['value_type'], fields.get('business_name'),
                     fields.get('aliases') or [], fields.get('description') or '',
                     fields.get('source_type') or 'MANUAL', fields.get('enabled', True)))
            except psycopg2.errors.UniqueViolation as error:
                raise Text2SqlConflict('该字段下已存在相同的枚举值') from error
            value_id = cursor.fetchone()['id']
        _bump_revision(cursor, datasource_id)
    return str(value_id)


def update_value(datasource_id: str, value_id: str, fields: dict) -> bool:
    with _transaction() as cursor:
        if not _lock_datasource(cursor, datasource_id):
            raise Text2SqlNotFound('数据源不存在或已删除')
        assignments: list[str] = []
        params: list = []
        for key, column in (('business_name', 'business_name'),
                            ('aliases', 'aliases'),
                            ('description', 'description'),
                            ('enabled', 'enabled')):
            if key in fields:
                assignments.append(f'{column} = %s')
                params.append(fields[key])
        if not assignments:
            cursor.execute('SELECT 1 FROM text2sql.t2s_value WHERE id = %s AND datasource_id = %s',
                           (value_id, datasource_id))
            return cursor.fetchone() is not None
        params.extend([value_id, datasource_id])
        cursor.execute(
            f"UPDATE text2sql.t2s_value SET {', '.join(assignments)} "
            'WHERE id = %s AND datasource_id = %s RETURNING id', params)
        if cursor.fetchone() is None:
            return False
        _bump_revision(cursor, datasource_id)
    return True


def delete_value(datasource_id: str, value_id: str) -> bool:
    """停用枚举值（软删除）。

    历史版本的 ``t2s_knowledge.value_id`` 会引用该行，物理删除会破坏版本快照；
    停用后新版本不再收录该值，列表默认隐藏，重复删除保持幂等。
    """
    with _transaction() as cursor:
        if not _lock_datasource(cursor, datasource_id):
            raise Text2SqlNotFound('数据源不存在或已删除')
        cursor.execute(
            'SELECT enabled FROM text2sql.t2s_value '
            'WHERE id = %s AND datasource_id = %s FOR UPDATE',
            (value_id, datasource_id))
        row = cursor.fetchone()
        if row is None:
            return False
        if not row['enabled']:
            return True
        cursor.execute(
            'UPDATE text2sql.t2s_value SET enabled = FALSE, updated_at = now() '
            'WHERE id = %s AND datasource_id = %s',
            (value_id, datasource_id))
        _bump_revision(cursor, datasource_id)
    return True


# ---------------------------------------------------------------------------
# 指标
# ---------------------------------------------------------------------------
def list_metrics(datasource_id: str) -> list[dict]:
    with _transaction() as cursor:
        cursor.execute(_SELECT_METRIC + ' ORDER BY m.metric_key', (datasource_id,))
        metrics = [dict(item) for item in cursor.fetchall()]
        cursor.execute(
            """
            SELECT mc.metric_id, mc.column_id, mc.dependency_role,
                   c.column_name,
                   t.schema_name || '.' || t.table_name AS table_name
              FROM text2sql.t2s_metric_column mc
              JOIN text2sql.t2s_column c ON c.id = mc.column_id
              JOIN text2sql.t2s_table t ON t.id = c.table_id
             WHERE mc.datasource_id = %s
             ORDER BY mc.metric_id, mc.dependency_role, t.table_name, c.column_name
            """, (datasource_id,))
        columns: dict[str, list[dict]] = {}
        for item in cursor.fetchall():
            columns.setdefault(str(item['metric_id']), []).append(dict(item))
        cursor.execute(
            """
            SELECT metric_id, relation_id FROM text2sql.t2s_metric_relation
             WHERE datasource_id = %s ORDER BY metric_id, relation_id
            """, (datasource_id,))
        relations: dict[str, list[str]] = {}
        for item in cursor.fetchall():
            relations.setdefault(str(item['metric_id']), []).append(str(item['relation_id']))
    for metric in metrics:
        metric['column_dependencies'] = columns.get(str(metric['id']), [])
        metric['relation_dependencies'] = relations.get(str(metric['id']), [])
    return metrics


def get_metric(datasource_id: str, metric_id: str) -> dict | None:
    for metric in list_metrics(datasource_id):
        if str(metric['id']) == str(metric_id):
            return metric
    return None


def create_metric(datasource_id: str, fields: dict) -> str:
    with _transaction() as cursor:
        if not _lock_datasource(cursor, datasource_id):
            raise Text2SqlNotFound('数据源不存在或已删除')
        _validate_metric_refs(cursor, datasource_id, fields)
        try:
            cursor.execute(
                """
                INSERT INTO text2sql.t2s_metric
                    (datasource_id, base_table_id, metric_key, business_name,
                     business_description, aliases, expression_sql,
                     filter_definition, time_column_id, unit, business_timezone,
                     aggregation_behavior, attribution_description, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'DRAFT')
                RETURNING id
                """,
                (datasource_id, fields['base_table_id'], fields['metric_key'],
                 fields['business_name'], fields.get('business_description') or '',
                 fields.get('aliases') or [], fields['expression_sql'],
                 psycopg2.extras.Json(fields.get('filter_definition') or {}),
                 fields.get('time_column_id'), fields.get('unit'),
                 fields['business_timezone'], fields['aggregation_behavior'],
                 fields.get('attribution_description') or ''))
        except psycopg2.errors.UniqueViolation as error:
            raise Text2SqlConflict('该数据源下已存在同名指标') from error
        metric_id = cursor.fetchone()['id']
        _replace_metric_dependencies(cursor, datasource_id, metric_id, fields)
        _bump_revision(cursor, datasource_id)
    return str(metric_id)


def update_metric(datasource_id: str, metric_id: str, fields: dict) -> bool:
    with _transaction() as cursor:
        if not _lock_datasource(cursor, datasource_id):
            raise Text2SqlNotFound('数据源不存在或已删除')
        cursor.execute(
            'SELECT id FROM text2sql.t2s_metric WHERE id = %s AND datasource_id = %s',
            (metric_id, datasource_id))
        if cursor.fetchone() is None:
            return False
        _validate_metric_refs(cursor, datasource_id, fields, partial=True)
        assignments: list[str] = []
        params: list = []
        mapping = (
            ('business_name', 'business_name'), ('business_description', 'business_description'),
            ('aliases', 'aliases'), ('expression_sql', 'expression_sql'),
            ('time_column_id', 'time_column_id'), ('unit', 'unit'),
            ('business_timezone', 'business_timezone'),
            ('aggregation_behavior', 'aggregation_behavior'),
            ('attribution_description', 'attribution_description'),
        )
        for key, column in mapping:
            if key in fields:
                assignments.append(f'{column} = %s')
                params.append(fields[key])
        if 'filter_definition' in fields:
            assignments.append('filter_definition = %s')
            params.append(psycopg2.extras.Json(fields['filter_definition'] or {}))
        if assignments:
            params.extend([metric_id, datasource_id])
            cursor.execute(
                f"UPDATE text2sql.t2s_metric SET {', '.join(assignments)} "
                'WHERE id = %s AND datasource_id = %s', params)
        if ('column_dependencies' in fields
                or 'relation_dependencies' in fields):
            _replace_metric_dependencies(cursor, datasource_id, metric_id, fields)
        _bump_revision(cursor, datasource_id)
    return True


def delete_metric(datasource_id: str, metric_id: str) -> bool:
    with _transaction() as cursor:
        if not _lock_datasource(cursor, datasource_id):
            raise Text2SqlNotFound('数据源不存在或已删除')
        cursor.execute(
            'SELECT id FROM text2sql.t2s_metric WHERE id = %s AND datasource_id = %s',
            (metric_id, datasource_id))
        if cursor.fetchone() is None:
            return False
        cursor.execute('DELETE FROM text2sql.t2s_metric_column WHERE metric_id = %s',
                       (metric_id,))
        cursor.execute('DELETE FROM text2sql.t2s_metric_relation WHERE metric_id = %s',
                       (metric_id,))
        cursor.execute('DELETE FROM text2sql.t2s_metric WHERE id = %s', (metric_id,))
        _bump_revision(cursor, datasource_id)
    return True


def set_metric_status(datasource_id: str, metric_id: str, status: str,
                      actor: str) -> bool:
    with _transaction() as cursor:
        if not _lock_datasource(cursor, datasource_id):
            raise Text2SqlNotFound('数据源不存在或已删除')
        cursor.execute(
            """
            UPDATE text2sql.t2s_metric
               SET status = %s,
                   verified_by = CASE WHEN %s = 'APPROVED' THEN %s ELSE NULL END,
                   verified_at = CASE WHEN %s = 'APPROVED' THEN now() ELSE NULL END
             WHERE id = %s AND datasource_id = %s
            RETURNING id
            """,
            (status, status, actor or None, status, metric_id, datasource_id))
        if cursor.fetchone() is None:
            return False
        _bump_revision(cursor, datasource_id)
    return True


def _validate_metric_refs(cursor, datasource_id: str, fields: dict,
                          partial: bool = False) -> None:
    if 'base_table_id' in fields:
        if not _table_belongs(cursor, datasource_id, fields['base_table_id']):
            raise Text2SqlNotFound('指标的基础表不存在')
    elif not partial:
        raise Text2SqlNotFound('指标的基础表不存在')
    time_column = fields.get('time_column_id')
    if time_column and not _column_belongs(cursor, datasource_id, time_column):
        raise Text2SqlNotFound('指标的时间字段不存在')
    for dependency in fields.get('column_dependencies') or []:
        if not _column_belongs(cursor, datasource_id, dependency['column_id']):
            raise Text2SqlNotFound('指标依赖字段不存在')
    for relation_id in fields.get('relation_dependencies') or []:
        cursor.execute(
            'SELECT 1 FROM text2sql.t2s_relation WHERE id = %s AND datasource_id = %s',
            (relation_id, datasource_id))
        if cursor.fetchone() is None:
            raise Text2SqlNotFound('指标依赖关联不存在')


def _replace_metric_dependencies(cursor, datasource_id: str, metric_id: str,
                                 fields: dict) -> None:
    if 'column_dependencies' in fields:
        cursor.execute('DELETE FROM text2sql.t2s_metric_column WHERE metric_id = %s',
                       (metric_id,))
        for dependency in fields['column_dependencies'] or []:
            cursor.execute(
                """
                INSERT INTO text2sql.t2s_metric_column
                    (metric_id, datasource_id, column_id, dependency_role)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (metric_id, datasource_id, dependency['column_id'],
                 dependency['role']))
    if 'relation_dependencies' in fields:
        cursor.execute('DELETE FROM text2sql.t2s_metric_relation WHERE metric_id = %s',
                       (metric_id,))
        for relation_id in fields['relation_dependencies'] or []:
            cursor.execute(
                """
                INSERT INTO text2sql.t2s_metric_relation
                    (metric_id, datasource_id, relation_id)
                VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
                """, (metric_id, datasource_id, relation_id))
