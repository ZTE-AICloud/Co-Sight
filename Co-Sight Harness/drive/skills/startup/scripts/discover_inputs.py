"""输入发现 — 扫描工作目录，把 7 类用户输入归位成 InputManifest。

7 类输入（proposal 必填，其余可选）:
    proposal   用户原始 intent，驱动整个 workflow
    workflow   自定义阶段流（无则走默认 5-stage）
    gates      流开关覆盖（gates.yaml）
    review     评审规则库
    skills     可复用 skill 库
    rules      项目级规则
    knowledge  背景知识库

发现策略是纯路径约定（first-exists）：按每类的候选路径列表，在 work_dir 下
依次查找，第一个存在的即命中。不做 provider fallback、不猜测、不写文件。
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 每类输入的候选路径（相对 work_dir），按优先级排列，first-exists 命中。
CATEGORY_PATHS: dict[str, tuple[str, ...]] = {
    "proposal": ("proposal.md", "inputs/proposal.md", "README.md"),
    "workflow": ("workflow.yaml", "workflow.yml", "workflow/"),
    "gates": ("gates.yaml", "gates.yml"),
    "review": ("review/", "review-prompts/", ".claude/review-prompts/"),
    "skills": (".claude/skills/", "skills/"),
    "rules": (".claude/rules/", "rules/"),
    "knowledge": ("knowledge/", "docs/"),
}

# 必填类别：缺失会让 manifest.ready 为 False。
REQUIRED_CATEGORIES: frozenset[str] = frozenset({"proposal"})

# 稳定的类别顺序（供渲染 / 遍历用）。
CATEGORY_ORDER: tuple[str, ...] = (
    "proposal",
    "workflow",
    "gates",
    "review",
    "skills",
    "rules",
    "knowledge",
)


@dataclass(frozen=True)
class InputCategory:
    """单个输入类别的发现结果。不可变。"""

    name: str
    found: bool
    required: bool
    relative_path: str | None = None
    abs_path: str | None = None
    is_dir: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "found": self.found,
            "required": self.required,
            "relative_path": self.relative_path,
            "abs_path": self.abs_path,
            "is_dir": self.is_dir,
        }


@dataclass(frozen=True)
class InputManifest:
    """一次输入发现的完整结果。不可变。"""

    work_dir: str
    categories: dict[str, InputCategory] = field(default_factory=dict)

    @property
    def found_categories(self) -> list[str]:
        """已命中的类别名（按 CATEGORY_ORDER 稳定排序）。"""
        return [name for name in CATEGORY_ORDER if self.categories.get(name, _MISSING).found]

    @property
    def missing_required(self) -> list[str]:
        """缺失的必填类别名。"""
        return [
            name
            for name in CATEGORY_ORDER
            if (cat := self.categories.get(name)) is not None and cat.required and not cat.found
        ]

    @property
    def ready(self) -> bool:
        """所有必填类别都命中即为 ready。"""
        return not self.missing_required

    @property
    def has_workflow(self) -> bool:
        """是否发现了自定义 workflow（决定是否走默认 5-stage）。"""
        cat = self.categories.get("workflow")
        return bool(cat and cat.found)

    def category(self, name: str) -> InputCategory | None:
        return self.categories.get(name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_dir": self.work_dir,
            "ready": self.ready,
            "found_categories": self.found_categories,
            "missing_required": self.missing_required,
            "has_workflow": self.has_workflow,
            "categories": {name: cat.to_dict() for name, cat in self.categories.items()},
        }


# 哨兵：found_categories 里做 .found 访问时避免 KeyError。
_MISSING = InputCategory(name="", found=False, required=False)


def _first_existing(work_dir: Path, candidates: tuple[str, ...]) -> Path | None:
    """按候选顺序返回第一个存在的路径。"""
    for rel in candidates:
        candidate = work_dir / rel
        if candidate.exists():
            return candidate
    return None


def discover_inputs(work_dir: Path | str) -> InputManifest:
    """扫描 work_dir，发现 7 类用户输入，返回 InputManifest。

    纯发现：只读，不写文件、不猜测、不做 provider fallback。

    Args:
        work_dir: 用户工作目录（含 proposal / workflow 等的项目根）。

    Returns:
        InputManifest — 每类的命中情况 + ready 判定。
    """
    root = Path(work_dir).resolve()
    categories: dict[str, InputCategory] = {}
    for name in CATEGORY_ORDER:
        required = name in REQUIRED_CATEGORIES
        found_path = _first_existing(root, CATEGORY_PATHS[name])
        if found_path is None:
            categories[name] = InputCategory(name=name, found=False, required=required)
            continue
        categories[name] = InputCategory(
            name=name,
            found=True,
            required=required,
            relative_path=str(found_path.relative_to(root)),
            abs_path=str(found_path),
            is_dir=found_path.is_dir(),
        )
    return InputManifest(work_dir=str(root), categories=categories)


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：stdout 输出 JSON，必填输入缺失时 exit 1。

    ready 为假即 input_check gate 该拦的情况 —— 用 exit code 让调用方无法忽略。
    """
    parser = argparse.ArgumentParser(description="发现 7 类用户输入")
    parser.add_argument("--work-dir", default=".", help="项目工作目录")
    args = parser.parse_args(argv)

    root = Path(args.work_dir)
    if not root.is_dir():
        payload = {
            "ok": False,
            "reason": "invalid_arg",
            "details": {"work_dir": str(root), "error": "目录不存在"},
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 1

    manifest = discover_inputs(root)
    data = manifest.to_dict()
    ok = manifest.ready
    payload = {"ok": ok, "data": data} if ok else {
        "ok": False,
        "reason": "inputs_incomplete",
        "details": {
            "missing_required": sorted(manifest.missing_required),
            "hint": "补齐必填输入后重跑本 stage；proposal 可放 proposal.md 或 inputs/proposal.md",
            **data,
        },
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if ok else 1


__all__ = [
    "CATEGORY_PATHS",
    "CATEGORY_ORDER",
    "REQUIRED_CATEGORIES",
    "InputCategory",
    "InputManifest",
    "discover_inputs",
]


if __name__ == "__main__":
    sys.exit(main())
