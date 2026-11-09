#!/usr/bin/env python3
"""
validate_skills.py — /skill_optimize 业务方 Skill 自检工具

借鉴 steipete/agent-scripts/scripts/validate-skills 的设计：
- 校验最小集（只 name + description 非空）
- description ≤ 100 字（短触发短语，不是摘要）
- frontmatter 字段 ≤ 3 个（name + description + 可选 protected_assets）
- 检测重复 name
- 失败聚合 + 硬阻断（exit 1）

用法：
    python3 scripts/validate_skills.py [skill_root]   # 默认仓根
    python3 scripts/validate_skills.py /path/to/分库
    python3 scripts/validate_skills.py /path/to/分库/consume_lib/design/方法库/系统方案设计/skills
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

# 借鉴 steipete: 硬阻断阈值
MAX_DESCRIPTION_LENGTH = 100
ALLOWED_FRONTMATTER_FIELDS = {"name", "description", "protected_assets"}


def parse_frontmatter(content: str) -> Optional[dict[str, object]]:
    """解析 SKILL.md 的 YAML frontmatter。返回 dict 或 None（解析失败）。"""
    if not content.startswith("---"):
        return None
    end = content.find("\n---", 3)
    if end < 0:
        return None
    fm_text = content[3:end].strip()
    if not fm_text:
        return {}

    fm: dict[str, object] = {}
    current_key: Optional[str] = None
    current_list: Optional[list[str]] = None
    for line in fm_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_list is not None:
            current_list.append(stripped[2:].strip())
            continue
        if ":" in stripped and not stripped.startswith("-"):
            if current_list is not None and current_key:
                fm[current_key] = current_list
                current_list = None
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            if value == "":
                current_key = key
                current_list = []
            else:
                fm[key] = value.strip('"').strip("'")
                current_key = None
    if current_list is not None and current_key:
        fm[current_key] = current_list
    return fm


def validate_one(skill_md: Path) -> list[str]:
    """校验单个 SKILL.md。返回错误列表（空 = PASS）。"""
    errors: list[str] = []
    try:
        content = skill_md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return [f"{skill_md}: 读取失败: {e}"]

    fm = parse_frontmatter(content)
    if fm is None:
        return [f"{skill_md}: 缺少 frontmatter（必须以 --- 开头）"]

    # 1. name 必填 + 非空
    name = fm.get("name", "")
    if not isinstance(name, str) or not name.strip():
        errors.append(f"{skill_md}: frontmatter.name 缺失或为空")

    # 2. description 必填 + 非空 + ≤ 100 字
    desc = fm.get("description", "")
    if not isinstance(desc, str) or not desc.strip():
        errors.append(f"{skill_md}: frontmatter.description 缺失或为空")
    elif len(desc) > MAX_DESCRIPTION_LENGTH:
        errors.append(
            f"{skill_md}: description 长度 {len(desc)} > {MAX_DESCRIPTION_LENGTH} "
            f"（应为短触发短语，不是摘要）"
        )

    # 3. frontmatter 字段 ≤ 3 个（name + description + 可选 protected_assets）
    extra_fields = set(fm.keys()) - ALLOWED_FRONTMATTER_FIELDS
    if extra_fields:
        errors.append(
            f"{skill_md}: frontmatter 含禁加字段 {sorted(extra_fields)} "
            f"（仅允许 {sorted(ALLOWED_FRONTMATTER_FIELDS)}）"
        )

    return errors


def find_skill_files(skill_root: Path) -> list[Path]:
    """扫描 skill_root 下所有 SKILL.md。

    - 如果 skill_root 本身是 skill（含 SKILL.md），返回 [skill_root/SKILL.md]
    - 否则递归查找所有 **/SKILL.md
    """
    direct = skill_root / "SKILL.md"
    if direct.is_file():
        return [direct]
    return sorted(skill_root.rglob("SKILL.md"))


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 SKILL.md frontmatter 极简原则")
    parser.add_argument(
        "skill_root",
        nargs="?",
        default=".",
        help="skill 根目录（默认当前目录；可以是单 skill 目录或含多个 skill 的根）",
    )
    args = parser.parse_args()

    skill_root = Path(args.skill_root).resolve()
    if not skill_root.exists():
        print(f"❌ 路径不存在: {skill_root}", file=sys.stderr)
        return 1

    skill_files = find_skill_files(skill_root)
    if not skill_files:
        print(f"⚠️ 未在 {skill_root} 下找到任何 SKILL.md", file=sys.stderr)
        return 1

    # 校验 + 收集所有错误
    all_errors: list[str] = []
    name_count: dict[str, int] = defaultdict(int)

    for skill_md in skill_files:
        # 先收集 name（用于重复检测）
        try:
            content = skill_md.read_text(encoding="utf-8")
            fm = parse_frontmatter(content)
            if fm and isinstance(fm.get("name"), str):
                name_count[fm["name"].strip()] += 1
        except (OSError, UnicodeDecodeError):
            pass

        all_errors.extend(validate_one(skill_md))

    # 4. 重复 name 检测（借鉴 steipete 模式）
    for name, count in name_count.items():
        if count > 1:
            all_errors.append(
                f"重复的 skill name: {name!r}（出现 {count} 次）"
            )

    # 输出
    if all_errors:
        print(f"❌ Skill 验证失败（共 {len(all_errors)} 个错误，扫描 {len(skill_files)} 个文件）：\n")
        for err in all_errors:
            print(f"  - {err}")
        return 1
    else:
        print(f"✅ Skill 验证通过（扫描 {len(skill_files)} 个文件）")
        return 0


if __name__ == "__main__":
    sys.exit(main())
