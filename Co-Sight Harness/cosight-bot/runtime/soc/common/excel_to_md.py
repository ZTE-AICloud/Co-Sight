#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Excel → Markdown 转换工具

将 .xls / .xlsx 转为带 Sheet 标题的 Markdown 表格字符串，
供 LlamaIndex 索引使用。

相比 preprocessor.py 中 openpyxl 兜底（line 129-138）的改进点：
  1. 多 Sheet 维度：每个 Sheet 输出 '## {Sheet名}' 标题
  2. Markdown 表格语法：'| col1 | col2 |' 替代 Tab 分隔，便于 LlamaIndex 按结构分块
  3. 智能跳过空 Sheet / 整行空白行
  4. 单元格值统一转字符串并 strip；None 渲染为空字符串
  5. 转义 Markdown 表格中的 '|' 字符，避免破坏列分隔

依赖：
  - openpyxl（仅 .xlsx，纯 Python 解析）
  - xlrd（旧版 .xls，可选；1.x/2.x 均可读 .xls，xlrd 2.0 仅移除了 .xlsx 支持）

使用示例：
    from common.excel_to_md import convert_excel_to_md
    md = convert_excel_to_md(Path("产品参数.xlsx"))
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

logger = logging.getLogger("common.excel_to_md")

# ---------------------------------------------------------------------------
# 依赖导入
# ---------------------------------------------------------------------------

try:
    import openpyxl  # noqa: F401
except ImportError:  # pragma: no cover
    openpyxl = None

try:
    import xlrd  # noqa: F401
except ImportError:  # pragma: no cover
    xlrd = None


# ---------------------------------------------------------------------------
# 单元格与表格渲染
# ---------------------------------------------------------------------------


def _escape_cell(value) -> str:
    """
    把单元格值规范化为 markdown 表格里的一个 cell 文本。

    - None / 空值 → 空字符串
    - 其余值统一 str()，strip 空白；'|' 转义为 '\\|'，换行替换为空格
    """
    if value is None:
        return ""
    text = str(value)
    # strip 空白与换行
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = text.strip()
    # markdown 表格里 '|' 是列分隔符，需要转义
    text = text.replace("|", "\\|")
    return text


def _is_blank_row(cells: Sequence[str]) -> bool:
    """整行所有 cell 都为空 → 视为空行"""
    return all(c == "" for c in cells)


def _render_sheet_as_table(rows: Iterable[Sequence], drop_empty_cols: bool = False) -> str:
    """
    把一个 Sheet 的所有行（已规范化为 [[str, ...], ...]）渲染为 markdown 表格。

    - 跳过全空行
    - 全空 Sheet 返回 ''
    - 表头：第一行非空行
    - 列宽：所有非空行中行宽的最大值（openpyxl 会把行 pad 到 max_column）

    drop_empty_cols=True 时：
      - 扫描所有非空行，统计每列的非空 cell 数
      - 整列非空值总数 = 0（包含表头在内的所有行都没有内容）的列被整体删除
      - 保留列的相对位置不变，header 与 body 的列对齐仍正确
      - 适用场景：宽矩阵型 Excel（如超宽特性矩阵表：16K 列中 99.78% 全空），
        不删空列会让单行渲染出 50K 字符的 padding，浪费 LLM 上下文
    """
    rendered_rows: List[List[str]] = []
    for row in rows:
        cells = [_escape_cell(c) for c in row]
        if _is_blank_row(cells):
            continue
        rendered_rows.append(cells)

    if not rendered_rows:
        return ""

    max_cols = max(len(r) for r in rendered_rows)
    if max_cols == 0:
        return ""

    if drop_empty_cols:
        # 找非空 cell 总数 >= 1 的列；只删 100% 全空的列（保留位置语义）
        keep_cols: List[int] = []
        for ci in range(max_cols):
            for r in rendered_rows:
                if ci < len(r) and r[ci] != "":
                    keep_cols.append(ci)
                    break
        if not keep_cols:
            return ""
        rendered_rows = [[r[ci] for ci in keep_cols] for r in rendered_rows]
        col_count = len(keep_cols)
    else:
        col_count = max_cols

    # 数据行：列数对齐到 col_count（不足补空，过多截断）
    body: List[List[str]] = []
    for row in rendered_rows[1:]:
        if len(row) < col_count:
            row = list(row) + [""] * (col_count - len(row))
        elif len(row) > col_count:
            row = list(row)[:col_count]
        body.append(row)

    lines: List[str] = []
    lines.append("| " + " | ".join(rendered_rows[0]) + " |")
    lines.append("| " + " | ".join(["---"] * col_count) + " |")
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# .xlsx 读取（openpyxl）
# ---------------------------------------------------------------------------


def _read_xlsx(path: Path, drop_empty_cols: bool = False) -> List[tuple[str, str]]:
    """
    读取 .xlsx，返回 [(sheet_name, sheet_md), ...] 列表。
    Sheet_md 是该 Sheet 渲染后的 markdown 表格（无 Sheet 标题）。
    空 Sheet 的 sheet_md 为 ''，调用方按需跳过。
    """
    if openpyxl is None:
        raise ImportError("openpyxl is required to read .xlsx files")

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    sheets: List[tuple[str, str]] = []
    try:
        for ws in wb.worksheets:
            rows = [list(row) for row in ws.iter_rows(values_only=True)]
            md = _render_sheet_as_table(rows, drop_empty_cols=drop_empty_cols)
            sheets.append((ws.title or "(未命名)", md))
    finally:
        wb.close()
    return sheets


# ---------------------------------------------------------------------------
# .xls 读取（xlrd；1.x/2.x 均支持 .xls——xlrd 2.0 移除的是 .xlsx 支持）
# ---------------------------------------------------------------------------


def _read_xls(path: Path, drop_empty_cols: bool = False) -> List[tuple[str, str]]:
    """
    读取旧版 .xls，返回 [(sheet_name, sheet_md), ...] 列表。

    xlrd 1.x / 2.x 均可读 .xls：xlrd 2.0 砍掉的是 .xlsx 支持（改用 openpyxl），
    .xls 读取不受影响——早期"必须 xlrd<2.0"的门禁是误传，已移除。
    """
    if xlrd is None:
        raise ImportError("xlrd is required to read legacy .xls files")

    book = xlrd.open_workbook(str(path))
    sheets: List[tuple[str, str]] = []
    for sheet in book.sheets():
        rows: List[List] = []
        for r in range(sheet.nrows):
            row = [sheet.cell_value(r, c) for c in range(sheet.ncols)]
            rows.append(row)
        md = _render_sheet_as_table(rows, drop_empty_cols=drop_empty_cols)
        sheets.append((sheet.name or "(未命名)", md))
    return sheets


# ---------------------------------------------------------------------------
# 公共入口
# ---------------------------------------------------------------------------


def convert_excel_to_md(
    path: Path,
    *,
    skip_empty_sheets: bool = True,
    include_sheet_index: bool = True,
    drop_empty_cols: bool = False,
) -> str:
    """
    把 Excel 文件（.xls / .xlsx）转为带 Sheet 标题的 markdown 字符串。

    Args:
        path: Excel 文件绝对路径
        skip_empty_sheets: 跳过全空 Sheet（默认 True）
        include_sheet_index: 在 Sheet 标题里加 'Sheet N: ' 前缀（默认 True）
        drop_empty_cols: 删除整列全空的列（默认 False，保持向后兼容）
            - 仅删除"整列所有行（包括 header）非空值总数 = 0"的列
            - 保留列的相对位置不变，header/body 列对齐仍正确
            - 适用：宽矩阵型 Excel（数千列中绝大部分是空 padding）
            - 不适用风险：宽矩阵中恰好某些列在所有行都没有值的"真·稀疏列"
              （这种情况本身就只贡献空 padding，删了不会丢数据）

    Returns:
        完整的 markdown 字符串；如果所有 Sheet 都被跳过或文件无 Sheet，返回 ''

    Raises:
        ImportError: 缺少 openpyxl / xlrd 依赖
        RuntimeError: xlrd>=2.0 且文件是 .xls
        FileNotFoundError: 文件不存在
        ValueError: 文件扩展名不是 .xls / .xlsx
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Excel file not found: {path}")

    ext = path.suffix.lower()
    if ext == ".xlsx":
        sheets = _read_xlsx(path, drop_empty_cols=drop_empty_cols)
    elif ext == ".xls":
        sheets = _read_xls(path, drop_empty_cols=drop_empty_cols)
    else:
        raise ValueError(f"Unsupported Excel extension: {ext} (expected .xls or .xlsx)")

    if skip_empty_sheets:
        sheets = [(name, md) for name, md in sheets if md]

    if not sheets:
        logger.info("excel_to_md: no non-empty sheets in %s", path.name)
        return ""

    # 拼装：每个 Sheet 渲染为 '## Sheet 名' 标题 + 表格
    sections: List[str] = []
    total = len(sheets)
    for idx, (name, md) in enumerate(sheets, 1):
        if include_sheet_index:
            heading = f"## Sheet {idx}: {name}"
        else:
            heading = f"## {name}"
        sections.append(f"{heading}\n\n{md}")

    final_md = "\n\n".join(sections)
    logger.info(
        "excel_to_md: %s → %d sheets, %d chars",
        path.name,
        total,
        len(final_md),
    )
    return final_md


# ---------------------------------------------------------------------------
# 便捷别名（与 preprocessor 风格保持一致）
# ---------------------------------------------------------------------------

# 让调用方既可以 `from common.excel_to_md import convert_excel_to_md`，
# 也可以 `from common.excel_to_md import excel_to_md` 走更短的别名。
excel_to_md = convert_excel_to_md
