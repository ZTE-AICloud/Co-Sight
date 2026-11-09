#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cosightbot-soc-extract —— Excel 结构勘察器（胶水工具）。

把标书 Excel 的结构信息（sheet 列表、每个 sheet 的表头候选行、前列内容样例、
合并单元格概况）以 JSON 打到 stdout，供 Claude 决定：哪些 sheet 是应答列表、
表头在哪一行、各字段在哪一列。

只读操作，不写任何文件。
"""
import json
import sys
from pathlib import Path

# ---- sys.path 引导：本脚本位于 <插件根>/skills/cosightbot-soc-extract/scripts/ ----
_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_RUNTIME = _PLUGIN_ROOT / "runtime" / "soc"
for _p in (str(_RUNTIME), str(_RUNTIME / "watch_dog")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common.bootstrap import bootstrap  # noqa: E402

bootstrap()  # venv 重入 + .env 加载 + preflight（失败 exit 3）

import openpyxl  # noqa: E402

_MAX_PREVIEW_ROWS = 8      # 每个 sheet 打印前 N 行（含表头候选）
_MAX_PREVIEW_COLS = 12     # 每行最多打印 N 列
_MAX_CELL_CHARS = 60       # 单元格内容截断


def _cell_text(v) -> str:
    if v is None:
        return ""
    s = str(v).replace("\n", " ").replace("\r", " ").strip()
    return s[:_MAX_CELL_CHARS] + ("…" if len(s) > _MAX_CELL_CHARS else "")


def inspect_excel(excel_path: Path) -> dict:
    wb = openpyxl.load_workbook(excel_path, data_only=True)
    sheets = []
    for ws in wb.worksheets:
        preview = []
        for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, _MAX_PREVIEW_ROWS),
                                max_col=min(ws.max_column, _MAX_PREVIEW_COLS)):
            preview.append([_cell_text(c.value) for c in row])
        # 统计非空行数（粗略反映 sheet 体量）
        nonempty_rows = 0
        for row in ws.iter_rows(values_only=True):
            if any(v is not None and str(v).strip() for v in row):
                nonempty_rows += 1
        sheets.append({
            "title": ws.title,
            "max_row": ws.max_row,
            "max_column": ws.max_column,
            "nonempty_rows": nonempty_rows,
            "merged_ranges": [str(r) for r in list(ws.merged_cells.ranges)[:10]],
            "preview_first_rows": preview,
        })
    return {"excel": str(excel_path), "sheet_count": len(sheets), "sheets": sheets}


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: python inspect_excel.py <Excel路径>", file=sys.stderr)
        return 2
    excel_path = Path(sys.argv[1]).expanduser().resolve()
    if not excel_path.is_file():
        print(json.dumps({"ok": False, "error": f"文件不存在: {excel_path}"}, ensure_ascii=False))
        return 1
    if excel_path.suffix.lower() not in (".xls", ".xlsx", ".xlsm"):
        print(json.dumps({"ok": False, "error": f"仅支持 .xls/.xlsx/.xlsm: {excel_path.suffix}"},
                         ensure_ascii=False))
        return 1
    result = inspect_excel(excel_path)
    result["ok"] = True
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
