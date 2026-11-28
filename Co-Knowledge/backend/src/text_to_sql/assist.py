"""AI 辅助：为语义层给出「建议」，不落库、不改配置。

三个场景：

* ``descriptions`` —— 表/字段的业务名称、说明、别名与语义类型；
* ``tables`` —— 按业务主题推荐纳入查询范围的表；
* ``values`` —— 为已收录的枚举原始值补业务名称与别名。

调用方（service）负责取目录与外部库连接；这里只做「组织证据 → 调模型 → 校验
输出」。模型输出必须能对回目录里的真实 id，编造的对象直接丢弃——建议只用于
人工确认，写入仍走既有的 PATCH 接口。
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

import psycopg2

from text_to_sql import sql_ast
from text_to_sql.errors import SqlGuardError, Text2SqlUpstreamError
from text_to_sql.sql_guard import extract_json_object

KINDS = ('descriptions', 'tables', 'values', 'relations', 'metrics')
_AGGREGATE = re.compile(r'\b(sum|count|avg|min|max)\s*\(', re.IGNORECASE)
_KEY_PATTERN = re.compile(r'^[a-z][a-z0-9_]{1,63}$')
MAX_TABLES = 12
MAX_PROMPT_TABLES = 150
MAX_VALUES = 200
MAX_SAMPLE_ROWS = 3
SAMPLE_TEXT_LIMIT = 80
MAX_NAME = 255
MAX_DESCRIPTION = 4000
MAX_ALIASES = 8
SEMANTIC_TYPES = ('identifier', 'measure', 'dimension', 'time', 'category')

_SYSTEM = (
    '你是数据治理助手，为 Text2SQL 语义层补全业务语义。只输出一个 JSON 对象，'
    '不要 Markdown，不要解释 JSON 之外的内容。只能引用输入里给出的 id，'
    '禁止编造表、字段或取值。中文表达简洁、可判断：名称用业务术语（不超过 12 字），'
    '说明写清「这一列在业务上表示什么、怎么用」，不要复述英文列名。'
)


def prompt_for(kind: str, *, datasource: dict, tables: list[dict],
               relations: list[dict], values: list[dict],
               samples: dict[str, list[dict]],
               question: str = '',
               metrics: Optional[list[dict]] = None) -> tuple[str, str]:
    """返回 ``(system, user)``。tables 需带 ``columns``。"""
    metrics = metrics or []
    header = {
        '数据源': datasource.get('name'),
        '数据库': datasource.get('database'),
        '业务说明': datasource.get('business_description') or '',
        '主题': datasource.get('topic_name') or '',
        '主题说明': datasource.get('topic_description') or '',
    }
    if kind == 'tables':
        payload = {
            '数据源': header,
            '主题问题': question,
            '候选表': [_table_brief(table) for table in tables[:MAX_PROMPT_TABLES]],
            '关系': _relations(relations),
        }
        task = (
            '任务：根据主题问题，从候选表里选出 8–12 张真正需要用于查询的表，'
            '按相关度排序。输出 {"tables":[{"id":"表id","reason":"一句话理由"}]}。'
            '只选业务实体表或事实表，不要选日志、任务队列、密钥、审计之类的内部表。')
    elif kind == 'relations':
        payload = {
            '数据源': header,
            '表与字段': [_table_with_columns(table) for table in tables],
            '已有关系': _relations(relations),
            '样本': samples,
        }
        task = (
            '任务：推断查询需要、但数据库里没有外键的关联。依据：同名字段、'
            '形如 <表名>_id 的字段、样本里取值互相匹配的字段。'
            '输出 {"relations":[{"sourceTableId":"表id","sourceColumnName":"字段名",'
            '"targetTableId":"表id","targetColumnName":"字段名",'
            '"cardinality":"ONE_TO_ONE|ONE_TO_MANY|MANY_TO_ONE|MANY_TO_MANY",'
            '"reason":"一句话依据"}]}。'
            '只给出高置信度的关联；不要与已有关系重复；同一对字段只输出一次；'
            '没有把握就少输出。')
    elif kind == 'questions':
        payload = {
            '数据源': header,
            '表与字段': [_table_brief(table) for table in tables],
            '已有指标': [metric.get('business_name') or metric.get('metric_key')
                         for metric in metrics],
        }
        task = (
            '任务：为提问框生成 6 个业务问题示例，像业务同学会问出口的话，'
            '覆盖不同维度（趋势、占比、对比、明细、异常）。'
            '每个问题都要能只用给定表/指标回答，不要出现英文表名。'
            '输出 {"questions":[{"question":"问题原文","hint":"用了哪些表/口径"}]}。')
    elif kind == 'metrics':
        payload = {
            '数据源': header,
            '表与字段': [_table_with_columns(table) for table in tables],
            '已有指标': [metric.get('business_name') or metric.get('metric_key')
                         for metric in metrics],
        }
        task = (
            '任务：基于数值字段提出 1–3 个业务指标。表达式只能引用基础表自己的字段，'
            '必须包含聚合函数（SUM/COUNT/AVG/MIN/MAX），例如 '
            'SUM(order_info.pay_amount)、COUNT(DISTINCT user_info.user_id)。'
            '输出 {"metrics":[{"baseTableId":"表id","key":"小写英文key",'
            '"businessName":"业务名称","businessDescription":"口径说明",'
            '"expressionSql":"SUM(...)","unit":"元","reason":"一句话依据"}]}。'
            '不要重复已有指标。')
    elif kind == 'values':
        payload = {
            '数据源': header,
            '表与字段': [_table_with_columns(table) for table in tables],
            '关系': _relations(relations),
            '待解释取值': [_value_brief(value) for value in values[:MAX_VALUES]],
            '样本': samples,
        }
        task = (
            '任务：为每个取值补中文业务名称（如 status=1 → 已支付）和可选别名。'
            '输出 {"values":[{"id":"取值id","businessName":"...","aliases":["..."]}]}。'
            '无法从上下文判断含义的取值不要输出。')
    else:
        payload = {
            '数据源': header,
            '表与字段': [_table_with_columns(table) for table in tables],
            '关系': _relations(relations),
            '样本': samples,
        }
        task = (
            '任务：为每张表的表名和每个字段生成业务名称、说明与别名。'
            '输出 {"tables":[{"id":"表id","businessName":"...",'
            '"businessDescription":"...","aliases":["..."]}],'
            '"columns":[{"id":"字段id","businessName":"...",'
            '"businessDescription":"...","aliases":["..."],'
            '"semanticType":"identifier|measure|dimension|time|category"}]}。'
            '字段说明必须结合类型、主外键与样本判断；id 是主键或外键时 semanticType 用 '
            'identifier；金额、数量、次数用 measure；时间字段用 time；其余维度用 dimension。')
    return _SYSTEM, f'{task}\n\n输入：{json.dumps(payload, ensure_ascii=False, default=str)}'


# ---------------------------------------------------------------------------
# 证据组织
# ---------------------------------------------------------------------------
def _table_brief(table: dict) -> dict[str, Any]:
    return {
        'id': str(table.get('id')),
        '名称': f"{table.get('schema_name')}.{table.get('table_name')}",
        '注释': table.get('db_comment') or '',
        '业务名称': table.get('business_name') or '',
        '已启用': bool(table.get('enabled')),
        '字段': [column.get('column_name') for column in table.get('columns') or []],
    }


def _table_with_columns(table: dict) -> dict[str, Any]:
    return {
        'id': str(table.get('id')),
        '名称': f"{table.get('schema_name')}.{table.get('table_name')}",
        '注释': table.get('db_comment') or '',
        '业务名称': table.get('business_name') or '',
        '业务说明': table.get('business_description') or '',
        '字段': [_column_brief(column) for column in table.get('columns') or []],
    }


def _column_brief(column: dict) -> dict[str, Any]:
    item = {
        'id': str(column.get('id')),
        '名称': column.get('column_name'),
        '类型': column.get('data_type'),
        '主键': bool(column.get('is_primary_key')),
        '可空': bool(column.get('is_nullable')),
    }
    if column.get('is_unique'):
        item['唯一'] = True
    if column.get('db_comment'):
        item['注释'] = column['db_comment']
    if column.get('business_name'):
        item['业务名称'] = column['business_name']
    if column.get('business_description'):
        item['业务说明'] = column['business_description']
    if column.get('semantic_type'):
        item['语义类型'] = column['semantic_type']
    if column.get('distinct_value_count'):
        item['取值数'] = column['distinct_value_count']
    return item


def _relations(relations: list[dict]) -> list[dict]:
    return [{
        '名称': relation.get('relation_name') or relation.get('name'),
        '来源': relation.get('source_table') or relation.get('source'),
        '目标': relation.get('target_table') or relation.get('target'),
        '基数': relation.get('cardinality'),
    } for relation in relations]


def _value_brief(value: dict) -> dict[str, Any]:
    return {
        'id': str(value.get('id')),
        '字段': f"{value.get('table_name')}.{value.get('column_name')}",
        '原始值': value.get('raw_value'),
        '当前业务名称': value.get('business_name') or '',
    }


# ---------------------------------------------------------------------------
# 样本数据（只读）
# ---------------------------------------------------------------------------
def sample_rows(connection: dict, table_keys: list[tuple[str, str]],
                limit: int = MAX_SAMPLE_ROWS) -> dict[str, list[dict[str, Any]]]:
    """每个表取少量样例行；失败不抛错（建议功能不该被样本拖垮）。"""
    if not table_keys:
        return {}
    try:
        conn = psycopg2.connect(
            host=connection.get('host'),
            port=connection.get('port') or 5432,
            dbname=connection.get('database'),
            user=connection.get('username'),
            password=connection.get('password') or '',
            connect_timeout=8,
            application_name='co-knowledge-text2sql',
            options='-c statement_timeout=3000',
        )
    except psycopg2.Error:
        return {}
    try:
        conn.set_session(readonly=True, autocommit=True)
        result: dict[str, list[dict[str, Any]]] = {}
        with conn.cursor() as cursor:
            for schema, table in table_keys:
                key = f'{schema}.{table}'
                try:
                    cursor.execute(
                        'SELECT * FROM "{}"."{}" LIMIT {}'.format(
                            schema.replace('"', '""'), table.replace('"', '""'),
                            int(limit)))
                    names = [item[0] for item in cursor.description or []]
                    result[key] = [
                        {name: _scalar(value) for name, value in zip(names, row)}
                        for row in cursor.fetchall()
                    ]
                except psycopg2.Error:
                    continue
        return result
    finally:
        conn.close()


def _scalar(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = value if isinstance(value, str) else str(value)
    return text[:SAMPLE_TEXT_LIMIT]


# ---------------------------------------------------------------------------
# 模型调用与结果校验
# ---------------------------------------------------------------------------
def call_model(system: str, user: str,
               model: Optional[str] = None) -> tuple[str, dict[str, Any], str]:
    """调用注册表里的生成模型，返回 ``(content, usage, model_name)``。"""
    from model.operator_client import invoke_llm
    from model.resolver import resolve

    try:
        target = resolve('llm', model)
    except Exception as error:                                    # noqa: BLE001
        raise Text2SqlUpstreamError(f'无法解析生成模型：{error}') from error
    endpoint = {
        'url': target.url,
        'model': target.api_model,
        'api_key': target.api_key,
        'thinking_payload': target.thinking_payload,
        'timeout': target.timeout,
    }
    content, usage = invoke_llm(
        [{'role': 'system', 'content': system},
         {'role': 'user', 'content': user}],
        model=target.api_model, temperature=0.0, endpoint=endpoint,
        with_usage=True)
    return content, usage or {}, (target.model_name or target.api_model or '')


def parse_suggestions(kind: str, content: str, *, tables: list[dict],
                      values: list[dict],
                      relations: Optional[list[dict]] = None,
                      metrics: Optional[list[dict]] = None
                      ) -> list[dict[str, Any]]:
    """把模型输出收敛成「只引用真实 id」的建议列表。"""
    payload = extract_json_object(content)
    table_by_id = {str(table['id']): table for table in tables}
    column_by_id = {
        str(column['id']): (table, column)
        for table in tables for column in table.get('columns') or []
    }
    value_by_id = {str(value['id']): value for value in values}
    suggestions: list[dict[str, Any]] = []

    if kind == 'relations':
        return _relation_suggestions(payload, tables, table_by_id, relations or [])
    if kind == 'metrics':
        return _metric_suggestions(payload, table_by_id, metrics or [])
    if kind == 'questions':
        return _question_suggestions(payload)

    if kind == 'tables':
        for item in _items(payload, 'tables'):
            table = table_by_id.get(str(item.get('id')))
            if table is None:
                continue
            suggestions.append({
                'target': 'table',
                'id': str(table['id']),
                'label': f"{table['schema_name']}.{table['table_name']}",
                'reason': _text(item.get('reason'), 300),
                'enabled': bool(table.get('enabled')),
            })
        return suggestions

    if kind == 'values':
        for item in _items(payload, 'values'):
            value = value_by_id.get(str(item.get('id')))
            if value is None:
                continue
            suggestion = _named(item)
            if not suggestion['businessName'] and not suggestion['aliases']:
                continue
            suggestions.append({
                'target': 'value',
                'id': str(value['id']),
                'label': f"{value.get('table_name')}.{value.get('column_name')} = "
                         f"{value.get('raw_value')}",
                'rawValue': value.get('raw_value'),
                **suggestion,
            })
        return suggestions

    for item in _items(payload, 'tables'):
        table = table_by_id.get(str(item.get('id')))
        if table is None:
            continue
        suggestion = _named(item)
        if not suggestion['businessName'] and not suggestion['businessDescription']:
            continue
        suggestions.append({
            'target': 'table',
            'id': str(table['id']),
            'label': f"{table['schema_name']}.{table['table_name']}",
            **suggestion,
        })
    for item in _items(payload, 'columns'):
        found = column_by_id.get(str(item.get('id')))
        if found is None:
            continue
        table, column = found
        suggestion = _named(item)
        semantic = item.get('semanticType')
        if semantic not in SEMANTIC_TYPES:
            semantic = None
        if (not suggestion['businessName'] and not suggestion['businessDescription']
                and not semantic):
            continue
        suggestions.append({
            'target': 'column',
            'id': str(column['id']),
            'tableId': str(table['id']),
            'label': f"{table['schema_name']}.{table['table_name']}."
                     f"{column['column_name']}",
            'semanticType': semantic,
            **suggestion,
        })
    return suggestions[:300]


CARDINALITIES = ('ONE_TO_ONE', 'ONE_TO_MANY', 'MANY_TO_ONE', 'MANY_TO_MANY')


def _question_suggestions(payload: dict) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in _items(payload, 'questions'):
        question = _text(item.get('question'), 200)
        if not question or question in seen:
            continue
        seen.add(question)
        suggestions.append({
            'target': 'question',
            'id': f'q{len(suggestions) + 1}',
            'label': question,
            'title': question[:24],
            'question': question,
            'hint': _text(item.get('hint'), 200),
        })
    return suggestions[:8]


def _relation_suggestions(payload: dict, tables: list[dict],
                          table_by_id: dict[str, dict],
                          relations: list[dict]) -> list[dict[str, Any]]:
    existing = _existing_pairs(relations)
    used_names = {str(item.get('relation_name') or '').lower()
                  for item in relations}
    seen: set[tuple[str, str, str, str]] = set()
    suggestions: list[dict[str, Any]] = []
    for item in _items(payload, 'relations'):
        source = table_by_id.get(str(item.get('sourceTableId')))
        target = table_by_id.get(str(item.get('targetTableId')))
        if source is None or target is None or source is target:
            continue
        source_column = _column_named(source, item.get('sourceColumnName'))
        target_column = _column_named(target, item.get('targetColumnName'))
        if source_column is None or target_column is None:
            continue
        key = (str(source['id']), str(source_column['id']),
               str(target['id']), str(target_column['id']))
        reverse = (key[2], key[3], key[0], key[1])
        if key in existing or key in seen or reverse in existing:
            continue
        seen.add(key)
        cardinality = str(item.get('cardinality') or '').upper()
        if cardinality not in CARDINALITIES:
            cardinality = 'MANY_TO_ONE'
        name = _unique_relation_name(source, target, used_names)
        source_label = (f"{source['schema_name']}.{source['table_name']}."
                        f"{source_column['column_name']}")
        target_label = (f"{target['schema_name']}.{target['table_name']}."
                        f"{target_column['column_name']}")
        suggestions.append({
            'target': 'relation',
            'id': f'{source_label}->{target_label}',
            'label': f'{source_label} → {target_label}',
            'name': name,
            'sourceTableId': str(source['id']),
            'targetTableId': str(target['id']),
            'cardinality': cardinality,
            'columnPairs': [{'sourceColumnId': str(source_column['id']),
                             'targetColumnId': str(target_column['id'])}],
            'reason': _text(item.get('reason'), 300),
        })
    return suggestions[:100]


def _existing_pairs(relations: list[dict]) -> set[tuple[str, str, str, str]]:
    pairs = set()
    for relation in relations:
        source_table = str(relation.get('source_table_id') or '')
        target_table = str(relation.get('target_table_id') or '')
        for pair in relation.get('column_pairs') or []:
            pairs.add((source_table, str(pair.get('source_column_id') or ''),
                       target_table, str(pair.get('target_column_id') or '')))
    return pairs


def _column_named(table: dict, name: Any) -> Optional[dict]:
    wanted = str(name or '').strip().lower()
    if not wanted:
        return None
    for column in table.get('columns') or []:
        if str(column.get('column_name') or '').lower() == wanted:
            return column
    return None


def _unique_relation_name(source: dict, target: dict,
                          used: set[str]) -> str:
    base = re.sub(r'[^a-z0-9_]+', '_',
                  f"inferred_{source['table_name']}_{target['table_name']}".lower())
    base = base[:60].strip('_') or 'inferred_relation'
    name, index = base, 1
    while name in used:
        index += 1
        name = f'{base}_{index}'
    used.add(name)
    return name


def _metric_suggestions(payload: dict, table_by_id: dict[str, dict],
                        metrics: list[dict]) -> list[dict[str, Any]]:
    used = {str(item.get('metric_key') or '').lower() for item in metrics}
    suggestions: list[dict[str, Any]] = []
    for item in _items(payload, 'metrics'):
        table = table_by_id.get(str(item.get('baseTableId')))
        if table is None:
            continue
        expression = _text(item.get('expressionSql'), 4000)
        if not expression or not _metric_expression_ok(table, expression):
            continue
        business_name = _text(item.get('businessName'), MAX_NAME)
        if not business_name:
            continue
        key = _text(item.get('key'), 64).lower()
        if not _KEY_PATTERN.match(key):
            key = re.sub(r'[^a-z0-9_]+', '_',
                         f"{table['table_name']}_{business_name}".lower()).strip('_')[:60]
        if not key or not _KEY_PATTERN.match(key):
            key = f"metric_{len(suggestions) + 1}"
        base_key, index = key, 1
        while key in used:
            index += 1
            key = f'{base_key[:58]}_{index}'
        used.add(key)
        suggestions.append({
            'target': 'metric',
            'id': f'{table["schema_name"]}.{table["table_name"]}:{key}',
            'label': f'{business_name} = {expression}',
            'key': key,
            'businessName': business_name,
            'businessDescription': _text(item.get('businessDescription'),
                                         MAX_DESCRIPTION),
            'baseTableId': str(table['id']),
            'baseTable': f"{table['schema_name']}.{table['table_name']}",
            'expressionSql': expression,
            'unit': _text(item.get('unit'), 64),
            'reason': _text(item.get('reason'), 300),
        })
    return suggestions[:50]


def _metric_expression_ok(table: dict, expression: str) -> bool:
    """表达式必须能作为该表的只读聚合查询通过 AST 白名单。"""
    if not _AGGREGATE.search(expression):
        return False
    schema = _quote(table.get('schema_name'))
    name = _quote(table.get('table_name'))
    sql = f'SELECT {expression} AS value FROM {schema}.{name}'
    snapshot = {'tables': [{
        'schema': table.get('schema_name'),
        'name': table.get('table_name'),
        'columns': [{'name': column.get('column_name')}
                    for column in table.get('columns') or []],
    }]}
    try:
        sql_ast.validate(sql, snapshot)
    except SqlGuardError:
        return False
    return True


def _quote(value: Any) -> str:
    return '"' + str(value or '').replace('"', '""') + '"'


def _items(payload: dict, key: str) -> list[dict]:
    items = payload.get(key)
    return [item for item in items if isinstance(item, dict)] \
        if isinstance(items, list) else []


def _named(item: dict) -> dict[str, Any]:
    aliases = item.get('aliases')
    cleaned: list[str] = []
    if isinstance(aliases, list):
        for alias in aliases:
            text = _text(alias, 64)
            if text and text not in cleaned:
                cleaned.append(text)
    return {
        'businessName': _text(item.get('businessName'), MAX_NAME),
        'businessDescription': _text(item.get('businessDescription'), MAX_DESCRIPTION),
        'aliases': cleaned[:MAX_ALIASES],
    }


def _text(value: Any, limit: int) -> str:
    return str(value).strip()[:limit] if value is not None else ''
