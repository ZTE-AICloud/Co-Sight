"""整页表格不能被「页眉/页脚」判据整张丢掉。

场景：一份 223 页的获奖名单 PDF，
每页都是一张整页表格。如果判据是「元素与页眉/页脚带有**重叠**就丢」，整页表
同时压到上下两条带，于是表格被丢；它覆盖的文本行又被 ``_in_any_table`` 全部
过滤 —— 每页正文全空，最终 ``ParseEmptyError``（对外「解析失败」）。

判据改成「**整个**落在带子里才丢」：页眉/页脚照旧过滤，跨页的正文和整页表
不再误伤。

``read_pdf`` 会拉起 ``pdfplumber``，轻量测试环境没有这个依赖时整文件跳过。
"""

import pytest

pytest.importorskip('pdfplumber')

from parsing.parsers.pdf_tool.read_pdf import PdfContentParser  # noqa: E402

PAGE_HEIGHT = 842.0
HEADER_BOUNDARY = PAGE_HEIGHT * 0.075          # 页面底部页脚带的上沿
FOOTER_BOUNDARY = PAGE_HEIGHT * (1 - 0.075)    # 页面顶部页眉带的下沿


@pytest.fixture
def parser():
    return PdfContentParser()


def test_full_page_table_is_not_dropped(parser):
    bbox = (52.0, 40.0, 543.0, 810.0)          # 整页表格，压到上下两条带
    assert parser._is_in_header_footer(bbox, HEADER_BOUNDARY, FOOTER_BOUNDARY) is False


def test_footer_only_element_is_dropped(parser):
    bbox = (72.0, 20.0, 300.0, 45.0)           # 整条在页面底部页脚带内
    assert parser._is_in_header_footer(bbox, HEADER_BOUNDARY, FOOTER_BOUNDARY) is True


def test_header_only_element_is_dropped(parser):
    bbox = (72.0, 800.0, 300.0, 830.0)         # 整条在页面顶部页眉带内
    assert parser._is_in_header_footer(bbox, HEADER_BOUNDARY, FOOTER_BOUNDARY) is True


def test_body_line_touching_header_band_is_kept(parser):
    """紧贴页眉带下沿的正文（比如页面顶部的大标题）要保留。"""
    bbox = (72.0, 770.0, 300.0, 785.0)
    assert parser._is_in_header_footer(bbox, HEADER_BOUNDARY, FOOTER_BOUNDARY) is False


# ---------------------------------------------------------------------------
# 「整页表格型」文档的选路
# ---------------------------------------------------------------------------

class _FakeTable:
    def __init__(self, bbox):
        self.bbox = bbox


class _FakePage:
    def __init__(self, width, height, tables):
        self.width = width
        self.height = height
        self._tables = tables

    def find_tables(self):
        return self._tables


class _FakePdf:
    def __init__(self, pages):
        self.pages = pages


def _pages_with_coverage(ratio, count=5):
    width, height = 100.0, 100.0
    table_width = width * ratio
    return [_FakePage(width, height, [_FakeTable((0.0, 0.0, table_width, height))])
            for _ in range(count)]


def test_table_list_document_is_detected(parser):
    """每页都是整页表格的名单/报表 → 走 pdfium 快速路径。"""
    assert parser.is_table_list_document(_FakePdf(_pages_with_coverage(0.9))) is True


def test_normal_document_is_not_table_list(parser):
    assert parser.is_table_list_document(_FakePdf(_pages_with_coverage(0.1))) is False


def test_document_without_pages_is_not_table_list(parser):
    assert parser.is_table_list_document(_FakePdf([])) is False
