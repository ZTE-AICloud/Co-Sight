"""ES 查询 DSL 的白名单校验。

和 SQL 那边同一条原则：**判定对象是结构，不是字符串**。模型输出的是 JSON，
所以这里直接走结构检查，不存在「把危险内容藏在字面量里」的绕法：

* 顶层只允许 ``query`` / ``size`` / ``from`` / ``sort`` / ``_source`` / ``track_scores``；
* 查询子句只允许 bool / match / match_phrase / term / terms / range / exists /
  match_all / multi_match；
* 递归出现 ``script`` / ``function_score`` / ``script_score`` / ``more_like_this`` /
  ``percolate`` / ``regexp`` / ``wildcard`` 一律拒绝（脚本与高开销子句）；
* 每个叶子字段名必须在该索引的 mapping 里；
* ``size`` 上限 100，递归深度上限 8。
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from knowledge_engine.operator import OperatorError

ALLOWED_TOP_KEYS = {'query', 'size', 'from', 'sort', '_source', 'track_scores'}
ALLOWED_CLAUSES = {'bool', 'match', 'match_phrase', 'term', 'terms', 'range',
                   'exists', 'match_all', 'multi_match'}
DENIED_CLAUSES = {'script', 'script_score', 'function_score', 'more_like_this',
                  'percolate', 'regexp', 'wildcard', 'geo_distance', 'knn'}
BOOL_KEYS = {'must', 'should', 'must_not', 'filter', 'minimum_should_match',
             'boost'}
RANGE_KEYS = {'gte', 'gt', 'lte', 'lt', 'format', 'time_zone', 'boost',
              'relation'}
MAX_SIZE = 100
MAX_DEPTH = 8


def validate(body: Any, allowed_fields: Iterable[str]) -> dict[str, Any]:
    """校验并返回规范化后的查询体；失败抛 :class:`OperatorError`。"""
    if not isinstance(body, dict) or not body:
        raise OperatorError('SEARCH_DSL_INVALID', '查询体必须是 JSON 对象', 'validation')
    unknown = set(body) - ALLOWED_TOP_KEYS
    if unknown:
        raise OperatorError('SEARCH_DSL_INVALID',
                            f'不支持的顶层字段：{", ".join(sorted(unknown))}', 'validation')

    size = body.get('size', 10)
    if not isinstance(size, int) or isinstance(size, bool) or size < 1 or size > MAX_SIZE:
        raise OperatorError('SEARCH_DSL_INVALID', f'size 必须是 1–{MAX_SIZE} 的整数',
                            'validation')
    offset = body.get('from', 0)
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise OperatorError('SEARCH_DSL_INVALID', 'from 必须是非负整数', 'validation')

    fields = set(allowed_fields)
    if body.get('query') is not None:
        _walk(body['query'], fields, depth=0)
    if body.get('sort') is not None:
        _check_sort(body['sort'], fields)
    if body.get('_source') is not None:
        _check_source(body['_source'], fields)
    return body


def _check_sort(spec: Any, fields: set[str]) -> None:
    """``sort`` 可以是 ``["field", ...]``、``[{"field": "asc"}]`` 或 ``{"field": ...}``。"""
    items = spec if isinstance(spec, list) else [spec]
    for item in items:
        names = [item] if isinstance(item, str) else list((item or {}))
        for name in names:
            if name not in fields:
                raise OperatorError('SEARCH_FIELD_NOT_ALLOWED',
                                    f'排序字段 {name} 不在该索引的 mapping 里',
                                    'validation')


def _check_source(spec: Any, fields: set[str]) -> None:
    if isinstance(spec, str):
        names = [spec]
    elif isinstance(spec, list):
        names = [item for item in spec if isinstance(item, str)]
    elif isinstance(spec, dict):
        names = [name for name in spec.get('includes') or [] if isinstance(name, str)]
    else:
        raise OperatorError('SEARCH_DSL_INVALID', '_source 形式不支持', 'validation')
    for name in names:
        if name not in fields:
            raise OperatorError('SEARCH_FIELD_NOT_ALLOWED',
                                f'_source 字段 {name} 不在该索引的 mapping 里',
                                'validation')


def _walk(node: Any, fields: set[str], *, depth: int) -> None:
    """按「子句类型」分派——每种子句里「哪个位置是字段名」的规则不同。"""
    if depth > MAX_DEPTH:
        raise OperatorError('SEARCH_DSL_INVALID', '查询嵌套过深', 'validation')
    if isinstance(node, list):
        for item in node:
            _walk(item, fields, depth=depth + 1)
        return
    if not isinstance(node, dict):
        return
    for clause, body in node.items():
        if clause in DENIED_CLAUSES:
            raise OperatorError('SEARCH_DSL_DENIED',
                                f'不允许的查询子句：{clause}', 'validation')
        if clause == 'bool':
            _walk_bool(body, fields, depth)
        elif clause == 'match_all':
            continue
        elif clause in ('match', 'match_phrase', 'term', 'terms'):
            _require_fields(body, fields, clause)
            _walk(body, fields, depth=depth + 1)
        elif clause == 'range':
            _walk_range(body, fields, depth)
        elif clause == 'exists':
            name = (body or {}).get('field')
            if name not in fields:
                raise OperatorError('SEARCH_FIELD_NOT_ALLOWED',
                                    f'字段 {name} 不在该索引的 mapping 里', 'validation')
        elif clause == 'multi_match':
            for name in (body or {}).get('fields') or []:
                base = str(name).split('^')[0]
                if base not in fields and base != '*':
                    raise OperatorError('SEARCH_FIELD_NOT_ALLOWED',
                                        f'字段 {base} 不在该索引的 mapping 里', 'validation')
            _walk({k: v for k, v in (body or {}).items() if k != 'fields'}, fields,
                  depth=depth + 1)
        elif clause in ALLOWED_CLAUSES:
            _walk(body, fields, depth=depth + 1)


def _walk_bool(body: Any, fields: set[str], depth: int) -> None:
    if not isinstance(body, dict):
        raise OperatorError('SEARCH_DSL_INVALID', 'bool 必须是对象', 'validation')
    extra = set(body) - BOOL_KEYS
    if extra:
        raise OperatorError('SEARCH_DSL_INVALID',
                            f'bool 不支持：{", ".join(sorted(extra))}', 'validation')
    _walk({key: value for key, value in body.items()
           if key != 'minimum_should_match'}, fields, depth=depth + 1)


def _require_fields(body: Any, fields: set[str], clause: str) -> None:
    if not isinstance(body, dict) or not body:
        raise OperatorError('SEARCH_DSL_INVALID', f'{clause} 必须指定字段', 'validation')
    for name in body:
        if name not in fields:
            raise OperatorError('SEARCH_FIELD_NOT_ALLOWED',
                                f'字段 {name} 不在该索引的 mapping 里', 'validation')


def _walk_range(body: Any, fields: set[str], depth: int) -> None:
    if not isinstance(body, dict) or not body:
        raise OperatorError('SEARCH_DSL_INVALID', 'range 必须指定字段', 'validation')
    for name, spec in body.items():
        if name not in fields:
            raise OperatorError('SEARCH_FIELD_NOT_ALLOWED',
                                f'字段 {name} 不在该索引的 mapping 里', 'validation')
        if spec is not None and not isinstance(spec, dict):
            raise OperatorError('SEARCH_DSL_INVALID',
                                'range 的条件必须是对象', 'validation')
        unknown = set(spec or {}) - RANGE_KEYS
        if unknown:
            raise OperatorError('SEARCH_DSL_INVALID',
                                f'range 不支持：{", ".join(sorted(unknown))}', 'validation')
    _walk({}, fields, depth=depth + 1)


def normalize(body: dict[str, Any]) -> str:
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
