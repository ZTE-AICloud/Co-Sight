"""图谱查询（``POST /graph/query``）的纯函数测试。

这一族函数**不碰库也不碰网络**（只拼 SQL 与格式化字面量），所以能直接单测。
钉的是三类「照着直觉写就会错」的地方：

1. **错误码分裂**：DTO 注解那五条是 **0004**，服务层那两条是 **0005**。
   五条 DTO 文案在 messages.py 里 zh 与 en 写成同一句中文（实测不跟语言）。
2. **操作符语义**：``ne`` 是 ``!=`` 不是 ``<>``；数值比较**直接拼数字不加引号**；
   ``contains_all`` 是列表包含判断（逐个元素 ``in``），
   **不是**把条件 AND 串起来（照直觉写就会串成 AND）。
3. **``null`` 的格式化**：query 这边是 ``= ''``，不是 ``IS NULL`` —— 与 review 相反。

跑法::

    python -m pytest tests/test_kb_api_graph_query.py -q
"""


import pytest

from shared.errors.api import KbApiError  # noqa: E402
from infrastructure.http import binding
from graph.service import graph_query_api as svc  # noqa: E402

G = '0f28f086c3cd4e55a16b19784609951e'


def bind(payload):
    """按 ``GraphQueryDTO`` 绑定 —— 与 ``query()`` 入口用的是同一份规格。"""
    return binding.bind(payload, binding.QUERY_FIELDS)


def body(**overrides):
    payload = {'kb_id': 'graph_' + G, 'query_type': 'entity'}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# 校验：0004 与 0005 的分界
# ----------------------------------------------------------------------


@pytest.mark.parametrize('override, expected', [
    ({'kb_id': ''}, 'RetCode.graph.query.kbid.empty'),
    ({'kb_id': None}, 'RetCode.graph.query.kbid.empty'),
    ({'kb_id': '   '}, 'RetCode.graph.query.kbid.empty'),
    ({'query_type': ''}, 'RetCode.graph.query.type.empty'),
    ({'depth': 0}, 'RetCode.graph.query.depth.invalid'),
    ({'depth': 101}, 'RetCode.graph.query.depth.invalid'),
    ({'limit': 0}, 'RetCode.graph.query.limit.invalid'),
    ({'limit': 5001}, 'RetCode.graph.query.limit.invalid'),
    ({'offset': -1}, 'RetCode.graph.query.offset.invalid'),
])
def test_dto_violations_are_0004(override, expected):
    """DTO 注解违规一律 **0004**。"""
    payload = body(**override)
    if override.get('kb_id', 'x') is None and 'kb_id' in override:
        payload['kb_id'] = None
    if 'kb_id' not in override:
        payload['kb_id'] = 'graph_' + G
    with pytest.raises(KbApiError) as caught:
        svc._validate(payload)
    assert caught.value.key == expected
    assert caught.value.code == '0004'


@pytest.mark.parametrize('query_type', ['bogus', 'ENTITY', ''])
def test_query_type_invalid_or_empty(query_type):
    """空 → DTO 的 0004；非法 → 服务层的 0005。**两者码不同**。"""
    with pytest.raises(KbApiError) as caught:
        svc._validate({'kb_id': G, 'query_type': query_type})
    if query_type == '':
        assert caught.value.code == '0004'
        assert caught.value.key == 'RetCode.graph.query.type.empty'
    else:
        assert caught.value.code == '0005'
        assert caught.value.key == 'RetCode.graph.query.type.invalid'


def test_boundaries_are_inclusive():
    """1 与 100 / 1 与 1000 / 0 都是合法的。"""
    svc._validate(body(depth=1, limit=1, offset=0))
    svc._validate(body(depth=100, limit=1000))


def test_multi_violation_follows_declaration_order():
    """多违规时按 DTO 字段声明顺序取第一条 —— kbId 先于 depth/limit。

    这里只保证「我们自己是确定的」：同一请求永远取同一条违规。
    """
    with pytest.raises(KbApiError) as caught:
        svc._validate({'kb_id': '', 'query_type': 'entity', 'depth': 0, 'limit': 0})
    assert caught.value.key == 'RetCode.graph.query.kbid.empty'


# ----------------------------------------------------------------------
# DTO 绑定（强转规则）
# ----------------------------------------------------------------------


def test_bind_coerces_numeric_string_to_int():
    """``depth="5"`` 必须能绑成 5 —— 不认的话就会走到比较时崩成 0001。"""
    assert bind(body(depth='5', limit='7'))['depth'] == 5
    assert bind(body(limit='7'))['limit'] == 7


def test_bind_truncates_float_like_jackson():
    """``ACCEPT_FLOAT_AS_INT``：1.5 → 1（截断，不是四舍五入）。"""
    assert bind(body(depth=1.5))['depth'] == 1
    assert bind(body(depth=2.9))['depth'] == 2


@pytest.mark.parametrize('value', [True, False, {}, [], 'abc'])
def test_bind_rejects_non_numeric_depth(value):
    """布尔**不能**当 1 用；对象/数组/非数字串一律绑不上 → 0004。"""
    with pytest.raises(ValueError):
        bind(body(depth=value))


def test_bind_coerces_scalar_to_string():
    """``kb_id=123`` → ``"123"``（标量可以强制成字符串），但对象/数组不行。"""
    assert bind(body(kb_id=123))['kb_id'] == '123'
    assert bind(body(kb_id=True))['kb_id'] == 'true'
    for bad in ({}, []):
        with pytest.raises(ValueError):
            bind(body(kb_id=bad))


def test_bind_filters_must_be_list_of_objects():
    with pytest.raises(ValueError):
        bind(body(filters={}))
    with pytest.raises(ValueError):
        bind(body(filters='x'))
    with pytest.raises(ValueError):
        bind(body(filters=[1]))
    assert bind(body(filters=[{}]))['filters'] == [{}]


def test_bind_keeps_null_filter_element():
    """``[null]`` 必须能绑出来（随后 NPE → 0005），所以这里**不能**提前拦。"""
    assert bind(body(filters=[None]))['filters'] == [None]


def test_bind_type_field_must_be_list():
    with pytest.raises(ValueError):
        bind(body(filters=[{'entity_type': 'Person'}]))


def test_bind_type_list_coerces_scalars():
    """``List<String>`` 里的标量会被转成字符串。"""
    bound = bind(body(filters=[{'entity_type': [123, True]}]))
    assert bound['filters'][0]['entity_type'] == ['123', 'true']


def test_bind_properties_must_be_object():
    with pytest.raises(ValueError):
        bind(body(filters=[{'properties': []}]))
    assert bind(body(filters=[{'properties': {'a': 1}}]))['filters'][0]['properties'] == {'a': 1}


@pytest.mark.parametrize('snake, camel, value', [
    ('entity_type', 'entityType', ['Person']),
    ('edge_type', 'edgeType', ['WorksAt']),
    ('start_entity_type', 'startEntityType', ['Person']),
    ('path_entity_type', 'pathEntityType', ['Company']),
    ('path_edge_type', 'pathEdgeType', ['WorksAt']),
])
def test_bind_accepts_json_alias_for_type_lists(snake, camel, value):
    """``@JsonAlias``：这 9 个字段两种写法都认（前端发的是蛇形，别名是契约的一部分）。"""
    bound = bind(body(filters=[{camel: value}]))
    assert bound['filters'][0][snake] == value


@pytest.mark.parametrize('snake, camel', [
    ('start_entity_properties', 'startEntityProperties'),
    ('path_entity_properties', 'pathEntityProperties'),
    ('path_edge_properties', 'pathEdgeProperties'),
])
def test_bind_accepts_json_alias_for_maps(snake, camel):
    bound = bind(body(filters=[{camel: {'name': 'x'}}]))
    assert bound['filters'][0][snake] == {'name': 'x'}


def test_bind_alias_last_key_wins_when_both_present():
    """主名与别名同时给 → **后出现的那个赢**（按出现顺序覆盖）。

    实测对齐：``{entity_type: Company, entityType: Person}`` → Person；
    两键对调 → Company。**不是**「主名优先」，照直觉写会反。
    """
    bound = bind(body(filters=[{'entity_type': ['Snake'], 'entityType': ['Camel']}]))
    assert bound['filters'][0]['entity_type'] == ['Camel']

    bound = bind(body(filters=[{'entityType': ['Camel'], 'entity_type': ['Snake']}]))
    assert bound['filters'][0]['entity_type'] == ['Snake']


def test_bind_ignores_unknown_fields():
    """多给的键**静默忽略**（不报未知字段错误）。"""
    assert bind(body(nope=1)) == {'kb_id': 'graph_' + G, 'query_type': 'entity'}


def test_bind_returns_absent_fields_as_absent():
    """没给的字段不补默认值 —— 默认值在取用处按 ``None`` 回落。"""
    bound = bind({'kb_id': 'g', 'query_type': 'entity'})
    assert 'depth' not in bound and 'limit' not in bound


def test_bind_keeps_keyword():
    """``keyword`` 是实体搜索字段，绑定**不能**把它吃掉。

    详情页「搜索实体名称、ID 或描述」框的输入若从未进入请求体，
    前半段原因就是这里 —— 不在白名单里的键会被静默忽略，前端即使发了也到不了服务层。
    """
    assert bind(body(keyword='林致远'))['keyword'] == '林致远'
    assert 'keyword' not in bind(body())


# ----------------------------------------------------------------------
# keyword → SQL 片段
# ----------------------------------------------------------------------


def test_keyword_sql_matches_id_and_every_property_value():
    """关键字匹配**实体 ID + 所有属性值**，不写死 ``name``。

    属性名随 schema 变（通用算子建出来的是 ``entity_name``，另一套是 ``name``），
    写死任何一个键都会让搜索在另一半图上静默失效。
    """
    from graph.repository import graph_pg

    sql, params = graph_pg._keyword_sql('林致远')
    assert 'e.entity_id' in sql
    assert 'jsonb_each_text(properties)' in sql
    # 只比值不比键：直接 (properties)::text LIKE 会让 `name` 这类键名子串命中全表
    assert 'kv.v ILIKE' in sql and 'kv.k <> ' in sql
    assert params == ['%林致远%', '%林致远%']


def test_keyword_sql_escapes_like_wildcards_and_ignores_blank():
    from graph.repository import graph_pg

    _, params = graph_pg._keyword_sql('50%_x')
    assert params == ['%50\\%\\_x%', '%50\\%\\_x%']
    assert graph_pg._keyword_sql(None) == ('', [])
    assert graph_pg._keyword_sql('   ') == ('', [])


# ----------------------------------------------------------------------
# 起点条件 / 笛卡尔积
# ----------------------------------------------------------------------


def test_expand_property_combinations_cartesian_order():
    """顺序照最后一个键变化最快的进位规则，``itertools.product`` 正好一致。"""
    assert svc._expand_property_combinations({'a': [1, 2], 'b': ['x', 'y']}) == [
        {'a': 1, 'b': 'x'}, {'a': 1, 'b': 'y'},
        {'a': 2, 'b': 'x'}, {'a': 2, 'b': 'y'},
    ]


def test_expand_keeps_operator_conditions_unexpanded():
    spec = {'op': 'in', 'value': [1, 2]}
    assert svc._expand_property_combinations({'age': spec}) == [{'age': spec}]


def test_expand_empty_is_single_empty_map():
    assert svc._expand_property_combinations({}) == [{}]


def test_start_conditions_default_to_in_degree_zero():
    """没有任何起点条件时用「入度为 0」的特殊条件（**不是**空列表）。"""
    assert svc._start_conditions_for_paths({'filters': []}) == {'_use_in_degree_zero': True}
    assert svc._start_conditions_for_paths({}) == {'_use_in_degree_zero': True}


def test_start_conditions_expand_types_times_properties():
    conditions = svc._start_conditions_for_paths({'filters': [{
        'start_entity_type': ['Person', 'Company'],
        'start_entity_properties': {'name': ['a', 'b']},
    }]})
    assert conditions == [
        {'@class': 'Person', 'name': 'a'}, {'@class': 'Person', 'name': 'b'},
        {'@class': 'Company', 'name': 'a'}, {'@class': 'Company', 'name': 'b'},
    ]


def test_start_conditions_rid_only_filter():
    conditions = svc._start_conditions_for_paths({'filters': [{'start_entity_rid': '#12:0'}]})
    assert conditions == [{'@rid': '#12:0'}]


# ----------------------------------------------------------------------
# 响应装配
# ----------------------------------------------------------------------


def test_blank_response_key_order_matches_dto():
    """键序照 DTO 字段声明序（前端不依赖，但保持形状一致）。"""
    assert list(svc._blank_response()) == [
        'entities', 'edges', 'paths', 'entity_num', 'edge_num',
        'total', 'has_more', 'offset', 'limit', 'next_cursor']


def test_empty_response_has_no_offset_with_cursor():
    """游标分页时不回 offset/limit。"""
    response = svc._empty_response(body(cursor='#12:5'))
    assert response['offset'] is None and response['limit'] is None
    assert response['next_cursor'] is None


def test_empty_response_has_offset_and_limit_without_cursor():
    response = svc._empty_response(body())
    assert response['offset'] == 0 and response['limit'] == 100


def test_apply_pagination_has_more_is_ge_limit_not_gt():
    """``has_more`` 判据是 ``>=``：**刚好用满一页**也算「还有更多」。"""
    response = svc._blank_response()
    svc._apply_pagination(response, body(limit=2), [{'@rid': '#1:0'}, {'@rid': '#1:1'}])
    assert response['has_more'] is True

    response = svc._blank_response()
    svc._apply_pagination(response, body(limit=3), [{'@rid': '#1:0'}, {'@rid': '#1:1'}])
    assert response['has_more'] is False


def test_next_cursor_only_when_has_more():
    response = svc._blank_response()
    svc._apply_pagination(response, body(limit=1, cursor='#1:0'), [{'@rid': '#1:5'}])
    assert response['next_cursor'] == '#1:5'

    response = svc._blank_response()
    svc._apply_pagination(response, body(limit=9, cursor='#1:0'), [{'@rid': '#1:5'}])
    assert response['next_cursor'] is None


def test_ensure_fields_not_null_fills_paths():
    """``createEmptyResponse`` 留的 null ``paths`` 在这里被补成 ``[]``。"""
    response = {'entities': None, 'edges': None, 'paths': None}
    svc._ensure_fields_not_null(response)
    assert response == {'entities': [], 'edges': [], 'paths': []}
