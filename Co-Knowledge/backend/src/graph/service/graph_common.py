"""图谱读路径的公共件：SchemaIndex、属性条件拼装、原始行展平。

两套读接口共用**完全相同**的 ``SchemaIndex`` 构造、实体/边转换与属性条件构造。
这里收成一份 —— 两处逻辑完全相同，合并不会引入差异。

## 三个容易看漏的点

1. **``properties`` 在 SchemaIndex 里只当 List 认**（review/query 的实现如此；
   实体/边的写服务额外支持 Map 形态）。所以 ``{"properties": {"a": {...}}}`` 这种
   模式下，主键/展示字段/属性白名单**全都取不到**，展平出来就是 ``{}`` + 兜底值。
2. **属性是做「白名单 + 补空串」**，不是过滤掉未声明的键那么简单：
   凡 schema 里声明的属性名，行里没有或值为 null 的，一律补 **``""``**。
   schema 没声明任何属性时给 ``{}``。
3. **``entityId`` 与 ``entityName`` 有兜底链**：``entity_id`` 属性 → 按主键组合
   （多个主键用 ``|`` 连）→ 空串；展示字段取不到时回落成 entityId。
"""

from __future__ import annotations

import json
from typing import Any, Optional

from graph.constants import GRAPH_ROW_SYSTEM_FIELDS

# ``GraphQueryServiceImpl`` 的常量
DEFAULT_DISPLAY_FIELD = 'name'
DEFAULT_PRIMARY_KEYS = ('id',)


def schema_obj(kbase: Optional[dict]) -> Optional[dict]:
    """取 ``kb_kbase.schema_obj`` 并**尽力**转成 dict。

    PG 那边这一列是 jsonb，正常取出来就是 dict；也接受 JSON 字符串输入，
    所以这里兜一层 ``json.loads``。解析不了就当「没 schema」返回 None ——
    调用方一律按「schema 为空 = 回空结果」处理，**不报错**。
    """
    raw = (kbase or {}).get('schema_obj')
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


class SchemaIndex:
    """从 ``kb_kbase.schema_obj`` 里抽出来的索引。

    构造只读 ``entities`` / ``edges`` 两个数组；两者缺一就给空集合（不报错）。
    """

    def __init__(self, schema_obj: Optional[dict]):
        schema_obj = schema_obj or {}
        entities = schema_obj.get('entities') if isinstance(schema_obj.get('entities'), list) else []
        edges = schema_obj.get('edges') if isinstance(schema_obj.get('edges'), list) else []

        self.entity_types = {entity.get('entity_type') for entity in entities}
        self.edge_types = {edge.get('edge_type') for edge in edges}
        self.entity_primary_keys = {entity.get('entity_type'): _extract_primary_keys(entity)
                                    for entity in entities}
        self.edge_primary_keys = {edge.get('edge_type'): _extract_primary_keys(edge)
                                  for edge in edges}
        self.entity_display_fields = {entity.get('entity_type'): _extract_display_field(entity)
                                      for entity in entities}
        self.entity_properties = {entity.get('entity_type'): _extract_property_names(entity)
                                  for entity in entities}
        self.edge_properties = {edge.get('edge_type'): _extract_property_names(edge)
                                for edge in edges}


def _property_list(definition: dict) -> Optional[list]:
    """**只认 List 形态**（见模块注释第 1 条）。"""
    properties = definition.get('properties')
    return properties if isinstance(properties, list) else None


def _extract_primary_keys(definition: dict) -> list[str]:
    """按 ``primary_keys`` → ``primaryKeys`` → ``pk`` → ``pks`` 的顺序取第一个非空列表。"""
    for field in ('primary_keys', 'primaryKeys', 'pk', 'pks'):
        value = definition.get(field)
        if isinstance(value, list) and value:
            return [str(item) for item in value]

    properties = _property_list(definition)
    if properties:
        primary = [str(prop.get('name')) for prop in properties
                   if prop.get('is_primary') is True]
        if primary:
            return primary
    return list(DEFAULT_PRIMARY_KEYS)


def _extract_display_field(definition: dict) -> str:
    properties = _property_list(definition) or []
    for prop in properties:
        if prop.get('is_primary') is True:
            return prop.get('name')
    if properties:
        return properties[0].get('name')
    return DEFAULT_DISPLAY_FIELD


def _extract_property_names(definition: dict) -> set:
    properties = _property_list(definition)
    if properties is None:
        return set()
    return {prop.get('name') for prop in properties}


# ----------------------------------------------------------------------
# 展平
# ----------------------------------------------------------------------


def _without_system_fields(row: dict) -> dict:
    """剔除 ``@*`` 与 ``out``/``in``/``#labels``，并**丢掉值为 null 的键**。"""
    result = {}
    for key, value in row.items():
        if key in GRAPH_ROW_SYSTEM_FIELDS:
            continue
        if value is None:
            continue
        result[key] = value
    return result


def _schema_filtered(properties: dict, declared: set) -> dict:
    """白名单 + **缺失补空串**；schema 没声明属性时给 ``{}``。"""
    if not declared:
        return {}
    return {name: ('' if properties.get(name) is None else properties[name])
            for name in declared}


def _derive_entity_id(properties: dict, primary_keys: list[str]) -> str:
    """``entity_id`` 属性优先；否则按主键取值组合（多个用 ``|``）。"""
    if properties.get('entity_id') is not None:
        return str(properties['entity_id'])
    values = [str(properties[key]) for key in primary_keys if properties.get(key) is not None]
    if not values:
        return ''
    return '|'.join(values) if len(values) > 1 else values[0]


def to_entity(row: dict, schema: SchemaIndex) -> Optional[dict]:
    """``convertToEntityFromOrient``。缺 ``@class`` 的行**被静默丢弃**（返回 None）。"""
    entity_type = row.get('@class')
    if entity_type is None:
        return None

    properties = _without_system_fields(row)
    entity_id = _derive_entity_id(properties, schema.entity_primary_keys.get(entity_type) or [])
    display_field = schema.entity_display_fields.get(entity_type) or DEFAULT_DISPLAY_FIELD
    entity_name = properties.get(display_field)
    entity_name = entity_id if entity_name is None else str(entity_name)

    return {
        'entity_id': entity_id,
        'entity_type': entity_type,
        'entity_name': entity_name,
        'properties': _schema_filtered(properties, schema.entity_properties.get(entity_type, set())),
    }


def to_edge(row: dict, schema: SchemaIndex) -> dict:
    """``convertToEdgeFromOrient``。

    ``edgeId`` 取不到时是 **null**（不是空串）；``sourceId``/``targetId`` 取不到时
    回落成 ``out``/``in`` 的**原始 RID**（字符串化）。
    """
    properties = _without_system_fields(row)
    edge_type = row.get('@class')

    def identifier(name: str, fallback_key: str) -> Any:
        value = properties.get(name)
        if value is not None:
            return value
        return str(row.get(fallback_key, ''))

    return {
        'edge_id': None if properties.get('edge_id') is None else properties['edge_id'],
        'edge_type': edge_type,
        'source_id': identifier('source_id', 'out'),
        'target_id': identifier('target_id', 'in'),
        'properties': _schema_filtered(properties, schema.edge_properties.get(edge_type, set())),
    }


# ----------------------------------------------------------------------
# 属性条件（review 与 query 各有一份，细节不同）
# ----------------------------------------------------------------------


def escape_sql_value(value: str) -> str:
    """``escapeSqlValue``：**先转义反斜杠再转义单引号**（顺序要紧）。

    不先处理反斜杠的话，``\\"`` 之类的序列会让图存储
    把后面那个 ``:`` 当成命名参数，报词法错误。
    """
    return str(value).replace('\\', '\\\\').replace("'", "\\'")


def format_sql_value(value: Any) -> str:
    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return '[' + ','.join(format_sql_value(item) for item in value) + ']'
    return "'" + escape_sql_value(value) + "'"


def backtick(key: str) -> str:
    if key.startswith('@') or (key.startswith('`') and key.endswith('`')):
        return key
    return f'`{key}`'


def simple_property_condition(key: str, value: Any, *, use_backtick: bool = True) -> str:
    """标量/列表的字面条件。

    ``None`` → ``key IS NULL``；空列表 → ``FALSE``；列表 → ``key IN [...]``。
    ``use_backtick`` 用来区分 query（加反引号）与 review（**不加**）—— 两边实现不同。
    """
    name = backtick(key) if use_backtick else key
    if value is None:
        return f'{name} IS NULL'
    if isinstance(value, (list, tuple)):
        if not value:
            return 'FALSE'
        return f'{name} IN [' + ','.join(format_sql_value(item) for item in value) + ']'
    if isinstance(value, str):
        return f"{name} = '{escape_sql_value(value)}'"
    return f'{name} = {format_sql_value(value)}'
