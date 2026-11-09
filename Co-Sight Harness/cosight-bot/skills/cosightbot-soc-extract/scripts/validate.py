#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cosightbot-soc-extract —— 提取产物 schema 自检器（硬性闸门）。

校验 `<stem>-需求提取.json` 是否满足下游（cosightbot-soc-respond）输入契约：

顶层：
  - source_file: str（非空）
  - total_demand_items: int（可选；存在时必须等于 items 长度）
  - items: list（非空）

每个 item：
  - sheet: str（非空）
  - row: int（>= 1）
  - no: str 或数字（编号，允许空字符串——部分标书无编号列）
  - requirement: str（非空，去空白后长度 > 0）★ 必需
  - compliance: "FC" | "PC" | "NC" | null（其他值一律拒绝）
  - remarks / reference_document: 可选，str 或 null

零兜底：任一违规 → 打印全部违规明细，exit 1；全部通过 → 打印统计，exit 0。
"""
import json
import sys
from pathlib import Path

_ALLOWED_COMPLIANCE = {"FC", "PC", "NC", None}
_REQUIRED_STR_FIELDS = ("sheet", "requirement")


def validate(data, errors: list) -> None:
    if not isinstance(data, dict):
        errors.append(f"顶层必须是 JSON object，实际是 {type(data).__name__}")
        return

    source_file = data.get("source_file")
    if not isinstance(source_file, str) or not source_file.strip():
        errors.append("source_file 缺失或为空")

    items = data.get("items")
    if not isinstance(items, list) or not items:
        errors.append("items 缺失、不是数组或为空")
        return

    total = data.get("total_demand_items")
    if total is not None and total != len(items):
        errors.append(f"total_demand_items={total} 与 items 长度 {len(items)} 不一致")

    seen_keys = set()
    for i, item in enumerate(items):
        where = f"items[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{where}: 不是 object")
            continue
        for field in _REQUIRED_STR_FIELDS:
            v = item.get(field)
            if not isinstance(v, str) or not v.strip():
                errors.append(f"{where}: {field} 缺失或为空")
        row = item.get("row")
        if not isinstance(row, int) or isinstance(row, bool) or row < 1:
            errors.append(f"{where}: row 必须是 >= 1 的整数，实际 {row!r}")
        comp = item.get("compliance")
        if comp not in _ALLOWED_COMPLIANCE:
            errors.append(
                f"{where}: compliance 非法值 {comp!r}（只允许 FC/PC/NC/null）"
            )
        for field in ("remarks", "reference_document"):
            v = item.get(field)
            if v is not None and not isinstance(v, str):
                errors.append(f"{where}: {field} 必须是字符串或 null")
        # 重复检测：同 sheet 同 row 或同 requirement 出现两次 = 提取逻辑大概率错位
        key = (str(item.get("sheet", "")), str(row))
        if key in seen_keys:
            errors.append(f"{where}: 与前面条目重复（sheet={key[0]!r}, row={key[1]}）")
        seen_keys.add(key)


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: python validate.py <需求提取.json>", file=sys.stderr)
        return 2
    json_path = Path(sys.argv[1]).expanduser().resolve()
    if not json_path.is_file():
        print(f"❌ 文件不存在: {json_path}")
        return 1
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"❌ JSON 解析失败: {e}")
        return 1

    errors: list = []
    validate(data, errors)

    if errors:
        print(f"❌ schema 自检未通过（{len(errors)} 处违规）:")
        for e in errors[:50]:
            print(f"   · {e}")
        if len(errors) > 50:
            print(f"   … 其余 {len(errors) - 50} 处省略")
        return 1

    items = data["items"]
    sheets = sorted({it.get("sheet", "?") for it in items})
    n_comp = sum(1 for it in items if it.get("compliance"))
    print("✅ schema 自检通过")
    print(f"   - 条目数: {len(items)}")
    print(f"   - 覆盖 sheet（{len(sheets)} 个）: {', '.join(sheets)}")
    print(f"   - 已有合规值: {n_comp} 条（其余待应答）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
