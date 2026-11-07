"""黑名单（敏感词）加载与屏蔽。

覆盖的链路：`BLACK_LIST_DIR` 下的 `black_list/*.txt` → `black_list_loader` 读进内存 →
模型输出里命中的词替换成等长 `*`。
「怎么读、怎么排序、怎么屏蔽」都是对外行为的一部分，不能改。
"""

import pytest


import engine.settings as config
from engine.config_loader import black_list_loader
from engine.custom_llm.openai_llm import _mask_sensitive_words


@pytest.fixture(autouse=True)
def clean_cache(monkeypatch):
    """每个用例都从空缓存开始，且默认不碰真实目录。"""
    monkeypatch.setitem(config.Config, 'black_list_dir', '')
    black_list_loader.sensitive_words_cache.clear()
    yield
    black_list_loader.sensitive_words_cache.clear()


def _write_vocabulary(directory, name, content):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / (name + '.txt')).write_text(content, encoding='utf-8')


def test_keywords_are_split_by_separator_and_sorted_longest_first(tmp_path):
    """`|#|` 分隔、按长度倒序（先替换长词，避免短词把长词切碎）。"""
    _write_vocabulary(tmp_path, 'politics', '甲|#|乙丙丁|#|乙丙')
    black_list_loader.reload_black_list(str(tmp_path))

    assert black_list_loader.get_sensitive_words('politics') == ['乙丙丁', '乙丙', '甲']


def test_missing_directory_is_a_normal_deployment_not_an_error(tmp_path):
    """没有黑名单的部署是合法状态：不抛异常、缓存为空。"""
    black_list_loader.reload_black_list(str(tmp_path / 'not-exists'))

    assert black_list_loader.sensitive_words_cache == {}
    assert black_list_loader.get_sensitive_words('politics') == []


def test_lazy_load_when_cache_is_empty(tmp_path):
    """保证「没加载过就懒加载」，否则部署忘了调 reload 时会静默不屏蔽。"""
    _write_vocabulary(tmp_path, 'politics', '甲')
    import engine.settings as config_module
    config_module.Config['black_list_dir'] = str(tmp_path)

    assert black_list_loader.get_sensitive_words('politics') == ['甲']


def test_words_are_masked_with_equal_length_stars(tmp_path):
    _write_vocabulary(tmp_path, 'politics', '甲|#|乙丙')
    black_list_loader.reload_black_list(str(tmp_path))

    assert _mask_sensitive_words('这里有甲和乙丙', 'politics') == '这里有*和**'


def test_unknown_vocabulary_leaves_text_untouched(tmp_path):
    """算子声明了没配的词表：原样返回（空列表不做替换），不报错。"""
    _write_vocabulary(tmp_path, 'politics', '甲')
    black_list_loader.reload_black_list(str(tmp_path))

    assert _mask_sensitive_words('这里有甲', 'not-configured') == '这里有甲'


def test_none_and_empty_vocabulary_are_passed_through():
    """None（模型返回形状异常）保持 None，交给调用方的空内容判定去报错；
    vocabulary 为空（默认部署）不做任何处理。"""
    assert _mask_sensitive_words(None, 'politics') is None
    assert _mask_sensitive_words('任何内容', '') == '任何内容'


def test_empty_keyword_in_file_does_not_explode(tmp_path):
    """文件尾部多一个分隔符会产生空关键词。空串替换会膨胀（'*' * 0 插进每个字符之间），
    必须跳过 —— 用 `if sensitive_word` 兜住。"""
    _write_vocabulary(tmp_path, 'politics', '甲|#|')
    black_list_loader.reload_black_list(str(tmp_path))

    assert _mask_sensitive_words('你好甲', 'politics') == '你好*'
