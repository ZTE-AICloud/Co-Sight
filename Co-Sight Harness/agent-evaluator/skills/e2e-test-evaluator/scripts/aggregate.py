#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aggregate.py — 把裁判答案折成 eval 子对象，并渲染人读报告。

分工：**裁判只报事实（逐项判定 + 四维整数分），算术全在这里。** 把加权外包给 LLM
会让 5 条用例各用一把尺子，且不可复算。

两层结论（单条 / 整轮）严格分开：单条的阈值判定是 rubric 的原口径；整轮只做汇总，
且**无效样本（run_valid=false）与解析失败样本一律单列，绝不进任何平均值**。
"""

import config

# 报告里逐项判定的中文标签
VERDICT_LABELS = {
    config.VERDICT_HIT: "命中",
    config.VERDICT_MISS: "未命中",
    config.VERDICT_UNVERIFIABLE: "无法判定",
}


# ============================== 算术 ==============================

def weighted_score(scores: dict) -> float:
    """按 rubric 的权重算加权总分。"""
    return round(sum(scores[dim] * config.DIMENSION_WEIGHTS[dim]
                     for dim in config.DIMENSIONS), 2)


def is_passed(scores: dict, weighted: float) -> bool:
    """rubric 的三个阈值：加权总分 ≥3.5、correctness ≥3.0、completeness ≥3.0。"""
    return (weighted >= config.THRESHOLD_WEIGHTED
            and scores["correctness"] >= config.THRESHOLD_CORRECTNESS
            and scores["completeness"] >= config.THRESHOLD_COMPLETENESS)


def hit_ratio(items: list) -> tuple:
    """命中率。unverifiable 既不计分子也不计分母（Q5 已定）。

    返回 (命中数, 可判定数)；可判定数为 0 时命中率为 None。
    """
    hits = sum(1 for item in items
               if item.get(config.ANS_ITEM_VERDICT) == config.VERDICT_HIT)
    judgeable = sum(1 for item in items
                    if item.get(config.ANS_ITEM_VERDICT) != config.VERDICT_UNVERIFIABLE)
    return hits, judgeable


def band_of(ratio: float) -> int:
    """命中率对应的 completeness 档位（rubric 的 ≥80% / ≥60% / ≥30% 分档）。"""
    for lower, band in config.COMPLETENESS_BANDS:
        if ratio >= lower:
            return band
    return config.COMPLETENESS_BANDS[-1][1]


def inconsistency_note(items: list, completeness: int) -> str:
    """命中率与裁判自报的 completeness 是否明显矛盾。

    **只提示、不覆盖。** completeness 档位表并不纯粹是命中率（rubric 里还有
    "关键类别遗漏"这类定性判据），硬覆盖会引入脚本自己的误判；但矛盾太明显时
    应当让人看见。
    """
    hits, judgeable = hit_ratio(items)
    if judgeable == 0:
        return ""
    ratio = hits / judgeable
    band = band_of(ratio)
    if abs(band - completeness) <= config.INCONSISTENT_TOLERANCE:
        return ""
    return (f"命中率 {hits}/{judgeable}（{ratio:.0%}）对应 completeness 档位约 {band}，"
            f"但裁判给了 {completeness}")


# ============================== eval 子对象装配 ==============================

def build_eval(answer: dict, expected: list) -> dict:
    """把一份**已校验通过**的裁判答案折成 eval 子对象。"""
    items = answer.get(config.ANS_ITEMS) or []
    scores = {dim: int(answer[dim]) for dim in config.DIMENSIONS}
    weighted = weighted_score(scores)

    eval_obj = {
        config.EVAL_STATUS: config.EVAL_STATUS_OK,
        config.EVAL_RUN_VALID: bool(answer[config.ANS_RUN_VALID]),
        config.EVAL_INVALID_REASON: (answer.get(config.ANS_INVALID_REASON) or None),
        config.EVAL_ITEMS: [
            {
                config.ANS_ITEM_TEXT: str(item.get(config.ANS_ITEM_TEXT) or ""),
                config.ANS_ITEM_VERDICT: item.get(config.ANS_ITEM_VERDICT),
                config.ANS_ITEM_NOTE: str(item.get(config.ANS_ITEM_NOTE) or ""),
            }
            for item in items
        ],
        **scores,
        config.EVAL_WEIGHTED: weighted,
        config.EVAL_PASSED: is_passed(scores, weighted),
        config.EVAL_REASONING: str(answer.get(config.ANS_REASONING) or ""),
    }

    note = inconsistency_note(eval_obj[config.EVAL_ITEMS], scores["completeness"])
    if note:
        eval_obj[config.EVAL_INCONSISTENT] = note
    return eval_obj


def build_parse_error(reason: str) -> dict:
    """裁判答案最终仍不可用的条目：单列，不进任何平均值。"""
    return {
        config.EVAL_STATUS: config.EVAL_STATUS_PARSE_ERROR,
        config.EVAL_ERROR: reason,
    }


# ============================== 整轮统计 ==============================

def summarize(records: list) -> dict:
    """整轮汇总。

    "加权平均分"用**算法甲：先逐条加权、再平均** —— 忠实于 rubric"每条用例算出
    weighted_score"的原口径，且与单条 passed 同源。各维度均分只作辅助（用来看是
    哪一维拖后腿），**不合成第二个"总分"**。
    """
    ok = [r for r in records
          if (r.get(config.EVAL_KEY) or {}).get(config.EVAL_STATUS) == config.EVAL_STATUS_OK]
    valid = [r for r in ok if (r[config.EVAL_KEY] or {}).get(config.EVAL_RUN_VALID)]
    invalid = [r for r in ok if not (r[config.EVAL_KEY] or {}).get(config.EVAL_RUN_VALID)]
    broken = [r for r in records
              if (r.get(config.EVAL_KEY) or {}).get(config.EVAL_STATUS)
              == config.EVAL_STATUS_PARSE_ERROR]

    def mean(values: list) -> float | None:
        return round(sum(values) / len(values), 2) if values else None

    dimension_means = {
        dim: mean([r[config.EVAL_KEY][dim] for r in valid])
        for dim in config.DIMENSIONS
    }
    passed = [r for r in valid if r[config.EVAL_KEY].get(config.EVAL_PASSED)]

    groups = {}
    for record in valid:
        key = str(record.get(config.DIMENSION_KEY) or "（未标注）")
        groups.setdefault(key, []).append(record)

    by_dimension = {}
    for key, members in groups.items():
        group_passed = [r for r in members if r[config.EVAL_KEY].get(config.EVAL_PASSED)]
        by_dimension[key] = {
            "有效样本": len(members),
            "通过": len(group_passed),
            "通过率": f"{len(group_passed) / len(members):.0%}",
            "加权均分": mean([r[config.EVAL_KEY][config.EVAL_WEIGHTED] for r in members]),
        }

    return {
        "total": len(records),
        "valid": valid,
        "invalid": invalid,
        "broken": broken,
        "dimension_means": dimension_means,
        "weighted_mean": mean([r[config.EVAL_KEY][config.EVAL_WEIGHTED] for r in valid]),
        "passed_count": len(passed),
        "pass_rate": (f"{len(passed) / len(valid):.0%}" if valid else "—"),
        "by_dimension": by_dimension,
    }


# ============================== 报告渲染 ==============================

def fmt(value) -> str:
    return "—" if value is None else str(value)


def _cell(text: str) -> str:
    """表格单元格：换行折叠、竖线转义，避免把表格撑破。"""
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def _summary_section(summary: dict) -> str:
    lines = [
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 有效样本 | {len(summary['valid'])} / {summary['total']} |",
        f"| 通过率 | {summary['pass_rate']} |",
        f"| 加权平均分 | {fmt(summary['weighted_mean'])} |",
    ]
    for dim in config.DIMENSIONS:
        lines.append(f"| {dim} 均分 | {fmt(summary['dimension_means'][dim])} |")
    lines.append(f"| 解析失败（未参与评测） | {len(summary['broken'])} |")
    lines.append("")
    lines.append(f"> 加权平均分口径：逐条先算加权总分、再取平均。"
                 f"阈值：总分 ≥ {config.THRESHOLD_WEIGHTED}、"
                 f"correctness ≥ {config.THRESHOLD_CORRECTNESS}、"
                 f"completeness ≥ {config.THRESHOLD_COMPLETENESS}。")
    if not summary["valid"]:
        lines += [
            "",
            f"> **本轮无有效评测结论**：{summary['total']} 条用例中 0 条"
            f"`{config.EVAL_RUN_VALID}=true`。"
            f"下表给出的分数反映的是执行环境未就绪，而非被测 Agent 的能力，"
            f"请先修复环境或夹具路径后重跑。",
        ]
    return "\n".join(lines)


def _invalid_section(summary: dict) -> str:
    if not summary["invalid"]:
        return ""
    lines = [
        "",
        "`run_valid=false`：执行环境未如 `precondition` 所述就绪。"
        "分数照常展示——它本身就是这批为何无效的证据，但不参与任何均值。",
        "",
        "| data_id | 维度 | 失效原因 | 四维分（c/co/f/a） | 加权分 |",
        "|---|---|---|---|---|",
    ]
    for record in summary["invalid"]:
        ev = record[config.EVAL_KEY]
        scores = "/".join(str(ev[dim]) for dim in config.DIMENSIONS)
        lines.append(
            f"| {_cell(record.get(config.DATA_ID_KEY))} "
            f"| {_cell(record.get(config.DIMENSION_KEY))} "
            f"| {_cell(ev.get(config.EVAL_INVALID_REASON) or '（未说明）')} "
            f"| {scores} | {ev.get(config.EVAL_WEIGHTED)} |")
    return "\n".join(lines)


def _broken_section(summary: dict) -> str:
    if not summary["broken"]:
        return ""
    lines = [
        "",
        "| data_id | 原因 |",
        "|---|---|",
    ]
    for record in summary["broken"]:
        ev = record[config.EVAL_KEY]
        lines.append(f"| {_cell(record.get(config.DATA_ID_KEY))} "
                     f"| {_cell(ev.get(config.EVAL_ERROR) or '（未说明）')} |")
    return "\n".join(lines)


def _detail_section(summary: dict) -> str:
    if not summary["valid"]:
        return ""
    lines = ["", "### 逐条明细（有效样本）", ""]
    for record in summary["valid"]:
        ev = record[config.EVAL_KEY]
        mark = "✓" if ev.get(config.EVAL_PASSED) else "✗"
        lines += [
            f"### {record.get(config.DATA_ID_KEY)} — "
            f"{'通过' if ev.get(config.EVAL_PASSED) else '未通过'} {mark}",
            "",
            f"- **维度**：`{record.get(config.DIMENSION_KEY)}`",
            f"- **任务要求**：{_cell(str(record.get(config.INPUT_KEY))[:300])}",
            "",
            "| # | 期望项 | 判定 | 说明 |",
            "|---|---|---|---|",
        ]
        for position, item in enumerate(ev[config.EVAL_ITEMS], 1):
            label = VERDICT_LABELS.get(item[config.ANS_ITEM_VERDICT],
                                       str(item[config.ANS_ITEM_VERDICT]))
            lines.append(f"| {position} | {_cell(item[config.ANS_ITEM_TEXT])} "
                         f"| {label} | {_cell(item[config.ANS_ITEM_NOTE])} |")
        scores = " / ".join(f"{dim} {ev[dim]}" for dim in config.DIMENSIONS)
        lines += [
            "",
            f"- **四维得分**：{scores} → **加权 {ev[config.EVAL_WEIGHTED]}**",
            f"- **裁判理由**：{_cell(ev.get(config.EVAL_REASONING) or '（未提供）')}",
        ]
        if ev.get(config.EVAL_INCONSISTENT):
            lines.append(f"- **⚠ 矛盾提示**：{_cell(ev[config.EVAL_INCONSISTENT])}")
        lines.append("")
    return "\n".join(lines)


def _distribution_section(summary: dict) -> str:
    if not summary["by_dimension"]:
        return ""
    lines = [
        "",
        "| dimension | 有效样本 | 通过 | 通过率 | 加权均分 |",
        "|---|---|---|---|---|",
    ]
    for key, stats in sorted(summary["by_dimension"].items()):
        lines.append(f"| {_cell(key)} | {stats['有效样本']} | {stats['通过']} "
                     f"| {stats['通过率']} | {fmt(stats['加权均分'])} |")
    lines += [
        "",
        "> 各组之间**不合成总分**：生成器的 `dimension_weights` 是抽样配额权重，"
        "把它当评分权重会让抽了几条影响得几分。",
    ]
    return "\n".join(lines)


def _environment_section(manifest: dict) -> str:
    judge = manifest.get("judge") or {}
    return "\n".join([
        "",
        f"- 评分细则：`{manifest.get('rubric_path')}` @ sha256:"
        f"`{manifest.get('rubric_sha256')}`",
        f"- 裁判模型：{judge.get('model') or '（主 agent 未登记）'}",
        f"- 主 agent 模型：{judge.get('main_agent_model') or '（未登记）'}",
        f"- 并发数：{manifest.get('concurrency')}",
        f"- 阈值：总分 ≥ {config.THRESHOLD_WEIGHTED}、"
        f"correctness ≥ {config.THRESHOLD_CORRECTNESS}、"
        f"completeness ≥ {config.THRESHOLD_COMPLETENESS}",
        f"- 输入用例集：`{manifest.get('input_seed')}`",
    ])


def render_report(task_name: str, summary: dict, manifest: dict) -> str:
    """渲染 report.md。

    小节编号**渲染时按实际出现顺序分配**，而不是写死在标题里：无效样本、解析失败、
    逐条明细等小节在对应数据为空时整段省略，写死编号会在报告里留下跳号的窟窿
    （"二、无效样本"之后直接"六、环境记录"）。
    """
    blocks = [
        ("结论", _summary_section(summary)),
        ("无效样本（不计入上述任何指标）", _invalid_section(summary)),
        ("解析失败（未参与评测）", _broken_section(summary)),
        ("逐条明细（有效样本）", _detail_section(summary)),
        ("按维度分布", _distribution_section(summary)),
        ("环境记录", _environment_section(manifest)),
    ]

    numerals = "一二三四五六七八九十"
    sections = [f"# 评测报告 — {task_name}", "",
                f"> 生成工具：`{config.TOOL_VERSION}`"]
    number = 0
    for title, body in blocks:
        if not body.strip():
            continue
        number += 1
        sections += ["", "---", "", f"## {numerals[number - 1]}、{title}", body]

    return "\n".join(sections).rstrip() + "\n"
