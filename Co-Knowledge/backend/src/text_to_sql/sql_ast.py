"""SQL 结构校验：PostgreSQL 官方语法树（pglast / libpg_query）。

这里是 Text2SQL 的**结构安全边界**。与「字符串正则 + 关键词黑名单」不同，
判定对象是解析后的 AST：

* 只承认单条 ``SELECT`` / ``WITH ... SELECT``（集合运算按两侧 SelectStmt 递归）；
* 拒绝 ``SELECT INTO``、``FOR UPDATE/SHARE``、函数调用出现在 FROM；
* 表名必须落在当前冻结快照的白名单里（CTE 名除外）；
* 字段必须存在于该语句作用域内的白名单表中；
* 函数必须落在 :data:`ALLOWED_FUNCTIONS`（白名单，默认拒绝）。

**字符串字面量永远不参与判定。** 它是 AST 里的 ``A_Const``，不是 SQL 片段；
因此 ``query_to_xml('SELECT ... FROM pg_catalog.pg_class')`` 这类把 SQL 塞进字面量的
写法既不会被误当成表名，也不会因此获得任何权限——它只会因为 ``query_to_xml``
不在函数白名单里被拒绝。
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from pglast import parser

from text_to_sql.errors import SqlGuardError

#: 允许出现在生成 SQL 里的函数（小写、不带 schema 前缀）。
#: 默认拒绝：不在名单里的函数一律报 ``SQL_FUNCTION_NOT_ALLOWED``。
#: 只收「无副作用 + 不读服务器文件/系统视图 + 不执行动态 SQL」的分析函数。
ALLOWED_FUNCTIONS = frozenset({
    # 聚合
    'count', 'sum', 'avg', 'min', 'max', 'stddev', 'stddev_pop', 'stddev_samp',
    'variance', 'var_pop', 'var_samp', 'array_agg', 'string_agg', 'bool_and',
    'bool_or', 'every', 'percentile_cont', 'percentile_disc', 'mode',
    # 窗口
    'row_number', 'rank', 'dense_rank', 'percent_rank', 'cume_dist', 'ntile',
    'lag', 'lead', 'first_value', 'last_value', 'nth_value',
    # 字符串
    'lower', 'upper', 'initcap', 'btrim', 'ltrim', 'rtrim', 'trim', 'length',
    'char_length', 'character_length', 'octet_length', 'bit_length',
    'substring', 'substr', 'replace', 'concat', 'concat_ws', 'left', 'right',
    'lpad', 'rpad', 'repeat', 'reverse', 'split_part', 'strpos', 'position',
    'starts_with', 'translate', 'md5', 'to_hex',
    # 数值
    'abs', 'ceil', 'ceiling', 'floor', 'round', 'trunc', 'sign', 'sqrt',
    'cbrt', 'power', 'pow', 'exp', 'ln', 'log', 'log10', 'mod', 'div',
    'width_bucket',
    # 日期时间
    'date_trunc', 'date_part', 'extract', 'age', 'make_date', 'make_time',
    'make_timestamp', 'make_interval', 'to_char', 'to_date', 'to_number',
    'to_timestamp', 'timezone', 'justify_days', 'justify_hours',
    'justify_interval', 'date_bin', 'isfinite', 'now',
    # 空值/类型
    'coalesce', 'nullif', 'cast',
    # JSON（只读构造与取值）
    'jsonb_build_object', 'json_build_object', 'jsonb_agg', 'json_agg',
    'jsonb_extract_path_text', 'json_extract_path_text', 'to_jsonb', 'to_json',
    # 数组
    'array_length', 'cardinality', 'array_position', 'array_to_string',
})

#: 出现在 FROM 里的函数（``RangeFunction``）一律拒绝：行数不可控。
_ALLOWED_SET_OPERATIONS = frozenset({'SETOP_NONE', 'SETOP_UNION',
                                     'SETOP_INTERSECT', 'SETOP_EXCEPT'})


def validate(sql: str, snapshot: dict[str, Any]) -> str:
    """解析并校验 SQL；通过则原样返回（尾分号由调用方处理）。

    失败抛 :class:`SqlGuardError`，``code`` 取值：
    ``SQL_SYNTAX`` / ``SQL_UNSAFE`` / ``SQL_TABLE_NOT_ALLOWED`` /
    ``SQL_COLUMN_NOT_ALLOWED`` / ``SQL_FUNCTION_NOT_ALLOWED``。
    """
    statements = _parse(sql)
    if len(statements) != 1:
        raise SqlGuardError('SQL_UNSAFE', '只允许单条 SQL Statement')
    statement = statements[0].get('stmt') or {}
    if 'SelectStmt' not in statement:
        raise SqlGuardError('SQL_UNSAFE', '只允许 SELECT 查询')
    _SelectValidator(_Catalog(snapshot)).select(statement['SelectStmt'], {})
    return sql


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------
def _parse(sql: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(parser.parse_sql_json(sql))
    except parser.ParseError as error:
        raise SqlGuardError('SQL_SYNTAX', f'SQL 无法解析：{_parse_error_text(error)}') \
            from error
    except (ValueError, TypeError) as error:
        raise SqlGuardError('SQL_SYNTAX', 'SQL 无法解析') from error
    return payload.get('stmts') or []


def _parse_error_text(error: BaseException) -> str:
    text = str(error).strip().splitlines()[0] if str(error).strip() else ''
    return text[:200] or '语法错误'


# ---------------------------------------------------------------------------
# 白名单目录
# ---------------------------------------------------------------------------
class _Catalog:
    """冻结快照的表/列索引（表名、列名统一按小写比对）。"""

    def __init__(self, snapshot: dict[str, Any]):
        self._columns: dict[tuple[str, str], set[str]] = {}
        self._by_bare_name: dict[str, list[tuple[str, str]]] = {}
        for table in snapshot.get('tables') or []:
            key = (str(table.get('schema') or '').lower(),
                   str(table.get('name') or '').lower())
            if not key[1]:
                continue
            self._columns[key] = {
                str(column.get('name') or '').lower()
                for column in table.get('columns') or []
            }
            self._by_bare_name.setdefault(key[1], []).append(key)

    def is_allowed(self, schema: Optional[str], name: str) -> bool:
        """表是否在白名单内。无 schema 前缀时，同名表任一在名单内即放行。"""
        if schema:
            return (schema.lower(), name.lower()) in self._columns
        return bool(self._by_bare_name.get(name.lower()))

    def columns_of(self, schema: Optional[str], name: str) -> Optional[set[str]]:
        """返回表的列集合；无法唯一确定（同名/未知）时返回 ``None``。"""
        if schema:
            return self._columns.get((schema.lower(), name.lower()))
        matches = self._by_bare_name.get(name.lower()) or []
        return self._columns[matches[0]] if len(matches) == 1 else None


# ---------------------------------------------------------------------------
# 作用域
# ---------------------------------------------------------------------------
class _Scope:
    """一条 SELECT 的可见关系：别名 → 列集合（``None`` = 未知，跳过列校验）。"""

    def __init__(self) -> None:
        self._relations: dict[str, Optional[set[str]]] = {}
        #: SELECT 输出别名。PostgreSQL 允许 ORDER BY / GROUP BY / HAVING 引用它们，
        #: 它们不属于任何基表，必须单独放行。
        self._aliases: set[str] = set()

    def add(self, name: str, columns: Optional[set[str]]) -> None:
        key = name.lower()
        # 同一别名重复出现意味着自关联两次引用同一张表，列集合一致，保留即可。
        if key not in self._relations:
            self._relations[key] = columns

    def allow_alias(self, name: str) -> None:
        self._aliases.add(name.lower())

    def is_opaque(self) -> bool:
        return any(columns is None for columns in self._relations.values())

    def has_relation(self, name: str) -> bool:
        return name.lower() in self._relations

    def knows_column(self, name: str) -> bool:
        lowered = name.lower()
        if lowered in self._aliases:
            return True
        return any(columns and lowered in columns for columns in self._relations.values())

    def columns_for(self, name: str) -> Optional[set[str]]:
        return self._relations.get(name.lower())


class _SelectValidator:
    """递归校验一条 SELECT 及其子查询。"""

    def __init__(self, catalog: _Catalog):
        self._catalog = catalog

    # -- 入口 ---------------------------------------------------------------
    def select(self, node: dict[str, Any],
               outer_ctes: dict[str, Optional[set[str]]]
               ) -> Optional[set[str]]:
        """校验一条 SelectStmt，返回其输出列（无法确定时为 ``None``）。"""
        ctes = dict(outer_ctes)
        self._collect_ctes(node.get('withClause'), ctes)

        if node.get('lockingClause'):
            raise SqlGuardError('SQL_UNSAFE', '不允许加锁读取')
        if node.get('intoClause'):
            raise SqlGuardError('SQL_UNSAFE', '不允许 SELECT INTO')

        operation = node.get('op') or 'SETOP_NONE'
        if operation not in _ALLOWED_SET_OPERATIONS:
            raise SqlGuardError('SQL_UNSAFE', '不支持的集合运算')
        if operation != 'SETOP_NONE':
            # 集合运算：两侧各自成域（libpg_query 把两侧的 SelectStmt 内联，不再包一层）。
            for side in (node.get('larg') or {}, node.get('rarg') or {}):
                if not _is_select_body(side):
                    raise SqlGuardError('SQL_UNSAFE', '只允许 SELECT 查询')
                self.select(side, ctes)
            return None

        from_clause = node.get('fromClause') or []
        if len(from_clause) > 1 and any('JoinExpr' not in item for item in from_clause):
            raise SqlGuardError('SQL_UNSAFE', '请使用显式 JOIN，不允许多表逗号连接')

        scope = _Scope()
        qualifiers: list[Any] = []
        for item in from_clause:
            self._collect_from(item, ctes, scope, qualifiers)
        for target in node.get('targetList') or []:
            alias = (target.get('ResTarget') or {}).get('name')
            if alias:
                scope.allow_alias(str(alias))

        # 表达式里的列/函数/子查询。
        for clause in ('targetList', 'whereClause', 'groupClause', 'havingClause',
                       'sortClause', 'windowClause', 'distinctClause',
                       'limitCount', 'limitOffset', 'valuesLists'):
            if node.get(clause) is not None:
                qualifiers.append(node[clause])
        for root in qualifiers:
            self._scan(root, scope, ctes)

        return _output_columns(node)

    # -- WITH ---------------------------------------------------------------
    def _collect_ctes(self, with_clause: Optional[dict[str, Any]],
                      ctes: dict[str, Optional[set[str]]]) -> None:
        if not with_clause:
            return
        for item in with_clause.get('ctes') or []:
            cte = item.get('CommonTableExpr') or {}
            name = str(cte.get('ctename') or '')
            if not name:
                continue
            query = cte.get('ctequery') or {}
            if 'SelectStmt' not in query:
                raise SqlGuardError('SQL_UNSAFE', '只允许 SELECT 查询')
            # 先登记为未知再校验，递归 CTE 才能自引用；校验完再回填输出列。
            ctes[name.lower()] = None
            ctes[name.lower()] = self.select(query['SelectStmt'], ctes)

    # -- FROM ---------------------------------------------------------------
    def _collect_from(self, item: dict[str, Any],
                      ctes: dict[str, Optional[set[str]]],
                      scope: _Scope, qualifiers: list[Any]) -> None:
        if 'RangeVar' in item:
            self._add_range_var(item['RangeVar'], ctes, scope)
            return
        if 'JoinExpr' in item:
            join = item['JoinExpr']
            self._collect_from(join.get('larg') or {}, ctes, scope, qualifiers)
            self._collect_from(join.get('rarg') or {}, ctes, scope, qualifiers)
            if join.get('quals') is not None:
                qualifiers.append(join['quals'])
            return
        if 'RangeSubselect' in item:
            sub = item['RangeSubselect']
            query = sub.get('subquery') or {}
            if 'SelectStmt' not in query:
                raise SqlGuardError('SQL_UNSAFE', '只允许 SELECT 查询')
            columns = self.select(query['SelectStmt'], ctes)
            scope.add(_alias_name(sub.get('alias')) or '', columns)
            return
        if 'RangeFunction' in item:
            raise SqlGuardError('SQL_UNSAFE', '不允许在 FROM 中调用函数')
        # TABLESAMPLE / 其它未识别的 FROM 项：保守拒绝。
        raise SqlGuardError('SQL_UNSAFE', '不支持的 FROM 子句')

    def _add_range_var(self, range_var: dict[str, Any],
                       ctes: dict[str, Optional[set[str]]],
                       scope: _Scope) -> None:
        schema = range_var.get('schemaname')
        name = str(range_var.get('relname') or '')
        if not name:
            raise SqlGuardError('SQL_TABLE_NOT_ALLOWED', '无法识别的表引用')
        if not schema and name.lower() in ctes:
            scope.add(_alias_name(range_var.get('alias')) or name,
                      ctes[name.lower()])
            return
        if not self._catalog.is_allowed(schema, name):
            display = f'{schema}.{name}' if schema else name
            raise SqlGuardError('SQL_TABLE_NOT_ALLOWED',
                                f'表 {display} 不在当前查询范围内')
        alias = _alias_name(range_var.get('alias')) or name
        scope.add(alias, self._catalog.columns_of(schema, name))
        if schema is None:
            scope.add(name, self._catalog.columns_of(None, name))

    # -- 表达式 -------------------------------------------------------------
    def _scan(self, node: Any, scope: _Scope,
              ctes: dict[str, Optional[set[str]]]) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == 'SubLink':
                    self._scan_sub_link(value, scope, ctes)
                    continue
                if key == 'SelectStmt':
                    continue
                if key == 'ColumnRef':
                    self._check_column(value, scope)
                elif key == 'FuncCall':
                    self._check_function(value)
                self._scan(value, scope, ctes)
            return
        if isinstance(node, list):
            for value in node:
                self._scan(value, scope, ctes)

    def _scan_sub_link(self, sub_link: dict[str, Any], scope: _Scope,
                       ctes: dict[str, Optional[set[str]]]) -> None:
        subselect = sub_link.get('subselect') or {}
        if 'SelectStmt' in subselect:
            self.select(subselect['SelectStmt'], ctes)
            return
        # EXISTS/IN 之外的形态（如 ARRAY 子查询）：保守拒绝。
        raise SqlGuardError('SQL_UNSAFE', '不支持子查询形态')

    def _check_column(self, column_ref: dict[str, Any], scope: _Scope) -> None:
        fields = [item.get('String', {}).get('sval')
                  for item in column_ref.get('fields') or [] if 'String' in item]
        if not fields or any('A_Star' in item for item in column_ref.get('fields') or []):
            return
        column = str(fields[-1])
        if len(fields) >= 2:
            qualifier = str(fields[-2])
            if not scope.has_relation(qualifier):
                # 未知别名：可能来自外层查询或不可见域，跳过而不是误杀。
                return
            columns = scope.columns_for(qualifier)
            if columns is None:
                return
            if column.lower() not in columns:
                raise SqlGuardError(
                    'SQL_COLUMN_NOT_ALLOWED',
                    f'字段 {qualifier}.{column} 不在当前查询范围内')
            return
        if scope.is_opaque():
            return
        if not scope.knows_column(column):
            raise SqlGuardError(
                'SQL_COLUMN_NOT_ALLOWED', f'字段 {column} 不在当前查询范围内')

    def _check_function(self, call: dict[str, Any]) -> None:
        names = [item.get('String', {}).get('sval')
                 for item in call.get('funcname') or [] if 'String' in item]
        if not names:
            raise SqlGuardError('SQL_FUNCTION_NOT_ALLOWED', '无法识别的函数调用')
        if len(names) > 1:
            raise SqlGuardError(
                'SQL_FUNCTION_NOT_ALLOWED',
                f'不允许带 schema 前缀的函数调用：{".".join(str(n) for n in names)}')
        name = str(names[-1]).lower()
        if name not in ALLOWED_FUNCTIONS:
            raise SqlGuardError('SQL_FUNCTION_NOT_ALLOWED',
                                f'函数 {name} 不在允许范围内')
        if name == 'sum' and _contains_distinct_aggregate(call.get('args') or []):
            # 非可加指标的典型误用：把去重计数再求和（月度 UV 相加没有意义）。
            raise SqlGuardError(
                'SQL_AGGREGATION_NOT_ALLOWED',
                '去重计数（COUNT DISTINCT）不能再求和；非可加指标请按同一粒度直接'
                '取值，或改用可加指标')


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _alias_name(alias: Optional[dict[str, Any]]) -> Optional[str]:
    if not alias:
        return None
    name = alias.get('aliasname')
    return str(name) if name else None


def _contains_distinct_aggregate(node: Any) -> bool:
    """节点子树里是否有 ``DISTINCT`` 聚合（``count(distinct x)`` 等）。"""
    if isinstance(node, dict):
        call = node.get('FuncCall')
        if isinstance(call, dict) and call.get('agg_distinct'):
            return True
        return any(_contains_distinct_aggregate(value) for value in node.values())
    if isinstance(node, list):
        return any(_contains_distinct_aggregate(value) for value in node)
    return False


def _is_select_body(node: dict[str, Any]) -> bool:
    """``SelectStmt`` 的 JSON 有两种形态：包一层 ``{"SelectStmt": ...}``，或内联。"""
    return 'SelectStmt' in node or 'targetList' in node or 'valuesLists' in node


def _output_columns(node: dict[str, Any]) -> Optional[set[str]]:
    """尽力推断 SELECT 的输出列名；任一列不确定即返回 ``None``。"""
    names: set[str] = set()
    for item in node.get('targetList') or []:
        target = item.get('ResTarget') or {}
        name = target.get('name')
        if not name:
            value = target.get('val') or {}
            column = value.get('ColumnRef') or {}
            fields = [part.get('String', {}).get('sval')
                      for part in column.get('fields') or [] if 'String' in part]
            name = fields[-1] if fields else None
        if not name:
            return None
        names.add(str(name).lower())
    return names or None


def iter_nodes(node: Any) -> Iterable[dict[str, Any]]:
    """遍历 AST 里的全部 dict 节点（调试与测试用）。"""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from iter_nodes(value)
    elif isinstance(node, list):
        for value in node:
            yield from iter_nodes(value)
