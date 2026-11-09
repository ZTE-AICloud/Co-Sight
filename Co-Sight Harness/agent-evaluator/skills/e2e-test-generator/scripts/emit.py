#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""emit.py — S5 落盘。

把校验后的用例与全部中间产物落成 5 件交付物：
  seed.jsonl / agent-profile.json / eval-plan.json / manifest.json / report.md

落盘位置是 <run 目录>/generated_datasets/，run 目录由 S0 记进 run-args.json。

中间态目录 .work/ **一律保留**（含落盘后），便于复核与排查。
落盘成功会写入 50-emitted.json 标记；本脚本被指定了确切的中间态目录，
已落盘则拒绝重复落盘（否则会对同一批记录产出内容相同的副本）。
想重新生成请走 generate.py——它带 --agent 会新建一个中间态目录重跑全流程。

无缺口 → 退出码 0。
有缺口 → report.md 缺口置顶，退出码 1。

用法：
    python3 emit.py --work <中间态目录>
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import config
from common import (
    naming_slug as common_naming_slug,
    fail,
    read_json,
    read_jsonl,
    sha256_file,
    stamp_now,
    work_path,
    write_json,
    write_jsonl,
    write_text,
)


# ============================== 输出目录 ==============================

def resolve_output_dir(work_dir):
    """解析交付目录：<run 目录>/generated_datasets/。

    run 目录由 generate.py 在 S0 解析后记进 run-args.json，这里只读不算——
    因此续跑时无论从哪个 cwd 调用，交付物都落在首跑那一份 run 目录下。
    目录由 S0 预先建好（与 .work/ 一同），这里只做兜底确保存在。
    """
    saved = read_json(Path(work_dir) / "run-args.json") or {}
    recorded = saved.get("out_dir")
    if not recorded:
        fail(
            f"中间态没有记录产出位置（run-args.json 里无 out_dir）：{work_dir}\n"
            "       请用 generate.py 开新一轮（带 --agent --output）"
        )
    out_dir = Path(recorded) / config.ARTIFACT_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


# ============================== eval-plan ==============================

def build_coverage(records, plan, profile):
    """构造覆盖矩阵：维度 × 配额 × 实际 × 来源分解。"""
    gwts = (profile.get("gwt_baseline") or {}).get("entries") or []

    matrix = []
    for dim in config.DIMENSIONS:
        dim_id = dim["id"]
        own = [r for r in records if r["dimension"] == dim_id]
        from_gwt = sum(1 for r in own if r["source"] == config.SOURCE_GWT)
        from_llm = len(own) - from_gwt

        gwt_kept_here = sum(
            1 for g in plan["gwt_kept"] if g.get("dimension") == dim_id
        )
        gwt_dropped_here = sum(
            1 for g in plan["gwt_dropped"] if g.get("dimension") == dim_id
        )

        matrix.append({
            "dimension": dim_id,
            "name": dim["name"],
            "weight": plan["dimension_weights"].get(dim_id, dim["weight"]),
            "focused": dim_id in (plan.get("focus") or []),
            "quota": plan["quota"].get(dim_id, 0),
            "actual_total": len(own),
            "from_gwt": from_gwt,
            "from_llm": from_llm,
            "gwt_kept": gwt_kept_here,
            "gwt_dropped": gwt_dropped_here,
        })

    total_gwt = sum(1 for r in records if r["source"] == config.SOURCE_GWT)
    return {
        "matrix": matrix,
        "totals": {
            "records": len(records),
            "target": plan["count"],
            "from_gwt": total_gwt,
            "from_llm": len(records) - total_gwt,
            "gwt_available": len(gwts),
            "gwt_kept": len(plan["gwt_kept"]),
            "gwt_dropped": len(plan["gwt_dropped"]),
        },
    }


def build_eval_plan(records, plan, profile, verify_report, coverage):
    return {
        "count_target": plan["count"],
        "count_actual": len(records),
        "tier": plan["tier"],
        "tier_downgraded": profile.get("tier_downgraded", False),
        "focus": plan.get("focus") or [],
        "focus_reason": plan.get("focus_reason", ""),
        "dimension_weights": plan["dimension_weights"],
        "quota": plan["quota"],
        "generated_budget": plan["generated_budget"],
        "coverage": coverage["matrix"],
        "totals": coverage["totals"],
        "gaps": verify_report.get("gaps") or {},
        "repair_rounds": verify_report.get("round", 0),
        "rejected": verify_report.get("rejected") or [],
        "dedup_dropped": verify_report.get("dropped") or [],
        "over_cap_dropped": verify_report.get("over_cap") or [],
    }


# ============================== report.md ==============================

def render_report(task_id, records, plan, profile, asset, verify_report,
                  coverage, work_dir):
    gaps = verify_report.get("gaps") or {}
    totals = coverage["totals"]
    lines = [f"# 生成报告 — {task_id}", ""]

    # 超出上限时置顶（条数已压到 count 以内，仅作说明）
    over_cap_top = verify_report.get("over_cap") or []
    if over_cap_top:
        lines += [
            "> ## 条数已裁剪到上限",
            ">",
            f"> GWT 拆分使用例总数超过目标 `{plan['count']}` 条，"
            f"已按「GWT 主用例 > LLM 生成 > GWT 拆分用例」裁剪 {len(over_cap_top)} 条。",
            "> 明细见「四、缺口与丢弃」。",
            "",
        ]

    # 缺口时置顶
    if gaps:
        lines += [
            "> ## ⚠️ 未达标（存在缺口）",
            ">",
            f"> 目标 `{plan['count']}` 条，实际 `{len(records)}` 条。",
            f"> 补生成已用尽 {config.MAX_REPAIR_ROUNDS} 轮仍缺："
            + "、".join(f"`{k}` 缺 {v} 条" for k, v in gaps.items()),
            ">",
            "> 本目录已按实际条数落盘，退出码为 1。",
            "",
        ]

    # 一、概览
    lines += [
        "## 一、概览",
        "",
        f"- **task_id**：`{task_id}`",
        f"- **Agent 类型**：{profile.get('flavor_label') or config.flavor_label(None)}"
        f"（锚点 `{profile.get('anchor_file') or '—'}`）",
        f"- **档位**：`{plan['tier']}`"
        + ("（由 0 能力点降级）" if profile.get("tier_downgraded") else ""),
        f"- **输入路径**：`{asset['input_path']}`（{asset['input_kind']}）",
        f"- **扫描根**：`{asset['root']}`"
        + ("" if asset["anchor_found"] else "（未找到锚点，已回退）"),
        f"- **条数**：{len(records)} / 目标 {plan['count']}",
        f"- **来源**：验收基线 {totals['from_gwt']} 条，LLM 生成 {totals['from_llm']} 条",
        f"- **验收基线**（`acceptance_criteria`）：可用 {totals['gwt_available']} 条，"
        f"保留 {totals['gwt_kept']} 条，截断丢弃 {totals['gwt_dropped']} 条",
    ]
    baseline_file = (profile.get("gwt_baseline") or {}).get("file")
    if baseline_file:
        lines.append(f"  - 来源：`{baseline_file}`")
    else:
        lines.append(
            "  - 未找到验收契约（`clarified-agent-requirements.yaml` 的 "
            "`acceptance_criteria`），已按无验收基线处理"
        )
    if plan.get("focus"):
        lines.append(
            f"- **生成重点**：{'、'.join(plan['focus'])}"
            f"（权重 +{plan['focus_bonus']}）"
        )
        if plan.get("focus_reason"):
            lines.append(f"  - 解析依据：{plan['focus_reason']}")
    lines.append("")

    # 二、路径回顾
    lines += ["## 二、路径回顾", "", "| 阶段 | 中间态产物 | 大小 |", "|---|---|---|"]
    stages = [
        ("S0 输入解析", "00-asset.json"),
        ("S1 画像抽取", "10-profile-input.json"),
        ("S1 能力点归并", "11-merge.answer.json"),
        ("S1 画像冻结", "12-agent-profile.json"),
        ("S2 验收条目归类", "20-tag.answer.json"),
        ("S2 计划规划", "20-plan.json"),
        ("S3 用例生成", "30-*.answer.json"),
        ("S3 补生成", "31-repair-*.answer.json"),
        ("S4 校验结果", "40-verified.jsonl"),
    ]
    for label, pattern in stages:
        matches = sorted(Path(work_dir).glob(pattern))
        if not matches:
            lines.append(f"| {label} | （无） | — |")
            continue
        size = sum(p.stat().st_size for p in matches)
        names = "、".join(p.name for p in matches[:3])
        if len(matches) > 3:
            names += f" 等 {len(matches)} 个"
        lines.append(f"| {label} | `{names}` | {size} B |")
    lines += ["", "> 各阶段由主 agent 分步驱动，脚本不记录跨调用耗时。", ""]

    # 三、覆盖矩阵
    lines += [
        "## 三、覆盖矩阵",
        "",
        "| 维度 | 权重 | 重点 | 配额 | 实际 | GWT | LLM | GWT 截断丢弃 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in coverage["matrix"]:
        lines.append(
            f"| `{row['dimension']}` | {row['weight']} | "
            f"{'✓' if row['focused'] else '—'} | {row['quota']} | "
            f"{row['actual_total']} | {row['from_gwt']} | {row['from_llm']} | "
            f"{row['gwt_dropped']} |"
        )
    lines += [
        "",
        "> **配额语义**：`配额` 是**需 LLM 生成**的条数，不含验收基线。"
        "因此某维度出现「配额 0 但实际 > 0」是正常的——那些条目全部来自验收基线物化。",
        "> 判定是否达标看的是 `配额` 与 `LLM` 两列，不是 `配额` 与 `实际`。",
        "",
    ]

    # 四、缺口与丢弃
    lines += ["## 四、缺口与丢弃", ""]
    if gaps:
        lines.append("**缺口**：" + "、".join(f"`{k}` 缺 {v} 条" for k, v in gaps.items()))
    else:
        lines.append("无缺口，条数与配额完全吻合。")

    over_cap = verify_report.get("over_cap") or []
    if over_cap:
        lines.append(
            f"**超出上限**：GWT 拆分使总数超过 {plan['count']}，"
            f"已裁剪 {len(over_cap)} 条，最终 {totals['records']} 条。"
        )

    dropped_gwts = plan.get("gwt_dropped") or []
    if dropped_gwts:
        lines += ["", f"**验收基线截断丢弃（{len(dropped_gwts)} 条）**：按维度权重降序截断到 count。", ""]
        for gwt in dropped_gwts:
            lines.append(
                f"- #{gwt['index']} `{gwt.get('dimension', '?')}` — {gwt['title']}"
            )

    rejected = verify_report.get("rejected") or []
    if rejected:
        lines += ["", f"**硬校验驳回（{len(rejected)} 条）**：", ""]
        for item in rejected[:20]:
            lines.append(f"- `{item['source_ref']}`：{'；'.join(item['errors'])}")

    over_cap = verify_report.get("over_cap") or []
    if over_cap:
        lines += [
            "",
            f"**超出上限丢弃（{len(over_cap)} 条）**："
            f"GWT 拆分后总数超过 `--count {plan['count']}`，已按"
            "「GWT 主用例 > LLM 生成 > GWT 拆分用例」的顺序裁剪。",
            "",
        ]
        for item in over_cap[:20]:
            lines.append(
                f"- `{item['source_ref']}` `{item['dimension']}` — {item['reason']}"
            )

    dedup_dropped = verify_report.get("dropped") or []
    if dedup_dropped:
        lines += ["", f"**去重丢弃（{len(dedup_dropped)} 条）**：", ""]
        for item in dedup_dropped[:20]:
            lines.append(
                f"- `{item['source_ref']}`（{item['dimension']}）：{item['reason']}"
            )
    lines.append("")

    # 五、画像摘要
    caps = profile.get("capabilities") or []
    engine = profile.get("engine") or {}
    lines += [
        "## 五、画像摘要",
        "",
        f"- **能力点**：{len(caps)} 个",
    ]
    for cap in caps:
        lines.append(f"  - `{cap['id']}` {cap['name']}：{cap['desc']}")
    tools = (profile.get("tools") or {}).get("allow") or []
    lines.append(f"- **工具面**：{'、'.join(tools) if tools else '（未声明）'}")
    if engine:
        lines.append(
            f"- **引擎**：`{engine.get('source_file')}`"
            f"（{engine.get('source_bytes')} B），"
            f"CLI 参数 {engine.get('cli_args') or '未识别'}，"
            f"退出码 {engine.get('exit_codes') or '未识别'}"
        )
    else:
        lines.append("- **引擎**：未识别")
    demo = profile.get("demo_code") or {}
    if demo:
        lines.append(f"- **demo_code**：{demo.get('file_count', 0)} 个文件（仅作上下文素材）")
    for warning in profile.get("warnings") or []:
        lines.append(f"- ⚠️ {warning}")
    lines.append("")

    # 六、已排除文件与原因
    lines += ["## 六、已排除文件与原因", ""]
    excluded = profile.get("excluded") or []
    if excluded:
        lines += ["| 路径 | 大小 | 原因 |", "|---|---|---|"]
        for item in excluded:
            lines.append(f"| `{item['path']}` | {item['bytes']} B | {item['reason']} |")
    else:
        lines.append("无。")
    lines.append("")

    return "\n".join(lines)


# ============================== 主流程 ==============================

def parse_args(argv=None):
    parser = argparse.ArgumentParser(prog="emit.py", description="S5 落盘")
    parser.add_argument("--work", required=True, help="中间态目录")
    parser.add_argument("--stamp", default=None,
                        help="本轮时间戳（由 generate.py 传入，与中间态目录同名）")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    work_dir = Path(args.work)

    records = read_jsonl(work_path(work_dir, "verified"))
    profile = read_json(work_path(work_dir, "profile"))
    plan = read_json(work_path(work_dir, "plan"))
    asset = read_json(work_path(work_dir, "asset"))
    verify_report = read_json(work_path(work_dir, "verify_report")) or {}

    if not all([profile, plan, asset]):
        fail("中间态不完整，请先跑完 S0~S4")
    if not records:
        fail("没有可落盘的用例（40-verified.jsonl 为空）")

    # 幂等守卫：本脚本被指定了确切的中间态目录，若它已落盘则拒绝重复落盘
    # （否则会对同一批记录产出一份内容相同的副本）。
    # 想重新生成请走 generate.py——它会自动滚到一个新的中间态目录重跑全流程。
    existing = read_json(work_path(work_dir, "emitted"))
    if existing:
        print("该中间态已落盘过，本脚本不重复落盘。")
        print(f"  产出目录：{existing.get('artifacts_dir')}")
        print(f"  条数：{existing.get('record_count')}"
              f"{'（存在缺口）' if existing.get('has_gaps') else ''}")
        print(f"  落盘时间：{existing.get('emitted_at')}")
        print("\n  如需重新生成，请用 generate.py 带 --agent 重跑；"
              "它会新建一个中间态目录，产出必然是新的。")
        return 1 if existing.get("has_gaps") else 0

    coverage = build_coverage(records, plan, profile)
    eval_plan = build_eval_plan(records, plan, profile, verify_report, coverage)

    agent_name = common_naming_slug(profile)
    # task_id 与 run 目录名**解耦**：run 目录可能是用户显式指定的（--output），
    # 而 task_id 始终是 <agent 名>_<时间戳>，所以用同一份 stamp 来拼，而不是
    # 取目录名。优先用 generate.py 透传的时间戳，缺失（单独跑本脚本）时回退
    # 到 run-args.json 里记的，最后才回退到当前时刻。
    saved = read_json(work_dir / "run-args.json") or {}
    stamp = args.stamp or saved.get("stamp") or stamp_now()
    out_dir = resolve_output_dir(work_dir)
    # agent_name 已由 agent_slug() 归一过，不再重复 slugify。
    task_id = f"{agent_name}_{stamp}"

    write_jsonl(out_dir / config.ARTIFACT_SEED, records)
    write_json(out_dir / config.ARTIFACT_PROFILE, profile)
    write_json(out_dir / config.ARTIFACT_PLAN, eval_plan)
    write_text(
        out_dir / config.ARTIFACT_REPORT,
        render_report(task_id, records, plan, profile, asset, verify_report,
                      coverage, work_dir),
    )

    artifacts = {}
    for name in (config.ARTIFACT_SEED, config.ARTIFACT_PROFILE,
                 config.ARTIFACT_PLAN, config.ARTIFACT_REPORT):
        artifacts[name] = "sha256:" + sha256_file(out_dir / name)

    manifest = {
        "task_id": task_id,
        "agent_input": asset["input_path"],
        "agent_root": asset["root"],
        "agent_sha256": asset["root_sha256"],
        "count": plan["count"],
        "input": plan.get("user_input", ""),
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "tool_version": config.TOOL_VERSION,
        "artifacts": artifacts,
    }
    write_json(out_dir / config.ARTIFACT_MANIFEST, manifest)

    # 落盘标记：中间态保留在 .work/，靠它区分"已完成"与"待落盘"。
    # 主要防手工对同一中间态重复跑本脚本——那会对同一批记录产出内容相同的副本。
    write_json(work_path(work_dir, "emitted"), {
        "task_id": task_id,
        # 交付目录（run 目录/generated_datasets）。刻意不叫 out_dir——那个名字
        # 在 run-args.json 里指的是 run 目录本身，同名不同义容易看岔。
        "artifacts_dir": str(out_dir),
        "emitted_at": manifest["created_at"],
        "record_count": len(records),
        "has_gaps": bool(verify_report.get("gaps")),
    })

    gaps = verify_report.get("gaps") or {}
    if gaps:
        print(f"⚠️  存在缺口：{gaps}（.work/ 已保留供排查）")
        print(f"落盘：{out_dir}")
        return 1

    print(f"落盘完成：{out_dir}")
    print(f"    {config.ARTIFACT_SEED}  {len(records)} 条")
    for name in (config.ARTIFACT_PROFILE, config.ARTIFACT_PLAN,
                 config.ARTIFACT_MANIFEST, config.ARTIFACT_REPORT):
        print(f"    {name}")
    print(f"    中间态保留于 {work_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
