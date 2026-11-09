#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""freeze_profile.py — S1 收尾：校验并冻结画像。

读取 10-profile-input.json（扫描结果）与 11-merge.answer.json（LLM 归并结果），
校验后写出 12-agent-profile.json。

按共识：抽到 0 能力点**不中止**，降级为档 C，并在画像中标记 tier_downgraded。

用法：
    python3 freeze_profile.py --work <中间态目录>
"""

import argparse
import sys

import config
from common import (
    GoldevalError,
    fail,
    read_json,
    slug_from_path,
    work_path,
    write_json,
)


def parse_capabilities(answer):
    """从归并结果里取出能力点清单，做 id 归一与去重。"""
    raw = answer.get("capabilities")
    if not isinstance(raw, list):
        raise GoldevalError("归并结果缺少 capabilities 数组")

    capabilities = []
    seen = set()
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        cap_id = str(item.get("id") or f"C{index:02d}").strip()
        if cap_id in seen:
            cap_id = f"C{index:02d}"
        if cap_id in seen:
            continue
        seen.add(cap_id)
        capabilities.append({
            "id": cap_id,
            "name": name,
            "desc": str(item.get("desc") or "").strip(),
            "evidence": str(item.get("evidence") or "").strip(),
        })
    return capabilities


def resolve_tier(answer, profile_input, capabilities):
    """确定档位；0 能力点降级档 C 并标记。"""
    hint = str(answer.get("tier") or profile_input.get("tier_hint") or config.TIER_C).upper()
    if hint not in (config.TIER_A, config.TIER_B, config.TIER_C):
        hint = config.TIER_C

    if capabilities:
        return hint, False

    # 0 能力点：不中止，强制降级为档 C
    return config.TIER_C, True


def build_profile(profile_input, answer):
    """组装 agent-profile.json。"""
    capabilities = parse_capabilities(answer)
    tier, downgraded = resolve_tier(answer, profile_input, capabilities)

    manifest = profile_input.get("manifest") or {}
    settings = profile_input.get("settings") or {}
    criteria = profile_input.get("pass_criteria") or {}
    skills = profile_input.get("skills") or []

    flavor = profile_input.get("flavor") or config.FALLBACK_FLAVOR

    # 元数据来自锚点的两个来源：COSIGHT.md 的正文表格 + 任一锚点的 YAML
    # frontmatter（见 extract.merge_anchor_meta）。两者都没有时才是空串。
    meta = manifest.get("meta") or {}

    # 规范名由 S0 从 --agent 路径推导并带下来；老中间态没有该字段时
    # 这里按同样的规则回退推导一次，保证产出目录名与中间态目录名一致。
    agent_slug = (profile_input.get("agent_slug")
                  or slug_from_path(profile_input["root"]))

    profile = {
        "root": profile_input["root"],
        "agent_slug": agent_slug,
        "flavor": flavor,
        "flavor_label": profile_input.get("flavor_label")
                        or config.flavor_label(flavor),
        "anchor_file": profile_input.get("anchor_file") or config.flavor_of(flavor)["anchor"],
        # project_id 参与产出命名：common.naming_slug() 优先用它推 data_id
        # 前缀与 task_id，为空才回退到路径推导的 agent_slug。它同时是溯源字段。
        "project_id": str(meta.get("project_id") or "").strip(),
        "project_name": str(meta.get("project_name") or "").strip(),
        "version": str(meta.get("version") or "").strip(),
        "tier": tier,
        "tier_reason": str(answer.get("tier_reason") or "").strip(),
        "tier_downgraded": downgraded,
        "capabilities": capabilities,
        "tools": {
            "allow": settings.get("allow") or [],
            "deny": settings.get("deny") or [],
        },
        "constraints": settings.get("constraints") or {},
        "model_tier": settings.get("model_tier"),
        "boundaries": {
            "capability_boundary": manifest.get("capability_boundary", ""),
            "positioning": manifest.get("positioning", ""),
            "quickstart": manifest.get("quickstart", ""),
            "skill_constraints": [s.get("constraints", "") for s in skills if s.get("constraints")],
            "skill_not_for": [s.get("not_for", "") for s in skills if s.get("not_for")],
        },
        "gwt_baseline": {
            "file": criteria.get("file"),
            "count": criteria.get("gwt_count", 0),
            "entries": criteria.get("gwt_entries") or [],
            "nonfunctional": criteria.get("nonfunctional", ""),
        },
        "engine": profile_input.get("engine"),
        "demo_code": profile_input.get("demo_code"),
        "rules": profile_input.get("rules") or [],
        "structure_index": manifest.get("structure_index") or {},
        "excluded": profile_input.get("excluded") or [],
        # S1 扫描阶段带下来的告警（验收契约缺失/坏条目等）
        "warnings": list(profile_input.get("warnings") or []),
    }

    if downgraded:
        profile["warnings"].append(
            "画像抽取得到 0 个能力点，已降级为档 C：用例将不带 capability_ref 由 LLM 自由生成"
        )
    if not profile["engine"]:
        profile["warnings"].append("未识别到引擎实现文件，能力边界仅来自文本声明")

    return profile


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="freeze_profile.py", description="S1 收尾：校验归并结果并冻结画像"
    )
    parser.add_argument("--work", required=True, help="中间态目录")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    profile_input = read_json(work_path(args.work, "profile_input"))
    if not profile_input:
        fail("未找到 10-profile-input.json，请先运行 extract.py")

    answer = read_json(work_path(args.work, "merge_answer"))
    if not answer:
        fail(
            "未找到 11-merge.answer.json，请先按 11-merge.prompt.md 生成归并结果"
        )

    try:
        profile = build_profile(profile_input, answer)
    except GoldevalError as exc:
        fail(str(exc))

    write_json(work_path(args.work, "profile"), profile)

    print(f"S1 完成：tier={profile['tier']}  能力点 {len(profile['capabilities'])} 个")
    for cap in profile["capabilities"]:
        print(f"    {cap['id']}  {cap['name']} — {cap['desc']}")
    for warning in profile["warnings"]:
        print(f"    WARN: {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
