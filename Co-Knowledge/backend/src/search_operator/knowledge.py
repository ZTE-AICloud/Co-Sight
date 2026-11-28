"""索引 mapping → 知识对象。

一个索引的「结构」就是它的 mapping：索引名 + 每个字段的名字、类型、分词器。
把这些投影成 ``INDEX`` / ``FIELD`` 两类知识，检索时模型才能知道
「哪个字段适合做全文匹配、哪个适合做范围过滤」。
"""

from __future__ import annotations

from typing import Any, Iterable

from knowledge_engine.object import KnowledgeObject

#: 这些类型适合全文 match；其余类型只能做 term/range/exists。
TEXT_TYPES = {'text'}
KEYWORD_TYPES = {'keyword', 'constant_keyword'}
NUMERIC_TYPES = {'long', 'integer', 'short', 'byte', 'double', 'float', 'half_float',
                 'scaled_float', 'unsigned_long'}
DATE_TYPES = {'date', 'date_nanos'}


def build_objects(index: str, properties: dict[str, Any],
                  *, max_fields: int = 500) -> list[KnowledgeObject]:
    """把 mapping 的 ``properties`` 摊平成知识对象（嵌套对象用点号路径）。"""
    objects: list[KnowledgeObject] = [KnowledgeObject(
        object_type='INDEX',
        object_key=index,
        title=index,
        content=f'索引 {index}。字段：'
                + '、'.join(path for path, _spec in _flatten(properties))[:1500],
        metadata={'index': index},
    )]
    for path, spec in _flatten(properties, max_fields=max_fields):
        if spec is None:
            continue
        field_type = str(spec.get('type') or 'object')
        analyzer = (spec.get('analyzer') or (spec.get('fields') or {})
                    .get('keyword', {}).get('analyzer') or '')
        hint = _usage_hint(field_type)
        content = f'字段 {path}（{field_type}{"，分词器 " + analyzer if analyzer else ""}）。{hint}'
        objects.append(KnowledgeObject(
            object_type='FIELD',
            object_key=path,
            title=path,
            content=content,
            metadata={'index': index, 'field': path, 'type': field_type},
        ))
    return objects


def field_types(properties: dict[str, Any]) -> dict[str, str]:
    return {path: str(spec.get('type') or 'object')
            for path, spec in _flatten(properties) if spec is not None}


def _flatten(properties: dict[str, Any], prefix: str = '',
             max_fields: int = 500) -> Iterable[tuple[str, dict[str, Any]]]:
    count = 0
    for name, spec in (properties or {}).items():
        if count >= max_fields:
            return
        count += 1
        path = f'{prefix}{name}'
        yield path, spec
        if isinstance(spec, dict) and isinstance(spec.get('properties'), dict):
            yield from _flatten(spec['properties'], f'{path}.', max_fields - count)


def _usage_hint(field_type: str) -> str:
    if field_type in TEXT_TYPES:
        return '可用 match / match_phrase 做全文检索。'
    if field_type in KEYWORD_TYPES:
        return '可用 term / terms 做精确过滤，也可用 match。'
    if field_type in NUMERIC_TYPES:
        return '可用 range 做数值过滤，或用 term 精确匹配。'
    if field_type in DATE_TYPES:
        return '可用 range（gte/lte）做时间过滤。'
    return '可用 exists 判断是否存在。'
