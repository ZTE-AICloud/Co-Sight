"""markdown → 结构块：标题、表格、代码围栏、转义竖线。

非 docx 格式（md/pdf/pptx/html）都先转 markdown 再解析；以前只保留「句子 → 整段
正文」的字典，标题在重组正文时被丢掉（实测 pptx 32 个标题有 26 个不在正文里）。
"""

from parsing.md_blocks import markdown_to_blocks, parse_table_rows, split_table_row


def test_headings_and_paragraphs_in_order():
    markdown = '# 第一章 概述\n\n第一段正文。\n\n## 1.1 子节\n\n第二段正文。\n'

    blocks = markdown_to_blocks(markdown)

    assert blocks == [
        {'kind': 'heading', 'level': 1, 'text': '第一章 概述'},
        {'kind': 'text', 'text': '第一段正文。'},
        {'kind': 'heading', 'level': 2, 'text': '1.1 子节'},
        {'kind': 'text', 'text': '第二段正文。'},
    ]


def test_table_rows_keep_all_cells():
    markdown = '| 问题 | 答案 |\n| --- | --- |\n| 1+1 | 2 |\n'

    blocks = markdown_to_blocks(markdown)

    assert blocks == [{
        'kind': 'table',
        'title': '',
        'rows': [['问题', '答案'], ['1+1', '2']],
    }]


def test_table_separator_row_is_dropped():
    assert parse_table_rows(['| a | b |', '| :--- | ---: |', '| 1 | 2 |']) == [
        ['a', 'b'], ['1', '2']]


def test_escaped_pipe_in_cell():
    assert split_table_row(r'| a\|b | c |') == ['a|b', 'c']


def test_code_fence_is_text_not_heading():
    markdown = '```\n# 不是标题\n```\n'

    blocks = markdown_to_blocks(markdown)

    assert blocks == [{'kind': 'text', 'text': '# 不是标题'}]


def test_html_comment_is_removed():
    markdown = '<!-- Slide 1 -->\n正文内容。\n'

    blocks = markdown_to_blocks(markdown)

    assert blocks == [{'kind': 'text', 'text': '正文内容。'}]


def test_empty_markdown_returns_no_blocks():
    assert markdown_to_blocks('') == []
    assert markdown_to_blocks('   \n\n') == []


def test_empty_heading_is_skipped():
    assert markdown_to_blocks('#\n\n正文。\n') == [{'kind': 'text', 'text': '正文。'}]


def test_has_markdown_headings_accepts_article_titles():
    from parsing.md_blocks import has_markdown_headings

    text = '## 1908 in organized crime\n正文。\n\n## 1917 Washington\n正文。\n'

    assert has_markdown_headings(text) is True


def test_has_markdown_headings_rejects_logs_and_comments():
    from parsing.md_blocks import has_markdown_headings

    assert has_markdown_headings('普通文本。\n# 只有一行标题\n') is False
    assert has_markdown_headings('# ' + 'x' * 200 + '\n# ' + 'y' * 200 + '\n') is False
    assert has_markdown_headings('') is False
