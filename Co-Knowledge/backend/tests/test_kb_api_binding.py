"""请求体绑定（``compat/kb_api/binding.py``）的测试。

这一层实现**请求体的强转规则**，规则本身反直觉、又不会自己报错
（不做绑定只会静默算出错结果），所以逐条钉住。

边界用例里这一层最容易出缺口：``/kbase/search``、``/kbase/retrieve``、
``/directory/getNameById`` 三处都依赖绑定；缺绑定时会出现 0004 与 0001（500 类）
的分叉，或本该拒绝却正常返回。

跑法::

    python -m pytest tests/test_kb_api_binding.py -q
"""


import pytest

from infrastructure.http import binding  # noqa: E402
from shared.errors.api import KbLiteralValidationError  # noqa: E402


# ----------------------------------------------------------------------
# 标量强转：能转与不能转的分界
# ----------------------------------------------------------------------


@pytest.mark.parametrize('raw, expected', [('5', 5), (5, 5), (1.5, 1), (-3, -3)])
def test_integer_accepts_numbers_and_numeric_strings(raw, expected):
    """数字字符串可以；浮点**截断**（``ACCEPT_FLOAT_AS_INT``）。"""
    assert binding.as_integer('n', raw) == expected


@pytest.mark.parametrize('raw', [True, False, {}, [], 'abc', '1.5'])
def test_integer_rejects_boolean_object_array_and_junk(raw):
    """``true`` **不能**当 1 用 —— 这是与「标量可强转」相反的一条。"""
    with pytest.raises(ValueError):
        binding.as_integer('n', raw)


def test_string_accepts_scalars_but_not_containers():
    assert binding.as_string('s', 123) == '123'
    assert binding.as_string('s', True) == 'true'      # 小写，布尔文本一律小写
    assert binding.as_string('s', 1.5) == '1.5'
    for bad in ({}, []):
        with pytest.raises(ValueError):
            binding.as_string('s', bad)


def test_boolean_accepts_only_real_booleans_and_string_literals():
    assert binding.as_boolean('b', True) is True
    assert binding.as_boolean('b', 'false') is False
    for bad in (1, 0, {}, []):
        with pytest.raises(ValueError):
            binding.as_boolean('b', bad)


# ----------------------------------------------------------------------
# 集合类型
# ----------------------------------------------------------------------


def test_list_of_strings_coerces_scalars():
    assert binding.as_string_list('t', [1, True, 'x']) == ['1', 'true', 'x']


def test_list_of_strings_rejects_containers_but_keeps_nulls():
    assert binding.as_string_list('t', [None, 'x']) == [None, 'x']
    with pytest.raises(ValueError):
        binding.as_string_list('t', [{}])


def test_list_of_objects_requires_objects_but_keeps_nulls():
    """``[null]`` 必须能绑出来（随后 NPE → 0005），**别提前拦**。"""
    assert binding.as_list_of_objects('t', [None, {'a': 1}]) == [None, {'a': 1}]
    with pytest.raises(ValueError):
        binding.as_list_of_objects('t', [1])


def test_bind_objects_binds_each_element():
    bound = binding.bind_objects(
        [{'baseList': [1], 'priority': '0'}], binding.RETRIEVE_BASE_FIELDS)
    assert bound == [{'baseList': ['1'], 'priority': 0}]


# ----------------------------------------------------------------------
# 各端点的字段表
# ----------------------------------------------------------------------


def test_search_fields_bind_the_document_contract():
    bound = binding.bind(
        {'currentPage': '1', 'pageSize': 10, 'categories': ['1', 2], 'keyword': 5},
        binding.SEARCH_FIELDS)
    assert bound == {'currentPage': 1, 'pageSize': 10, 'categories': [1, 2], 'keyword': '5'}


def test_search_rejects_non_list_categories():
    """``categories`` 声明是 ``List<Integer>``：字符串/对象都绑不上 → 0004。"""
    for bad in ('1', {}, True):
        with pytest.raises(ValueError):
            binding.bind({'categories': bad}, binding.SEARCH_FIELDS)


def test_retrieve_base_list_is_a_list_not_a_string():
    """``RetrieveBaseDTO.baseList`` 是 ``List<String>`` —— 传字符串绑不上。

    嵌套要绑**两层**：外层 ``bases`` 是 ``List<DTO>``，内层每个元素再按
    ``RETRIEVE_BASE_FIELDS`` 绑一遍。``retrieve()`` 就是这么调的。

    探针若把 ``baseList`` 发成字符串，期望是 0004；不要把这种输入当成正常值。
    """
    def bind_bases(bases):
        return binding.bind_objects(bases, binding.RETRIEVE_BASE_FIELDS)

    with pytest.raises(ValueError):
        bind_bases([{"baseList": "doc_x"}])
    assert bind_bases([{'baseList': ['a'], 'priority': '0'}]) == [{'baseList': ['a'], 'priority': 0}]


def test_content_search_type_is_a_string():
    """``ContentSearchDTO.type`` 是 **String**（默认 "kbase"），不是整数。

    必须按字符串读：``type=1`` 要转成 ``"1"`` 再按白名单拦下；按整数读会当成
    某个有效分支走下去。
    """
    assert binding.bind({'type': 1}, binding.CONTENT_SEARCH_FIELDS) == {'type': '1'}
    assert binding.bind({'type': 'kbase'}, binding.CONTENT_SEARCH_FIELDS) == {'type': 'kbase'}


def test_unknown_fields_are_dropped():
    """多给的键静默忽略（不报未知字段错误）。"""
    assert binding.bind({'currentPage': 1, 'nope': 2}, binding.SEARCH_FIELDS) == {'currentPage': 1}


def test_absent_fields_stay_absent():
    """没给就不补默认值；默认值由各 DTO 的取用处决定。"""
    assert binding.bind({'currentPage': 1}, binding.SEARCH_FIELDS) == {'currentPage': 1}


def test_non_object_body_rejected():
    with pytest.raises(ValueError):
        binding.bind(['x'], binding.SEARCH_FIELDS)


# ----------------------------------------------------------------------
# 字面量错误（非 i18n）
# ----------------------------------------------------------------------


def test_literal_validation_error_renders_as_is():
    """默认校验文案**恒为英文**，别塞进 i18n 表。"""
    error = KbLiteralValidationError('must not be null')
    assert error.code == '0004'
    assert error.render('zh') == 'must not be null'
    assert error.render('en') == 'must not be null'
