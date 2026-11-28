"""外部数据库的结构扫描（只读）。

只读 ``pg_catalog``：表/字段/数据库注释、主键与唯一约束、外键列对。扫描结果
不写本地库；落库与差异判断由 :mod:`text_to_sql.repository_pg` 在事务里完成。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

import psycopg2

from text_to_sql import account_guard
from text_to_sql.errors import Text2SqlUpstreamError

CONNECT_TIMEOUT_SECONDS = 8
STATEMENT_TIMEOUT_MS = 15000
PROFILE_TIMEOUT_MS = 3000
# 只自动收录“真正的字典”规模；姓名/编号这类几十个取值的属性列不枚举，
# 交给查询时的值解析（城市、商品等开放维度也走同一条路）。
LOW_CARDINALITY_LIMIT = 20
MAX_PROFILED_COLUMNS = 200
VALUE_MAX_LENGTH = 120

# 标识类列名：不做枚举收录（值不是业务分类）。
_IDENTIFIER_COLUMN = re.compile(
    r'(^|_)(id|uuid|guid|hash|token|secret|password|passwd|email|mail|phone|mobile'
    r'|url|uri|path|dir|key)$', re.IGNORECASE)
# 标识类取值：UUID / 长十六进制 / 邮箱 / URL / 文件名。
_IDENTIFIER_VALUE = re.compile(
    r'^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
    r'|[0-9a-f]{32,64}'
    r'|[^@\s]+@[^@\s]+\.[^@\s]+'
    r'|https?://\S+'
    r'|\S+\.(md|txt|docx?|pdf|xlsx?|csv|json|ya?ml|html?|png|jpe?g|gif|zip))$',
    re.IGNORECASE)

_TABLE_TYPES = {'BASE_TABLE', 'VIEW', 'MATERIALIZED_VIEW', 'FOREIGN_TABLE',
                'PARTITIONED_TABLE'}
_PROFILED_TABLE_TYPES = {'BASE_TABLE', 'PARTITIONED_TABLE'}
_TEXT_TYPE_MARKERS = ('char', 'text', 'citext', 'name')


@dataclass(frozen=True)
class ScannedColumn:
    name: str
    data_type: str
    ordinal_position: int
    nullable: bool
    default_value: Optional[str]
    primary_key: bool
    unique: bool
    comment: Optional[str]
    value_cardinality: str = 'UNKNOWN'
    distinct_value_count: Optional[int] = None


@dataclass(frozen=True)
class ScannedValue:
    schema: str
    table: str
    column: str
    raw_value: str
    value_type: str


@dataclass(frozen=True)
class ScannedTable:
    schema: str
    name: str
    table_type: str
    comment: Optional[str]
    constraints: list[dict]
    columns: list[ScannedColumn]

    @property
    def key(self) -> tuple[str, str]:
        return self.schema, self.name

    @property
    def schema_hash(self) -> str:
        payload = [
            {
                'name': column.name,
                'dataType': column.data_type,
                'ordinalPosition': column.ordinal_position,
                'nullable': column.nullable,
                'defaultValue': column.default_value,
                'primaryKey': column.primary_key,
                'unique': column.unique,
            }
            for column in self.columns
        ]
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                               separators=(',', ':'))
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class ScannedRelation:
    name: str
    source: tuple[str, str]
    target: tuple[str, str]
    cardinality: str
    description: str
    column_pairs: list[tuple[str, str]]


@dataclass(frozen=True)
class ScanSnapshot:
    tables: list[ScannedTable] = field(default_factory=list)
    relations: list[ScannedRelation] = field(default_factory=list)
    values: list[ScannedValue] = field(default_factory=list)


def scan_database(connection: dict, schemas: Iterable[str],
                  profile_scope: Optional[set[tuple[str, str, str]]] = None
                  ) -> ScanSnapshot:
    """连接外部 PostgreSQL，返回结构快照。

    ``connection``：``host`` / ``port`` / ``database`` / ``username`` / ``password``。
    ``profile_scope``：允许自动收录取值的列（``(schema, table, column)`` 集合），
    由调用方按「已启用表 + 已启用列」给出；None 表示不限制（脚本/测试用）。
    任何连接或查询失败都收敛成 :class:`Text2SqlUpstreamError`（不回传密码）。
    """
    schema_list = [name for name in schemas if name]
    if not schema_list:
        raise Text2SqlUpstreamError('数据源没有可扫描的 schema')
    try:
        conn = psycopg2.connect(
            host=connection.get('host'),
            port=connection.get('port') or 5432,
            dbname=connection.get('database'),
            user=connection.get('username'),
            password=connection.get('password') or '',
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
            application_name='co-knowledge-text2sql',
            options=f'-c statement_timeout={STATEMENT_TIMEOUT_MS}',
        )
    except psycopg2.Error as error:
        raise Text2SqlUpstreamError(f'外部数据库连接失败：{_safe_error(error)}') from error

    try:
        conn.set_session(readonly=True, autocommit=False)
        with conn.cursor() as cursor:
            # 只读事务挡写不挡读：扫描是「这条数据源即将可用」的关口，
            # 在这里拒绝超级用户账号（见 account_guard 的说明）。
            account_guard.assert_minimal_privilege(
                account_guard.readonly_state(cursor),
                host=str(connection.get('host') or ''))
            tables = _read_tables(cursor, schema_list)
            columns = _read_columns(cursor, schema_list)
            constraints = _read_constraints(cursor, schema_list)
            foreign_keys = _read_foreign_keys(cursor, schema_list)
            profiles = _read_value_profiles(cursor, tables, columns, profile_scope)
    except psycopg2.Error as error:
        raise Text2SqlUpstreamError(f'读取外部数据库结构失败：{_safe_error(error)}') from error
    finally:
        conn.close()

    by_table: dict[tuple[str, str], list[ScannedColumn]] = {}
    for row in columns:
        profile = profiles.get((row['schema'], row['table'], row['name']))
        by_table.setdefault((row['schema'], row['table']), []).append(
            ScannedColumn(
                name=row['name'],
                data_type=row['data_type'],
                ordinal_position=row['ordinal_position'],
                nullable=row['nullable'],
                default_value=row['default_value'],
                primary_key=row['primary_key'],
                unique=row['unique'],
                comment=row['comment'],
                value_cardinality=profile[0] if profile else 'UNKNOWN',
                distinct_value_count=profile[1] if profile else None,
            ))

    constraint_map: dict[tuple[str, str], list[dict]] = {}
    for row in constraints:
        constraint_map.setdefault((row['schema'], row['table']), []).append({
            'type': row['type'],
            'name': row['name'],
            'columns': list(row['columns']),
        })

    scanned_tables = [
        ScannedTable(
            schema=row['schema'],
            name=row['table'],
            table_type=row['table_type'] if row['table_type'] in _TABLE_TYPES else 'BASE_TABLE',
            comment=row['comment'],
            constraints=constraint_map.get((row['schema'], row['table']), []),
            columns=sorted(by_table.get((row['schema'], row['table']), []),
                           key=lambda column: column.ordinal_position),
        )
        for row in tables
    ]

    unique_groups = {
        (row['schema'], row['table']): {tuple(group['columns'])
                                        for group in constraint_map.get((row['schema'], row['table']), [])}
        for row in tables
    }

    relations: list[ScannedRelation] = []
    for row in foreign_keys:
        source_key = (row['source_schema'], row['source_table'])
        target_key = (row['target_schema'], row['target_table'])
        source_columns = tuple(row['source_columns'])
        one_to_one = source_columns in unique_groups.get(source_key, set())
        relations.append(ScannedRelation(
            name=row['name'],
            source=source_key,
            target=target_key,
            cardinality='ONE_TO_ONE' if one_to_one else 'MANY_TO_ONE',
            description=f"{row['source_table']}.{', '.join(source_columns)} = "
                        f"{row['target_table']}.{', '.join(row['target_columns'])}",
            column_pairs=list(zip(source_columns, row['target_columns'])),
        ))

    scanned_values = [
        ScannedValue(schema=row['schema'], table=row['table'],
                     column=row['name'], raw_value=value,
                     value_type=row['data_type'])
        for row in columns
        for value in (profiles.get((row['schema'], row['table'], row['name']),
                                   ('', None, ()))[2] or ())
    ]

    return ScanSnapshot(tables=scanned_tables, relations=relations,
                        values=scanned_values)


def _read_value_profiles(cursor, tables: list[dict], columns: list[dict],
                         profile_scope: Optional[set[tuple[str, str, str]]] = None
                         ) -> dict[tuple[str, str, str],
                                   tuple[str, Optional[int], tuple[str, ...]]]:
    """对文本列做低基数值发现；高基数只打标，不拉取全量值。

    只处理 ``profile_scope`` 内的列（已启用表 + 已启用列）——没被选进查询范围的表
    收集取值没有意义，还会把文件名、UUID 之类的东西堆进语义目录。

    返回 ``(schema, table, column) -> (LOW/HIGH/UNKNOWN, distinct_count, values)``。
    用 pg_stats 估算基数，避免对大表做全量 DISTINCT；每条取样查询都有短超时，
    失败/超时降级为 UNKNOWN，不影响结构扫描。
    """
    table_types = {(row['schema'], row['table']): row['table_type']
                   for row in tables}
    candidates = [
        row for row in columns
        if table_types.get((row['schema'], row['table'])) in _PROFILED_TABLE_TYPES
        and is_text_type(row['data_type'])
        and not _IDENTIFIER_COLUMN.search(row['name'])
        and (profile_scope is None
             or (row['schema'], row['table'], row['name']) in profile_scope)
    ][:MAX_PROFILED_COLUMNS]
    if not candidates:
        return {}

    profiles: dict[tuple[str, str, str], tuple[str, Optional[int], tuple[str, ...]]] = {}
    cursor.execute('SAVEPOINT value_profiles')
    cursor.execute(f'SET LOCAL statement_timeout = {PROFILE_TIMEOUT_MS}')
    try:
        for row in candidates:
            key = (row['schema'], row['table'], row['name'])
            cursor.execute('SAVEPOINT value_profile_item')
            try:
                estimate = _estimate_distinct(cursor, key)
                if estimate is not None and estimate > LOW_CARDINALITY_LIMIT:
                    profiles[key] = ('HIGH', int(estimate), ())
                else:
                    values = _fetch_distinct(cursor, key)
                    profiles[key] = _classify(estimate, values)
            except psycopg2.Error:
                cursor.execute('ROLLBACK TO SAVEPOINT value_profile_item')
                profiles[key] = ('UNKNOWN', None, ())
            finally:
                cursor.execute('RELEASE SAVEPOINT value_profile_item')
    finally:
        cursor.execute(f'SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}')
        cursor.execute('RELEASE SAVEPOINT value_profiles')
    return profiles


def _classify(estimate: Optional[int], values: Optional[list[str]]
              ) -> tuple[str, Optional[int], tuple[str, ...]]:
    """把「基数估计 + 取样结果」判成 LOW/HIGH/UNKNOWN。"""
    if values is None:
        return ('UNKNOWN', estimate, ())
    if (len(values) > LOW_CARDINALITY_LIMIT
            or any(len(value) > VALUE_MAX_LENGTH for value in values)):
        return ('HIGH', None, ())
    # 取值本身是 UUID / 哈希 / 邮箱 / URL / 文件名 的列不是字典。
    if any(_IDENTIFIER_VALUE.match(str(value).strip()) for value in values):
        return ('HIGH', None, ())
    return ('LOW', len(values), tuple(values))


def _estimate_distinct(cursor, key: tuple[str, str, str]) -> Optional[int]:
    cursor.execute(
        """
        SELECT s.n_distinct, c.reltuples
        FROM pg_catalog.pg_stats s
        JOIN pg_catalog.pg_class c ON c.relname = s.tablename
        JOIN pg_catalog.pg_namespace n
          ON n.oid = c.relnamespace AND n.nspname = s.schemaname
        WHERE s.schemaname = %s AND s.tablename = %s AND s.attname = %s
        """, key)
    row = cursor.fetchone()
    if row is None:
        return None
    n_distinct, reltuples = row
    if n_distinct is None:
        return None
    if n_distinct >= 0:
        return int(n_distinct)
    if reltuples is None or reltuples < 0:
        return None
    return int(round(-n_distinct * reltuples))


def _fetch_distinct(cursor, key: tuple[str, str, str]) -> Optional[list[str]]:
    schema, table, column = (_quote_identifier(part) for part in key)
    cursor.execute(
        f'SELECT DISTINCT {column}::text FROM {schema}.{table} '
        f'WHERE {column} IS NOT NULL LIMIT {LOW_CARDINALITY_LIMIT + 1}')
    values = [row[0] for row in cursor.fetchall()
              if row[0] is not None and str(row[0]).strip() != '']
    return [str(value) for value in values]


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def is_text_type(data_type: Optional[str]) -> bool:
    lowered = str(data_type or '').lower()
    return any(marker in lowered for marker in _TEXT_TYPE_MARKERS)


def list_schemas(cursor) -> list[str]:
    """当前账号可用的业务 schema（排除系统 schema 与无权访问的）。

    「测试连接」把它带回前端，作为 Schema 多选的候选——否则用户只能盲猜名字。
    """
    cursor.execute(
        """
        SELECT n.nspname
          FROM pg_catalog.pg_namespace n
         WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
           AND n.nspname NOT LIKE 'pg_%'
           AND has_schema_privilege(n.oid, 'USAGE')
         ORDER BY n.nspname
        """)
    return [row[0] for row in cursor.fetchall()]


def _safe_error(error: BaseException) -> str:
    """psycopg2 的错误文本含主机/用户，但不含口令；截断避免超长。"""
    text = str(error).strip().splitlines()[0] if str(error).strip() else error.__class__.__name__
    return text[:300]


def _read_tables(cursor, schemas: list[str]) -> list[dict]:
    cursor.execute(
        """
        SELECT n.nspname AS schema_name,
               c.relname AS table_name,
               CASE c.relkind
                    WHEN 'v' THEN 'VIEW'
                    WHEN 'm' THEN 'MATERIALIZED_VIEW'
                    WHEN 'f' THEN 'FOREIGN_TABLE'
                    WHEN 'p' THEN 'PARTITIONED_TABLE'
                    ELSE 'BASE_TABLE'
               END AS table_type,
               obj_description(c.oid, 'pg_class') AS table_comment
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = ANY(%s)
          AND c.relkind IN ('r', 'v', 'm', 'f', 'p')
          AND NOT c.relispartition
          -- 扩展自带的对象（如 pg_stat_statements 的两个视图）不属于业务数据，
          -- 扫描进来只会污染语义目录，还可能把全库 SQL 文本暴露给模型。
          AND NOT EXISTS (
              SELECT 1 FROM pg_catalog.pg_depend d
               WHERE d.classid = 'pg_catalog.pg_class'::regclass
                 AND d.objid = c.oid AND d.deptype = 'e')
        ORDER BY n.nspname, c.relname
        """, (schemas,))
    return [{'schema': row[0], 'table': row[1], 'table_type': row[2], 'comment': row[3]}
            for row in cursor.fetchall()]


def _read_columns(cursor, schemas: list[str]) -> list[dict]:
    cursor.execute(
        """
        SELECT n.nspname AS schema_name,
               c.relname AS table_name,
               a.attname AS column_name,
               format_type(a.atttypid, a.atttypmod) AS data_type,
               a.attnum AS ordinal_position,
               NOT a.attnotnull AS is_nullable,
               pg_get_expr(d.adbin, d.adrelid) AS default_value,
               col_description(c.oid, a.attnum) AS column_comment,
               EXISTS (
                   SELECT 1 FROM pg_catalog.pg_constraint con
                   WHERE con.conrelid = c.oid AND con.contype = 'p'
                     AND a.attnum = ANY (con.conkey)
               ) AS is_primary_key,
               EXISTS (
                   SELECT 1 FROM pg_catalog.pg_constraint con
                   WHERE con.conrelid = c.oid AND con.contype = 'u'
                     AND con.conkey = ARRAY [a.attnum]
               ) AS is_unique
        FROM pg_catalog.pg_attribute a
        JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
        WHERE n.nspname = ANY(%s)
          AND c.relkind IN ('r', 'v', 'm', 'f', 'p')
          AND a.attnum > 0
          AND NOT a.attisdropped
        ORDER BY n.nspname, c.relname, a.attnum
        """, (schemas,))
    return [{
        'schema': row[0], 'table': row[1], 'name': row[2], 'data_type': row[3],
        'ordinal_position': row[4], 'nullable': row[5], 'default_value': row[6],
        'comment': row[7], 'primary_key': row[8], 'unique': row[9],
    } for row in cursor.fetchall()]


def _read_constraints(cursor, schemas: list[str]) -> list[dict]:
    cursor.execute(
        """
        SELECT n.nspname AS schema_name,
               c.relname AS table_name,
               con.conname AS constraint_name,
               CASE con.contype WHEN 'p' THEN 'PRIMARY_KEY' ELSE 'UNIQUE' END AS constraint_type,
               array_agg(a.attname ORDER BY k.ord) AS columns
        FROM pg_catalog.pg_constraint con
        JOIN pg_catalog.pg_class c ON c.oid = con.conrelid
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE
        JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.attnum
        WHERE n.nspname = ANY(%s) AND con.contype IN ('p', 'u')
        GROUP BY n.nspname, c.relname, con.conname, con.contype
        ORDER BY n.nspname, c.relname, con.conname
        """, (schemas,))
    return [{'schema': row[0], 'table': row[1], 'name': row[2], 'type': row[3],
             'columns': row[4]} for row in cursor.fetchall()]


def _read_foreign_keys(cursor, schemas: list[str]) -> list[dict]:
    cursor.execute(
        """
        SELECT con.conname AS constraint_name,
               sn.nspname AS source_schema,
               sc.relname AS source_table,
               tn.nspname AS target_schema,
               tc.relname AS target_table,
               array_agg(sa.attname ORDER BY k.ord) AS source_columns,
               array_agg(ta.attname ORDER BY k.ord) AS target_columns
        FROM pg_catalog.pg_constraint con
        JOIN pg_catalog.pg_class sc ON sc.oid = con.conrelid
        JOIN pg_catalog.pg_namespace sn ON sn.oid = sc.relnamespace
        JOIN pg_catalog.pg_class tc ON tc.oid = con.confrelid
        JOIN pg_catalog.pg_namespace tn ON tn.oid = tc.relnamespace
        JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE
        JOIN pg_catalog.pg_attribute sa ON sa.attrelid = sc.oid AND sa.attnum = k.attnum
        JOIN LATERAL unnest(con.confkey) WITH ORDINALITY AS fk(attnum, ord) ON fk.ord = k.ord
        JOIN pg_catalog.pg_attribute ta ON ta.attrelid = tc.oid AND ta.attnum = fk.attnum
        WHERE con.contype = 'f' AND sn.nspname = ANY(%s)
        GROUP BY con.conname, sn.nspname, sc.relname, tn.nspname, tc.relname
        ORDER BY sn.nspname, sc.relname, con.conname
        """, (schemas,))
    return [{
        'name': row[0], 'source_schema': row[1], 'source_table': row[2],
        'target_schema': row[3], 'target_table': row[4],
        'source_columns': row[5], 'target_columns': row[6],
    } for row in cursor.fetchall()]
