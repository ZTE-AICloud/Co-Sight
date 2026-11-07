"""Word 正文解析。

正文遍历方式：**按 ``w:body`` 的文档顺序处理段落与表格**，
不要「逐段落回头找它后面那张表」。旧结构有三个后果（均可复现）：

* 表在文档开头 / 两张表相邻 / 整篇只有表 —— 没有段落去触发，表读不到；
* ``set_content`` 丢掉了 ``read_and_set_title`` 返回的 ``table_number``，
  每段都从 1 重来；``concact_table`` 于是按「行数+列数相同」在 ``doc.tables``
  里猜表，24 张表的文档读出 46 个表块、只有 11 份不同正文（内容重复/串表）；
* ``combine_content_text`` 用空格拼接，``table is finished`` 与下一段挤在
  同一行，``split_paragraph`` 认不出哨兵，表格状态污染后续段落。

现在段落、表格各走各的；``w:sdt``（内容控件）展开后一起遍历，段落里的
文本框、行内内容控件也会被带出来。
"""

import re

from docx.table import Table
from docx.text.paragraph import Paragraph

from parsing.common.sentence_add_validator import SentenceValidator
from parsing.common.special_filter import SpecialFilter
from parsing.common.special_filter_docx import SpecialFilter_docx
from parsing.parsers.docx_tool.word_table_tool import WordTableParser

#: 判「有没有实义内容」用的字符集：中英文与数字。只有标点/空白的段落视为空。
_MEANINGFUL_CHAR = re.compile(r'[0-9A-Za-z一-鿿]')


def _local_name(tag):
    return tag.rsplit('}', 1)[-1]


class WordContentParser:
    _PARAGRAPH = 'p'
    _TABLE = 'tbl'
    #: 只做展开、自身不产出正文的容器（内容控件 / 自定义 XML）
    _WRAPPER_TAGS = ('sdt', 'sdtContent', 'customXml')
    #: 表格标题取「紧挨着的上一段」，且不能是长段落（上限 30 字）
    _TABLE_TITLE_MAX_LEN = 30
    _TABLE_TITLE_LOOKBACK = 6

    def __init__(self):
        self.table_parser = WordTableParser()
        #: style_id → 样式名。``paragraph.style`` 每次都要解析 styles.xml：
        #: 没有显式样式时走 ``default_for``，线性扫一遍全部样式并逐个反序列化
        #: 枚举。1500 段的文档光这一步就要 12.4s（占解析总时长 74%）。
        self._style_names = {}

    # ------------------------------------------------------------------
    # 正文收集
    # ------------------------------------------------------------------

    def read_content(self, doc):
        content = {}
        headers = ["", "", "", "", ""]
        self.set_content(content, doc, headers, '')
        self.add_header_footer(content, doc)
        for entry in content.values():
            if entry.get('blocks'):
                entry['blocks'] = self.drop_repeated_table_titles(entry['blocks'])
        # 结构块只挂在**分区条目**上：``create_key_by_content`` 之后会追加大量
        # 句子级派生条目，它们和分区条目共用同一段正文，不应重复携带块。
        section_blocks = {key: value.get('blocks') for key, value in content.items()}
        section_keys = list(content.keys())
        paragraph_content_dict = self.create_key_by_content(content)
        content.update(paragraph_content_dict)
        self.replace_content_text(content)
        self.drop_empty_sections(content, section_keys)
        for key, blocks in section_blocks.items():
            if blocks and key in content:
                content[key]['blocks'] = blocks
        return content

    def set_content(self, content, doc, headers, headers_record):
        """按文档顺序遍历正文块。

        段落和表格都由 ``w:body`` 的直接子节点驱动，位置与顺序不再靠
        「段落后面有没有表」推断；``w:sdt`` 递归展开。

        正文同时写成两份：``text``（给 ``content_expand`` / 敏感词 / 兜底切分）
        和 ``blocks``（给 ``BlockChunkSplitter`` 做结构化切分）。
        """
        blocks = list(self.iter_blocks(doc.element.body))
        index = 0
        while index < len(blocks):
            kind, element = blocks[index]
            if kind == self._PARAGRAPH:
                paragraph = Paragraph(element, doc)
                text = self.paragraph_text(paragraph)
                level = self.heading_level(paragraph)
                headers, headers_record = self.method_name(paragraph, text, headers, headers_record)
                key = self.create_key_by_title(headers)
                self.add_block(content, key, self.text_block(level, text))
                self.combine_content_text(content, key, SpecialFilter_docx().char_filter(text))
                index = index + 1
            else:
                index = self.read_and_set_table(content, doc, headers, blocks, index)
        return headers_record

    def text_block(self, level, text):
        text = (text or '').strip()
        if not text:
            return None
        if level:
            return {'kind': 'heading', 'level': level, 'text': text}
        return {'kind': 'text', 'text': text}

    def drop_repeated_table_titles(self, blocks):
        """表格标题就是紧邻上方那段文字 —— 不要再单独切一块。

        否则每个表前面的说明行都会变成 15~35 字的小切片（实测 ip.docx
        46 块里 20 块不到 100 字）。
        """
        result = []
        for block in blocks:
            if block.get('kind') == 'table' and (block.get('title') or '').strip():
                title = block['title'].strip()
                previous = result[-1] if result else None
                if previous and (previous.get('text') or '').strip() == title:
                    if previous.get('kind') == 'text':
                        result.pop()
                    elif previous.get('kind') == 'heading':
                        block = dict(block, title='')
            result.append(block)
        return result

    def add_block(self, content, key, block):
        if not block:
            return
        entry = content.get(key)
        if entry is None:
            entry = {'text': '', 'blocks': []}
            content[key] = entry
        entry.setdefault('blocks', []).append(block)

    #: 页脚页码（"6 / 24"、"第 6 页 共 24 页"、"- 6 -" 之类）不是正文
    _PAGE_NUMBER_ONLY = re.compile(r'^[\s第页共之\-—–/|\\0-9．.()（）]+$')

    def add_header_footer(self, content, doc):
        """把页眉/页脚里的**有效文字**并进正文首尾。

        Word 的页眉页脚不在 ``doc.paragraphs`` 里，必须单独处理。但实测
        文档的页眉往往是正文里已有的标题、页脚是页码，直接拼进去只是噪声，
        所以：跳过纯页码、跳过正文里已经出现过的文字、跨节去重。
        """
        if not content:
            return
        body_text = '\n'.join(item['text'] for item in content.values())
        header_parts = []
        footer_parts = []
        for section in doc.sections:
            header_parts.extend(self.extra_text(section.header, body_text))
            footer_parts.extend(self.extra_text(section.footer, body_text))
        header_text = '\n'.join(dict.fromkeys(header_parts))
        footer_text = '\n'.join(dict.fromkeys(footer_parts))
        keys = list(content.keys())
        if header_text:
            content[keys[0]]['text'] = header_text + '\n' + content[keys[0]]['text']
            blocks = content[keys[0]].get('blocks')
            if blocks is not None:
                blocks.insert(0, {'kind': 'text', 'text': header_text})
        if footer_text:
            content[keys[-1]]['text'] = content[keys[-1]]['text'].rstrip('\n') + '\n' + footer_text
            blocks = content[keys[-1]].get('blocks')
            if blocks is not None:
                blocks.append({'kind': 'text', 'text': footer_text})

    def extra_text(self, source, body_text):
        parts = []
        for paragraph in source.paragraphs:
            text = paragraph.text.strip()
            if not text or not _MEANINGFUL_CHAR.search(text):
                continue
            if self._PAGE_NUMBER_ONLY.match(text):
                continue
            if text in body_text:
                continue
            parts.append(text)
        return parts

    def iter_blocks(self, element):
        """按顺序产出 ``('p'|'tbl', 元素)``；容器节点递归展开。"""
        for child in element.iterchildren():
            name = _local_name(child.tag)
            if name == self._PARAGRAPH or name == self._TABLE:
                yield name, child
            elif name in self._WRAPPER_TAGS:
                yield from self.iter_blocks(child)

    def paragraph_text(self, paragraph):
        """段落正文 + 文本框 + 行内内容控件的文字。

        ``python-docx`` 的 ``Paragraph.text`` 只拼直属 ``w:r``，``w:pict`` /
        ``w:drawing`` 里的文本框、``w:sdt`` 里的内容都不在其中（实测整段丢失）。
        """
        text = paragraph.text
        extras = []
        for node in paragraph._p.iter():
            if _local_name(node.tag) == 'txbxContent':
                extras.append(self.node_text(node))
        for node in paragraph._p.iterchildren():
            if _local_name(node.tag) == 'sdt':
                extras.append(self.node_text(node))
        for extra in extras:
            if extra and extra not in text:
                text = f'{text}\n{extra}' if text else extra
        return text

    def node_text(self, node):
        return ''.join(child.text or '' for child in node.iter() if _local_name(child.tag) == 't')

    # ------------------------------------------------------------------
    # 表格
    # ------------------------------------------------------------------

    def read_and_set_table(self, content, doc, headers, blocks, index):
        """读第 ``index`` 个块（表格），合上跨页续表；返回下一个待处理下标。"""
        tables = [Table(blocks[index][1], doc)]
        next_index = index + 1
        while self.is_continuation(blocks, next_index, tables[-1], doc):
            tables.append(Table(blocks[next_index + 1][1], doc))
            next_index = next_index + 2

        result = []
        table_text = []
        rows = self.table_parser.read_tables(result, table_text, tables)
        table_title = self.table_title(doc, blocks, index).strip()
        key = self.create_key_by_title(headers)
        if rows:
            self.add_block(content, key, {'kind': 'table', 'title': table_title, 'rows': rows})
        self.combine_content_text(content, key, self.render_table(table_title, rows))
        return next_index

    def render_table(self, table_title, rows):
        """表格的纯文本形态（给 ``content_expand`` / 兜底切分用）。

        不再写 ``table is find`` / ``table is finished`` 这两个内部哨兵 ——
        它们会被切进检索切片里（实测 a.docx 1361/5730 块带哨兵）。

        也不重复写表标题：``table_title`` 取的就是紧邻上方那个段落，正文里
        已经有了，再拼一遍会变成「段落、段落」两行。
        """
        return '\n'.join('|'.join(row) for row in rows or [])

    def is_continuation(self, blocks, index, previous_table, doc):
        """跨页续表：两张表之间只隔一个空段落，且列数相同（沿用原判据的意图）。"""
        if index + 1 >= len(blocks):
            return False
        kind, element = blocks[index]
        if kind != self._PARAGRAPH:
            return False
        if Paragraph(element, doc).text.strip():
            return False
        next_kind, next_element = blocks[index + 1]
        if next_kind != self._TABLE:
            return False
        return len(Table(next_element, doc).columns) == len(previous_table.columns)

    def table_title(self, doc, blocks, index):
        """表标题 = 紧邻上方那个短段落；上方是表格或长段落时没有标题。"""
        step = 1
        while index - step >= 0 and step <= self._TABLE_TITLE_LOOKBACK:
            kind, element = blocks[index - step]
            if kind == self._TABLE:
                return ''
            if kind == self._PARAGRAPH:
                text = Paragraph(element, doc).text
                return text if len(text) < self._TABLE_TITLE_MAX_LEN else ''
            step = step + 1
        return ''

    # ------------------------------------------------------------------
    # 标题 / 正文拆分
    # ------------------------------------------------------------------

    def create_key_by_title(self, headers: list):
        new_header = []
        for header in headers:
            if header:
                text = header
                new_header.append(text)
        return "，".join(new_header)

    def create_key_by_content(self, content):
        paragraph_content_dict = {}
        for number, key in enumerate(content.keys()):
            paragraph_content = content[key]['text']
            self.split_paragraph(content, key, paragraph_content_dict, paragraph_content)
        return paragraph_content_dict

    def split_paragraph(self, content, key, paragraph_content_dict, paragraph_content):
        sentences = paragraph_content.split("\n")
        table_title = ''
        is_table = 0
        for number, sentence in enumerate(sentences):

            # 哨兵行只切换状态，**不进句子流**：以前它会被当成正文，生成一个
            # 名为 'table is finished' 的 key，并在每次出现时把整段正文再拼一遍，
            # 于是同一篇文档会多出一份「多两行 table is finished」的重复全文。
            if sentence == 'table is find': ##判断sentence是否是表格
                is_table = 1
                # 正文里本来就写着「table is find」时后面可能没有下一行
                if number + 1 < len(sentences) and sentences[number + 1].find('。') != -1:
                    table_title = sentences[number + 1].split('。')[0]
                continue
            if sentence == 'table is finished':
                table_title = ''
                is_table = 0
                continue

            if is_table == 1:
                paragraph_content_dict[key + table_title + sentence] = {'text': paragraph_content}
            else:
                self.add_sentence_for_content(key, paragraph_content_dict, paragraph_content, sentence)

    def add_sentence_for_content(self, key, paragraph_content_dict, paragraph_content, sentence):
        sentence = SpecialFilter().replace_pic_and_serial(sentence)
        if SentenceValidator().is_add_sentence_key(sentence):
            if sentence in paragraph_content_dict:
                paragraph_content_dict[sentence]['text'] = paragraph_content_dict[sentence]['text'] + '\n' + sentence
            else:
                paragraph_content_dict[key + sentence] = {'text': paragraph_content}

    def drop_empty_sections(self, content, section_keys):
        """删掉「只有标题、没有正文」的空段落，连同它的派生条目。

        不能加「key 与正文都短于 15 字就删」的兜底规则 —— 一份只有
        一句话的正常文档会被整篇清空，上层报 ``ParseEmptyError``（对外
        「解析失败」）。按**有没有实义字符**判定：只有标题、标点或
        空白的段落才删。

        只对**分区 key** 判定一次，派生条目按「正文是不是同一段」一起删：
        不要对每个句子 key 都做一次 ``str.replace(整段正文)``，12000 段的
        文档光这一步要 4.9s（O(段落数 × 正文长度)）。
        """
        dropped = []
        for key in section_keys:
            if key not in content:
                continue
            text = content[key]['text']
            body = text.replace(key, '') if key else text
            if _MEANINGFUL_CHAR.search(body):
                continue
            dropped.append(text)          # 保留引用，后面用 is 比较
            del content[key]
        if not dropped:
            return
        for key in list(content.keys()):
            text = content[key]['text']
            if any(text is empty_text for empty_text in dropped):
                del content[key]

    def combine_content_text(self, content, key, text):
        """按段落拼正文（换行分隔，保留段落边界）。"""
        if not text or not text.strip():
            return
        entry = content.get(key)
        if entry is None:
            content[key] = {'text': text}
        elif (entry.get('text') or '').strip():
            entry['text'] = entry['text'].rstrip("\n") + "\n" + text
        else:
            entry['text'] = text

    # ------------------------------------------------------------------
    # 标题层级
    # ------------------------------------------------------------------

    def style_name(self, paragraph):
        """样式名（按 style_id 缓存）。

        同一份文档里绝大多数段落没有显式样式（``style_id is None``），
        每段为此要解析 5 次样式表 —— 缓存后只算一次。
        """
        style_id = paragraph._p.style
        if style_id not in self._style_names:
            style = paragraph.style
            # 文档引用了 styles.xml 里不存在的样式时 python-docx 返回 None；
            # 直接取 .name 会让整份文档报「解析失败」（《雷雨》.docx）。
            self._style_names[style_id] = style.name if style is not None else ''
        return self._style_names[style_id]

    def heading_level(self, paragraph):
        """``Heading 1``~``Heading 5`` 返回 1~5，其它样式返回 0。"""
        style_name = self.style_name(paragraph)
        if not style_name or not style_name.startswith('Heading '):
            return 0
        try:
            level = int(style_name.split()[1])
        except (IndexError, ValueError):
            return 0
        return level if 1 <= level <= 5 else 0

    def method_name(self, paragraph, text, headers: list, headers_record):
        style_name = self.style_name(paragraph)
        if style_name == 'Heading 1':
            headers[0] = text
            headers[1: -1] = ['' for i in headers[1: -1]]
            headers_record = headers_record + text + ' '
        elif style_name == 'Heading 2':
            headers[1] = text
            headers[2: -1] = ['' for i in headers[2: -1]]
            headers_record = headers_record + text + ' '
        elif style_name == 'Heading 3':
            headers[2] = text
            headers[3: -1] = ['' for i in headers[3: -1]]
            headers_record = headers_record + text + ' '
        elif style_name == 'Heading 4':
            headers[3] = text
            headers[4] = ""
            headers_record = headers_record + text + ' '
        elif style_name == 'Heading 5':
            headers[4] = text
            headers_record = headers_record + text + ' '
        return headers, headers_record

    def replace_content_text(self, content):
        """按**字符串对象**缓存清洗结果。

        每个句子 key 都指向同一段正文（同一个字符串对象），逐条跑正则是
        O(段落数 × 正文长度)；这里按 ``id()`` 去重，同一段正文只处理一次。
        """
        cache = {}
        for key in content.keys():
            text = content[key]['text']
            slot = id(text)
            if slot not in cache:
                cache[slot] = (text, SpecialFilter_docx().replace_char_for_pic(text))
            content[key]['text'] = cache[slot][1]
