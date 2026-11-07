"""建库时关键词 analyzer 的选择（英文库不能用 ik_smart）。"""

from knowledge_base.service.kbase_write_service import _keyword_analyzer


def test_explicit_props_wins():
    assert _keyword_analyzer({'keywordAnalyzer': 'standard'}, 'zh-CN') == 'standard'


def test_chinese_language_uses_ik():
    assert _keyword_analyzer({}, 'zh-CN') == 'ik_smart'
    assert _keyword_analyzer({}, 'zh') == 'ik_smart'
    assert _keyword_analyzer({}, 'zh-CN,en;q=0.9') == 'ik_smart'


def test_english_language_uses_english_analyzer():
    assert _keyword_analyzer({}, 'en-US') == 'english'
    assert _keyword_analyzer({}, '') == 'english'
