"""解析 → 切分的端到端行为：标题前缀、表格行原子、xlsx QA 类型。

这些用例盯的是「切片里到底有没有正确的内容」，不是内部实现细节：

* md/pdf/pptx/html 走 markdown 结构块后，切片必须带章节标题；
* 表格行不能被 512 字从中间切断，且每行只出现一次；
* xlsx/csv 的 QA 形态（``type=1``）不能在落库前被抹成 0。
"""

import openpyxl

from parsing.split_common import file_split_common


def _split(path, work_dir, chunk_size=512, overlap=128):
    return file_split_common(str(path), chunk_size, overlap, True,
                             custom_work_dir=str(work_dir))


def test_markdown_chunks_carry_heading_path(tmp_path):
    markdown = (
        '# 第一章 概述\n\n第一段正文。\n\n'
        '## 1.1 子节\n\n子节正文。\n\n'
        '# 第二章 详细设计\n\n详细设计正文。\n'
    )
    path = tmp_path / 'sample.md'
    path.write_text(markdown, encoding='utf-8')

    docs = _split(path, tmp_path)
    texts = [doc.page_content for doc in docs]
    joined = '\n'.join(texts)

    assert '第一章 概述' in joined
    assert '1.1 子节' in joined
    assert '第一段正文。' in joined
    assert '子节正文。' in joined
    assert '详细设计正文。' in joined


def test_markdown_table_rows_stay_atomic(tmp_path):
    rows = ''.join(f'| 值{index} | 说明{index} |\n' for index in range(1, 60))
    markdown = '# 设备表\n\n| 列一 | 列二 |\n| --- | --- |\n' + rows
    path = tmp_path / 'table.md'
    path.write_text(markdown, encoding='utf-8')

    docs = _split(path, tmp_path, chunk_size=200, overlap=0)
    texts = [doc.page_content for doc in docs]

    assert len(texts) > 1
    for index in range(1, 60):
        assert sum(f'值{index}|说明{index}' in text for text in texts) == 1


def test_markdown_repeated_heading_is_not_duplicated_into_body(tmp_path):
    markdown = '# 唯一标题\n\n正文内容。\n'
    path = tmp_path / 'one.md'
    path.write_text(markdown, encoding='utf-8')

    docs = _split(path, tmp_path)
    joined = '\n'.join(doc.page_content for doc in docs)

    assert joined.count('唯一标题') == 1
    assert '正文内容。' in joined


def test_xlsx_rows_are_not_split_and_qa_type_is_kept(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(['问题', '答案'])
    for index in range(1, 60):
        sheet.append([f'问题{index}', f'答案{index}'])
    path = tmp_path / 'qa.xlsx'
    workbook.save(path)

    docs = _split(path, tmp_path, chunk_size=200, overlap=0)
    texts = [doc.page_content for doc in docs]

    assert len(texts) > 1
    assert all(doc.metadata['type'] == 1 for doc in docs)
    for index in range(1, 60):
        assert sum(f'问题{index}|答案{index}' in text for text in texts) == 1


def test_docx_chunks_are_not_marked_as_qa(tmp_path):
    import docx

    document = docx.Document()
    document.add_heading('第一章', level=1)
    document.add_paragraph('第一段正文内容。')
    path = tmp_path / 'plain.docx'
    document.save(str(path))

    docs = _split(path, tmp_path)

    assert docs
    assert all(doc.metadata['type'] == 0 for doc in docs)


def test_operator_2_low_level_entry_still_works(tmp_path, monkeypatch):
    """``-2`` 入口（512 字符、无重叠）保持可用。"""
    from parsing import split_common
    from operators.text_split.main import file_split

    monkeypatch.setattr(split_common, 'get_workdir', lambda: str(tmp_path))
    path = tmp_path / 'plain.md'
    path.write_text('# 标题\n\n正文内容。\n', encoding='utf-8')

    docs = file_split(str(path))

    assert docs
    assert all(doc.metadata['content_expand'] == doc.page_content for doc in docs)


def test_txt_with_article_headings_keeps_titles(tmp_path):
    """txt 里的 ``## 标题`` 要进切片，且不跨文章混切（2Wiki 抽图语料形态）。"""
    text = (
        '## 1908 in organized crime\n'
        'Organized crime in 1908 in the U.S.:\n\n'
        '## 1917 Washington and Lee Generals football team\n'
        'The 1917 team represented Washington and Lee during the 1917 season.\n'
    )
    path = tmp_path / 'articles.txt'
    path.write_text(text, encoding='utf-8')

    docs = _split(path, tmp_path, chunk_size=512, overlap=0)
    texts = [doc.page_content for doc in docs]

    assert len(texts) == 2
    assert texts[0].startswith('1908 in organized crime')
    assert texts[1].startswith('1917 Washington and Lee Generals football team')
    assert 'represented Washington and Lee' in texts[1]


def test_plain_txt_is_not_treated_as_markdown(tmp_path):
    text = '2024-01-01 INFO service started\n2024-01-01 INFO request handled\n'
    path = tmp_path / 'app-log.txt'
    path.write_text(text, encoding='utf-8')

    docs = _split(path, tmp_path)
    texts = [doc.page_content for doc in docs]

    assert len(texts) == 1
    assert 'INFO service started' in texts[0]
