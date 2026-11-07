"""Word 正文结构回归：多表、表在开头、相邻表、嵌套表、文本框、内容控件、短文档。

这些缺陷都是「静默丢内容 / 串内容」，不报错也不落日志，
只体现在检索结果里：

* **多表串内容**：``set_content`` 丢掉了 ``read_and_set_title`` 返回的表序号，
  每段都从 1 重来，``concact_table`` 只能按「行数列数相同」在 ``doc.tables``
  里猜表。例如 24 张表的文档会读出 46 个表块、只有 11 份不同正文。
* **表读不到**：表在文档开头 / 两张表相邻 / 整篇只有表 —— 若由段落驱动
  「回头找表」，这几种情况没有段落能触发。
* **嵌套表 / 文本框 / 内容控件**：``_Cell.text`` 与 ``Paragraph.text`` 都只读
  直属内容，这几种容器里的文字整段消失。
* **短文档被清空**：``delete_key`` 有条「key 与正文都短于 15 字就删」的规则，
  一份只有一句话的正常文档会被删空，上层报 ``ParseEmptyError``（对外「解析失败」）。
* **表格状态污染**：``combine_content_text`` 用空格拼接，``table is finished``
  和下一段挤成一行，``split_paragraph`` 认不出哨兵。
"""

from docx import Document
from lxml import etree

from parsing.block_splitter import BlockChunkSplitter
from parsing.parsers.strategies import FILE_PARSE_STRATEGIES

_W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
_V = 'urn:schemas-microsoft-com:vml'


def _chunks(path):
    """走真实链路：解析器 → 结构块 → 块切分器。"""
    blocks = []
    for doc in FILE_PARSE_STRATEGIES['docx'].process(str(path)):
        blocks.extend(getattr(doc, 'blocks', None) or [])
    return BlockChunkSplitter().split(blocks)


def _parsed_text(path):
    return '\n'.join(_chunks(path))


def _save(doc, tmp_path, name='case.docx'):
    path = tmp_path / name
    doc.save(str(path))
    return path


def _add_table(doc, rows):
    table = doc.add_table(rows=len(rows), cols=len(rows[0]))
    for i, row in enumerate(rows):
        for j, text in enumerate(row):
            table.cell(i, j).text = text
    return table


# ----------------------------------------------------------------------
# 多表格不能串内容 / 重复
# ----------------------------------------------------------------------

def test_each_table_content_parsed_once(tmp_path):
    doc = Document()
    doc.add_paragraph('第一节说明文字，长度足够避免被短文本规则删掉。')
    _add_table(doc, [['表一头', '表一列'], ['表一数据甲', '表一数据乙']])
    doc.add_paragraph('两张表之间的段落，同样写得长一些。')
    _add_table(doc, [['表二头', '表二列'], ['表二数据丙', '表二数据丁']])
    doc.add_paragraph('结尾段落，长度足够。')

    chunks = _chunks(_save(doc, tmp_path))

    assert sum('表一数据甲' in chunk for chunk in chunks) == 1
    assert sum('表二数据丙' in chunk for chunk in chunks) == 1
    assert any('表二头' in chunk for chunk in chunks)


def test_three_tables_all_parsed(tmp_path):
    doc = Document()
    doc.add_paragraph('开头段落，长度足够避免被短文本规则删掉。')
    for index in range(3):
        _add_table(doc, [[f'表{index}头', '列'], [f'表{index}数据', '值']])
        doc.add_paragraph(f'第{index}张表之后的段落，长度足够。')

    chunks = _chunks(_save(doc, tmp_path))

    for index in range(3):
        assert sum(f'表{index}数据' in chunk for chunk in chunks) == 1


# ----------------------------------------------------------------------
# 表格读不到的位置
# ----------------------------------------------------------------------

def test_table_at_document_start_is_parsed(tmp_path):
    doc = Document()
    _add_table(doc, [['列一', '列二'], ['值一', '值二']])
    doc.add_paragraph('表格后面的正文，长度足够避免被删掉。')

    text = _parsed_text(_save(doc, tmp_path))

    assert '值一' in text and '列二' in text


def test_document_with_only_tables_is_not_empty(tmp_path):
    doc = Document()
    _add_table(doc, [['唯一表头', '列二'], ['唯一数据', '数据二']])

    text = _parsed_text(_save(doc, tmp_path))

    assert '唯一数据' in text


def test_consecutive_tables_both_parsed(tmp_path):
    doc = Document()
    doc.add_paragraph('说明段落，长度足够避免被短文本规则删掉。')
    _add_table(doc, [['第一张表']])
    _add_table(doc, [['第二张表']])
    doc.add_paragraph('结束段落，长度足够。')

    text = _parsed_text(_save(doc, tmp_path))

    assert '第一张表' in text and '第二张表' in text


def test_nested_table_text_is_parsed(tmp_path):
    doc = Document()
    doc.add_paragraph('嵌套表说明，长度足够避免被短文本规则删掉。')
    outer = doc.add_table(rows=2, cols=1)
    outer.cell(0, 0).text = '外层标题'
    outer.cell(1, 0).add_table(rows=1, cols=1).cell(0, 0).text = '内层独有内容'

    text = _parsed_text(_save(doc, tmp_path))

    assert '内层独有内容' in text


def test_text_box_text_is_parsed(tmp_path):
    doc = Document()
    doc.add_paragraph('正文段落，长度足够避免被短文本规则删掉。')
    paragraph = doc.add_paragraph()
    paragraph._p.append(etree.fromstring(
        f'<w:pict xmlns:w="{_W}" xmlns:v="{_V}"><v:shape><v:textbox><w:txbxContent>'
        '<w:p><w:r><w:t>文本框里的隐蔽内容</w:t></w:r></w:p>'
        '</w:txbxContent></v:textbox></v:shape></w:pict>'))

    text = _parsed_text(_save(doc, tmp_path))

    assert '文本框里的隐蔽内容' in text


def test_content_control_text_is_parsed(tmp_path):
    doc = Document()
    doc.add_paragraph('正文段落，长度足够避免被短文本规则删掉。')
    body = doc.element.body
    body.insert(len(body) - 1, etree.fromstring(
        f'<w:sdt xmlns:w="{_W}"><w:sdtPr><w:alias w:val="说明"/></w:sdtPr>'
        '<w:sdtContent><w:p><w:r><w:t>内容控件里的正文，长度也足够长。</w:t></w:r></w:p>'
        '</w:sdtContent></w:sdt>'))

    text = _parsed_text(_save(doc, tmp_path))

    assert '内容控件里的正文' in text


# ----------------------------------------------------------------------
# 短文档与表格状态
# ----------------------------------------------------------------------

def test_short_document_is_not_deleted(tmp_path):
    """整篇只有一句话也要保留 —— 旧规则会把 key 与正文都短于 15 字的段落删光。"""
    doc = Document()
    doc.add_paragraph('通知：明天停电。')

    text = _parsed_text(_save(doc, tmp_path))

    assert '明天停电' in text


def test_short_document_with_heading_is_not_deleted(tmp_path):
    doc = Document()
    doc.add_heading('通知', level=1)
    doc.add_paragraph('明天停电。')

    text = _parsed_text(_save(doc, tmp_path))

    assert '明天停电' in text


def test_header_and_footer_text_is_kept(tmp_path):
    """页眉页脚里的有效文字要进来（只读 doc.paragraphs 会整块读不到）。"""
    doc = Document()
    doc.add_paragraph('正文段落，长度足够避免被短文本规则删掉。')
    doc.sections[0].header.paragraphs[0].text = '内部资料 注意保密'
    doc.sections[0].footer.paragraphs[0].text = '文档编号：SD-2026-001'

    text = _parsed_text(_save(doc, tmp_path))

    assert '内部资料 注意保密' in text
    assert '文档编号：SD-2026-001' in text


def test_page_number_footer_is_dropped(tmp_path):
    doc = Document()
    doc.add_paragraph('正文段落，长度足够避免被短文本规则删掉。')
    doc.sections[0].footer.paragraphs[0].text = '6 / 24'

    text = _parsed_text(_save(doc, tmp_path))

    assert '6 / 24' not in text
    assert '正文段落' in text


def test_header_duplicating_body_is_not_repeated(tmp_path):
    doc = Document()
    doc.sections[0].header.paragraphs[0].text = '某省应急预案'
    doc.add_paragraph('某省应急预案')
    doc.add_paragraph('正文段落，长度足够避免被短文本规则删掉。')

    text = _parsed_text(_save(doc, tmp_path))

    assert text.count('某省应急预案') == 1


def test_paragraph_after_table_is_not_glued_to_rows(tmp_path):
    """表格后的段落不能被并进表格块里 —— 它要能和表格行分开检索。"""
    doc = Document()
    doc.add_paragraph('表格前的段落，长度足够避免被删掉。')
    _add_table(doc, [['头A', '头B'], ['体A', '体B']])
    doc.add_paragraph('表格之后另起一段的正文，长度也足够长。')

    chunks = _chunks(_save(doc, tmp_path))

    table_chunks = [chunk for chunk in chunks if '体A' in chunk]
    assert table_chunks and all('表格之后另起一段' not in chunk for chunk in table_chunks)
    assert any('表格之后另起一段' in chunk for chunk in chunks)


def test_paragraph_without_a_resolved_style_does_not_crash():
    """styles.xml 缺失/样式被删干净时 ``paragraph.style`` 是 None。

    《雷雨》.docx 在这条路径上会抛
    ``AttributeError: 'NoneType' object has no attribute 'name'``，整份文档
    报「解析失败」。样式名解析不出来时按「无标题」处理即可。
    """
    from parsing.parsers.docx_tool.read_word import WordContentParser

    class _ParagraphWithoutStyle:
        class _Element:
            style = 'MissingStyle'

        _p = _Element()
        style = None

    assert WordContentParser().style_name(_ParagraphWithoutStyle()) == ''
