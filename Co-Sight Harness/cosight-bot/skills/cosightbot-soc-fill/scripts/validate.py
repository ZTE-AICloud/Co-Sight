#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cosightbot-soc-fill —— 回填完整性自检器（硬性闸门）。

校验 `<stem>-应答后.xlsx` 是否完整、正确地承载了应答 JSON：

  1. 产物存在且可用 openpyxl 打开；原 Excel 仍在（未被删除/覆盖路径）。
  2. 应答 JSON 的每条 requirement 都映射到原 Excel 中对应的 sheet/row，
     且产物中同一行仍包含该文本（归一化：去首尾空白 + 换行/回车折叠为空格）。
  3. 每条匹配行的合规列已填写（单列 Compliance 非空，或三列式 Complied/
     Partial Complied/Not Complied 恰有一列打了 Y/✓/√/FC/PC/NC）——
     未命中知识库的条目（JSON compliance 为空）除外：其合规列必须留空，
     且【其他说明】必须带「未命中知识库」标记，最终强制列出清单。
  4. 【是否冲突】列：JSON 标记 conflict=true 的行，单元格必须填真值
     （是/True）且已做红色填充（FFFF0000）。
  5. 8 个新增列（检索来源/检索来源文件/资料入库时间/匹配到的需求描述/
     置信度/是否冲突/大模型复核/其他说明）在表头行中存在。
  6. 无两条 requirement 匹配同一行（重复需求防漂移）。

零兜底：任一违规 → 打印全部违规明细，exit 1；全部通过 → 打印统计，exit 0。

用法：
  python validate.py <原Excel> <应答JSON> [产物Excel]
  （产物缺省 = 原 Excel 同目录 <stem>-应答后.xlsx）
"""
import json
import sys
from pathlib import Path

# ---- sys.path 引导：本脚本位于 <插件根>/skills/cosightbot-soc-fill/scripts/ ----
_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_RUNTIME = _PLUGIN_ROOT / "runtime" / "soc"
for _p in (str(_RUNTIME), str(_RUNTIME / "watch_dog")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common.bootstrap import bootstrap  # noqa: E402

bootstrap()  # venv 重入 + .env 加载 + preflight（失败 exit 3）

import openpyxl  # noqa: E402

_NEW_COLUMNS = (
    "检索来源", "检索来源文件", "资料入库时间", "匹配到的需求描述",
    "置信度", "是否冲突", "大模型复核", "其他说明",
)
_COMPLIANCE_SINGLE_NAMES = {"compliance", "应答", "合规", "合规性", "应答情况"}
_COMPLIANCE_TRI_NAMES = ("complied", "partial complied", "not complied")
_MARK_VALUES = {"y", "✓", "√", "fc", "pc", "nc", "yes"}
_CONFLICT_TRUTHY = {"是", "true", "True", "TRUE"}
_RED_ARGB = {"FFFF0000", "00FF0000"}


def _norm(s) -> str:
    if s is None:
        return ""
    return " ".join(str(s).replace("\r", " ").replace("\n", " ").split())


def _header_map(ws) -> dict:
    """扫前 10 行找表头行：返回 {归一化表头文本: (row, col)}（取最浅一行）。"""
    mapping: dict = {}
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 10)):
        for cell in row:
            text = _norm(cell.value).lower()
            if not text:
                continue
            key = (text, cell.row)
            if text not in mapping or cell.row < mapping[text][0]:
                mapping[text] = (cell.row, cell.column)
    return mapping


def _find_compliance_cells(ws, row_idx: int, headers: dict) -> list:
    """返回该行所有"合规指示单元格"的文本值列表（单列或三列式）。"""
    values = []
    for name in _COMPLIANCE_SINGLE_NAMES:
        if name in headers:
            _, col = headers[name]
            values.append(_norm(ws.cell(row=row_idx, column=col).value))
    tri_cols = [headers[n][1] for n in _COMPLIANCE_TRI_NAMES if n in headers]
    if len(tri_cols) == 3:
        values.extend(_norm(ws.cell(row=row_idx, column=c).value) for c in tri_cols)
    return values


def _compliance_matches(ws, row_idx: int, headers: dict, expected: str) -> bool:
    """检查目标行的合规标记是否与 JSON 判定一致。"""
    expected = _norm(expected).upper()
    single_values = {
        "FC": {"fc", "y", "✓", "√", "yes", "complied", "fully compliant", "满足", "完全满足"},
        "PC": {"pc", "p", "partial", "partial complied", "partially complied", "部分满足"},
        "NC": {"nc", "n", "no", "not complied", "non-compliant", "不满足"},
    }
    if expected not in single_values:
        return False

    single_cols = [headers[name][1] for name in _COMPLIANCE_SINGLE_NAMES if name in headers]
    if single_cols:
        return any(
            _norm(ws.cell(row=row_idx, column=col).value).lower() in single_values[expected]
            for col in single_cols
        )

    if all(name in headers for name in _COMPLIANCE_TRI_NAMES):
        expected_name = {
            "FC": "complied",
            "PC": "partial complied",
            "NC": "not complied",
        }[expected]
        for name in _COMPLIANCE_TRI_NAMES:
            value = _norm(ws.cell(row=row_idx, column=headers[name][1]).value).lower()
            if name == expected_name:
                if value not in {"y", "✓", "√"}:
                    return False
            elif value in {"y", "✓", "√"}:
                return False
        return True
    return False


def _matching_rows(wb, requirement: str) -> list[tuple[str, int]]:
    """Return source rows containing an exact normalized requirement."""
    matches = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row):
            if any(_norm(cell.value) == requirement for cell in row):
                matches.append((ws.title, row[0].row))
    return matches


def validate(excel_path: Path, json_path: Path, out_path: Path, errors: list) -> dict:
    if not excel_path.is_file():
        errors.append(f"原 Excel 不存在: {excel_path}")
        return {}
    if not out_path.is_file():
        errors.append(f"产物不存在: {out_path}（应另存为 <stem>-应答后.xlsx，禁止覆盖原件）")
        return {}
    if out_path.resolve() == excel_path.resolve():
        errors.append("产物路径与原 Excel 相同——禁止覆盖原件（S-06）")
        return {}

    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        errors.append(f"应答 JSON 解析失败: {e}")
        return {}
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list) or not items:
        errors.append("应答 JSON 的 items 缺失或为空")
        return {}

    source_wb = None
    try:
        source_wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
        wb = openpyxl.load_workbook(out_path)
    except Exception as e:
        if source_wb is not None:
            source_wb.close()
        errors.append(f"产物 Excel 打开失败: {e}")
        return {}

    filled = 0
    conflict_checked = 0
    unmatched: list = []        # 未命中知识库的条目（需人工应答），强制列出
    seen_rows: dict = {}        # (sheet, row) -> items[i]，防止多条 JSON 覆盖同一行
    for i, item in enumerate(items):
        req = _norm(item.get("requirement"))
        if not req:
            continue
        where = f"items[{i}] requirement={req[:30]!r}"
        has_source_location = "sheet" in item or "row" in item
        if has_source_location:
            sheet_name = item.get("sheet")
            row_idx = item.get("row")
            if (
                not isinstance(sheet_name, str)
                or not sheet_name
                or not isinstance(row_idx, int)
                or isinstance(row_idx, bool)
                or row_idx < 1
            ):
                errors.append(f"{where}: source sheet/row 元数据不完整或无效")
                continue
        else:
            source_matches = _matching_rows(source_wb, req)
            if len(source_matches) > 1:
                errors.append(
                    f"{where}: 原 Excel 中有 {len(source_matches)} 行包含相同 requirement，"
                    "JSON 缺少 sheet/row，无法安全确定回填行"
                )
                continue
            if not source_matches:
                errors.append(f"{where}: 原 Excel 中未找到匹配的需求行")
                continue
            sheet_name, row_idx = source_matches[0]

        if sheet_name not in source_wb.sheetnames:
            errors.append(f"{where}: 原 Excel 不存在 sheet={sheet_name!r}")
            continue
        source_ws = source_wb[sheet_name]
        if row_idx > source_ws.max_row or not any(
            _norm(cell.value) == req for cell in source_ws[row_idx]
        ):
            errors.append(
                f"{where}: source sheet={sheet_name!r} row={row_idx} "
                "中的文本与 JSON requirement 不一致"
            )
            continue
        if sheet_name not in wb.sheetnames or row_idx > wb[sheet_name].max_row:
            errors.append(f"{where}: 产物 Excel 中缺少 source 行 {sheet_name!r} row={row_idx}")
            continue
        ws = wb[sheet_name]
        if not any(_norm(cell.value) == req for cell in ws[row_idx]):
            errors.append(
                f"{where}: 产物 Excel 的 source 行 {sheet_name!r} row={row_idx} "
                "已不包含对应 requirement"
            )
            continue
        headers = _header_map(ws)
        row_key = (ws.title, row_idx)
        if row_key in seen_rows:
            prev_i = seen_rows[row_key]
            errors.append(
                f"{where}: 与 items[{prev_i}] 指向同一 source 行"
                f"（sheet={ws.title!r} row={row_idx}）"
            )
        else:
            seen_rows[row_key] = i
        comp_values = _find_compliance_cells(ws, row_idx, headers)
        # 缺口①：整表/该 sheet 找不到合规列时 comp_values 为空——此前静默通过
        if not comp_values:
            errors.append(f"{where}: 匹配行（sheet={ws.title!r}）缺少合规列")
            continue
        is_unmatched = not _norm(item.get("compliance"))
        if is_unmatched:
            # 未命中条目：合规列必须留空（不得误标 FC/PC/NC），且【其他说明】
            # 必须带"未命中"标记——保证人工应答清单一眼可见
            unmatched.append(req)
            if any(v.lower() in _MARK_VALUES for v in comp_values):
                errors.append(
                    f"{where}: 未命中知识库的条目（row={row_idx}）不应填写合规标记"
                )
            notes_col = headers.get("其他说明")
            if notes_col is None:
                errors.append(f"{where}: 未命中条目但产物缺少【其他说明】列")
            else:
                notes_val = _norm(ws.cell(row=row_idx, column=notes_col[1]).value)
                if "未命中" not in notes_val:
                    errors.append(
                        f"{where}: 未命中条目（row={row_idx}）的【其他说明】未标注"
                        f"「未命中知识库」标记"
                    )
        elif not any(v.lower() in _MARK_VALUES for v in comp_values):
            errors.append(f"{where}: 匹配行（sheet={ws.title!r} row={row_idx}）合规列未填写")
        elif not _compliance_matches(ws, row_idx, headers, item.get("compliance")):
            errors.append(
                f"{where}: source 行（sheet={ws.title!r} row={row_idx}）的回填合规"
                f"与 JSON 判定 {item.get('compliance')!r} 不一致"
            )
        else:
            filled += 1
        # 冲突行红色高亮检查
        if item.get("conflict") in (True, "true", "True", "是"):
            conflict_checked += 1
            conflict_col = None
            for name in ("是否冲突",):
                if name in headers:
                    conflict_col = headers[name][1]
            if conflict_col is None:
                errors.append(f"{where}: JSON 标记 conflict=true，但产物缺少【是否冲突】列")
            else:
                cell = ws.cell(row=row_idx, column=conflict_col)
                fill_color = getattr(getattr(cell.fill, "start_color", None), "rgb", None)
                # 缺口②：conflict=true 时单元格为空/非真值也算违规（此前只查
                # "真值但未标红"，空单元格静默漏过）
                if _norm(cell.value) not in _CONFLICT_TRUTHY:
                    errors.append(
                        f"{where}: JSON 标记 conflict=true，但产物冲突单元格"
                        f"（row={row_idx}）未填写真值（当前 {_norm(cell.value)!r}）"
                    )
                elif fill_color not in _RED_ARGB:
                    errors.append(
                        f"{where}: 冲突单元格（row={row_idx}）未做红色填充（当前 {fill_color}）"
                    )

    # 8 个新增列存在性（任一 sheet 表头命中即算有；逐列记录缺失）
    new_cols_found: set = set()
    for ws in wb.worksheets:
        headers = _header_map(ws)
        for name in _NEW_COLUMNS:
            if name.lower() in headers:
                new_cols_found.add(name)
    missing_cols = [n for n in _NEW_COLUMNS if n not in new_cols_found]
    if missing_cols:
        errors.append(f"新增列缺失: {', '.join(missing_cols)}（共需 8 列）")

    source_wb.close()
    wb.close()
    return {
        "items": len(items),
        "filled": filled,
        "unmatched": unmatched,
        "conflict_rows": conflict_checked,
        "sheets": len(wb.worksheets),
    }


def main() -> int:
    args = sys.argv[1:]
    if len(args) not in (2, 3):
        print("用法: python validate.py <原Excel> <应答JSON> [产物Excel]", file=sys.stderr)
        return 2
    excel_path = Path(args[0]).expanduser().resolve()
    json_path = Path(args[1]).expanduser().resolve()
    out_path = (Path(args[2]).expanduser().resolve() if len(args) == 3
                else excel_path.with_name(f"{excel_path.stem}-应答后{excel_path.suffix}"))

    errors: list = []
    stats = validate(excel_path, json_path, out_path, errors)

    if errors:
        print(f"❌ 回填自检未通过（{len(errors)} 处违规）:")
        for e in errors[:50]:
            print(f"   · {e}")
        if len(errors) > 50:
            print(f"   … 其余 {len(errors) - 50} 处省略")
        return 1

    print("✅ 回填自检通过")
    print(f"   - 应答条目: {stats['items']}，已填合规: {stats['filled']}")
    print(f"   - 冲突行红色高亮: {stats['conflict_rows']} 行")
    if stats["unmatched"]:
        print(f"   - ⚠️ 未命中知识库（合规列已留空，需人工应答）: {len(stats['unmatched'])} 条")
        for u in stats["unmatched"][:20]:
            print(f"     · {u[:60]}")
        if len(stats["unmatched"]) > 20:
            print(f"     … 其余 {len(stats['unmatched']) - 20} 条省略")
    print(f"   - 产物: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
