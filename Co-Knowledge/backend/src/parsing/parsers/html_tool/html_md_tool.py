import os
import re

from parsing.common.pathutil import get_workdir
from parsing.common.sentence_add_validator import SentenceValidator
from parsing.common.special_filter import SpecialFilter
from parsing.common import create_doc, pathutil
from parsing.common.logutil import log
from parsing.parsers.md_tool.read_md import MdContentParser
from markdownify import markdownify as md

chinese_numbers = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]

workdir = get_workdir()


def save_standard_txt(path_dir, md_dir):
    content = {}
    md_parser = MdContentParser()
    md_files = read_md_files(path_dir, md_dir)
    for md_file in md_files:
        log.info(f'process md_file for html {md_file}')
        with open(md_file, 'r', encoding='utf-8') as file:
            markdown_content = file.read()
            # 不再给「没有标题的 md」补一个 ``#{文件名}`` 假标题 —— 那是当年
            # ``extract_heading_and_paragraphs`` 会丢掉标题前正文的权宜之计。
            # 现在标题前正文归入空 key 章节（见 read_md.py），补假标题只会让
            # **完全空白**的页面也产出一条以文件名为正文的切片，掩盖真实的
            # 「解析不到文本」——``test_split.py`` 的 ``ParseEmptyError`` 用例就是盯这个。
            content.update(md_parser.create_doc_from_md(markdown_content, md_file))
    return content


def collect_blocks(path_dir, md_dir):
    """把 HTML 转换出的所有 markdown 文件拼成一条结构块序列。

    顺序与 ``save_standard_txt`` 一致（``read_md_files`` 的返回顺序），保证
    块序列和正文对得上。
    """
    from parsing.md_blocks import markdown_to_blocks

    blocks = []
    for md_file in read_md_files(path_dir, md_dir):
        try:
            with open(md_file, 'r', encoding='utf-8') as file:
                blocks.extend(markdown_to_blocks(file.read()))
        except OSError as error:
            log.warning(f'read md for blocks failed: {md_file}, {error}')
    return blocks


def add_sentence_for_content(content):
    result = {}
    for title in content.keys():
        sentences = content[title]['text'].split("。")
        for sentence in sentences:
            if SentenceValidator().is_add_sentence_key(sentence):
                sentence_with_out_char = SpecialFilter().replace_char(sentence)
                result[sentence_with_out_char] = content[title]
    content.update(result)


def create_standard_title(text):
    pattern_list = [r'\d+(\.\d+)+', r'\d+\.\s*', r'^\s*\w+、\s*|：']
    pattern = '|'.join(pattern_list)
    text = re.sub(pattern, '', text)
    new_text = text.replace(" ", "").replace("*", "").replace(r'\n(?!\n)', '').replace('\n', '')
    new_text = re.sub(r',+', ',', new_text)
    for str_sub in chinese_numbers:
        new_text = new_text.replace(str_sub + "、", '').replace(str_sub + ".", '')
    return new_text


def read_md_files(path_dir, md_dir):
    md_files = []
    md_dir = SpecialFilter().replace_path_char(md_dir)
    md_dir = f'{workdir}/temp/{path_dir}/{md_dir}_md'
    for root, dirs, files in os.walk(md_dir):
        for file in files:
            if file.endswith(".md"):
                md_files.append(os.path.join(root, file))
    return md_files

def write_md_for_html(html_file, md_dir, path_dir):
    md_dir = SpecialFilter().replace_path_char(md_dir)
    with open(html_file, 'r', encoding='utf-8') as f:
        html_data = f.read()
        # ``heading_style='ATX'`` 必须显式给：markdownify 默认是 setext（``标题`` 下面补
        # 一行 ``=====`` / ``---``），既让标题在 md 里**不是** ``#`` 形式（下游按 ``#``
        # 识别章节），也把那串符号当成正文拼进了切片 —— 切片里出现过
        # ``比亚迪简介=====比亚迪是…`` 这类伪影。
        markdown_text = md(_drop_non_content(html_data), heading_style='ATX')
        filename = get_file_name(html_file)
        pathutil.create_dir_under_root(f'/temp/{path_dir}/{md_dir}_md')
        log.info(f'create dir for html2md /temp/{path_dir}/{md_dir}_md')
        try:
            with open(f'{workdir}/temp/{path_dir}/{md_dir}_md/{filename}', 'w', encoding='utf-8') as out:
                out.write(markdown_text)
            log.info(f'write md for html {workdir}/temp/{path_dir}/{md_dir}_md/{filename}')
        except Exception as e:
            log.error(f'write md for html {workdir}/temp/{path_dir}/{md_dir}_md/{filename}  error', e)
    return md_dir


#: 转换前整段丢弃的标签：``<title>`` 会被 markdownify 当正文输出，
#: 于是「正文全在 script 里的 JS 渲染空壳页」也会解析出页面标题、产出一条
#: 无意义切片，掩盖「解析不到正文」这个真实结论（见 test_split.py 的同名用例）。
_NON_CONTENT_TAGS = ('title', 'script', 'style', 'noscript')


def _drop_non_content(html_data):
    """去掉 ``<head>`` 与脚本/样式，只留可读正文；解析失败时原样返回。"""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_data, 'html.parser')
        for tag in soup(_NON_CONTENT_TAGS):
            tag.decompose()
        for tag in soup.find_all('head'):
            tag.decompose()
        return str(soup)
    except Exception as error:  # noqa: BLE001 - 清洗失败不该阻断解析
        log.warning(f'drop non-content tags failed: {error}')
        return html_data


def get_file_name(html_file):
    if '/' in html_file:
        return os.path.basename(html_file).split('.')[0] + '.md'
    return f'{os.path.splitext(html_file)[0]}.md'


def save_corpus(content, corpus_name, save_path):
    pathutil.create_dir_under_root(save_path)
    create_doc.write_txt(content, f'{get_workdir()}{save_path}{corpus_name}')
