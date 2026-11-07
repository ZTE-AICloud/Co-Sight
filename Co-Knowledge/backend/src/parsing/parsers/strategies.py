"""格式 → 解析策略的唯一入口。

⚠️ **解析器一律在 ``process()`` 内部按需导入，不要提到模块顶层。**

切分算子跑在沙箱子进程里，子进程有 ``RLIMIT_AS``（基线 + 500MB，见
``ingestion/utility/self_operator.py``）。模块顶层把所有 8 种格式的解析器
都 import 进来时，``openpyxl`` 会连带 ``import numpy``，而 numpy 的 OpenBLAS
按 CPU 核数预分配 —— 8 核实测 VmSize 直接顶到 **+361MB**，加上其它解析器，
子进程在**还没开始解析文档时**就已用掉 434MB / 519MB。

后果不是"慢"，是**切分必挂且看不出原因**：文档稍大一点就会在
``queue.put()`` 启动 feeder 线程时 ``can't start new thread``（线程栈 8MB
分配不出来），子进程以 exitcode=0 退出但不交付结果，父进程只能报
``System operator subprocess crashed (exitcode=0)`` → 对外
``RetCode.operator.split.error``。

改成按格式懒加载后，pdf/md/txt/docx 这几种常见格式完全不会碰 numpy。
实测同一份 PDF：导入后 VmSize 434MB → 154MB，解析完 514MB → 236MB。
"""

import os

from parsing.common import create_doc
from parsing.common.logutil import log
from parsing.md_blocks import has_markdown_headings, markdown_to_blocks


def attach_markdown_blocks(docs, markdown_content):
    """把 markdown 的结构块挂到第一条文档上。

    ``parsing.corpus._collect_blocks`` 会把所有文档的 ``blocks`` 按顺序拼起来；
    这里只挂一份，避免每条句子级文档各带一份整篇结构（那会重复 N 次）。
    """
    if not docs or not markdown_content:
        return docs
    blocks = markdown_to_blocks(markdown_content)
    if blocks:
        docs[0].blocks = blocks
    return docs


class FileParseStrategy:
    def process(self, file_path):
        pass


class TxtFileParseStrategy(FileParseStrategy):
    def process(self, file_path):
        from parsing.parsers.txt_tool.read_txt import TxtContentParser

        doc_name = os.path.basename(file_path)
        parser = TxtContentParser()
        raw_text = parser.read_txt_content(file_path)
        content = parser.create_doc_from_txt(raw_text)
        docs = create_doc.create_doc(content, [doc_name], None)
        # 导出/抓取来的 txt 常用 ``## 标题`` 分文章；识别出来才能让切片带上
        # 标题、并且不跨文章混切（抽图尤其依赖这一点）。
        if has_markdown_headings(raw_text):
            docs = attach_markdown_blocks(docs, raw_text)
        return docs


class ExcelFileParseStrategy(FileParseStrategy):
    def process(self, file_path):
        from parsing.parsers.excel_tool.read_execl import ExcelContentParser

        doc_name = os.path.basename(file_path)
        source = os.path.splitext(doc_name)[0]
        log.info(f'parse excel {doc_name}')
        if doc_name.endswith('xlsx'):
            docs = ExcelContentParser().write_txt_for_xlsx(source, file_path)
        elif doc_name.endswith('csv'):
            docs = ExcelContentParser().write_txt_for_csv(source, file_path)
        # pathutil.delete_temp()
        return docs


class WordFileParseStrategy(FileParseStrategy):
    def process(self, file_path):
        import docx as python_docx

        from parsing.parsers.docx_tool.read_word import WordContentParser

        doc_name = os.path.basename(file_path)
        log.info(f'parse word {doc_name}')
        doc = python_docx.Document(file_path)
        content = WordContentParser().read_content(doc)
        docs = create_doc.create_doc(content, [doc_name], None)
        return docs


class HtmlFileParseStrategy(FileParseStrategy):
    def process(self, file_path):
        from parsing.parsers.html_tool.read_html import HtmlContentParser

        doc_name = os.path.basename(file_path)
        log.info(f'parse html {doc_name}')
        content, blocks = HtmlContentParser().read_html(file_path)
        docs = create_doc.create_doc(content, [doc_name], None)
        if docs and blocks:
            docs[0].blocks = blocks
        return docs


class MdFileParseStrategy(FileParseStrategy):
    def process(self, file_path):
        from parsing.parsers.md_tool.read_md import MdContentParser

        doc_name = os.path.basename(file_path)
        # corpus_name = os.path.splitext(doc_name)[0] + '.txt'
        md_parser = MdContentParser()
        markdown_content = md_parser.read_md_content(file_path)
        content = md_parser.create_doc_from_md(markdown_content, file_path)
        # log.info(f'parse txt content {content}')
        docs = create_doc.create_doc(content, [doc_name], None)
        attach_markdown_blocks(docs, markdown_content)
        # work_dir = get_workdir()
        # create_doc.write_txt(docs, f'{work_dir}/temp/md/corpus/content/{corpus_name}')
        return docs


class PptxFileParseStrategy(FileParseStrategy):
    def process(self, file_path):
        from parsing.parsers.md_tool.read_md import MdContentParser
        from parsing.parsers.pptx_tool.read_pptx import PPTXContentParser

        dir_name = os.path.dirname(file_path)
        basename = os.path.basename(file_path)
        pptx_parser = PPTXContentParser()
        md_file_path = pptx_parser.convert_pptx(dir_name, basename)
        md_parser = MdContentParser()
        markdown_content = md_parser.read_md_content(md_file_path)
        content = md_parser.create_doc_from_md(markdown_content, md_file_path)
        docs = create_doc.create_doc(content, [basename], None)
        attach_markdown_blocks(docs, markdown_content)
        return docs


class PdfFileParseStrategy(FileParseStrategy):
    def process(self, file_path):
        from parsing.parsers.md_tool.read_md import MdContentParser
        from parsing.parsers.pdf_tool.read_pdf import PdfContentParser

        dir_name = os.path.dirname(file_path)
        basename = os.path.basename(file_path)
        pdf_parser = PdfContentParser()
        md_file_path = pdf_parser.convert_pdf(dir_name, basename)
        md_parser = MdContentParser()
        markdown_content = md_parser.read_md_content(md_file_path)
        content = md_parser.create_doc_from_md(markdown_content, md_file_path)
        docs = create_doc.create_doc(content, [basename], None)
        attach_markdown_blocks(docs, markdown_content)
        return docs


FILE_PARSE_STRATEGIES = {
    'txt': TxtFileParseStrategy(),
    'docx': WordFileParseStrategy(),
    'html': HtmlFileParseStrategy(),
    'xlsx': ExcelFileParseStrategy(),
    'csv': ExcelFileParseStrategy(),
    'md': MdFileParseStrategy(),
    'pptx': PptxFileParseStrategy(),
    'pdf': PdfFileParseStrategy()
}

if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print('usage: python strategies.py <file_path>')
        sys.exit(1)
    file_path = sys.argv[1]
    doc_name = os.path.basename(file_path)
    source = os.path.splitext(doc_name)[1].lstrip('.')
    if source in FILE_PARSE_STRATEGIES:
        nodes = FILE_PARSE_STRATEGIES[source].process(file_path)
        for res in nodes:
            print(f"page_content is {res.page_content}, metadata is {res.metadata}")
