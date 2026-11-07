"""算子库查询条件的纯函数测试（不碰 DB）。

算子列表的搜索框显示的是「当前语言的名字」：英文界面显示 ``nameEn``。
只匹配 ``name`` 会让英文名搜不到。
"""

from operators.repository import operator_store


def test_keyword_matches_name_and_name_en():
    sql, params = operator_store._common_filters(None, 'Sample', None, None)

    assert 'name ILIKE' in sql
    assert 'name_en' in sql
    # 两个占位符共用同一个模式；两端带 % 做模糊匹配
    assert params == ['%Sample%', '%Sample%']


def test_keyword_escapes_like_wildcards():
    sql, params = operator_store._common_filters(None, 'a_b%', None, None)

    assert "ESCAPE '\\'" in sql
    assert params == ['%a\\_b\\%%', '%a\\_b\\%%']


def test_no_keyword_has_no_name_condition():
    sql, params = operator_store._common_filters(None, '', None, None)

    assert 'name' not in sql
    assert params == []
