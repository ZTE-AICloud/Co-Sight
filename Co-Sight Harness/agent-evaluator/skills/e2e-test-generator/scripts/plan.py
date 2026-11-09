#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""plan.py — S2 计划规划：GWT 截断 + focus 偏置 + 配额分配。

纯代码计数，不做任何 LLM 调用。归类提示词由 tag.py 产出（两者分开，
改提示词与改计数逻辑互不干扰）。

前置：12-agent-profile.json；有 GWT 时还需要 20-tag.answer.json。
产物：20-plan.json

用法：
    python3 plan.py --work <中间态目录> --count 10 [--input "..."]

配额算法（共识版）：
    generated_budget = count - |kept_gwt|
    if |D| >= budget: 取 (权重降序, id 字典序) 前 budget 个维度各 1 条
    else:             每维保底 1 条，余数按 (权重降序, id 字典序) 轮转
    断言 kept_gwt + Σquota == count
"""

import argparse
import sys

import config
from common import (
    GoldevalError,
    fail,
    read_json,
    require,
    work_path,
    write_json,
)
from tag import parse_tag_answer


# ============================== focus 与权重 ==============================

def apply_focus(dimension_ids, focus_ids):
    """对命中 focus 的维度加权；返回 {id: 权重}。"""
    weights = {}
    for dim in config.DIMENSIONS:
        bonus = config.FOCUS_WEIGHT_BONUS if dim["id"] in focus_ids else 0
        weights[dim["id"]] = dim["weight"] + bonus
    return weights


def priority_order(weights):
    """按 (权重降序, id 字典序) 排序，返回维度 id 列表。"""
    return sorted(weights, key=lambda dim_id: (-weights[dim_id], dim_id))


# ============================== GWT 截断 ==============================

def truncate_gwts(gwts, tags, count, weights):
    """按维度优先级截断 GWT 到 count 条。

    排序键 = (维度优先级, 维度内 GWT 原序)；超出部分丢弃并记录。
    """
    order = priority_order(weights)
    rank = {dim_id: i for i, dim_id in enumerate(order)}

    tagged = []
    for gwt in gwts:
        dim_id = tags.get(gwt["index"])
        if dim_id not in rank:
            dim_id = order[-1]
        tagged.append((rank[dim_id], gwt["index"], {**gwt, "dimension": dim_id}))

    tagged.sort(key=lambda item: (item[0], item[1]))
    kept = [item[2] for item in tagged[:count]]
    dropped = [item[2] for item in tagged[count:]]
    return kept, dropped


# ============================== 配额分配 ==============================

def allocate(budget, weights):
    """按权重把生成预算分给各维度；断言总和等于 budget。"""
    dim_ids = list(weights)
    order = priority_order(weights)
    quota = {dim_id: 0 for dim_id in dim_ids}

    if budget <= 0:
        return quota

    if len(dim_ids) >= budget:
        for dim_id in order[:budget]:
            quota[dim_id] = 1
    else:
        for dim_id in dim_ids:
            quota[dim_id] = 1
        remainder = budget - len(dim_ids)
        cursor = 0
        while remainder > 0:
            quota[order[cursor % len(order)]] += 1
            cursor += 1
            remainder -= 1

    total = sum(quota.values())
    require(
        total == budget,
        f"配额分配断言失败：Σquota={total} != budget={budget}",
    )
    return quota


# ============================== 主流程 ==============================

def build_plan(profile, count, user_input, tag_answer):
    """算出计划（不落盘）。"""
    gwts = profile["gwt_baseline"]["entries"]

    if gwts:
        tags, focus_ids, focus_reason = parse_tag_answer(tag_answer, gwts, user_input)
    else:
        tags, focus_ids, focus_reason = {}, [], ""

    weights = apply_focus(config.DIMENSION_IDS, focus_ids)
    kept_gwts, dropped_gwts = truncate_gwts(gwts, tags, count, weights)

    generated_budget = count - len(kept_gwts)
    quota = allocate(generated_budget, weights)

    focused = [d for d in config.DIMENSIONS if d["id"] in focus_ids]

    plan = {
        "count": count,
        "user_input": user_input,
        "tier": profile["tier"],
        "dimension_weights": weights,
        "focus": focus_ids,
        "focus_reason": focus_reason,
        "focus_bonus": config.FOCUS_WEIGHT_BONUS,
        "focused_dimensions": focused,
        "gwt_kept": kept_gwts,
        "gwt_dropped": dropped_gwts,
        "gwt_total": len(gwts),
        "generated_budget": generated_budget,
        "quota": quota,
        "batch_size": config.BATCH_SIZE,
    }

    require(
        len(kept_gwts) + sum(quota.values()) == count,
        f"计划总数校验失败：kept_gwt={len(kept_gwts)} + "
        f"Σquota={sum(quota.values())} != count={count}",
    )

    return plan


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="plan.py", description="S2 计划规划：GWT 截断 + focus 偏置 + 配额分配"
    )
    parser.add_argument("--work", required=True, help="中间态目录")
    parser.add_argument("--count", type=int, default=config.COUNT_DEFAULT)
    parser.add_argument("--input", dest="user_input", default="")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if not config.COUNT_MIN <= args.count <= config.COUNT_MAX:
        fail(
            f"--count 必须在 {config.COUNT_MIN}~{config.COUNT_MAX} 之间，"
            f"实际 {args.count}"
        )

    profile = read_json(work_path(args.work, "profile"))
    if not profile:
        fail("未找到 12-agent-profile.json，请先运行 freeze_profile.py")

    gwts = profile["gwt_baseline"]["entries"]
    tag_answer = read_json(work_path(args.work, "tag_answer"))

    if gwts and not tag_answer:
        fail(
            "有 GWT 但缺少 20-tag.answer.json；"
            "请先运行 tag.py 产出提示词并填写答案"
        )

    try:
        built = build_plan(profile, args.count, args.user_input, tag_answer)
    except GoldevalError as exc:
        fail(str(exc))

    write_json(work_path(args.work, "plan"), built)

    print(f"S2 完成：tier={built['tier']}  count={built['count']}")
    if built["focus"]:
        print(f"    生成重点：{built['focus']}（权重 +{built['focus_bonus']}）")
    if built["gwt_kept"]:
        ids = "、".join(f"#{g['index']}" for g in built["gwt_kept"])
        print(f"    GWT 保留 {len(built['gwt_kept'])}/{built['gwt_total']} 条：{ids}")
    if built["gwt_dropped"]:
        ids = "、".join(f"#{g['index']}" for g in built["gwt_dropped"])
        print(f"    GWT 丢弃 {len(built['gwt_dropped'])} 条（按维度优先级截断）：{ids}")
    print(f"    生成预算 {built['generated_budget']} 条，配额：")
    for dim_id, value in built["quota"].items():
        if value:
            print(f"        {dim_id}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
