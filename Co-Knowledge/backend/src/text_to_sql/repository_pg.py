"""``text2sql`` schema 的 PostgreSQL 实现。

与 ``model`` / ``workflow`` 的 store 同一套取舍：

1. 自己拿连接、自己提交/回滚，**异常一律抛**（不折成静默空结果）；
2. 事务里先锁 datasource 行，再改版本号/子表，避免并发扫描互相覆盖；
3. 时间戳在 SQL 里格式化成 ``YYYY-MM-DD HH24:MI:SS``，接口层直接展示。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

import psycopg2
import psycopg2.extras

from text_to_sql.credentials import encrypt_password
from text_to_sql.db import row as _row, transaction as _transaction
from text_to_sql.errors import Text2SqlConflict
from text_to_sql.scanner import ScannedColumn, ScanSnapshot, is_text_type

_SELECT_DATASOURCE = """
SELECT d.id, d.name, d.db_type, d.host, d.port, d.database_name, d.username,
       d.credential_ref, d.include_schemas, d.business_description, d.topic_name,
       d.topic_description, d.maintainer_ref, d.business_timezone, d.query_policy,
       d.query_examples, d.embedding_model, d.llm_model,
       d.enabled, d.config_revision, d.active_version_id, d.deleted_at,
       v.revision AS active_revision, v.status AS active_status,
       to_char(d.connection_tested_at, 'YYYY-MM-DD HH24:MI:SS') AS connection_tested_at,
       to_char(d.last_sync_at, 'YYYY-MM-DD HH24:MI:SS') AS last_sync_at,
       to_char(v.ready_at, 'YYYY-MM-DD HH24:MI:SS') AS active_ready_at,
       to_char(d.created_at, 'YYYY-MM-DD HH24:MI:SS') AS created_at,
       to_char(d.updated_at, 'YYYY-MM-DD HH24:MI:SS') AS updated_at
FROM text2sql.t2s_datasource d
LEFT JOIN text2sql.t2s_config_version v
       ON v.id = d.active_version_id AND v.datasource_id = d.id
WHERE d.deleted_at IS NULL
"""

_UPDATE_COLUMNS = {
    'name': 'name',
    'db_type': 'db_type',
    'host': 'host',
    'port': 'port',
    'database_name': 'database_name',
    'username': 'username',
    'include_schemas': 'include_schemas',
    'business_description': 'business_description',
    'business_timezone': 'business_timezone',
    'query_policy': 'query_policy',
    'query_examples': 'query_examples',
    'embedding_model': 'embedding_model',
    # SQL 生成模型只影响运行期，不进 _REVISION_FIELDS：换模型不需要重建语义索引。
    'llm_model': 'llm_model',
    'enabled': 'enabled',
}

#: 改变这些字段必须递增 ``config_revision``（表/列语义变更另在各自接口里递增）。
_REVISION_FIELDS = {
    'db_type', 'host', 'port', 'database_name', 'username', 'credential_ref',
    'include_schemas', 'business_timezone', 'query_policy',
}

_TABLE_UPDATE_COLUMNS = {
    'enabled': 'enabled',
    'business_name': 'business_name',
    'business_description': 'business_description',
    'business_aliases': 'business_aliases',
}

_COLUMN_UPDATE_COLUMNS = {
    'enabled': 'enabled',
    'business_name': 'business_name',
    'business_description': 'business_description',
    'business_aliases': 'business_aliases',
    'semantic_type': 'semantic_type',
}




# ---------------------------------------------------------------------------
# 数据源
# ---------------------------------------------------------------------------
def list_datasources() -> list[dict[str, Any]]:
    with _transaction() as cursor:
        cursor.execute(_SELECT_DATASOURCE + ' ORDER BY d.updated_at DESC, d.id')
        return [dict(item) for item in cursor.fetchall()]


def get_datasource(datasource_id: str) -> Optional[dict[str, Any]]:
    with _transaction() as cursor:
        cursor.execute(_SELECT_DATASOURCE + ' AND d.id = %s', (datasource_id,))
        return _row(cursor.fetchone())


def find_datasource_by_name(name: str) -> Optional[dict[str, Any]]:
    with _transaction() as cursor:
        cursor.execute(_SELECT_DATASOURCE + ' AND lower(d.name) = lower(%s)', (name,))
        return _row(cursor.fetchone())


def create_datasource(fields: dict[str, Any]) -> dict[str, Any]:
    values = dict(fields)
    topic = values.get('topic') or {}
    password = values.pop('password', '')
    try:
        with _transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO text2sql.t2s_datasource
                    (name, db_type, host, port, database_name, username,
                     credential_ref, include_schemas, business_description,
                     topic_name, topic_description, maintainer_ref,
                     business_timezone, query_policy, embedding_model,
                     llm_model, enabled)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    values['name'], values['db_type'], values['host'], values['port'],
                    values['database_name'], values['username'],
                    encrypt_password(password), values['include_schemas'],
                    values['business_description'], topic.get('name') or None,
                    topic.get('description') or '', topic.get('owner') or None,
                    values['business_timezone'],
                    psycopg2.extras.Json(values['query_policy']),
                    values.get('embedding_model'),
                    values.get('llm_model'),
                    values['enabled'],
                ),
            )
            datasource_id = cursor.fetchone()['id']
            cursor.execute(_SELECT_DATASOURCE + ' AND d.id = %s', (datasource_id,))
            row = dict(cursor.fetchone())
    except psycopg2.errors.UniqueViolation as error:
        raise Text2SqlConflict('已存在同名数据源') from error
    return row


def update_datasource(datasource_id: str,
                      fields: dict[str, Any]) -> Optional[dict[str, Any]]:
    values = dict(fields)
    topic = values.pop('topic', None)
    password = values.pop('password', None)
    mapped: dict[str, tuple[str, Any]] = {}
    for key, value in values.items():
        column = _UPDATE_COLUMNS.get(key)
        if column:
            mapped[column] = (key, value)
    if topic is not None:
        mapped['topic_name'] = ('topic_name', topic.get('name') or None)
        mapped['topic_description'] = ('topic_description',
                                       topic.get('description') or '')
        mapped['maintainer_ref'] = ('maintainer_ref', topic.get('owner') or None)
    if password:
        mapped['credential_ref'] = ('credential_ref', encrypt_password(password))
    if not mapped:
        return get_datasource(datasource_id)

    try:
        with _transaction() as cursor:
            cursor.execute(
                'SELECT * FROM text2sql.t2s_datasource '
                'WHERE id = %s AND deleted_at IS NULL FOR UPDATE', (datasource_id,))
            current = cursor.fetchone()
            if current is None:
                return None
            current = dict(current)

            assignments: list[str] = []
            params: list[Any] = []
            bump_revision = False
            for column, (key, value) in mapped.items():
                if current.get(column) == value:
                    continue
                assignments.append(f'{column} = %s')
                params.append(psycopg2.extras.Json(value)
                              if key in ('query_policy', 'query_examples')
                              else value)
                if key in _REVISION_FIELDS:
                    bump_revision = True
            if not assignments:
                cursor.execute(_SELECT_DATASOURCE + ' AND d.id = %s', (datasource_id,))
                return _row(cursor.fetchone())
            if bump_revision:
                assignments.append('config_revision = config_revision + 1')
            params.append(datasource_id)
            cursor.execute(
                f"UPDATE text2sql.t2s_datasource SET {', '.join(assignments)} "
                'WHERE id = %s', params)
            cursor.execute(_SELECT_DATASOURCE + ' AND d.id = %s', (datasource_id,))
            return _row(cursor.fetchone())
    except psycopg2.errors.UniqueViolation as error:
        raise Text2SqlConflict('已存在同名数据源') from error


def soft_delete_datasource(datasource_id: str) -> bool:
    with _transaction() as cursor:
        cursor.execute(
            """
            UPDATE text2sql.t2s_datasource
               SET enabled = FALSE, deleted_at = now(), active_version_id = NULL,
                   credential_ref = 'deleted://credential-removed'
             WHERE id = %s AND deleted_at IS NULL
            RETURNING id
            """, (datasource_id,))
        if cursor.fetchone() is None:
            return False
        cursor.execute(
            'UPDATE text2sql.t2s_workspace SET datasource_id = NULL WHERE datasource_id = %s',
            (datasource_id,))
        cursor.execute(
            """
            UPDATE text2sql.t2s_favorite
               SET datasource_id = NULL, verified_version_id = NULL,
                   verified_by = NULL, verified_at = NULL
             WHERE datasource_id = %s
            """, (datasource_id,))
        return True


def mark_connection_tested(datasource_id: str) -> Optional[dict[str, Any]]:
    with _transaction() as cursor:
        cursor.execute(
            'UPDATE text2sql.t2s_datasource SET connection_tested_at = now() '
            'WHERE id = %s AND deleted_at IS NULL RETURNING id', (datasource_id,))
        if cursor.fetchone() is None:
            return None
        cursor.execute(_SELECT_DATASOURCE + ' AND d.id = %s', (datasource_id,))
        return _row(cursor.fetchone())


def datasource_connection(datasource_id: str) -> Optional[dict[str, Any]]:
    """连接外部库所需的字段（含密文引用；调用方负责解密）。"""
    with _transaction() as cursor:
        cursor.execute(
            """
            SELECT id, host, port, database_name, username, credential_ref,
                   include_schemas
              FROM text2sql.t2s_datasource
             WHERE id = %s AND deleted_at IS NULL
            """, (datasource_id,))
        return _row(cursor.fetchone())


# ---------------------------------------------------------------------------
# 目录（表 / 字段）
# ---------------------------------------------------------------------------
def list_tables(datasource_id: str) -> list[dict[str, Any]]:
    with _transaction() as cursor:
        cursor.execute(
            """
            SELECT id, schema_name, table_name, table_type, db_comment,
                   business_name, business_description, business_aliases,
                   schema_hash, enabled, missing_since, last_seen_at,
                   to_char(last_seen_at, 'YYYY-MM-DD HH24:MI:SS') AS last_seen_at_text,
                   to_char(missing_since, 'YYYY-MM-DD HH24:MI:SS') AS missing_since_text
              FROM text2sql.t2s_table
             WHERE datasource_id = %s
             ORDER BY schema_name, table_name
            """, (datasource_id,))
        tables = [dict(item) for item in cursor.fetchall()]
        cursor.execute(
            """
            SELECT id, table_id, column_name, data_type, ordinal_position,
                   is_nullable, default_value, is_primary_key, is_unique,
                   db_comment, business_name, business_description,
                   business_aliases, semantic_type, enabled,
                   value_cardinality, distinct_value_count,
                   to_char(missing_since, 'YYYY-MM-DD HH24:MI:SS') AS missing_since_text
              FROM text2sql.t2s_column
             WHERE datasource_id = %s
             ORDER BY table_id, ordinal_position
            """, (datasource_id,))
        columns = [dict(item) for item in cursor.fetchall()]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for column in columns:
        grouped.setdefault(str(column['table_id']), []).append(column)
    for table in tables:
        table['last_seen_at'] = table.pop('last_seen_at_text')
        table['missing_since'] = table.pop('missing_since_text')
        table['columns'] = []
        for column in grouped.get(str(table['id']), []):
            column['missing_since'] = column.pop('missing_since_text')
            table['columns'].append(column)
    return tables


def update_table(datasource_id: str, table_id: str,
                 fields: dict[str, Any]) -> Optional[dict[str, Any]]:
    return _update_catalog_row(
        table='text2sql.t2s_table', datasource_id=datasource_id, row_id=table_id,
        fields=fields, columns=_TABLE_UPDATE_COLUMNS)


def update_column(datasource_id: str, column_id: str,
                  fields: dict[str, Any]) -> Optional[dict[str, Any]]:
    return _update_catalog_row(
        table='text2sql.t2s_column', datasource_id=datasource_id, row_id=column_id,
        fields=fields, columns=_COLUMN_UPDATE_COLUMNS)


def _update_catalog_row(*, table: str, datasource_id: str, row_id: str,
                        fields: dict[str, Any],
                        columns: dict[str, str]) -> Optional[dict[str, Any]]:
    mapped = {columns[key]: value for key, value in fields.items()
              if key in columns}
    if not mapped:
        return None
    with _transaction() as cursor:
        cursor.execute(
            'SELECT id FROM text2sql.t2s_datasource '
            'WHERE id = %s AND deleted_at IS NULL FOR UPDATE', (datasource_id,))
        if cursor.fetchone() is None:
            return None
        cursor.execute(f'SELECT * FROM {table} WHERE id = %s AND datasource_id = %s',
                       (row_id, datasource_id))
        current = cursor.fetchone()
        if current is None:
            return None
        current = dict(current)

        assignments: list[str] = []
        params: list[Any] = []
        for column, value in mapped.items():
            if current.get(column) == value:
                continue
            assignments.append(f'{column} = %s')
            params.append(value)
        if not assignments:
            return current
        cursor.execute(
            'UPDATE text2sql.t2s_datasource '
            'SET config_revision = config_revision + 1 WHERE id = %s',
            (datasource_id,))
        params.extend([row_id, datasource_id])
        cursor.execute(
            f"UPDATE {table} SET {', '.join(assignments)} "
            'WHERE id = %s AND datasource_id = %s', params)
        cursor.execute(f'SELECT * FROM {table} WHERE id = %s', (row_id,))
        return _row(cursor.fetchone())


def get_table(datasource_id: str, table_id: str) -> Optional[dict[str, Any]]:
    for table in list_tables(datasource_id):
        if str(table['id']) == str(table_id):
            return table
    return None


def get_column(datasource_id: str, column_id: str) -> Optional[dict[str, Any]]:
    with _transaction() as cursor:
        cursor.execute(
            """
            SELECT id, table_id, column_name, data_type, ordinal_position,
                   is_nullable, default_value, is_primary_key, is_unique,
                   db_comment, business_name, business_description,
                   business_aliases, semantic_type, enabled,
                   value_cardinality, distinct_value_count,
                   to_char(missing_since, 'YYYY-MM-DD HH24:MI:SS') AS missing_since
              FROM text2sql.t2s_column
             WHERE id = %s AND datasource_id = %s
            """, (column_id, datasource_id))
        return _row(cursor.fetchone())


def selected_tables_map() -> dict[str, list[str]]:
    """所有数据源的「已启用表」：``{datasource_id: ['schema.table', ...]}``。"""
    with _transaction() as cursor:
        cursor.execute(
            """
            SELECT datasource_id, schema_name, table_name
              FROM text2sql.t2s_table
             WHERE enabled = TRUE AND missing_since IS NULL
             ORDER BY datasource_id, schema_name, table_name
            """)
        result: dict[str, list[str]] = {}
        for row in cursor.fetchall():
            result.setdefault(str(row['datasource_id']), []).append(
                f"{row['schema_name']}.{row['table_name']}")
        return result


# ---------------------------------------------------------------------------
# 扫描落库
# ---------------------------------------------------------------------------
def apply_scan(datasource_id: str, snapshot: ScanSnapshot) -> Optional[dict[str, Any]]:
    """把扫描结果合并进目录；返回 ``{summary, revisionChanged, datasource}``。"""
    summary = {
        'tablesAdded': 0, 'tablesUpdated': 0, 'tablesMissing': 0,
        'columnsAdded': 0, 'columnsUpdated': 0, 'columnsMissing': 0,
        'relationsAdded': 0, 'relationsUpdated': 0,
        'valuesDiscovered': 0,
    }
    values_changed = False
    with _transaction() as cursor:
        cursor.execute(
            'SELECT id, config_revision FROM text2sql.t2s_datasource '
            'WHERE id = %s AND deleted_at IS NULL FOR UPDATE', (datasource_id,))
        if cursor.fetchone() is None:
            return None

        cursor.execute(
            """
            SELECT id, schema_name, table_name, enabled, schema_hash,
                   missing_since IS NOT NULL AS missing
              FROM text2sql.t2s_table WHERE datasource_id = %s
            """, (datasource_id,))
        existing = {(row['schema_name'], row['table_name']): dict(row)
                    for row in cursor.fetchall()}
        before = {str(row['id']): row['schema_hash']
                  for row in existing.values() if row['enabled']}
        scanned_keys = {table.key for table in snapshot.tables}

        table_ids: dict[tuple[str, str], str] = {}
        for table in snapshot.tables:
            row = existing.get(table.key)
            if row:
                table_id = row['id']
                table_ids[table.key] = table_id
                cursor.execute(
                    """
                    UPDATE text2sql.t2s_table
                       SET table_type = %s, db_comment = %s,
                           constraints_metadata = %s, schema_hash = %s,
                           last_seen_at = now(), missing_since = NULL
                     WHERE id = %s
                    """,
                    (table.table_type, table.comment,
                     psycopg2.extras.Json(table.constraints), table.schema_hash,
                     table_id))
                summary['tablesUpdated'] += 1
            else:
                cursor.execute(
                    """
                    INSERT INTO text2sql.t2s_table
                        (datasource_id, schema_name, table_name, table_type,
                         db_comment, constraints_metadata, schema_hash,
                         last_seen_at, enabled)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, now(), FALSE)
                    RETURNING id
                    """,
                    (datasource_id, table.schema, table.name, table.table_type,
                     table.comment, psycopg2.extras.Json(table.constraints),
                     table.schema_hash))
                table_id = cursor.fetchone()['id']
                table_ids[table.key] = table_id
                summary['tablesAdded'] += 1

            cursor.execute(
                'SELECT column_name FROM text2sql.t2s_column WHERE table_id = %s',
                (table_id,))
            existing_columns = {row['column_name'] for row in cursor.fetchall()}
            scanned_columns = set()
            for column in table.columns:
                scanned_columns.add(column.name)
                _upsert_column(cursor, datasource_id, table_id, column, table.schema_hash)
                if column.name in existing_columns:
                    summary['columnsUpdated'] += 1
                else:
                    summary['columnsAdded'] += 1
            missing_columns = existing_columns - scanned_columns
            if missing_columns:
                cursor.execute(
                    """
                    UPDATE text2sql.t2s_column SET missing_since = now()
                     WHERE table_id = %s AND missing_since IS NULL
                       AND column_name = ANY(%s)
                    """, (table_id, list(missing_columns)))
                summary['columnsMissing'] += len(missing_columns)

            discovered, changed = _sync_discovered_values(
                cursor, datasource_id, table_id, table, snapshot)
            summary['valuesDiscovered'] += discovered
            values_changed = values_changed or changed

        missing_tables = [str(row['id']) for key, row in existing.items()
                          if key not in scanned_keys and not row['missing']]
        if missing_tables:
            cursor.execute(
                # 行 id 是 UUID 列：字符串数组要显式转 uuid[]，否则 uuid = text 报错。
                'UPDATE text2sql.t2s_table SET missing_since = now() '
                'WHERE id = ANY(%s::uuid[])', (missing_tables,))
            summary['tablesMissing'] = len(missing_tables)

        _apply_relations(cursor, datasource_id, snapshot, table_ids, summary)

        after = {}
        cursor.execute(
            'SELECT id, enabled, schema_hash FROM text2sql.t2s_table '
            'WHERE datasource_id = %s AND missing_since IS NULL', (datasource_id,))
        for row in cursor.fetchall():
            if row['enabled']:
                after[str(row['id'])] = row['schema_hash']
        effective_changed = any(before.get(key) != value for key, value in after.items()) \
            or bool(set(before) - set(after)) or values_changed
        if effective_changed:
            cursor.execute(
                'UPDATE text2sql.t2s_datasource '
                'SET config_revision = config_revision + 1, last_sync_at = now() '
                'WHERE id = %s', (datasource_id,))
        else:
            cursor.execute(
                'UPDATE text2sql.t2s_datasource SET last_sync_at = now() WHERE id = %s',
                (datasource_id,))

        cursor.execute(_SELECT_DATASOURCE + ' AND d.id = %s', (datasource_id,))
        datasource = _row(cursor.fetchone())
    return {'summary': summary, 'revisionChanged': effective_changed,
            'datasource': datasource}


def _sync_discovered_values(cursor, datasource_id: str, table_id: str,
                            table, snapshot: ScanSnapshot
                            ) -> tuple[int, bool]:
    """把扫描发现的值写入目录，保留人工维护的值。

    只同步本次扫描做出基数判断的列；``UNKNOWN``（未取样）保持原状。
    只有已启用的表才会被采样，未启用表上残留的旧值不会被引用（快照只收
    ``enabled`` 的值、渲染时还要按选中表过滤），因此不必在此清理。
    """
    profiles = {column.name: column for column in table.columns}
    discovered: dict[str, list[str]] = {}
    for value in snapshot.values:
        if value.schema == table.schema and value.table == table.name:
            discovered.setdefault(value.column, []).append(value.raw_value)

    cursor.execute(
        'SELECT id, column_name, data_type FROM text2sql.t2s_column '
        'WHERE table_id = %s', (table_id,))
    column_ids = {row['column_name']: row for row in cursor.fetchall()}
    total = 0
    changed = False
    for name, row in column_ids.items():
        profile = profiles.get(name)
        if profile is None or profile.value_cardinality == 'UNKNOWN':
            continue
        column_id = row['id']
        if not is_text_type(row['data_type']):
            cursor.execute(
                "UPDATE text2sql.t2s_value SET enabled = FALSE, updated_at = now() "
                "WHERE column_id = %s AND source_type = 'DATABASE' AND enabled",
                (column_id,))
            changed = changed or cursor.rowcount > 0
            continue
        target = discovered.get(name, []) if profile.value_cardinality == 'LOW' else []
        cursor.execute(
            "SELECT raw_value FROM text2sql.t2s_value WHERE column_id = %s "
            "AND source_type = 'DATABASE'", (column_id,))
        current = {item['raw_value'] for item in cursor.fetchall()}
        stale = sorted(current - set(target))
        if stale:
            cursor.execute(
                "UPDATE text2sql.t2s_value SET enabled = FALSE, updated_at = now() "
                "WHERE column_id = %s AND source_type = 'DATABASE' "
                "AND raw_value = ANY(%s) AND enabled",
                (column_id, stale))
            changed = changed or cursor.rowcount > 0
        for value in target:
            cursor.execute(
                """
                INSERT INTO text2sql.t2s_value
                    (datasource_id, column_id, raw_value, value_type,
                     business_name, aliases, description, source_type, enabled)
                VALUES (%s, %s, %s, %s, NULL, '{}', '', 'DATABASE', TRUE)
                ON CONFLICT (column_id, raw_value) DO NOTHING
                """, (datasource_id, column_id, value, row['data_type']))
            changed = changed or cursor.rowcount > 0
        if profile.value_cardinality == 'LOW':
            total += len(target)
    return total, changed


def _column_hash(column: ScannedColumn) -> str:
    canonical = json.dumps({
        'name': column.name,
        'dataType': column.data_type,
        'ordinalPosition': column.ordinal_position,
        'nullable': column.nullable,
        'defaultValue': column.default_value,
        'primaryKey': column.primary_key,
        'unique': column.unique,
    }, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _upsert_column(cursor, datasource_id: str, table_id: str,
                   column: ScannedColumn, table_hash: str) -> None:
    cursor.execute(
        """
        INSERT INTO text2sql.t2s_column
            (datasource_id, table_id, column_name, data_type, ordinal_position,
             is_nullable, default_value, is_primary_key, is_unique, db_comment,
             schema_hash, missing_since, value_cardinality,
             distinct_value_count)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, %s, %s)
        ON CONFLICT (table_id, column_name) DO UPDATE
           SET data_type = EXCLUDED.data_type,
               ordinal_position = EXCLUDED.ordinal_position,
               is_nullable = EXCLUDED.is_nullable,
               default_value = EXCLUDED.default_value,
               is_primary_key = EXCLUDED.is_primary_key,
               is_unique = EXCLUDED.is_unique,
               db_comment = EXCLUDED.db_comment,
               schema_hash = EXCLUDED.schema_hash,
               missing_since = NULL,
               value_cardinality = EXCLUDED.value_cardinality,
               distinct_value_count = EXCLUDED.distinct_value_count
        """,
        (datasource_id, table_id, column.name, column.data_type,
         column.ordinal_position, column.nullable, column.default_value,
         column.primary_key, column.unique, column.comment,
         _column_hash(column) or table_hash,
         column.value_cardinality, column.distinct_value_count))


def _apply_relations(cursor, datasource_id: str, snapshot: ScanSnapshot,
                     table_ids: dict[tuple[str, str], str],
                     summary: dict[str, int]) -> None:
    for relation in snapshot.relations:
        source_id = table_ids.get(relation.source)
        target_id = table_ids.get(relation.target)
        if source_id is None or target_id is None:
            continue
        cursor.execute(
            'SELECT id, relation_type FROM text2sql.t2s_relation '
            'WHERE datasource_id = %s AND source_table_id = %s AND relation_name = %s',
            (datasource_id, source_id, relation.name))
        row = cursor.fetchone()
        if row and row['relation_type'] == 'MANUAL':
            continue
        if row:
            relation_id = row['id']
            cursor.execute(
                """
                UPDATE text2sql.t2s_relation
                   SET target_table_id = %s, relation_type = 'FOREIGN_KEY',
                       cardinality = %s, description = %s
                 WHERE id = %s
                """,
                (target_id, relation.cardinality, relation.description, relation_id))
            summary['relationsUpdated'] += 1
        else:
            cursor.execute(
                """
                INSERT INTO text2sql.t2s_relation
                    (datasource_id, source_table_id, target_table_id,
                     relation_name, relation_type, cardinality, description)
                VALUES (%s, %s, %s, %s, 'FOREIGN_KEY', %s, %s)
                RETURNING id
                """,
                (datasource_id, source_id, target_id, relation.name,
                 relation.cardinality, relation.description))
            relation_id = cursor.fetchone()['id']
            summary['relationsAdded'] += 1

        cursor.execute(
            'DELETE FROM text2sql.t2s_relation_column WHERE relation_id = %s',
            (relation_id,))
        for ordinal, (source_column, target_column) in enumerate(
                relation.column_pairs, start=1):
            source_column_id = _column_id(cursor, source_id, source_column)
            target_column_id = _column_id(cursor, target_id, target_column)
            if source_column_id is None or target_column_id is None:
                continue
            cursor.execute(
                """
                INSERT INTO text2sql.t2s_relation_column
                    (relation_id, datasource_id, source_table_id, target_table_id,
                     ordinal_position, source_column_id, target_column_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (relation_id, datasource_id, source_id, target_id, ordinal,
                 source_column_id, target_column_id))


def _column_id(cursor, table_id: str, column_name: str) -> Optional[str]:
    cursor.execute(
        'SELECT id FROM text2sql.t2s_column WHERE table_id = %s AND column_name = %s',
        (table_id, column_name))
    row = cursor.fetchone()
    return row['id'] if row else None


def profiling_scope(datasource_id: str) -> set[tuple[str, str, str]]:
    """允许自动收录取值的列：已启用表上的已启用列。

    扫描时只对这些列做基数采样，避免为「永远不查询」的表收集账号名、文件名、
    UUID 之类的东西。
    """
    with _transaction() as cursor:
        cursor.execute(
            """
            SELECT t.schema_name, t.table_name, c.column_name
              FROM text2sql.t2s_table t
              JOIN text2sql.t2s_column c ON c.table_id = t.id
             WHERE t.datasource_id = %s AND t.enabled AND c.enabled
               AND t.missing_since IS NULL AND c.missing_since IS NULL
            """, (datasource_id,))
        return {(row['schema_name'], row['table_name'], row['column_name'])
                for row in cursor.fetchall()}


def selected_table_names(datasource_id: str) -> list[str]:
    with _transaction() as cursor:
        cursor.execute(
            """
            SELECT schema_name, table_name FROM text2sql.t2s_table
             WHERE datasource_id = %s AND enabled = TRUE AND missing_since IS NULL
             ORDER BY schema_name, table_name
            """, (datasource_id,))
        return [f"{row['schema_name']}.{row['table_name']}" for row in cursor.fetchall()]
