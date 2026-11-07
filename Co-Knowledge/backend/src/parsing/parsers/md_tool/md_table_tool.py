import re
import os

from parsing.common.sentence_add_validator import SentenceValidator
from parsing.common.special_filter import SpecialFilter


chinese_numbers = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]

class MdTableTool:
    def __init__(self):
        pass

    def md_table_parser(self, markdown_content, md_file):
        content = {}
        pattern = r'^(#+)\s*(.*?)\n(.*?)(?=(?:\n#|\Z))'
        matches = re.findall(pattern, markdown_content, re.MULTILINE | re.DOTALL)
        title_content_dict, page_name, table_head = self.read_table(matches)
        clean_content = self.add_title_for_content(title_content_dict, os.path.basename(md_file).split('.')[0])
        content = self.create_key_by_content(clean_content, table_head)
        for key, value in list(content.items()):
            self.delete_key(content, key)
        return content

    def read_table(self, matches):
        title_content_dict = {}
        page_name = ''
        table_head = ''
        # 遍历匹配结果
        for idx, match in enumerate(matches):
            level, title, content = match
            level_num = len(level)
            is_table, table_content, title, page_name = self.is_table_find(content, match, title, idx, level_num, page_name)

            table_head = self.table_parser(is_table, level, table_content, table_head, title, title_content_dict)
        return title_content_dict, page_name, table_head.replace('|', ' ').replace('*', '')

    def table_parser(self, is_table, level, table_content, table_head, title, title_content_dict):
        if is_table == 1:
            result = ''
            table_rows = table_content.split('\n')  ##按行切开
            table_rows = [item for item in table_rows if len(item) > 2]
            col_num = self.find_table_col_num(table_rows)
            table_head, head_row_index = self.find_table_head(table_rows, col_num)
            table_heads = self.split_table_head(col_num, table_head)

            self.get_row(col_num, head_row_index, level, result, table_head, table_heads, table_rows, title,
                         title_content_dict)
        return table_head

    def get_row(self, col_num, head_row_index, level, result, table_head, table_heads, table_rows, title,
                title_content_dict):
        for num, table_row in enumerate(table_rows):
            row_text = ''
            cells = [cell.strip() for cell in table_row.split('|') if cell.strip()]
            # 第一种情况，非表头，非分割行
            result = self.table_split_and_fill(cells, col_num, head_row_index, num, result, row_text,
                                               table_heads, table_row)
        key = title + table_head.replace('|', ' ').replace('*', '')
        title_content_dict[key] = {"level": len(level), "content": result}

    def table_split_and_fill(self, cells, col_num, head_row_index, num, result, row_text, table_heads, table_row):
        if num > head_row_index and (all(cell == '-' for cell in cells) == 0) and (table_row.find('---') == -1) and (
                len(cells) == col_num):
            row_text = self.split_table_body(cells, row_text, table_heads)
        elif num < head_row_index or (len(cells) == col_num):
            row_text = self.split_other(cells, row_text)
        # row_text.replace('。', ';')
        result = result + row_text + '\n'  ##之后按。切割表格中每一行
        return result

    def split_other(self, cells, row_text):
        for cell in cells:
            row_text = row_text + cell + ';'
        return row_text

    def split_table_body(self, cells, row_text, table_heads):
        for cell_num, cell in enumerate(cells):
            if table_heads[cell_num] != '':
                row_text = row_text + table_heads[cell_num] + ":" + cell + ';'
            else:
                row_text = row_text + cell + ';'
        return row_text

    def split_table_head(self, col_num, table_head):
        if table_head == '':
            table_heads = [''] * col_num
        else:
            table_heads = table_head.split('|')
            table_heads = [item.strip().replace('*', '') for item in table_heads if item.strip()]
        return table_heads

    def is_table_find(self, content, match, title, idx, level_num, page_name):
        is_table = 0
        table_content = ''
        if title.find('|') != -1 and content.find('|') != -1:  ##情况1，第一个单元格内容是“#”，导致识别出错
            title = ''
            table_content = match[1] + match[2]
            is_table = 1
        elif title.find('|') == -1 and content.find('|') != -1:  ##情况2，识别未出错
            table_content = match[2]
            is_table = 1
        if idx == 0 and level_num == 1:
            page_name = title
        return is_table, table_content, title, page_name

    def find_table_col_num(self, table_rows):
        columns = 0
        if '|' in table_rows[0]:
            columns = table_rows[0].count('|') - 1
        else:
            for num, row in enumerate(table_rows):
                if row.strip() and row.count('|') > 1:
                    columns = row.count('|') - 1
                    break
        return columns

    def find_table_head(self, table_rows, col_num):
        head_row = ''
        head_row_index = -1
        for i in range(len(table_rows) - 1):
            if self.is_header_row(table_rows[i], table_rows[i + 1], col_num):
                head_row = table_rows[i]
                head_row_index = i
                break
        return head_row, head_row_index

    def is_header_row(self, row, next_row, col_num):
        # 将行拆分为各个单元格
        cells = [cell.strip() for cell in row.split('|') if cell.strip()]

        # 检查列数是否匹配
        if len(cells) != col_num:
            return False

        # 检查单元格是否为空或仅包含空格
        if any(not cell or cell.isspace() for cell in cells[1:-1]):
            return False

        # 第一种情况：所有单元格都被'**文字**'标注
        if all(cell.startswith('**') and cell.endswith('**') for cell in cells):
            return True

        next_cells = [cell.strip() for cell in next_row.split('|') if cell.strip()]
        # 第二种情况：检查下一行是否为分隔行
        if next_cells and all(cell == '-' for cell in next_cells):
            return True

        # 第三种情况：检查当下一行行是否存在'---'
        if any('---' in cell for cell in next_cells):
            return True

        return False


    def create_key(self, headers: list):
        new_header = []
        for header in headers:
            if header:
                new_header.append(header.replace(" ", ""))
        return "，".join(new_header)

    def add_title_for_content(self,  title_content_dict,  file_name):
        clean_content = {}
        for title, data in title_content_dict.items():
            standard_title = self.create_standard_title(title)
            standard_content = data['content']
            #standard_content = self.create_standard_title(standard_content)
            clean_content[standard_title] = {'text': standard_content, 'source': file_name}
        return clean_content

    def create_standard_title(self, text):
        pattern_list = [r'\d+(\.\d+)+', r'\d+\.\s*', r'^\s*\w+、\s*|：']
        pattern = '|'.join(pattern_list)
        text = re.sub(pattern, '', text)
        new_text = text.replace(" ", "").replace("*", "").replace(r'\n(?!\n)', '').replace('\n', '')
        new_text = re.sub(r',+', ',', new_text)
        for str_sub in chinese_numbers:
            new_text = new_text.replace(str_sub + "、", '').replace(str_sub + ".", '')
        return new_text

    def create_key_by_content(self, content, table_head):
        paragraph_content_dict = {}
        for key in content.keys():
            paragraph_content = content[key]['text']
            self.split_paragraph(content, key, paragraph_content_dict, paragraph_content)
        return paragraph_content_dict

    def split_paragraph(self, content, key, paragraph_content_dict, paragraph_content):
        sentences = paragraph_content.split("\n")
        sentences = [sentence.strip() for sentence in sentences if sentence.strip()]
        for sentence in sentences:
            self.add_sentence_for_content(content, key, paragraph_content_dict, paragraph_content, sentence)

    def add_sentence_for_content(self, content, key, paragraph_content_dict, paragraph_content_split, sentence):
        sentence = SpecialFilter().replace_pic_and_serial(sentence)
        if SentenceValidator().is_add_sentence_key(sentence):
            paragraph_content_dict[key + sentence] = {'text': paragraph_content_split}

    def delete_key(self, content, key):
        strr = content[key]['text']
        if len(key) < 10:
            del content[key]
        elif strr.find(key) != -1 and strr.find('\n') != -1:
            strr = strr.replace(key, '').replace('\n', '')
            if len(strr) < 5:
                del content[key]