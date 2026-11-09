#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify.py — S4 校验与补生成。

硬校验 → 去重 → 覆盖度检查 → 定向补生成提示词。

去重执行矩阵（共识版）：
              用例间去重   排除集（demo_code | GWT Given）
  source=gwt      参与              豁免
  source=llm      参与              参与

用法：
    python3 verify.py --work <中间态目录>
"""

import argparse
import re
import sys
from pathlib import Path

import config
from common import (
    naming_slug as common_naming_slug,
    case_text,
    containment,
    fail,
    jaccard,
    read_json,
    work_path,
    write_json,
    write_jsonl,
    write_text,
)

GWT_ANSWER = "30-gwt.answer.json"
BATCH_ANSWER_RE = re.compile(r"^30-batch-(?P<dim>[a-z_]+)-(?P<n>\d+)\.answer\.json$")
REPAIR_ANSWER_RE = re.compile(r"^31-repair-(?P<dim>[a-z_]+)-r(?P<r>\d+)-(?P<n>\d+)\.answer\.json$")


# ============================== 答案收集 ==============================

def load_answer_cases(path):
    """读取一个 answer 文件里的 cases 数组。"""
    payload = read_json(path)
    if payload is None:
        return None
    cases = payload.get("cases")
    if not isinstance(cases, list):
        return []
    return [c for c in cases if isinstance(c, dict)]


# 验收基线来源：<--agent>/.agent-genesis 下的 clarified-agent-requirements.yaml
ACCEPTANCE_REF_PREFIX = config.ACCEPTANCE_REF_PREFIX
UNATTRIBUTED_REF = ACCEPTANCE_REF_PREFIX + "?"


def resolve_gwt_attribution(case, position, kept, dropped):
    """确定 GWT 物化用例的归属。

    返回 (gwt_index, dimension, source_ref, error)。error 非空时该条会被驳回，
    不再像旧版那样把越界用例默默归到第一个维度。

    优先读答案里的 `gwt_index`——一条 GWT 可以拆成多条用例（例如同一 GWT 覆盖
    多种非法输入），只有按编号归属才能让每条都落到正确的维度。
    缺该字段时按位置回退到 `plan.gwt_kept`，兼容没有 `gwt_index` 的旧答案文件。
    """
    kept_by_index = {g["index"]: g for g in kept}
    dropped_indices = {g["index"] for g in dropped}

    raw_index = case.get("gwt_index")
    if raw_index is not None:
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            return None, None, UNATTRIBUTED_REF, f"gwt_index {raw_index!r} 不是整数"
        if index in kept_by_index:
            return (
                index,
                kept_by_index[index]["dimension"],
                f"{ACCEPTANCE_REF_PREFIX}{index}",
                None,
            )
        if index in dropped_indices:
            return index, None, f"{ACCEPTANCE_REF_PREFIX}{index}", (
                f"gwt_index #{index} 已被计划截断丢弃，超出 --count 配额"
            )
        return None, None, UNATTRIBUTED_REF, f"gwt_index #{index} 不在验收基线中"

    if position < len(kept):
        gwt = kept[position]
        return (
            gwt["index"],
            gwt["dimension"],
            f"{ACCEPTANCE_REF_PREFIX}{gwt['index']}",
            None,
        )
    return None, None, UNATTRIBUTED_REF, (
        "缺少 gwt_index，且答案序位超出保留的 GWT 条数，无法确定归属"
    )


def collect_cases(work_dir, profile, plan):
    """收集全部来源的用例，附带 dimension / source / source_ref 归因。"""
    work_dir = Path(work_dir)
    collected = []

    # 源① GWT 物化
    gwt_cases = load_answer_cases(work_dir / GWT_ANSWER)
    if gwt_cases is not None:
        kept = plan["gwt_kept"]
        dropped = plan.get("gwt_dropped") or []
        for position, case in enumerate(gwt_cases):
            index, dimension, source_ref, error = resolve_gwt_attribution(
                case, position, kept, dropped
            )
            item = {
                "case": case,
                "dimension": dimension,
                "source": config.SOURCE_GWT,
                "source_ref": source_ref,
                "gwt_index": index,
            }
            if error:
                item["attribution_error"] = error
            collected.append(item)

    # 源③ LLM 生成（批次）与补生成（修补）
    for path in sorted(work_dir.glob("30-batch-*.answer.json")):
        match = BATCH_ANSWER_RE.match(path.name)
        if not match:
            continue
        for case in load_answer_cases(path) or []:
            collected.append({
                "case": case,
                "dimension": match.group("dim"),
                "source": config.SOURCE_LLM,
                "source_ref": path.name,
                "gwt_index": None,
            })

    for path in sorted(work_dir.glob("31-repair-*.answer.json")):
        match = REPAIR_ANSWER_RE.match(path.name)
        if not match:
            continue
        for case in load_answer_cases(path) or []:
            collected.append({
                "case": case,
                "dimension": match.group("dim"),
                "source": config.SOURCE_LLM,
                "source_ref": path.name,
                "gwt_index": None,
            })

    return collected


# ============================== 硬校验 ==============================

def validate_case(case):
    """硬校验单条用例；返回错误消息列表（空表示通过）。"""
    errors = []

    text_input = case.get("input")
    if not isinstance(text_input, str) or not text_input.strip():
        errors.append("input 为空")
    elif len(text_input.strip()) < config.MIN_INPUT_CHARS:
        errors.append(f"input 短于 {config.MIN_INPUT_CHARS} 字符")

    expected = case.get("expected_output")
    if not isinstance(expected, list) or not expected:
        errors.append("expected_output 必须是非空数组")
    else:
        for position, item in enumerate(expected, 1):
            if not isinstance(item, str) or not item.strip():
                errors.append(f"expected_output 第 {position} 条为空")
            elif len(item.strip()) < config.MIN_EXPECTED_ITEM_CHARS:
                errors.append(
                    f"expected_output 第 {position} 条短于 "
                    f"{config.MIN_EXPECTED_ITEM_CHARS} 字符"
                )

    return errors


def validate_records(collected, profile):
    """批量硬校验；返回 (通过项, 失败项)。"""
    cap_ids = {c["id"] for c in (profile.get("capabilities") or [])}
    passed, rejected = [], []

    for item in collected:
        case = item["case"]
        errors = validate_case(case)

        if item.get("attribution_error"):
            errors.append(item["attribution_error"])

        ref = case.get("capability_ref")
        if "capability_ref" in case and ref not in cap_ids:
            errors.append(f"capability_ref {ref!r} 不在能力点集合内")

        if errors:
            rejected.append({"source_ref": item["source_ref"], "errors": errors})
        else:
            passed.append(item)

    return passed, rejected


# ============================== 去重 ==============================

def build_exclusion_corpus(profile):
    """构造排除集语料（仅对 source=llm 生效）。"""
    corpus = []

    for gwt in (profile.get("gwt_baseline") or {}).get("entries") or []:
        if gwt.get("given"):
            corpus.append(("GWT Given", gwt["given"]))

    demo = profile.get("demo_code") or {}
    for item in demo.get("files") or []:
        if item.get("head"):
            corpus.append((f"demo_code/{item['file']}", item["head"]))

    return corpus


def dedup_cases(passed, profile):
    """用例间去重 + 排除集比对；返回 (保留项, 丢弃项)。"""
    corpus = build_exclusion_corpus(profile)
    kept, dropped = [], []
    seen = []

    for item in passed:
        text = case_text(item["case"])

        duplicate = None
        for other_text, other_item in seen:
            if jaccard(text, other_text) > config.DEDUP_THRESHOLD:
                duplicate = f"与已有用例重复（{other_item['source_ref']}）"
                break

        if duplicate is None and item["source"] == config.SOURCE_LLM:
            for label, source_text in corpus:
                # 素材通常短于用例，用包含度而非 Jaccard（见 common.containment）
                if containment(text, source_text) > config.DEDUP_THRESHOLD:
                    duplicate = f"与排除集素材近义（{label}）"
                    break

        if duplicate:
            dropped.append({
                "source_ref": item["source_ref"],
                "dimension": item["dimension"],
                "reason": duplicate,
            })
        else:
            seen.append((text, item))
            kept.append(item)

    return kept, dropped


# ============================== 条数上限 ==============================

def cap_records(kept: list[dict], plan: dict) -> tuple[list[dict], list[dict]]:
    """把用例总数压到 `plan["count"]` 以内，返回 (保留项, 超限丢弃项)。

    GWT 物化允许一条 GWT 拆成多条用例（见 prompts.py 的物化说明），拆分会让
    总数超过 count。这里按固定优先级裁剪，保证最终条数 ≤ count：

    1. GWT 主用例——每个 `gwt_index` 的第一条，必留；
    2. LLM 生成用例——计划里的配额，优先于拆分；
    3. GWT 拆分用例——只消耗前两类用不完的预算。

    裁剪不改变保留项的原始顺序，也不把超限项计入缺口。
    """
    limit = int(plan["count"])
    if len(kept) <= limit:
        return kept, []

    primary, generated, split = [], [], []
    seen_gwt = set()
    for position, item in enumerate(kept):
        if item["source"] == config.SOURCE_GWT:
            index = item.get("gwt_index")
            if index in seen_gwt:
                split.append(position)
            else:
                seen_gwt.add(index)
                primary.append(position)
        else:
            generated.append(position)

    budget = limit
    chosen = set()
    for bucket in (primary, generated, split):
        for position in bucket:
            if budget <= 0:
                break
            chosen.add(position)
            budget -= 1

    capped = [item for position, item in enumerate(kept) if position in chosen]
    over_cap = [
        {
            "source_ref": item["source_ref"],
            "dimension": item["dimension"],
            "source": item["source"],
            "reason": f"超出 --count 上限 {limit} 条",
        }
        for position, item in enumerate(kept)
        if position not in chosen
    ]
    return capped, over_cap


# ============================== 物料化 ==============================

def assign_ids(kept, agent_slug):
    """分配 data_id 并转成最终 record。"""
    counters = {}
    records = []

    for item in kept:
        dim_id = item["dimension"]
        counters[dim_id] = counters.get(dim_id, 0) + 1
        case = item["case"]

        record = {
            "data_id": f"{agent_slug}_{dim_id}_{counters[dim_id]:03d}",
            "kind": config.KIND_SEED,
            "dimension": dim_id,
            "source": item["source"],
            "source_ref": item["source_ref"],
            "input": case["input"].strip(),
            "precondition": str(case.get("precondition") or "").strip(),
            "expected_output": [str(x).strip() for x in case["expected_output"]],
        }
        if "capability_ref" in case and case["capability_ref"]:
            record["capability_ref"] = case["capability_ref"]
        records.append(record)

    return records


def compute_gaps(records, plan):
    """计算各维度生成缺口。

    quota 语义是"该维度**需生成**的条数"，因此只统计 source=llm 的记录。
    若把 GWT 派生记录也算进来，某维度会被验收基线"填满"，掩盖生成缺口。
    """
    actual = {}
    generated = {}
    for record in records:
        dim_id = record["dimension"]
        actual[dim_id] = actual.get(dim_id, 0) + 1
        if record["source"] == config.SOURCE_LLM:
            generated[dim_id] = generated.get(dim_id, 0) + 1

    gaps = {}
    for dim_id, need in plan["quota"].items():
        shortfall = need - generated.get(dim_id, 0)
        if shortfall > 0:
            gaps[dim_id] = shortfall
    return gaps, actual


# ============================== 补生成提示词 ==============================

def build_repair_prompts(work_dir, profile, plan, gaps, round_no, existing_inputs,
                         prompts_module):
    written = []
    for dim_id, shortfall in gaps.items():
        dim = config.dimension_by_id(dim_id)
        for batch_index, start in enumerate(
            range(0, shortfall, config.BATCH_SIZE), 1
        ):
            size = min(config.BATCH_SIZE, shortfall - start)
            body = [
                f"# 任务：补生成测试用例（第 {round_no} 轮）\n",
                f"维度 **`{dim_id}`（{dim['name']}）** 仍缺 **{size}** 条，请补足。\n",
                f"维度说明：{dim['desc']}\n",
                prompts_module.render_profile_brief(profile),
                prompts_module.HARD_CONSTRAINTS.format(
                    capability_rule=prompts_module.capability_rule(profile)
                ),
                prompts_module.render_case_schema(profile),
                "## 禁止重复素材\n\n"
                + prompts_module.exclusion_block(profile, existing_inputs),
            ]
            name = f"31-repair-{dim_id}-r{round_no}-{batch_index}.prompt.md"
            path = work_path(work_dir, name)
            write_text(path, "\n".join(body))
            written.append(path)
    return written


# ============================== 主流程 ==============================

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="verify.py", description="S4 校验与补生成"
    )
    parser.add_argument("--work", required=True, help="中间态目录")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    import prompts as prompts_module

    profile = read_json(work_path(args.work, "profile"))
    plan = read_json(work_path(args.work, "plan"))
    if not profile or not plan:
        fail("未找到画像或计划，请先运行 freeze_profile.py 与 plan.py")

    agent_slug = common_naming_slug(profile)
    state = read_json(work_path(args.work, "verify_report")) or {}
    round_no = int(state.get("round", 0))

    collected = collect_cases(args.work, profile, plan)
    passed, rejected = validate_records(collected, profile)
    kept, dropped = dedup_cases(passed, profile)
    kept, over_cap = cap_records(kept, plan)
    records = assign_ids(kept, agent_slug)
    gaps, actual = compute_gaps(records, plan)

    # 有缺口且仍有补生成轮次 → 出补生成提示词，回到主 agent
    if gaps and round_no < config.MAX_REPAIR_ROUNDS:
        next_round = round_no + 1
        existing = [r["input"] for r in records]
        written = build_repair_prompts(
            args.work, profile, plan, gaps, next_round, existing, prompts_module
        )
        write_json(work_path(args.work, "verify_report"), {
            "round": next_round,
            "gaps": gaps,
            "actual": actual,
            "rejected": rejected,
            "dropped": dropped,
            "over_cap": over_cap,
            "pending_prompts": [p.name for p in written],
            "complete": False,
        })
        write_jsonl(work_path(args.work, "verified"), records)

        print(f"S4 第 {round_no} 轮：通过 {len(records)} 条，缺口 {gaps}")
        if over_cap:
            print(f"    超出上限丢弃 {len(over_cap)} 条（GWT 拆分多于预算）")
        print("下一步：为以下补生成提示词写出同名 answer 文件，然后重跑本脚本")
        for path in written:
            print(f"    {path.name}")
        return 0

    # 无缺口，或补生成轮次用尽 → 收尾
    write_jsonl(work_path(args.work, "verified"), records)
    write_json(work_path(args.work, "verify_report"), {
        "round": round_no,
        "gaps": gaps,
        "actual": actual,
        "rejected": rejected,
        "dropped": dropped,
        "over_cap": over_cap,
        "pending_prompts": [],
        "complete": not gaps,
    })

    print(f"S4 完成：最终 {len(records)} 条 / 目标 {plan['count']} 条")
    if rejected:
        print(f"    硬校验驳回 {len(rejected)} 条")
    if dropped:
        print(f"    去重丢弃 {len(dropped)} 条")
    if over_cap:
        print(f"    超出上限丢弃 {len(over_cap)} 条（GWT 拆分多于预算）")
    if gaps:
        print(f"    GAP（补生成 {round_no} 轮后仍缺）：{gaps}")
        print("    → 将按实际条数落盘，并以退出码 1 结束")
    return 0


if __name__ == "__main__":
    sys.exit(main())
