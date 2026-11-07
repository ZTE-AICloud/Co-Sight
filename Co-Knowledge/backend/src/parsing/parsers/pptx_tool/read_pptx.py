import os
import re
import xml.etree.ElementTree as ET

from pptx import Presentation
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.shapes.group import GroupShape

from parsing.common import pathutil
from parsing.common.logutil import log
from parsing.common.pathutil import get_workdir

work_dir = get_workdir()


def parse_xml(xml_str):
    # 解析XML并处理命名空间
    root = ET.fromstring(xml_str)
    ns = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart',
          'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}

    # 提取分类
    categories = []
    cat_nodes = root.findall('.//c:cat/c:strRef/c:strCache/c:pt', ns)
    for pt in cat_nodes:
        categories.append(pt.find('c:v', ns).text)

    # 提取数值
    values = []
    val_nodes = root.findall('.//c:val/c:numRef/c:numCache/c:pt', ns)
    for pt in val_nodes:
        values.append(int(float(pt.find('c:v', ns).text)))  # 处理可能的浮点数格式

    chart_markdown = ["| Category | Value |", "|------|----|"]
    for category, value in zip(categories, values):
        chart_markdown.append(f"| {category} | {value} |")

    return '\n'.join(chart_markdown)


def replace_char(chars):
    return chars.replace(' ', '_').replace('【', '').replace('】', '').replace('“', '').replace(
        '”', '').replace('\\', '').replace('，', '')


def extract_chart_data_for_supported_type(chart):
    all_data = []
    for plot_idx, plot in enumerate(chart.plots):
        # 获取分类轴数据（X轴标签）
        process_each_plot(all_data, plot, plot_idx)

    if not all_data:
        raise Exception('no chart data')
    headers = ["Plot", "Series", "Category", "Value"]
    header_line = "| " + " | ".join(headers) + " |"
    separator_line = "| " + " | ".join(["---"] * len(headers)) + " |"
    # 生成数据行
    rows = []
    for row in all_data:
        rows.append("| " + " | ".join(map(str, [row[col] for col in headers])) + " |")

    return "\n".join([header_line, separator_line] + rows)


def process_each_plot(all_data, plot, plot_idx):
    categories = [cat.label for cat in plot.categories] if plot.categories else [f"Category {i + 1}" for i in
                                                                                 range(len(
                                                                                     plot.series[0].values))]
    # 遍历当前 plot 下的所有 series（如柱状图的不同颜色柱体）
    for series in plot.series:
        process_each_series(all_data, categories, plot_idx, series)


def process_each_series(all_data, categories, plot_idx, series):
    series_name = series.name or f"Series_{plot_idx + 1}_{len(all_data) + 1}"
    # 遍历 series 的每个数据点
    for idx, value in enumerate(series.values):
        # 处理空值（如 None 或 NaN）
        if value is None:
            value = 0  # 或保留为 None，根据需求调整
        # 构建数据行
        row = {
            "Plot": f"Plot {plot_idx + 1}",
            "Series": series_name,
            "Category": categories[idx] if idx < len(categories) else "Unknown",
            "Value": value
        }
        all_data.append(row)


def check_chart_type_supported(chart):
    try:
        chart_type = chart.chart_type
        if chart_type in (XL_CHART_TYPE.COLUMN_CLUSTERED, XL_CHART_TYPE.PIE_EXPLODED, XL_CHART_TYPE.LINE_MARKERS):
            return True
        return False
    except Exception as e:
        log.error(f'get chart type failed,{e}')
        return False


def get_chart_title(chart):
    try:
        return chart.chart_title.text_frame.text
    except Exception as e:
        log.error(f'get chart title failed,{e}')
        return ''


class PPTXContentParser:
    def __init__(self, left_threshold_ratio: float = 0.48):
        self.left_threshold_ratio = left_threshold_ratio
        self.table_counter = 1
        self.last_header = ''

    def convert_pptx(self, dir_name, basename):
        file_path = os.path.join(dir_name, basename)
        return self.ppt_to_markdown(file_path)

    def ppt_to_markdown(self, ppt_path):
        prs = Presentation(ppt_path)
        pptx_filename = os.path.basename(ppt_path)
        markdown_filename = pptx_filename.replace('.pptx', '.md')
        file_folder = replace_char(pptx_filename.split(".")[0])
        pathutil.create_dir_under_root(f'/temp/pptx/{file_folder}_md')
        output_md_path = os.path.join(work_dir, "temp", "pptx", f'{file_folder}_md', markdown_filename)

        markdown = []

        for i, slide in enumerate(prs.slides):
            # 添加幻灯片分隔符
            markdown.append(f"\n\n<!-- Slide {i + 1} -->\n\n")

            # 划分左、右区域
            slide_width = prs.slide_width
            left_threshold = slide_width * self.left_threshold_ratio

            # 按区域分组
            left_shapes = []
            right_shapes = []
            for shape in slide.shapes:
                if not shape.left or shape.left < left_threshold:
                    left_shapes.append(shape)
                else:
                    right_shapes.append(shape)

            sorted_shapes = sort_page_shapes(left_shapes)
            sorted_shapes.extend(sort_page_shapes(right_shapes))
            need_add_title = {"value": True}
            for shape in sorted_shapes:
                self.process_shape(shape, markdown, i, need_add_title)

        # 写入Markdown文件
        with open(output_md_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(markdown))

        return output_md_path

    def process_shape(self, shape, markdown, slide_num, need_add_title):
        if isinstance(shape, GroupShape):
            # 递归处理 GroupShape 内的子形状
            for sub_shape in shape.shapes:
                self.process_shape(sub_shape, markdown, slide_num, need_add_title)
            return

        # 处理文本框内容
        if shape.has_text_frame:
            text_frame = shape.text_frame
            for paragraph in text_frame.paragraphs:
                text = str(paragraph.text)
                text = clean_text(text.strip())
                if not text:
                    continue

                self.process_paragraph(markdown, need_add_title, paragraph, text)
        elif shape.has_table:
            table = shape.table
            markdown_table = convert_table_to_markdown(table)
            markdown.append(
                f"<!-- Slide {slide_num + 1}, Table {self.table_counter} -->\n\n{markdown_table}\n"
            )
            self.table_counter += 1
        # 图片不参与解析（纯图片内容没有可检索文本）
        elif shape.shape_type == MSO_SHAPE_TYPE.CHART:
            self.process_chart(markdown, shape, slide_num)

    def process_chart(self, markdown, shape, slide_num):
        try:
            chart_title = get_chart_title(shape.chart)
            if check_chart_type_supported(shape.chart):
                table_data = extract_chart_data_for_supported_type(shape.chart)
            else:
                xml_str = shape.chart.part.blob.decode('utf-8')
                table_data = parse_xml(xml_str)
            if chart_title:
                markdown.append(chart_title)
            markdown.append(
                f"<!-- Slide {slide_num + 1}, Chart {self.table_counter} -->\n\n{table_data}\n"
            )
            self.table_counter += 1
        except Exception as e:
            log.error(f'handle pptx chart failed,{e}')

    def process_paragraph(self, markdown, need_add_title, paragraph, text):
        # 处理列表项（简单检测项目符号）
        if paragraph.level > 0:
            indent = '  ' * (paragraph.level - 1)
            markdown.append(f"{indent}- {text}\n")
        else:
            # 处理普通段落
            if need_add_title["value"]:
                # 每页第一行文本作为标题
                if text != self.last_header:
                    markdown.append(f"{'#'} {text}\n")
                    self.last_header = text
                need_add_title["value"] = False
            else:
                markdown.append(f"{text}\n\n")


def sort_page_shapes(origin_shapes):
    try:
        return sorted(
            origin_shapes,
            key=lambda x: (
                x.top if x.top is not None else 0,
                x.left if x.left is not None else 0
            )
        )
    except Exception:
        return origin_shapes


def replace_pic_no_pre(text):
    # 替换顺序会导致部分字符串遗留，例如 -1所示
    text = re.sub(r'如图\d+-\d+所示', '', text)
    text = re.sub(r'如图\d+(\.\d+)?所示', '', text)
    text = re.sub(r'图\d+(\.\d+)?所示', '', text)
    text = re.sub(r'图\d+-\d+所示', '', text)
    text = re.sub(r'图\d+-\d+', '', text)
    text = re.sub(r'图\d+(\.\d+)?', '', text)
    return text


def clean_text(origin_text):
    replace_pic_text = replace_pic_no_pre(origin_text)
    return re.sub(r'[\x00-\x1F\x7F-\x9F]', '', replace_pic_text)


def convert_table_to_markdown(table):
    """将 PowerPoint 表格转换为 Markdown 格式"""
    markdown_lines = []

    # 提取表头
    headers = [clean_text(cell.text.replace('\n', ' ').strip()) for cell in table.rows[0].cells]
    markdown_lines.append("| " + " | ".join(headers) + " |")

    # 添加分隔行
    markdown_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

    # 提取数据行
    counter = 0
    for row in table.rows:
        if counter == 0:
            counter += 1
            continue
        cells = [clean_text(cell.text.replace('\n', ' ').strip()) for cell in row.cells]
        # 处理单元格数量不足的情况（如合并单元格）
        while len(cells) < len(headers):
            cells.append("")
        markdown_lines.append("| " + " | ".join(cells) + " |")
        counter += 1

    return "\n".join(markdown_lines)
