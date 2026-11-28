"""冻结快照与检索知识文本的生成（纯函数，无 DB / 网络）。

快照是历史解释的权威来源：进入 BUILDING 后不可修改，检索知识只能从它生成，
不能回头 join 当前 catalog。知识对象的 ``object_key`` 用对象 UUID（稳定、无歧义），
不要用未转义的点号拼接任意 SQL 标识符。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Optional

SNAPSHOT_FORMAT_VERSION = 1


@dataclass(frozen=True)
class KnowledgeDraft:
    object_type: str
    object_key: str
    link_field: str
    title: str
    content: str
    metadata: dict[str, Any]


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'))


def content_hash(value: Any) -> str:
    text = value if isinstance(value, str) else canonical_json(value)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def build_snapshot(*, datasource: dict, tables: list[dict], relations: list[dict],
                   values: list[dict], metrics: list[dict],
                   embedding_model: str, embedding_dimensions: int) -> dict[str, Any]:
    """把当前可发布的工作集收敛成白名单快照（数组按稳定键排序）。"""
    enabled_tables = {str(table['id']) for table in tables}
    snapshot_tables = []
    column_ids: dict[str, set[str]] = {}
    for table in sorted(tables, key=lambda item: (item['schema_name'], item['table_name'])):
        table_id = str(table['id'])
        columns = []
        for column in sorted(table.get('columns') or [],
                             key=lambda item: item['ordinal_position']):
            if not column.get('enabled', True):
                continue
            columns.append({
                'id': str(column['id']),
                'name': column['column_name'],
                'dataType': column['data_type'],
                'ordinalPosition': column['ordinal_position'],
                'nullable': bool(column['is_nullable']),
                'primaryKey': bool(column['is_primary_key']),
                'unique': bool(column['is_unique']),
                'dbComment': column.get('db_comment'),
                'businessName': column.get('business_name'),
                'businessDescription': column.get('business_description'),
                'aliases': list(column.get('business_aliases') or []),
                'semanticType': column.get('semantic_type'),
            })
        column_ids[table_id] = {column['id'] for column in columns}
        snapshot_tables.append({
            'id': table_id,
            'schema': table['schema_name'],
            'name': table['table_name'],
            'tableType': table['table_type'],
            'dbComment': table.get('db_comment'),
            'businessName': table.get('business_name'),
            'businessDescription': table.get('business_description'),
            'aliases': list(table.get('business_aliases') or []),
            'columns': columns,
        })

    snapshot_relations = []
    for relation in relations:
        if not relation.get('enabled', True):
            continue
        if str(relation['source_table_id']) not in enabled_tables:
            continue
        if str(relation['target_table_id']) not in enabled_tables:
            continue
        snapshot_relations.append({
            'id': str(relation['id']),
            'name': relation['relation_name'],
            'type': relation['relation_type'],
            'cardinality': relation.get('cardinality'),
            'description': relation.get('description') or '',
            'sourceTableId': str(relation['source_table_id']),
            'targetTableId': str(relation['target_table_id']),
            'columnPairs': [{
                'sourceColumnId': str(pair['source_column_id']),
                'targetColumnId': str(pair['target_column_id']),
            } for pair in relation.get('column_pairs') or []],
        })

    snapshot_values = []
    for value in values:
        if not value.get('enabled', True):
            continue
        column_id = str(value['column_id'])
        if not _column_in_scope(column_ids, column_id):
            continue
        snapshot_values.append({
            'id': str(value['id']),
            'columnId': column_id,
            'rawValue': value['raw_value'],
            'valueType': value['value_type'],
            'businessName': value.get('business_name'),
            'aliases': list(value.get('aliases') or []),
            'description': value.get('description') or '',
            'sourceType': value['source_type'],
        })

    snapshot_metrics = []
    for metric in metrics:
        if metric.get('status') == 'DISABLED':
            continue
        if str(metric['base_table_id']) not in enabled_tables:
            continue
        snapshot_metrics.append({
            'id': str(metric['id']),
            'key': metric['metric_key'],
            'businessName': metric['business_name'],
            'businessDescription': metric.get('business_description') or '',
            'aliases': list(metric.get('aliases') or []),
            'baseTableId': str(metric['base_table_id']),
            'expressionSql': metric['expression_sql'],
            'filterDefinition': metric.get('filter_definition') or {},
            'timeColumnId': (str(metric['time_column_id'])
                             if metric.get('time_column_id') else None),
            'unit': metric.get('unit'),
            'businessTimezone': metric.get('business_timezone'),
            'aggregationBehavior': metric['aggregation_behavior'],
            'attributionDescription': metric.get('attribution_description') or '',
            'status': metric['status'],
            'columnDependencies': [{
                'columnId': str(item['column_id']),
                'role': item['dependency_role'],
            } for item in metric.get('column_dependencies') or []],
            'relationDependencies': list(metric.get('relation_dependencies') or []),
        })

    return {
        'formatVersion': SNAPSHOT_FORMAT_VERSION,
        'datasource': {
            'id': str(datasource['id']),
            'name': datasource['name'],
            'dbType': datasource['db_type'],
            'host': datasource['host'],
            'port': datasource['port'],
            'database': datasource['database_name'],
            'username': datasource['username'],
            'credentialRef': datasource['credential_ref'],
            'includeSchemas': list(datasource['include_schemas']),
            'businessTimezone': datasource['business_timezone'],
            'queryPolicy': datasource.get('query_policy') or {},
            'businessDescription': datasource.get('business_description') or '',
            'topic': {
                'name': datasource.get('topic_name') or '',
                'description': datasource.get('topic_description') or '',
                'owner': datasource.get('maintainer_ref') or '',
            },
        },
        'tables': sorted(snapshot_tables, key=lambda item: (item['schema'], item['name'])),
        'relations': sorted(snapshot_relations, key=lambda item: item['name']),
        'values': sorted(snapshot_values, key=lambda item: (item['columnId'], item['rawValue'])),
        'metrics': sorted(snapshot_metrics, key=lambda item: item['key']),
        'embedding': {
            'model': embedding_model,
            'dimensions': embedding_dimensions,
        },
    }


def _column_in_scope(column_ids: dict[str, set[str]], column_id: str) -> bool:
    return any(column_id in ids for ids in column_ids.values())


def build_knowledge(snapshot: dict[str, Any]) -> list[KnowledgeDraft]:
    """从冻结快照生成 TABLE/COLUMN/RELATION/VALUE/METRIC 五类知识。"""
    tables = {table['id']: table for table in snapshot['tables']}
    columns = {column['id']: (table, column) for table in snapshot['tables']
               for column in table['columns']}
    drafts: list[KnowledgeDraft] = []

    for table in snapshot['tables']:
        title = f"{table['schema']}.{table['name']}"
        lines = [f"数据表 {title}（{table['tableType']}）。"]
        if table.get('dbComment'):
            lines.append(f"数据库注释：{table['dbComment']}。")
        _append_business(lines, table)
        if table['columns']:
            lines.append('字段：' + '；'.join(
                _column_brief(column) for column in table['columns']) + '。')
        content = ''.join(lines)
        drafts.append(KnowledgeDraft(
            object_type='TABLE', object_key=table['id'], link_field='table_id',
            title=title, content=content,
            metadata={'schema': table['schema'], 'table': table['name']}))

        for column in table['columns']:
            column_title = f"{title}.{column['name']}"
            column_lines = [
                f"字段 {column_title}（{column['dataType']}"
                f"{'，主键' if column['primaryKey'] else ''}"
                f"{'，唯一' if column['unique'] else ''}）。"]
            if column.get('dbComment'):
                column_lines.append(f"数据库注释：{column['dbComment']}。")
            _append_business(column_lines, column)
            if column.get('semanticType'):
                column_lines.append(f"语义类型：{column['semanticType']}。")
            drafts.append(KnowledgeDraft(
                object_type='COLUMN', object_key=column['id'], link_field='column_id',
                title=column_title, content=''.join(column_lines),
                metadata={'schema': table['schema'], 'table': table['name'],
                          'column': column['name']}))

    for relation in snapshot['relations']:
        pairs = _relation_pairs(relation, columns)
        content = (f"关联 {relation['name']}（{relation['type']}"
                   f"{'，' + relation['cardinality'] if relation.get('cardinality') else ''}）："
                   f"{pairs}。")
        if relation.get('description'):
            content += f"说明：{relation['description']}。"
        drafts.append(KnowledgeDraft(
            object_type='RELATION', object_key=relation['id'],
            link_field='relation_id', title=relation['name'], content=content,
            metadata={'type': relation['type'],
                      'cardinality': relation.get('cardinality')}))

    for value in snapshot['values']:
        table, column = columns.get(value['columnId'], (None, None))
        title = (f"{table['schema']}.{table['name']}.{column['name']}"
                 if table and column else value['columnId'])
        content = f"枚举值 {title} = {value['rawValue']}。"
        if value.get('businessName'):
            content += f"业务名称：{value['businessName']}。"
        if value.get('aliases'):
            content += f"同义词：{'、'.join(value['aliases'])}。"
        if value.get('description'):
            content += f"说明：{value['description']}。"
        drafts.append(KnowledgeDraft(
            object_type='VALUE', object_key=value['id'], link_field='value_id',
            title=f"{title} = {value['rawValue']}", content=content,
            metadata={'columnId': value['columnId'], 'rawValue': value['rawValue']}))

    for metric in snapshot['metrics']:
        table = tables.get(metric['baseTableId'])
        content = (f"指标 {metric['businessName']}（{metric['key']}）。")
        if metric.get('businessDescription'):
            content += f"说明：{metric['businessDescription']}。"
        content += f"表达式：{metric['expressionSql']}。"
        if metric.get('filterDefinition'):
            content += f"过滤条件：{canonical_json(metric['filterDefinition'])}。"
        if metric.get('timeColumnId') and metric['timeColumnId'] in columns:
            _, time_column = columns[metric['timeColumnId']]
            content += f"时间字段：{time_column['name']}。"
        if metric.get('unit'):
            content += f"单位：{metric['unit']}。"
        content += f"可加性：{metric['aggregationBehavior']}。"
        if metric.get('attributionDescription'):
            content += f"统计归属：{metric['attributionDescription']}。"
        if table:
            content += f"基础表：{table['schema']}.{table['name']}。"
        drafts.append(KnowledgeDraft(
            object_type='METRIC', object_key=metric['id'], link_field='metric_id',
            title=metric['businessName'], content=content,
            metadata={'key': metric['key'], 'status': metric['status']}))

    return drafts


def _append_business(lines: list[str], item: dict[str, Any]) -> None:
    if item.get('businessName'):
        lines.append(f"业务名称：{item['businessName']}。")
    if item.get('businessDescription'):
        lines.append(f"业务说明：{item['businessDescription']}。")
    if item.get('aliases'):
        lines.append(f"同义词：{'、'.join(item['aliases'])}。")


def _column_brief(column: dict[str, Any]) -> str:
    text = f"{column['name']}({column['dataType']}"
    if column['primaryKey']:
        text += ',主键'
    if column.get('businessDescription'):
        text += f"，{column['businessDescription']}"
    return text + ')'


def _relation_pairs(relation: dict[str, Any],
                    columns: dict[str, tuple[dict, dict]]) -> str:
    parts = []
    for pair in relation['columnPairs']:
        source = columns.get(pair['sourceColumnId'])
        target = columns.get(pair['targetColumnId'])
        if source and target:
            parts.append(f"{source[0]['schema']}.{source[0]['name']}.{source[1]['name']} = "
                         f"{target[0]['schema']}.{target[0]['name']}.{target[1]['name']}")
    return '；'.join(parts) or '列对缺失'


def knowledge_vector_namespace(datasource_id: str, revision: int) -> str:
    return f"text2sql:{datasource_id}:v{revision}"


def link_value(draft: KnowledgeDraft) -> Optional[str]:
    """``t2s_knowledge`` 的对象外键列名（TABLE→table_id …）。"""
    return draft.link_field
