import csv
import openpyxl

from parsing.common import create_doc
from parsing.common.decode_tool import detect_encoding
from parsing.common.logutil import log


class ExcelContentParser():
    def __init__(self):
        pass

    def write_txt_for_xlsx(self, source, excel_path):
        docs = []
        rows = []
        log.info(f'read excel {excel_path}')
        wb = openpyxl.load_workbook(excel_path)
        sheet = wb.active
        for row in sheet.iter_rows(min_row=1):
            cells = [_cell_text(cell.value) for cell in row]
            if not any(cells):
                continue
            rows.append(cells)
            self._append_row(docs, cells, source)
        _attach_table_block(docs, rows, source)
        return docs

    def write_txt_for_csv(self, source, excel_path):
        docs = []
        rows = []
        log.info(f'read csv {excel_path}')
        encoding = detect_encoding(excel_path)
        log.info(f'encoding {encoding}')
        with open(excel_path, newline='', encoding=encoding) as csvfile:
            csv_reader = csv.reader(csvfile)
            for row in csv_reader:
                cells = [_cell_text(value) for value in row]
                if not any(cells):
                    continue
                rows.append(cells)
                self._append_row(docs, cells, source)
        _attach_table_block(docs, rows, source)
        return docs

    @staticmethod
    def _append_row(docs, cells, source):
        """一行表格 → 一条记录。

        ⚠️ 以前**只取前两列**（``row[0]`` / ``row[1]``），第三列往后全部丢失 ——
        实测一份 3 列的 xlsx 切出来的切片只剩「Category EV」这种碎片。
        现在整行按 `` | `` 拼起来，列数不再影响内容完整性。
        """
        cells = [cell for cell in cells if cell]
        if not cells:
            return
        row_text = ' | '.join(cells)
        create_doc.create_doc_by_content(docs, row_text, row_text, source, True)


def _attach_table_block(docs, rows, title):
    """整张表作为**一个** table 块挂到第一条文档上。

    切片器按行分包并重复表头 —— 一行就是一个原子单位，不会被 512 字从中间
    切断。以前 xlsx/csv 是「每行一条文档 → 拼回全文 → 重新按字符切」，实测
    26.5% 的行被拆到两个切片里，问答对会被拆散。
    """
    if docs and rows:
        docs[0].blocks = [{'kind': 'table', 'title': title, 'rows': rows}]


def _cell_text(value):
    """单元格 → 文本；None 视为空（以前会变成字符串 'None'）。"""
    return '' if value is None else str(value).strip()
