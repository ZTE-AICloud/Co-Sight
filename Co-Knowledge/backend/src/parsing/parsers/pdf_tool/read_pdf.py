import os
import re
from dataclasses import dataclass
from typing import List, Dict, Tuple

import pdfplumber
import pypdfium2 as pdfium

from parsing.common import pathutil
from parsing.common.pathutil import get_workdir
from parsing.parsers.pdf_tool.bookmark_compat import (bookmark_level,
                                                      bookmark_page_index,
                                                      bookmark_title)


@dataclass
class PDFPageContent:
    page_num: int
    text: str


@dataclass
class PDFTable:
    table_id: str
    page_num: int
    content: str
    bbox: Tuple[float, float, float, float]
    page_height: float  # 新增页面高度字段


work_dir = get_workdir()


def replace_pic_no_pre(text):
    # 替换顺序会导致部分字符串遗留，例如 -1所示
    text = re.sub(r'如图\d+-\d+所示', '', text)
    text = re.sub(r'如图\d+(\.\d+)?所示', '', text)
    text = re.sub(r'图\d+(\.\d+)?所示', '', text)
    text = re.sub(r'图\d+-\d+所示', '', text)
    text = re.sub(r'图\d+-\d+', '', text)
    text = re.sub(r'图\d+(\.\d+)?', '', text)
    return text


def replace_char(chars):
    return chars.replace(' ', '_').replace('【', '').replace('】', '').replace('“', '').replace(
        '”', '').replace('\\', '').replace('，', '')


def find_last_match(pattern, content):
    """查找正则表达式在内容中最后一次匹配的位置"""
    last_match = None
    for match in pattern.finditer(content):
        last_match = match
    return last_match


def create_flexible_space_pattern(title):
    """创建带灵活空格匹配的正则模式"""
    escaped = re.escape(title)
    return re.compile(escaped.replace(r'\ ', r'[ \u2003\u3000]'))


def remove_first_space(title):
    """移除标题的第一个空格（兼容所有空格类型）"""
    parts = re.split(r'[ \u2003\u3000]', title, maxsplit=1)
    return parts[0] + parts[1] if len(parts) > 1 else title


def adjust_special_scene_title(title):
    """处理特殊场景标题格式"""
    # 在最后一个点后添加空格
    last_dot = title.rfind('.')
    if last_dot != -1:
        title = f"{title[:last_dot + 1]} {title[last_dot + 1:]}"

    # 规范斜杠周围的空格
    title = re.sub(r'(?<!\s)(/)(?!\s)', r' \1 ', title)
    return title


def process_origin_title(page_content, origin_title, title):
    # 尝试精确匹配（带灵活空格）
    base_pattern = create_flexible_space_pattern(origin_title)
    if last_match := find_last_match(base_pattern, page_content):
        return replace_content(page_content, last_match.span(), title)

    # 尝试移除第一个空格后匹配
    if any(c in origin_title for c in (' ', '\u2003', '\u3000')):
        modified_title = remove_first_space(origin_title)
        if modified_title != origin_title:  # 确实有空格被移除
            modified_pattern = create_flexible_space_pattern(modified_title)
            if last_match := find_last_match(modified_pattern, page_content):
                return replace_content(page_content, last_match.span(), title)

    # 处理特殊场景
    # page_content中为1. 系统启动 / 关闭，origin_title为1.系统启动/关闭
    processed_title = adjust_special_scene_title(origin_title.replace(" ", ""))
    return page_content.replace(processed_title, title)


def replace_content(content, span, new_text):
    """通用的内容替换方法"""
    start, end = span
    return content[:start] + new_text + content[end:]


class PdfContentParser:
    def __init__(self,
                 header_ratio: float = 0.075,
                 footer_ratio: float = 0.075,
                 line_threshold: float = 0.3,
                 paragraph_threshold: float = 1.2):
        self.header_ratio = header_ratio
        self.footer_ratio = footer_ratio
        self.line_threshold = line_threshold
        self.paragraph_threshold = paragraph_threshold
        self.table_counter = 1
        self.tables = []

    def convert_pdf(self, dir_name, basename):
        file_path = os.path.join(dir_name, basename)
        pdf_pages, pdf_tables = self.parse(file_path)
        return self.parser_pdf_to_md(file_path, pdf_pages, pdf_tables)

    #: 「整页表格」型文档（获奖名单、清单、报表）的采样页数与判定比例。
    #: 这类文档每页就是一张铺满页面的表，逐格转 markdown 没有收益：pdfminer
    #: 解析一页要 0.34s，而 pdfium（C++）整本 223 页只要 3.6s。采样前几页
    #: 判定，命中就整本走快速路径。
    TABLE_LIST_SAMPLE_PAGES = 5
    TABLE_LIST_PAGE_RATIO = 0.5
    TABLE_LIST_SAMPLE_HIT_RATIO = 0.6

    def parse(self, file_path: str) -> Tuple[List[PDFPageContent], List[List[PDFTable]]]:
        pages = []
        tables = []

        with pdfplumber.open(file_path) as pdf:
            if self.is_table_list_document(pdf):
                return self.parse_pages_with_pdfium(file_path), []

            for page_num, page in enumerate(pdf.pages, start=1):
                page_height = page.height
                # 获取页面元素并排序
                elements = self._get_page_elements(page, page_height)
                # 处理文本流
                page_text, page_tables = self._process_elements(elements, page_num, page_height)
                pages.append(PDFPageContent(page_num=page_num, text=page_text))
                tables.extend(page_tables)
                page.flush_cache()

        self.tables = tables
        return pages, self.group_continuous_tables()

    def is_table_list_document(self, pdf) -> bool:
        """采样前几页：表格覆盖页面一半以上，就认为整本都是「整页表格」。

        只用于选路，不影响正常文档的解析结果（非整页表格的文档一律走原流程）。
        """
        pages = pdf.pages[:self.TABLE_LIST_SAMPLE_PAGES]
        if not pages:
            return False
        hits = 0
        for page in pages:
            page_area = page.width * page.height
            for table in page.find_tables():
                width = table.bbox[2] - table.bbox[0]
                height = table.bbox[3] - table.bbox[1]
                if page_area and width * height / page_area >= self.TABLE_LIST_PAGE_RATIO:
                    hits = hits + 1
                    break
        return hits >= len(pages) * self.TABLE_LIST_SAMPLE_HIT_RATIO

    #: 同一视觉行里不同字号的字符，top 会相差几个点；行间距约 15pt。
    LINE_TOP_TOLERANCE = 5.0

    def parse_pages_with_pdfium(self, file_path: str) -> List[PDFPageContent]:
        """用 pdfium 取整页文本（快速路径）。

        只用于「整页表格型」文档：这类文档的行列本来就在阅读顺序里
        （``1 阮丹娅 陕西师范大学 …``），逐格转 markdown 只是把同样的字重排
        一遍。**不做页眉页脚过滤** —— 这里没有坐标可用，而且这类文档页首
        通常是表头行，保留下来对检索反而有用。

        文本按**行**重建：pdfium 的 ``get_text_range()`` 对表格行不插换行，
        整页会变成一行，下游只能按 512 字硬切，记录会被从中间切断。
        """
        document = pdfium.PdfDocument(file_path)
        pages = []
        try:
            for index in range(len(document)):
                page = document[index]
                try:
                    textpage = page.get_textpage()
                    try:
                        pages.append(PDFPageContent(page_num=index + 1,
                                                    text=self.textpage_lines(textpage)))
                    finally:
                        textpage.close()
                finally:
                    page.close()
        finally:
            document.close()
        return pages

    def textpage_lines(self, textpage) -> str:
        """按字符矩形把整页文本拆成行。"""
        text = textpage.get_text_range()
        lines = []
        current = []
        previous_top = None
        for index in range(textpage.count_chars()):
            char = text[index]
            if char in '\r\n':
                if current:
                    lines.append(''.join(current))
                    current = []
                previous_top = None
                continue
            if not char.isspace():
                top = textpage.get_charbox(index)[3]
                if previous_top is not None and abs(top - previous_top) > self.LINE_TOP_TOLERANCE:
                    lines.append(''.join(current))
                    current = []
                previous_top = top
            current.append(char)
        if current:
            lines.append(''.join(current))
        return '\n'.join(line.strip() for line in lines if line.strip())

    def _get_page_elements(self, page, page_height) -> List[Dict]:
        elements = []
        header_boundary = page_height * self.header_ratio
        footer_boundary = page_height * (1 - self.footer_ratio)

        # 表格只找一次：find_tables() 内部要过一遍全页图形对象，之前这里
        # 调了两次（一次取内容、一次取 bbox），平白多一倍开销。
        tables = page.find_tables()
        for table in tables:
            self._extract_table_content(elements, footer_boundary, header_boundary, page_height, table)
        table_bboxes = self._transform_table_bbox(page, tables)

        # 2. 提取文本行并过滤表格区域
        lines = [
            line for line in page.extract_text_lines(
                x_tolerance=15,
                y_tolerance=5,
                keep_blank_chars=False,
                use_text_flow=True,
                layout=False,
                horizontal_ltr=True,
                extra_attrs=["fontname", "size"]  # 携带字体信息
            )
            if not self._in_any_table(line, table_bboxes, page.height)
        ]
        # ---------------------------------

        for line in lines:
            self._extract_text_lines(elements, footer_boundary, header_boundary, line, page_height)

        self._combine_text_line(elements)

        # 按垂直位置排序（从上到下）
        return sorted(elements, key=lambda x: (-x['bbox'][1], x['bbox'][0]))

    def _combine_text_line(self, elements):
        i = 0
        while i < len(elements) - 1:
            current = elements[i]
            next_elem = elements[i + 1]
            if current['type'] != 'text' or next_elem['type'] != 'text':
                i += 1
                continue

            # 判断当前元素是否包含下一个元素的 Y 轴范围，或反之
            y_current_min, y_current_max = current['bbox'][1], current['bbox'][3]
            y_next_min, y_next_max = next_elem['bbox'][1], next_elem['bbox'][3]
            if (y_current_min <= y_next_min and y_current_max >= y_next_max) or \
                    (y_next_min <= y_current_min and y_next_max >= y_current_max):
                # 合并文本数据
                merged_data = current['data'] + next_elem['data']
                # 计算合并后的边界框
                new_bbox = (
                    min(current['bbox'][0], next_elem['bbox'][0]),  # x0 最小值
                    max(y_current_min, y_next_min),  # y0 最大值
                    max(current['bbox'][2], next_elem['bbox'][2]),  # x1 最大值
                    min(y_current_max, y_next_max)  # y1 最小值
                )
                # 替换当前元素为合并后的元素，并移除下一个元素
                elements.pop(i)
                elements.pop(i)
                elements.insert(i, {
                    'type': 'text',
                    'bbox': new_bbox,
                    'data': merged_data
                })
                # 合并后可能需要回退一步，检查与前一个元素的合并可能
                if i > 0:
                    i -= 1
            else:
                i += 1

    def _extract_text_lines(self, elements, footer_boundary, header_boundary, line, page_height):
        bbox = self._convert_bbox(
            (line['x0'], line['top'], line['x1'], line['bottom']),
            page_height
        )
        if not self._is_in_header_footer(bbox, header_boundary, footer_boundary):
            origin_text = line['text']
            # 过滤非打印字符（ASCII 控制字符，Unicode 除外）
            clean_text = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', origin_text)
            elements.append({
                'type': 'text',
                'bbox': bbox,
                'data': clean_text
            })

    def _transform_table_bbox(self, page, tables):
        table_bboxes = []
        for table in tables:
            # 将表格坐标转换为与文本行一致的左上原点坐标系
            table_bbox = (
                table.bbox[0],  # x0
                page.height - table.bbox[3],  # y0 (page_height - bottom)
                table.bbox[2],  # x1
                page.height - table.bbox[1]  # y1 (page_height - top)
            )
            table_bboxes.append(table_bbox)
        return table_bboxes

    def _extract_table_content(self, elements, footer_boundary, header_boundary, page_height, table):
        bbox = self._convert_bbox(table.bbox, page_height)
        if not self._is_in_header_footer(bbox, header_boundary, footer_boundary):
            table_data = table.extract(
                preserve_whitespace=True,
                split_text=False,
                layout=True
            )

            # 处理单元格内容（完全移除换行符）
            processed_data = []
            for row in table_data:
                merged_row = []
                for cell in row:
                    # 合并多行内容并移除所有换行符
                    if isinstance(cell, list):
                        cell = "".join([str(c).strip().replace("\n", "") for c in cell if c])
                    elif cell is None:
                        cell = ""
                    else:
                        cell = str(cell).strip().replace("\n", "")
                    # 过滤非打印字符（ASCII 控制字符，Unicode 除外）
                    clean_text = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', cell)
                    merged_row.append(clean_text)
                processed_data.append(merged_row)

            markdown_table = self._convert_to_markdown(processed_data)
            elements.append({
                'type': 'table',
                'bbox': bbox,
                'data': markdown_table
            })

    def _in_any_table(self, line, table_bboxes, page_height):
        """判断文本行是否位于任何表格区域内（修正版）"""
        # 转换文本行坐标系
        line_bbox = (
            line["x0"],
            page_height - line["bottom"],  # y0
            line["x1"],
            page_height - line["top"]  # y1
        )

        # 直接遍历已转换的表格坐标元组
        for table_bbox in table_bboxes:
            if self._bbox_overlap(line_bbox, table_bbox):
                return True
        return False

    # 修改threshold为2，保留表格的标题
    def _bbox_overlap(self, bbox1, bbox2, threshold=2):
        """修正后的重叠检测算法"""
        return (
                bbox1[0] < bbox2[2] + threshold and
                bbox1[2] > bbox2[0] - threshold and
                bbox1[1] < bbox2[3] + threshold and
                bbox1[3] > bbox2[1] - threshold
        )

    def _process_elements(self, elements, page_num, page_height):
        output = []
        tables = []

        for elem in elements:
            self._process_single_element(elem, output, page_height, page_num, tables)
        return "  \n".join(map(str, output)), tables

    def _process_single_element(self, elem, output, page_height, page_num, tables):
        elem_type = elem['type']
        bbox = elem['bbox']
        if elem_type == 'text':
            text = elem['data']
            output.append(text)

        elif elem_type == 'table':
            table_id = f"table{self.table_counter}"
            tables.append(PDFTable(
                table_id=table_id,
                page_num=page_num,
                content=elem['data'],
                bbox=bbox,
                page_height=page_height
            ))
            output.append(f"{{{{{table_id}}}}}")
            self.table_counter += 1

    def group_continuous_tables(self, threshold: float = 0.2) -> List[List[PDFTable]]:
        """
        分组连续跨页表格
        :param threshold: 页面边缘判定阈值（默认5%）
        :return: 分组后的表格列表
        """
        if not self.tables:
            return []

        groups = []
        current_group = [self.tables[0]]

        for i in range(1, len(self.tables)):
            prev_table = self.tables[i - 1]
            current_table = self.tables[i]

            # 计算位置关系
            is_consecutive_page = current_table.page_num == prev_table.page_num + 1
            prev_bottom_ratio = prev_table.bbox[3] / prev_table.page_height
            current_top_ratio = current_table.bbox[1] / current_table.page_height

            # 判断跨页连续条件
            if (is_consecutive_page and
                    prev_bottom_ratio > (1 - threshold) and  # 前表在页面底部
                    current_top_ratio < threshold):  # 后表在页面顶部
                current_group.append(current_table)
            else:
                groups.append(current_group)
                current_group = [current_table]

        groups.append(current_group)
        return groups

    def _is_in_header_footer(self, bbox, header_boundary, footer_boundary):
        """判断元素是否**整个**落在页眉/页脚带上。

        坐标是左下原点：``header_boundary`` 是页面底部的页脚带上沿，
        ``footer_boundary`` 是页面顶部的页眉带下沿。

        旧判据是「元素与带子有重叠就丢」，整页大表格（比如一整页的名单）
        同时压到上下两条带，会被整张丢掉；它覆盖掉的行又被 ``_in_any_table``
        全过滤 —— 一页正文全空，最终报 ``ParseEmptyError``（对外「解析失败」）。
        现场：223 页的获奖名单 PDF，每页都是一张整页表。
        """
        y0, y1 = bbox[1], bbox[3]
        return y1 <= header_boundary or y0 >= footer_boundary

    def _convert_bbox(self, bbox, page_height):
        x0, top, x1, bottom = bbox
        return (x0, page_height - bottom, x1, page_height - top)

    def parser_pdf_to_md(self, file_path: str, text: List[PDFPageContent], grouped_tables: List[List[PDFTable]]):
        outlines = self.extract_pdf_outlines(file_path)
        # 将文本中的标题替换为outlines中的标题
        if len(outlines) > 0:
            for outline in outlines:
                page_num = outline['page']
                title = outline['title']
                origin_title = outline['origin_title']
                # 找到对应页面的文本
                if page_num <= len(text):
                    page_content = text[page_num - 1].text
                    # 替换原始标题为Markdown格式标题
                    text[page_num - 1].text = process_origin_title(page_content, origin_title, title)

        pdf_filename = os.path.basename(file_path)
        file_folder = replace_char(pdf_filename.split(".")[0])
        pathutil.create_dir_under_root(f'/temp/pdf/{file_folder}_md')
        markdown_filename = pdf_filename.replace('.pdf', '.md')
        output_md_path = os.path.join(work_dir, "temp", "pdf", f'{file_folder}_md', markdown_filename)
        self.export_full_markdown(
            file_path,
            text,
            grouped_tables,
            output_md_path
        )
        return output_md_path

    def export_full_markdown(self, file_path: str, pages: List[PDFPageContent], grouped_tables: List[List[PDFTable]],
                             output_path: str):
        """
        将完整PDF内容导出为Markdown格式（包含文本和表格）
        :param pages: 解析后的文本页面
        :param grouped_tables: 分组后的表格列表
        :param output_path: 输出文件路径
        """
        # 根据PDF文件名生成Markdown文件名
        with open(output_path, 'w', encoding='utf-8') as f:
            # 写入文档内容
            for page in pages:
                page_content = page.text
                # 替换表格占位符为实际内容
                for table_group in grouped_tables:
                    for table in table_group:
                        if table.page_num == page.page_num:
                            placeholder = f"{{{{table{table.table_id.split('table')[-1]}}}}}"
                            page_content = page_content.replace(placeholder, f"\n{table.content}\n")
                page_content = replace_pic_no_pre(page_content)
                f.write(page_content + "\n\n")

    def extract_pdf_outlines(self, pdf_path):
        pdf = pdfium.PdfDocument(pdf_path)
        # 获取目录结构
        toc = pdf.get_toc()
        # 存储目录结构
        outlines = []
        # 将标题转换为Markdown格式的标题

        for item in toc:
            # pypdfium2 4.x 属性式 / 5.x 方法式，差异收在 bookmark_compat
            title = bookmark_title(item)
            level = bookmark_level(item)
            outlines.append({
                "title": self.convert_to_markdown_title(title, level + 1),  # 书签标题
                "origin_title": title,  # 书签标题
                "page": bookmark_page_index(item) + 1,  # 页码从 1 开始
                "level": level + 1  # 层级从 1 开始
            })

        return outlines

    @staticmethod
    def _convert_to_markdown(table_data: List[List[str]]) -> str:
        """优化后的Markdown转换方法（无需处理换行符）"""
        if not table_data:
            return ""

        # 统一列数
        max_columns = max(len(row) for row in table_data)
        normalized_data = [
            row + [""] * (max_columns - len(row))
            for row in table_data
        ]

        # 构建表格
        markdown = []
        headers = normalized_data[0]
        markdown.append("| " + " | ".join(headers) + " |")
        markdown.append("| " + " | ".join(["---"] * len(headers)) + " |")

        for row in normalized_data[1:]:
            markdown.append("| " + " | ".join(row) + " |")

        return "\n".join(markdown)

    def convert_to_markdown_title(self, title, level):
        """
        将标题转换为Markdown格式的标题

        参数:
            title (str): 原始标题
            level (int): 标题层级

        返回:
            str: Markdown格式的标题
        """
        if level == 1:
            return f"# {title}"
        elif level == 2:
            return f"## {title}"
        elif level == 3:
            return f"### {title}"
        elif level == 4:
            return f"#### {title}"
        elif level == 5:
            return f"##### {title}"
        else:
            return f"###### {title}"
