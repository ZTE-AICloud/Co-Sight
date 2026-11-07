"""图谱模板域（``/graph/schema/*``）的测试。

钉的是校验器里那些**文案与代码不一致**的地方 —— 这类差异照着文案实现就会静默跑偏，
而且因为文案本身是"合理"的，必须专门构造用例才抓得到。

跑法::

    python -m pytest tests/test_kb_api_graph_schema.py -q
"""


import pytest

from shared.errors.api import KbApiError  # noqa: E402
from graph.service import graph_schema_service as svc  # noqa: E402


def entity(entity_type='Person', desc='人物', properties=None):
    return {'entity_type': entity_type, 'entity_desc': desc,
            'properties': properties if properties is not None else [prop()]}


def prop(name='name', ptype='STRING', desc='名称', primary=True):
    return {'name': name, 'type': ptype, 'desc': desc, 'is_primary': primary,
            'is_embedding': False, 'is_index': False}


def doc(entities=None, edges=None, name='模板A', desc='描述'):
    return {'schema_id': 's1', 'schema_name': name, 'schema_desc': desc,
            'entities': [entity()] if entities is None else entities,
            'edges': [] if edges is None else edges}


def key_of(callable_, *args):
    with pytest.raises(KbApiError) as excinfo:
        callable_(*args)
    return excinfo.value.key


# ----------------------------------------------------------------------
# 名字长度：文案说 30，代码判 99
# ----------------------------------------------------------------------


def test_schema_name_length_boundary_is_99_not_30():
    """``validateSchemaName`` 的文案写「1-30」，实际判的是 **1-99**。

    这个差别只有靠构造 31~99 个字符的名字才能发现 —— 照文案实现会把一批合法名称拒掉。
    """
    svc.validate_schema_name('a' * 99)          # 99 个字符：合法
    assert key_of(svc.validate_schema_name, 'a' * 100) \
        == 'RetCode.graph.schema.name.invalid.length'


def test_schema_name_length_message_still_says_30():
    """对外文案仍然是 1-30（与 properties 一致），只有判定值是 99。"""
    from shared.i18n.messages import render

    text = render('RetCode.graph.schema.name.invalid.length', 'zh', 100, 1, 99)
    assert '1-30' in text


def test_schema_name_charset():
    svc.validate_schema_name('Person_Name中文123')
    assert key_of(svc.validate_schema_name, 'has-dash') \
        == 'RetCode.graph.schema.name.invalid.chars'
    assert key_of(svc.validate_schema_name, '') \
        == 'RetCode.graph.schema.name.invalid.length'
    assert key_of(svc.validate_schema_name, None) \
        == 'RetCode.graph.schema.name.invalid.chars'


# ----------------------------------------------------------------------
# 实体类型：正则不含数字
# ----------------------------------------------------------------------


@pytest.mark.parametrize('entity_type, ok', [
    ('Person', True),
    ('Company', True),
    ('Person2', False),        # ← 数字被拒，尽管文案说「首字母必须为字母」
    ('Person_Name', False),    # ← 下划线也被拒
    ('', False),
])
def test_class_type_rejects_digits_and_underscore(entity_type, ok):
    if ok:
        svc.validate_class_type(entity_type)
    else:
        assert key_of(svc.validate_class_type, entity_type) is not None


def test_class_type_reserved_keyword():
    assert key_of(svc.validate_class_type, 'ORDER') \
        == 'RetCode.graph.schema.entity_type.reserved'
    # 保留字判定是大小写无关的
    assert key_of(svc.validate_class_type, 'order') \
        == 'RetCode.graph.schema.entity_type.reserved'


# ----------------------------------------------------------------------
# 属性类型：没有 INT
# ----------------------------------------------------------------------


def test_property_type_enum_has_no_int():
    """``GraphPropertyTypeEnum`` 里 32 位整型叫 ``INTEGER`` —— ``INT`` 会被拒。"""
    svc.validate_property_type('INTEGER')
    assert key_of(svc.validate_property_type, 'INT') \
        == 'RetCode.graph.schema.entity.property.type.invalid'
    svc.validate_property_type('EMBEDDEDLIST')
    assert key_of(svc.validate_property_type, 'ARRAY') \
        == 'RetCode.graph.schema.entity.property.type.invalid'


def test_property_type_is_case_sensitive():
    assert key_of(svc.validate_property_type, 'string') is not None


# ----------------------------------------------------------------------
# 实体/边规则
# ----------------------------------------------------------------------


def test_entities_must_not_be_empty():
    assert key_of(svc.validate_schema_entities, []) \
        == 'RetCode.graph.schema.entities.not.empty'
    assert key_of(svc.validate_schema_entities, None) \
        == 'RetCode.graph.schema.entities.not.empty'


def test_entity_must_have_a_primary_property():
    """主键判定只认显式 ``True``（``False``/缺省都不算）。"""
    assert key_of(svc.validate_schema_entities,
                  [entity(properties=[prop(primary=False)])]) \
        == 'RetCode.graph.schema.entity.property.primary.not.found'


def test_duplicate_entity_type_rejected():
    assert key_of(svc.validate_schema_entities, [entity(), entity()]) \
        == 'RetCode.graph.schema.entities.duplicate.entity_type'


def test_edge_properties_may_be_empty_but_entities_may_not():
    """边属性为空是**允许**的（提前返回）；``edge.property.not.empty`` 那个键从不抛出。"""
    svc.validate_edge_properties(None, 'WorksAt')
    svc.validate_edge_properties([], 'WorksAt')

    assert key_of(svc.validate_entity_properties, None, 'Person') \
        == 'RetCode.graph.schema.entity.property.not.empty'


def test_edge_must_reference_defined_entities():
    edges = [{'edge_type': 'WorksAt', 'edge_desc': '任职', 'direction': 'out',
              'source_entity': 'Person', 'target_entity': 'Ghost', 'properties': []}]
    assert key_of(svc.validate_schema_edges, edges, [entity()]) \
        == 'RetCode.graph.schema.edge.entity.not.found'


def test_edge_duplicate_key_includes_endpoints():
    """边的查重键是 ``type||source||target`` 的复合键 —— 同一 type 不同端点是允许的。"""
    both = [{'edge_type': 'WorksAt', 'edge_desc': 'd', 'direction': 'out',
             'source_entity': 'Person', 'target_entity': 'Person', 'properties': []},
            {'edge_type': 'WorksAt', 'edge_desc': 'd', 'direction': 'out',
             'source_entity': 'Person', 'target_entity': 'Company', 'properties': []}]
    svc.validate_schema_edges(both, [entity('Person'), entity('Company')])

    dup = [both[0], dict(both[0])]
    assert key_of(svc.validate_schema_edges, dup, [entity('Person')]) \
        == 'RetCode.graph.schema.edge.duplicate.type'


# ----------------------------------------------------------------------
# 描述
# ----------------------------------------------------------------------


def test_desc_rules():
    svc.validate_desc('正常描述')
    assert key_of(svc.validate_desc, None) == 'RetCode.graph.schema.desc.null'
    assert key_of(svc.validate_desc, '   ') == 'RetCode.graph.schema.desc.invalid.chars'
    assert key_of(svc.validate_desc, '') == 'RetCode.graph.schema.desc.invalid.length'
    assert key_of(svc.validate_desc, 'x' * 1001) == 'RetCode.graph.schema.desc.invalid.length'


# ----------------------------------------------------------------------
# 结构转换
# ----------------------------------------------------------------------


def test_to_schema_obj_preserves_missing_edges_as_none():
    """``edges`` 缺失要保持 None —— 校验器对它直接 for 循环，None 会炸成 0001 而 ``[]`` 不会。"""
    converted = svc.to_schema_obj({'schema_id': 's', 'schema_name': 'n', 'schema_desc': 'd',
                                   'entities': [entity()]})
    assert converted['edges'] is None

    with_edges = svc.to_schema_obj(doc())
    assert with_edges['edges'] == []


def test_to_schema_obj_drops_unknown_keys():
    """``BeanUtil.copyProperties`` 只搬已知字段，未知键丢弃。"""
    converted = svc.to_schema_obj(dict(doc(), 未知字段='x'))
    assert set(converted) == set(svc.SCHEMA_OBJ_KEYS)


def test_missing_edges_raises_server_error_not_business_error():
    """缺 edges 触发 NPE → 0001；不是 0005。"""
    from shared.errors.api import KbServerError

    with pytest.raises(KbServerError):
        svc.validate_graph_schema_obj(svc.to_schema_obj(
            {'schema_id': 's', 'schema_name': 'n', 'schema_desc': 'd',
             'entities': [entity()]}))
