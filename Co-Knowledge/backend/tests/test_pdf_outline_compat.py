"""pypdfium2 书签 API 兼容层。

pypdfium2 4.x 的书签是属性式（``item.title`` / ``item.level`` / ``item.page_index``），
5.x 改成方法式（``get_title()`` / ``get_dest().get_index()``，``level`` 仍是属性）。
``read_pdf.extract_pdf_outlines`` 必须同时认这两套 API；只认 4.x 时，
5.x 下所有带书签的 PDF 解析都会在
``AttributeError: 'PdfBookmark' object has no attribute 'title'`` 处失败
（图谱抽取整条链路随之 103）。

这里只测纯适配函数，不 import ``read_pdf``（那会拉起 pdfplumber，轻量测试环境没有）。
"""

from parsing.parsers.pdf_tool.bookmark_compat import (bookmark_level,
                                                      bookmark_page_index,
                                                      bookmark_title)


class LegacyBookmark:
    """pypdfium2 < 5 的返回物：纯属性。"""

    title = '1 信令跟踪概述'
    level = 0
    page_index = 6


class NewDest:
    def __init__(self, index):
        self._index = index

    def get_index(self):
        return self._index


class NewBookmark:
    """pypdfium2 >= 5 的返回物：方法 + ``level`` 属性。"""

    def __init__(self, title='1.1 信令跟踪页面介绍', index=7, level=1):
        self._title = title
        self._index = index
        self.level = level

    def get_title(self):
        return self._title

    def get_dest(self):
        return NewDest(self._index)


class BookmarkWithoutDest:
    level = 0

    def get_title(self):
        return '无目标'

    def get_dest(self):
        return None


def test_title_reads_new_method_api():
    assert bookmark_title(NewBookmark()) == '1.1 信令跟踪页面介绍'


def test_title_reads_legacy_attribute_api():
    assert bookmark_title(LegacyBookmark()) == '1 信令跟踪概述'


def test_level_same_in_both_apis():
    assert bookmark_level(NewBookmark(level=2)) == 2
    assert bookmark_level(LegacyBookmark()) == 0


def test_page_index_uses_dest_in_new_api():
    assert bookmark_page_index(NewBookmark(index=7)) == 7


def test_page_index_uses_legacy_attribute():
    assert bookmark_page_index(LegacyBookmark()) == 6


def test_page_index_falls_back_to_zero_without_dest():
    assert bookmark_page_index(BookmarkWithoutDest()) == 0
