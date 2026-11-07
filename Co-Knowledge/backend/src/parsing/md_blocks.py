"""Markdown → 结构块序列（heading / text / table），保留文档顺序。

md、pdf、pptx、html 四种格式都先把文件转成 markdown 再解析。以前这条链只产出
「句子 → 整段正文」的字典，标题只存在于字典的 key 上，重组正文时被丢掉 ——
切片因此不知道自己在哪一章（实测 pptx 32 个标题有 26 个不在正文里）。

这份 block 序列让它们和 docx 一样走 ``BlockChunkSplitter``：章节标题成为切片
前缀、表格行不被切断、目录可以被识别并过滤。

约定与 ``parsing.block_splitter`` 一致::

    {'kind': 'heading', 'level': 1, 'text': '第一章'}
    {'kind': 'text', 'text': '段落正文…'}
    {'kind': 'table', 'title': '', 'rows': [['表头a', '表头b'], ['值1', '值2']]}

* 段落按**空行**分组，组内保留换行（交给切分器按行切句）；
* 代码围栏整体作为一个 text 块，围栏内部不参与标题/表格识别；
* 表格单元格里的 ``\\|`` 会被还原成 ``|``。
"""

import re

_HTML_COMMENT = re.compile(r'<!--.*?-->', re.DOTALL)
_FENCE = re.compile(r'^\s*(```|~~~)')
_HEADING = re.compile(r'^(#{1,6})\s*(.*?)\s*#*\s*$')
#: markdown 表格的分隔行：``| --- | :---: |``
_TABLE_SEPARATOR = re.compile(r'^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$')


_HEADING_LINE = re.compile(r'^#{1,6}\s+(\S.*)$')
#: 一段文本要不要按 markdown 结构解析的判据：标题要「够多、够短」
TXT_HEADING_MIN_COUNT = 2
TXT_HEADING_MAX_LEN = 80


def has_markdown_headings(text):
    """纯文本里是否出现「足够像文档标题」的 ``# 标题`` 行。

    ``.txt`` 默认按纯文本切分；但导出/抓取来的 txt 常用 ``## 标题`` 分隔
    文章或章节（2Wiki 语料就是每篇文章一个 ``## 标题``）。识别成结构块后，
    切片会带上标题、且不会跨文章混切 —— 对抽图和检索都更友好。

    判据刻意保守，避免把日志/配置里的 ``# 注释`` 误当结构：

    * 至少 ``TXT_HEADING_MIN_COUNT`` 行；
    * 每个标题文本不超过 ``TXT_HEADING_MAX_LEN`` 字符。
    """
    if not text:
        return False
    count = 0
    for line in text.splitlines():
        match = _HEADING_LINE.match(line.strip())
        if not match:
            continue
        if len(match.group(1).strip()) > TXT_HEADING_MAX_LEN:
            return False
        count += 1
        if count >= TXT_HEADING_MIN_COUNT:
            return True
    return False


def markdown_to_blocks(markdown_content):
    """把 markdown 文本解析成块序列；空文档返回 ``[]``。"""
    if not markdown_content:
        return []
    text = _HTML_COMMENT.sub('', markdown_content)
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    lines = text.split('\n')

    blocks = []
    paragraph = []
    fence = []
    in_fence = False

    def flush_paragraph():
        if paragraph:
            body = '\n'.join(paragraph).strip()
            if body:
                blocks.append({'kind': 'text', 'text': body})
            paragraph.clear()

    def flush_fence():
        if fence:
            body = '\n'.join(fence).strip()
            if body:
                blocks.append({'kind': 'text', 'text': body})
            fence.clear()

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if _FENCE.match(line):
            if in_fence:
                flush_fence()
                in_fence = False
            else:
                flush_paragraph()
                in_fence = True
            index += 1
            continue

        if in_fence:
            fence.append(line)
            index += 1
            continue

        if not stripped:
            flush_paragraph()
            index += 1
            continue

        heading = _HEADING.match(stripped)
        if heading:
            flush_paragraph()
            title = heading.group(2).strip()
            if title:
                blocks.append({
                    'kind': 'heading',
                    'level': len(heading.group(1)),
                    'text': title,
                })
            index += 1
            continue

        if stripped.startswith('|'):
            table_lines = []
            while index < len(lines) and lines[index].strip().startswith('|'):
                table_lines.append(lines[index].strip())
                index += 1
            rows = parse_table_rows(table_lines)
            if rows:
                flush_paragraph()
                blocks.append({'kind': 'table', 'title': '', 'rows': rows})
            continue

        paragraph.append(stripped)
        index += 1

    if in_fence:
        flush_fence()
    flush_paragraph()
    return blocks


def parse_table_rows(lines):
    """markdown 表格行 → ``[[cell, ...], ...]``；分隔行丢弃。"""
    rows = []
    for line in lines:
        if _TABLE_SEPARATOR.match(line):
            continue
        cells = split_table_row(line)
        if cells:
            rows.append(cells)
    return rows


def split_table_row(line):
    """拆一行表格；``\\|`` 是单元格内的字面量竖线。"""
    body = line.strip()
    if body.startswith('|'):
        body = body[1:]
    if body.endswith('|') and not body.endswith('\\|'):
        body = body[:-1]

    cells = []
    buffer = []
    escaped = False
    for char in body:
        if escaped:
            buffer.append(char)
            escaped = False
        elif char == '\\':
            escaped = True
        elif char == '|':
            cells.append(''.join(buffer).strip())
            buffer = []
        else:
            buffer.append(char)
    cells.append(''.join(buffer).strip())
    return cells if any(cells) else []
