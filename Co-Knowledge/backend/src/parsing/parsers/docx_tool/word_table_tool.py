def _local_name(tag):
    return tag.rsplit('}', 1)[-1]


class WordTableParser:
    """把 Word 表格读成「一行一条、单元格用 ``|`` 分隔」的文本。

    **只负责读表，不负责在文档里找表**：找表由 ``WordContentParser`` 按
    ``w:body`` 的文档顺序遍历完成。

    每一行用 **网格列号 → 文本** 的字典表示，而不是列表：
    ``python-docx`` 的 ``_Row.cells`` 会把横向合并（``gridSpan``）的单元格
    重复展开成多格，列号与列表下标不再是同一个东西 —— 用列表存会在「第一行
    有空白格 + 后面有横向合并」时越界（现场：4414 段 / 642 张表
    的 docx 报 ``IndexError: list index out of range``）。
    """

    def read_tables(self, result, table_text, tables):
        """连续读多张表（跨页续表）到同一组缓冲区，表头取第一张的首行。

        行号跨表连续：续表的第一行通常是重复的表头，按普通行处理、
        由第一张表的表头补前缀。

        :return: ``[[单元格, ...], ...]`` —— 结构化的行，供块切分器使用；
                 表头行是第 0 行。
        """
        rows = []
        row_offset = 0
        for table in tables:
            for j, tr in enumerate(table.rows):
                row = self.read_table_cell(row_offset + j, result, table_text, tr)
                if row:
                    rows.append(row)
            row_offset = row_offset + len(table.rows)
        return rows

    def read_table(self, result, table, table_text):
        """读单张表（调用方与测试的最小入口）。"""
        self.read_tables(result, table_text, [table])

    def read_table_cell(self, j, result, table_text, tr):
        cells = {}
        for grid_index, tc in self.row_cells(tr):
            if tc.vMerge == 'continue':
                # 纵向合并的延续格：值就是上一行同列那格，交给 blank 取值，
                # 不再走 python-docx 的 ``_tc_above``（每个延续格一次 lxml xpath）
                cell_text = ''
            else:
                # 多段单元格的换行换成空格：直接删掉会把英文粘成一个词
                # （「Sys」+「hw-module slot…」→「Syshw-module」，关键词检索
                # 再也匹配不上）。``ip.docx`` 的「关闭单板」列。
                cell_text = self.cell_text(tc).strip().replace("\n", " ").replace("。", "；")
            cells[grid_index] = self.cell_value(cell_text, grid_index, j, cells, table_text)
        if cells:
            table_text.append(cells)
            row = list(cells.values())
            result.append('|'.join(row))
            result[-1] = result[-1] + "\n"
            return row
        return None

    def row_cells(self, tr):
        """按 ``w:tc`` 逐个产出 ``(网格列号, w:tc 元素)``。

        ``python-docx`` 的 ``_Row.cells`` 会把横向合并（``gridSpan``）的同一个
        单元格重复展开成多格 —— 同一段文字在一行里重复输出（实测「预计倒换
        结果」那一行把同一句重复了 3 次）；纵向合并的延续格还会递归查上一行。
        这里直接遍历 ``w:tc``，列号按 ``gridSpan`` 累加，两件事都省掉。
        """
        grid_index = tr.grid_cols_before
        for tc in tr._tr.tc_lst:
            yield grid_index, tc
            grid_index = grid_index + tc.grid_span

    def cell_text(self, tc):
        """单元格文本，**包含嵌套表格与内容控件**。

        ``python-docx`` 的 ``_Cell.text`` 只读直属段落，单元格里再套一层表时
        那部分文字会整段消失（实测：嵌套表内容丢失）。

        这里直接遍历 ``w:tc`` 的子节点取 ``w:t``，不走 ``cell.paragraphs`` /
        ``Paragraph.text``：后者每个段落一次 lxml xpath，642 张表 / 8 万个
        单元格的文档光这一步就要 10s。
        """
        parts = []
        for child in tc.iterchildren():
            name = _local_name(child.tag)
            if name == 'tbl':
                nested = self.table_text(child)   # 嵌套表单独处理，避免重复
                if nested.strip():
                    parts.append(nested)
                continue
            text = ''.join(node.text or '' for node in child.iter()
                           if _local_name(node.tag) == 't')
            if text.strip():
                parts.append(text)
        return '\n'.join(parts)

    def table_text(self, tbl):
        """嵌套表格的文本：一行一条，单元格用空格分隔。"""
        rows = []
        for tr in tbl.iterchildren():
            if _local_name(tr.tag) != 'tr':
                continue
            cells = [self.cell_text(tc).strip() for tc in tr.iterchildren()
                     if _local_name(tc.tag) == 'tc']
            cells = [cell for cell in cells if cell]
            if cells:
                rows.append(' '.join(cells))
        return '\n'.join(rows)

    def cell_value(self, cell_text, grid_index, row_index, row_cells, table_text):
        if cell_text:
            if row_index > 0:
                header_text = self.header_text(table_text, grid_index)
                if header_text:
                    return header_text + "：" + cell_text  # 为第一行以外的表格内容添加表头信息，便于LLM理解
            return cell_text
        return self.blank_value(grid_index, row_index, row_cells, table_text)

    def blank_value(self, grid_index, row_index, row_cells, table_text):
        #优先左侧，没有的话上侧
        if grid_index == 0:
            return " " if row_index == 0 else self.above_text(table_text, row_index, grid_index)
        if row_index == 0:
            return self.left_text(row_cells)
        return self.above_text(table_text, row_index, grid_index)

    def left_text(self, row_cells):
        """本行左侧最近一个已填内容。"""
        if not row_cells:
            return " "
        return list(row_cells.values())[-1]

    def above_text(self, table_text, row_index, grid_index):
        """取上一行同网格列内容。

        Word/WPS 编辑过的表格，行与行的格子数可以不一致（合并单元格、残留的
        网格定义）。此时「上侧」可能根本没有这一列，退回空格，不能让整份
        文档因为一个空单元格而解析失败。
        """
        if row_index - 1 >= len(table_text):
            return " "
        return table_text[row_index - 1].get(grid_index, " ")

    def header_text(self, table_text, grid_index):
        """取表头行同网格列内容；表头缺这一列时返回空串。

        表头行比正文行短是真实存在的（两份应急预案 .docx：表头 2 格 /
        正文行 3 格、表头 4 格 / 末行 5 格）。不能直接 ``table_text[0][i]``：
        列号越界会 IndexError，整份文档报「解析失败」。
        """
        if not table_text:
            return ''
        return table_text[0].get(grid_index, '')
