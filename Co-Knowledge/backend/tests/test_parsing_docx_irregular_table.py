"""DOCX 表格首行比正文行短（缺列）时，切分不能整份失败。

场景：两份应急预案 .docx 上传后
「解析失败」，日志里是::

    File ".../docx_tool/word_table_tool.py", line 234, in cell_fillblack
        row_text.append(table_text[0][i] + "：" + cell_text)
    IndexError: list index out of range

这两份文档的表格由 Word/WPS 编辑过，**首行格子数比后面的行少**
（真实样本：表头 2 格 / 正文行 3 格；表头 4 格 / 末行 5 格）。
``cell_fillblack`` 拿「列号」直接索引表头行，列号一旦超出表头长度就抛
IndexError，整份文档因此解析失败；``fill_blank`` 索引上一行也有同样的问题。

这里钉住：表头缺列时退化成「只保留单元格文本」，不补假表头、不抛异常；
正常表格加表头前缀的行为保持不变。
"""

from docx import Document

from parsing.parsers.docx_tool.word_table_tool import WordTableParser


def _table(rows):
    """按行构造真实 docx 表格；行短于网格时删掉尾部 tc（模拟 WPS 编辑后的残表）。

    先填文字再删 tc：``Table.cell()`` 按 ``tblGrid`` 的等宽网格定位，行被截短
    之后它自己就会索引越界，只能走 ``row.cells``（逐行读真实 ``w:tc``）。
    """
    doc = Document()
    width = max(len(row) for row in rows)
    table = doc.add_table(rows=len(rows), cols=width)
    for i, row in enumerate(rows):
        for j, text in enumerate(row):
            table.cell(i, j).text = text
    for i, row in enumerate(rows):
        tr = table.rows[i]._tr
        for tc in list(tr.tc_lst)[len(row):]:
            tr.remove(tc)
    return table


def _read(table):
    result = []
    table_text = []
    WordTableParser().read_table(result, table, table_text)
    return result, table_text


def test_header_shorter_than_body_row_does_not_raise():
    """表头 2 格、正文行 3 格：第 3 列没有表头可拼，不能抛 IndexError。"""
    table = _table([
        ['检查项目', '预期结果'],
        ['检查告警', '无告警', '无告警'],
    ])

    result, table_text = _read(table)

    assert len(table_text) == 2
    # 有表头的列照旧拼前缀，缺列的那格保留原文
    assert result[0] == '检查项目|预期结果\n'
    assert result[1] == '检查项目：检查告警|预期结果：无告警|无告警\n'


def test_row_without_cells_does_not_raise():
    """首行一个单元格都没有时 table_text 还是空的，不能拿 table_text[0] 去索引。"""
    table = _table([
        [],
        ['倒回测试', '正常'],
    ])

    result, table_text = _read(table)

    assert list(table_text[0].values()) == ['倒回测试', '正常']
    assert result == ['倒回测试|正常\n']


def test_blank_cell_beyond_previous_row_does_not_raise():
    """空单元格要复制上侧内容，但上一行比这一行短时不能索引越界。"""
    table = _table([
        ['甲', '乙'],
        ['丙', '丁', ''],
    ])

    result, table_text = _read(table)

    assert list(table_text[1].values()) == ['甲：丙', '乙：丁', ' ']
    assert result[1] == '甲：丙|乙：丁| \n'


def test_blank_cell_after_horizontal_merge_does_not_raise():
    """首行先横向合并、后面还有空白格：网格列号会比已填格子多，不能按列号索引本行。

    场景（4414 段 / 642 张表的 docx）：把列号改成网格列号之后，
    ``row_text[line - 1]`` 直接按网格列号取本行列表 → IndexError，整份文档
    「解析失败」。
    """
    doc = Document()
    table = doc.add_table(rows=2, cols=3)
    table.cell(0, 0).merge(table.cell(0, 1)).text = '合并表头'
    table.cell(0, 2).text = ''          # 空白格，位于网格第 3 列
    table.cell(1, 0).text = '甲'
    table.cell(1, 1).text = '乙'
    table.cell(1, 2).text = '丙'

    result, table_text = _read(table)

    assert list(table_text[0].values()) == ['合并表头', '合并表头']
    assert result[1].startswith('合并表头：甲')


def test_blank_header_row_falls_back_to_cell_text():
    """整行都是空白的表头：仍按原逻辑填空格，正文行不能因此崩掉。"""
    table = _table([
        ['', ''],
        ['倒回测试', '正常'],
    ])

    result, table_text = _read(table)

    assert len(table_text) == 2
    assert '倒回测试' in result[1] and '正常' in result[1]


def test_regular_table_keeps_header_prefix():
    """常规等宽表格：除首行外每格都拼上同列表头，行为不变。"""
    table = _table([
        ['项目', '结果'],
        ['倒换', '成功'],
    ])

    result, table_text = _read(table)

    assert [list(row.values()) for row in table_text] == [['项目', '结果'], ['项目：倒换', '结果：成功']]
    assert result == ['项目|结果\n', '项目：倒换|结果：成功\n']


def test_nested_table_text_is_kept():
    """单元格里再套一张表：内层文字不能整段丢。"""
    doc = Document()
    outer = doc.add_table(rows=2, cols=1)
    outer.cell(0, 0).text = '标题'
    inner = outer.cell(1, 0).add_table(rows=1, cols=2)
    inner.cell(0, 0).text = '内层甲'
    inner.cell(0, 1).text = '内层乙'

    result, _ = _read(outer)

    assert '内层甲' in result[1] and '内层乙' in result[1]


def test_word_parse_strategy_parses_docx_with_short_header(tmp_path):
    """走真实 docx 解析入口：表头缺列的文档要能解析出内容，而不是整份失败。"""
    path = tmp_path / 'irregular-table.docx'
    doc = Document()
    doc.add_paragraph('1 总则')
    table = doc.add_table(rows=2, cols=3)
    table.cell(0, 0).text = '检查项目'
    table.cell(0, 1).text = '预期结果'
    table.cell(1, 0).text = '检查告警'
    table.cell(1, 1).text = '无告警'
    table.cell(1, 2).text = '无告警'
    header_row = table.rows[0]._tr
    header_row.remove(header_row.tc_lst[-1])
    doc.save(str(path))

    from parsing.parsers.strategies import FILE_PARSE_STRATEGIES

    docs = FILE_PARSE_STRATEGIES['docx'].process(str(path))

    text = '\n'.join(str(item) for item in _iter_text(docs))
    assert '检查告警' in text


def _iter_text(docs):
    """解析结果里既有 LCDocument 也有嵌套 dict/list，这里只取所有字符串，够断言用。"""
    if isinstance(docs, str):
        yield docs
    elif isinstance(docs, dict):
        for value in docs.values():
            yield from _iter_text(value)
    elif isinstance(docs, (list, tuple)):
        for item in docs:
            yield from _iter_text(item)
    else:
        yield from _iter_text(getattr(docs, 'page_content', ''))
        yield from _iter_text(getattr(docs, 'metadata', None) or {})
