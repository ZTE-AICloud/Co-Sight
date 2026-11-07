"""请求体的 DTO 绑定 —— 按 JSON 的类型强制规则（**全域共用**）。

Python 侧请求体是裸 dict，没有声明式绑定，于是「字段类型不对」这件事默认**不会**在入口
被拦下：值一路走到业务代码里，表现为 **500 类错误**、或者更糟 —— **静默算出错的结果**。

这不是图谱域独有的问题。按域扫了一遍已交付端点（``tools/verify/verify-kb-api-boundary-diff.py``），
同一个根因在 ``/kbase/search``、``/kbase/retrieve``、``/directory/getNameById``
上一样成立，而且是扫描里最大的一簇。

## 规则

| 目标类型 | 能强转的输入 | 绑不上就 0004 |
|---|---|---|
| ``String`` | 标量（数字/布尔 → 字符串） | 对象、数组 |
| ``Integer`` | 数字、数字**字符串**、浮点（**截断**） | 布尔、对象、数组、非数字串 |
| ``List<String>`` | 数组（元素是标量就转字符串） | 字符串、对象 |
| ``Map`` | 对象 | 数组、字符串、标量 |
| ``List<DTO>`` | 对象数组（``null`` 元素保留） | 其它 |

两个容易反直觉的点：

* ``true`` **不能**当 1 用（布尔不绑定成整数），但 ``1.5`` 可以（截断成 1）。
* ``{"filters": [null]}`` **绑得出来**（List 里含 null 元素），随后在业务里
  NPE → 0005。所以这里也保留 ``null`` 元素，**别提前拦**。

绑定失败抛 ``ValueError`` —— ``router._dispatch_sync`` 把它翻成 **0004**
``RetCode.illegalArgument``。
"""

from __future__ import annotations

from typing import Any, Optional

# 字段类型标记
STRING = 'string'
INTEGER = 'integer'
FLOAT = 'float'
BOOLEAN = 'boolean'
MAP = 'map'
OBJECT = 'object'
FILTERS = 'filters'
LIST_OF_OBJECTS = 'list_of_objects'
LIST_OF_STRINGS = 'list_of_strings'
LIST_OF_INTEGERS = 'list_of_integers'
# **原生整数**：JSON null 绑不上 —— 请求体绑定拒绝 null
# （``pageNO=null`` 回 0004 ``RetCode.illegalArgument``，而不是可空整数那条的必填文案）。
PRIMITIVE_INTEGER = 'primitive_integer'

# 字段别名：9 个字段同时接受 snake_case 与 camelCase。
# 两者都在时**后出现的那一个赢**（绑定器边遍历边赋值，不是「主名优先」）——
# ``{entity_type:[Company], entityType:[Person]}`` → Person，两键对调 → Company。
FILTER_ALIASES = {
    'entity_type': 'entityType',
    'edge_type': 'edgeType',
    'start_entity_type': 'startEntityType',
    'start_entity_properties': 'startEntityProperties',
    'start_entity_rid': 'startEntityRid',
    'path_entity_type': 'pathEntityType',
    'path_entity_properties': 'pathEntityProperties',
    'path_edge_type': 'pathEdgeType',
    'path_edge_properties': 'pathEdgeProperties',
}

_TYPE_LIST_FIELDS = ('entity_type', 'edge_type', 'start_entity_type',
                     'path_entity_type', 'path_edge_type')

# filter 的「键名 → 规范名」总表：蛇形、camelCase 别名、以及没有别名的 properties。
_FILTER_FIELD_BY_NAME = {
    **{name: name for name in FILTER_ALIASES},
    **{alias: name for name, alias in FILTER_ALIASES.items()},
    'properties': 'properties',
}

# ---- 各端点的 DTO 形状 ----------------------------------------------------

# ``GraphQueryDTO``（snake_case）
#
# ``keyword`` 是可选字段：图谱详情页的「搜索实体名称、ID 或描述」输入框需要它
# —— 见 ``graph_query_api`` 的说明。
QUERY_FIELDS = {
    'kb_id': STRING, 'query_type': STRING, 'filters': FILTERS,
    'depth': INTEGER, 'direction': STRING, 'limit': INTEGER,
    'offset': INTEGER, 'cursor': STRING, 'keyword': STRING,
}

# ``GraphReviewDTO``（camelCase）
REVIEW_FIELDS = {
    'kbId': STRING, 'filters': FILTERS,
    'depth': INTEGER, 'direction': STRING, 'limit': INTEGER,
}

# ``EntityCreateRequestDTO``（含嵌套 ``edgeInfo``）
ENTITY_CREATE_FIELDS = {
    'kbId': STRING, 'entityId': STRING, 'entityType': STRING,
    'properties': MAP, 'edgeInfo': OBJECT,
}
EDGE_INFO_FIELDS = {
    'edgeId': STRING, 'edgeType': STRING, 'currentEntityId': STRING,
    'direction': STRING, 'properties': MAP,
}

ENTITY_UPDATE_FIELDS = {
    'kbId': STRING, 'entityId': STRING, 'entityType': STRING, 'properties': MAP,
}
ENTITY_DELETE_FIELDS = {
    'kbId': STRING, 'entityId': STRING, 'entityType': STRING,
}
EDGE_CREATE_FIELDS = {
    'kbId': STRING, 'edgeId': STRING, 'edgeType': STRING,
    'sourceId': STRING, 'targetId': STRING, 'properties': MAP,
}
EDGE_UPDATE_FIELDS = {
    'kbId': STRING, 'edgeId': STRING, 'edgeType': STRING, 'properties': MAP,
}
EDGE_DELETE_FIELDS = {
    'kbId': STRING, 'edgeId': STRING, 'edgeType': STRING,
}

# ---- 知识库检索 / 列表（B1、B2 的读路径）---------------------------------

# **currentPage / pageSize 都是必填**（且各有上下界），
# 缺了不是「用默认值」，而是 0004 —— ``pageSize=null`` 回
# "must not be null"（默认文案）。
SEARCH_FIELDS = {
    'keyword': STRING, 'currentPage': INTEGER, 'pageSize': INTEGER,
    'orderList': LIST_OF_OBJECTS, 'embeddingModel': STRING,
    'categories': LIST_OF_INTEGERS, 'schemaId': STRING,
}

# ``RetrieveDTO`` + ``RetrieveBaseDTO``。``baseList`` 是 **List<String>**，
# 传字符串会让绑定失败 —— 这一条最早是拿错探针才发现的。
RETRIEVE_FIELDS = {
    'question': STRING, 'type': INTEGER, 'model': STRING, 'bases': LIST_OF_OBJECTS,
}
RETRIEVE_BASE_FIELDS = {
    'baseList': LIST_OF_STRINGS, 'priority': INTEGER,
    'top_k': INTEGER, 'score_threshold': FLOAT,
}

# ``InnerOrder``：``key`` 是枚举（按字符串绑定，无效值 → 0004）
ORDER_FIELDS = {'key': STRING, 'ascending': BOOLEAN}

# ``type`` 是 **String**（默认 ``"kbase"``），不是整数 —— 按整数读会让
# ``type=1`` 分叉。
CONTENT_SEARCH_FIELDS = {
    'type': STRING, 'ids': LIST_OF_OBJECTS, 'vectorType': STRING,
    'searchWeight': FLOAT, 'relatedIndex': FLOAT, 'matchNumber': INTEGER,
    'searchType': STRING, 'isRank': BOOLEAN, 'question': STRING,
}
RETRIEVE_CONTENT_FIELDS = {'kbaseId': STRING, 'id': STRING}


def bind(payload: Any, fields: dict) -> dict:
    """把裸请求体绑成 DTO 形状。

    未声明的键**静默丢弃**（不报未知字段错误）。
    """
    if not isinstance(payload, dict):
        raise ValueError(f'request body must be an object, got {type(payload).__name__}')

    bound: dict = {}
    for name, kind in fields.items():
        if name not in payload:
            continue                    # 没给就不补默认值，默认值在取用处按 None 回落
        bound[name] = _coerce(name, payload[name], kind)
    return bound


def bind_objects(items: Any, fields: dict) -> Any:
    """把「对象数组」里的**每个元素**按 ``fields`` 再绑一遍（``List<DTO>`` 用）。

    元素为 ``null`` 时原样保留 —— ``[null]`` 绑得出来，随后在业务里 NPE。
    """
    if not isinstance(items, list):
        return items
    bound = []
    for item in items:
        if item is None or not isinstance(item, dict):
            bound.append(item)
        else:
            bound.append(bind(item, fields))
    return bound


def _coerce(name: str, value: Any, kind: str) -> Any:
    if kind == STRING:
        return as_string(name, value)
    if kind == INTEGER:
        return as_integer(name, value)
    if kind == FLOAT:
        return as_float(name, value)
    if kind == BOOLEAN:
        return as_boolean(name, value)
    if kind == MAP:
        return as_map(name, value)
    if kind == FILTERS:
        return as_filters(value)
    if kind == LIST_OF_OBJECTS:
        return as_list_of_objects(name, value)
    if kind == LIST_OF_STRINGS:
        return as_string_list(name, value)
    if kind == LIST_OF_INTEGERS:
        return as_list_of_integers(name, value)
    if kind == PRIMITIVE_INTEGER:
        if value is None:
            raise ValueError(f'cannot deserialize {name} from null (primitive int)')
        return as_integer(name, value)
    if kind == OBJECT:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError(f'cannot deserialize {name} from {type(value).__name__}')
        return bind(value, EDGE_INFO_FIELDS)
    raise AssertionError(f'unknown field kind: {kind}')


def as_float(name: str, value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f'cannot deserialize {name} from Boolean')
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            raise ValueError(f'cannot deserialize {name} from "{value}"') from None
    raise ValueError(f'cannot deserialize {name} from {type(value).__name__}')


def as_boolean(name: str, value: Any) -> Optional[bool]:
    """``Boolean`` 字段：**只认真正的 JSON 布尔**（也要 ``"true"`` 字符串）。

    数字 1/0 绑不上 —— 与 Integer 那条相反，别合并。
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ('true', 'false'):
        return value.lower() == 'true'
    raise ValueError(f'cannot deserialize {name} from {type(value).__name__}')


def as_list_of_objects(name: str, value: Any) -> Optional[list]:
    """``List<DTO>``：元素必须是对象（``null`` 元素保留）。"""
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError(f'cannot deserialize {name} from {type(value).__name__}')
    for item in value:
        if item is not None and not isinstance(item, dict):
            raise ValueError(f'cannot deserialize {name} element from {type(item).__name__}')
    return value


def as_list_of_integers(name: str, value: Any) -> Optional[list]:
    """``List<Integer>``：元素逐个强制（字符串数字可以，布尔不行）。"""
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError(f'cannot deserialize {name} from {type(value).__name__}')
    return [None if item is None else as_integer(name, item) for item in value]


def as_string(name: str, value: Any) -> Optional[str]:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, (bool, int, float)):
        return java_string(value)       # 标量可以强制成字符串
    raise ValueError(f'cannot deserialize {name} from {type(value).__name__}')


def as_integer(name: str, value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        # 默认**不**把 boolean 当整数（``true`` 不是 1）
        raise ValueError(f'cannot deserialize {name} from Boolean')
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)               # ACCEPT_FLOAT_AS_INT：截断
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            raise ValueError(f'cannot deserialize {name} from "{value}"') from None
    raise ValueError(f'cannot deserialize {name} from {type(value).__name__}')


def as_map(name: str, value: Any) -> Optional[dict]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f'cannot deserialize {name} from {type(value).__name__}')
    return value


def as_filters(value: Any) -> Optional[list]:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError(f'cannot deserialize filters from {type(value).__name__}')
    result = []
    for item in value:
        # ``[null]`` 能绑成含 null 元素的 List，随后在业务里 NPE → 0005。
        # 保留 None，让后面的取值处自然抛错，落到同一条路径上。
        if item is None:
            result.append(None)
            continue
        if not isinstance(item, dict):
            raise ValueError(f'cannot deserialize filter from {type(item).__name__}')
        result.append(_bind_filter(item))
    return result


def _bind_filter(item: dict) -> dict:
    """按 **JSON 文档顺序**逐键绑定，同名（含别名）**后出现的覆盖先出现的**。"""
    bound: dict = {}
    for key, raw in item.items():
        primary = _FILTER_FIELD_BY_NAME.get(key)
        if primary is None:
            continue                    # 未知字段静默忽略
        if primary in _TYPE_LIST_FIELDS:
            bound[primary] = as_string_list(primary, raw)
        elif primary == 'start_entity_rid':
            bound[primary] = as_string(primary, raw)
        else:
            bound[primary] = as_map(primary, raw)   # ``properties`` 家族
    return bound


def as_string_list(name: str, value: Any) -> Optional[list]:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError(f'cannot deserialize {name} from {type(value).__name__}')
    result = []
    for item in value:
        if item is None:
            result.append(None)         # 元素为 null 时保持 null
        elif isinstance(item, str):
            result.append(item)
        elif isinstance(item, (bool, int, float)):
            result.append(java_string(item))
        else:
            raise ValueError(f'cannot deserialize {name} element from {type(item).__name__}')
    return result


def java_string(value: Any) -> str:
    """标量→字符串：布尔是**小写** ``true``/``false``。"""
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)
