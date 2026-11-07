import re

from parsing.common.decode_tool import detect_encoding
from parsing.common.sentence_add_validator import SentenceValidator
from parsing.common.special_filter import SpecialFilter
from parsing.common.logutil import log
from parsing.parsers.md_tool.md_table_tool import MdTableTool
chinese_numbers = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]

#: HTML 注释（含跨行）；解析语料时整段剔除
_HTML_COMMENT = re.compile(r'<!--.*?-->', re.DOTALL)

class MdContentParser:
    def __init__(self):
        pass

    def read_md_content(self, file_path):
        log.info(f'read md {file_path}')
        encoding = detect_encoding(file_path)
        log.info(f'encoding {encoding}')
        with open(file_path, newline='', encoding=encoding) as file:
            markdown_content = file.read()
        return markdown_content

    def clean_result(self, result):
        _result = {}
        for key in result.keys():
            # key 为空串是**合法**的：「第一个标题之前的正文」就挂在空 key 下，
            # 以前 `if key and ...` 会把它连同正文一起丢掉（见 extract_heading_and_paragraphs）。
            if key is not None and '目录' not in key and result[key] and result[key]['text']:
                _result[key] = result[key]
        return _result

    def clean_key(self, result):
        _result = {}
        for key in result.keys():
            _result[self.create_standard_title(key)] = result[key]
        return _result

    def create_standard_title(self, text):
        pattern_list = [r'\d+(\.\d+)+', r'\d+\.\s*', r'^\s*\w+、\s*|：']
        pattern = '|'.join(pattern_list)
        text = re.sub(pattern, '', text)
        new_text = text.replace(" ", "").replace("*", "").replace(r'\n(?!\n)', '').replace('\n', '')
        new_text = re.sub(r',+', ',', new_text)
        for str_sub in chinese_numbers:
            new_text = new_text.replace(str_sub + "、", '').replace(str_sub + ".", '')
        return new_text

    def create_doc_from_md(self, markdown_content, file_path):
        result = self.extract_heading_and_paragraphs(markdown_content)
        result = self.clean_result(result)
        paragraph_content_dict = self.create_key_by_content(result)
        result.update(paragraph_content_dict)
        table_content = MdTableTool().md_table_parser(markdown_content, file_path)
        result.update(table_content)
        result = self.clean_key(result)
        return result

    def create_key_by_content(self, content):
        paragraph_content_dict = {}
        for key in content.keys():
            paragraph_content = content[key]['text']
            self.split_paragraph(content, key, paragraph_content_dict, paragraph_content)
        return paragraph_content_dict

    def split_paragraph(self, content, key, paragraph_content_dict, paragraph_content):
        sentences = paragraph_content.split("。")
        for sentence in sentences:
            self.add_sentence_for_content(content, key, paragraph_content_dict, paragraph_content, sentence)

    def add_sentence_for_content(self, content, key, paragraph_content_dict, paragraph_content_split, sentence):
        sentence = SpecialFilter().replace_pic_and_serial(sentence)
        if SentenceValidator().is_add_sentence_key(sentence):
            paragraph_content_dict[sentence] = {'text': paragraph_content_split}

    def extract_heading_and_paragraphs(self, markdown_content):
        """把 markdown 拆成「标题 → 正文」。

        ⚠️ 以前两处**会静默丢正文**，一篇真实的 PDF / PPTX 因此产出 0 条记录，
        上层 corpus 报 ``RetCode.operator.split.empty``（对外表现为「解析失败」）：

        1. 第一个标题**之前**的正文没有归属，整段丢弃 —— 而 Word/PPT 导出的 PDF
           往往整篇没有一个 ``#``（没有可识别的大字号标题），于是全部丢光；
        2. **只有标题、没有正文**的章节（只有一页标题的 PPT、只有一行的 PDF）被
           ``if current_section and section_lines`` 跳过。

        现在：标题前正文归入 key 为空串的章节（不带假标题前缀），只有标题的章节
        用标题本身当正文 —— 宁可保留一行标题，也不要让整篇文档变成空。
        """
        headers = ["", "", "", "", "", ""]
        headings_pattern = re.compile(r'(#{1,6})\s*(.*?)\s*#*$', re.IGNORECASE)
        # HTML 注释不是正文：PPTX 转换器每页插一条 ``<!-- Slide N -->``，
        # 不清掉就会原样进切片（切片尾部会出现 ``<! -- Slide 1 -->``）。
        markdown_content = _HTML_COMMENT.sub('', markdown_content)
        sections = {}
        section_lines = []
        key = None
        current_section = None
        preamble_lines = []

        def flush(title, lines):
            """写入一个章节；正文为空时用标题兜底（标题本身也是内容）。

            行间**必须保留换行**：以前是 ``''.join(lines)``，PDF 的表格行、
            PPT 的分行正文会被粘成一整行，切片只能按字符硬切（实测 223 页
            的名单 PDF 每一块都从行中间断）。
            """
            text = '\n'.join(lines).strip()
            if text:
                sections[title] = {'text': text}
            elif title:
                sections[title] = {'text': title}

        for line in markdown_content.splitlines():
            match = headings_pattern.match(line.strip())
            if match:
                if current_section:
                    key = self.create_key_by_title(headers)
                    flush(key, section_lines)
                headers = self.conbine_header(line, headers)
                current_section = match.group(2).strip()
                section_lines = []  # 重置段落行列表
            else:
                if current_section:
                    section_lines.append(line)
                else:
                    preamble_lines.append(line)
        if current_section:
            flush(current_section, section_lines)
        if '\n'.join(preamble_lines).strip():
            # 空 key：``create_key_by_content`` 会拼成「句子」本身，不会出现假标题
            sections[''] = {'text': '\n'.join(preamble_lines).strip()}
        return sections

    def create_key_by_title(self, headers: list):
        new_header = []
        for header in headers:
            if header:
                text = header.replace("《", '').replace("》", '').replace('\t', '')
                text = re.sub(r'^(?:\d+(\.\d+)*\s+)+', '', text).replace(" ", "")
                new_header.append(text)
        return "，".join(new_header)

    def conbine_header(self, line, headers: list):
        match1 = re.match(r'^#\s+(.*)', line)
        match2 = re.match(r'^##\s+(.*)', line)
        match3 = re.match(r'^###\s+(.*)', line)
        match4 = re.match(r'^####\s+(.*)', line)
        match5 = re.match(r'^#####\s+(.*)', line)
        match6 = re.match(r'^#######\s+(.*)', line)
        if bool(match1):
            headers = ["", "", "", "", "", ""]
            headers[0] = match1.group(1).strip()
        if bool(match2):
            headers[1] = match2.group(1).strip()
        if bool(match3):
            headers[2] = match3.group(1).strip()
        if bool(match4):
            headers[3] = match4.group(1).strip()
        if bool(match5):
            headers[4] = match5.group(1).strip()
        if bool(match6):
            headers[5] = match6.group(1).strip()
        return headers


def create_key_by_content(self, content):
    paragraph_content_dict = {}
    for key in content.keys():
        paragraph_content = content[key]['text']
        self.split_paragraph(paragraph_content_dict, paragraph_content)
    return paragraph_content_dict


def split_paragraph(self, paragraph_content_dict, paragraph_content):
    sentences = paragraph_content.split("。")
    for sentence in sentences:
        self.add_sentence_for_content(paragraph_content_dict, sentence, paragraph_content)


def add_sentence_for_content(self, paragraph_content_dict, sentence, paragraph_content):
    sentence = SpecialFilter().replace_pic_and_serial(sentence)
    if SentenceValidator().is_add_sentence_key(sentence):
        paragraph_content_dict[sentence] = {'text': paragraph_content}
