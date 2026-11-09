#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate.py — 校验裁判写回的 answer.json 是否可用。

校验在这里是**唯一的把关口**：不合格的答案不进聚合，而是原样退回给主 agent 重派。
因此每条失败都要给出**能照做的归因**（"items 有 3 项，expected_output 有 5 项"），
而不是笼统的"格式错误"——主 agent 要把这句话连同重派指令一起转给新裁判。
"""

from pathlib import Path

import config
import common


class Verdict:
    """一条用例的校验结论。ok=False 时 reason 是一句能直接转述的话。"""

    def __init__(self, ok: bool, reason: str = "", answer: dict | None = None):
        self.ok = ok
        self.reason = reason
        self.answer = answer


def _is_int_in_range(value) -> bool:
    # bool 是 int 的子类，必须显式排除——True 会被当成 1 分蒙混过关
    return (isinstance(value, int) and not isinstance(value, bool)
            and config.SCORE_MIN <= value <= config.SCORE_MAX)


def validate_answer(path, expected: list, data_id: str) -> Verdict:
    """校验一份裁判答案。expected 是预期的 expected_output 列表（判等长用）。"""
    payload, error = common.read_json_text(Path(path))
    if error:
        return Verdict(False, f"裁判答案不可读：{error}")
    if not isinstance(payload, dict):
        return Verdict(False, f"裁判答案的顶层必须是 JSON 对象，实际是 {type(payload).__name__}")

    got_id = str(payload.get(config.DATA_ID_KEY) or "").strip()
    if got_id != data_id:
        return Verdict(False, f"data_id 不匹配：期望 {data_id!r}，答案是 {got_id!r}")

    items = payload.get(config.ANS_ITEMS)
    if not isinstance(items, list):
        return Verdict(False, f"缺少 {config.ANS_ITEMS} 字段或它不是数组")
    if len(items) != len(expected):
        return Verdict(
            False,
            f"{config.ANS_ITEMS} 项数不匹配：expected_output 有 {len(expected)} 项，"
            f"答案给了 {len(items)} 项——必须逐项等长同序")
    for position, item in enumerate(items, 1):
        if not isinstance(item, dict):
            return Verdict(False, f"{config.ANS_ITEMS} 第 {position} 项不是 JSON 对象")
        verdict = item.get(config.ANS_ITEM_VERDICT)
        if verdict not in config.VERDICTS:
            allowed = " / ".join(config.VERDICTS)
            return Verdict(
                False,
                f"{config.ANS_ITEMS} 第 {position} 项的 {config.ANS_ITEM_VERDICT} "
                f"非法：{verdict!r}（只能是 {allowed}）")

    missing = [dim for dim in config.DIMENSIONS if not _is_int_in_range(payload.get(dim))]
    if missing:
        return Verdict(
            False,
            f"四个维度分缺失或越界（需 {config.SCORE_MIN}~{config.SCORE_MAX} 的整数）："
            f"{'、'.join(missing)}")

    run_valid = payload.get(config.ANS_RUN_VALID)
    if not isinstance(run_valid, bool):
        return Verdict(False, f"{config.ANS_RUN_VALID} 必须是布尔值，实际是 {run_valid!r}")
    if not run_valid and not str(payload.get(config.ANS_INVALID_REASON) or "").strip():
        return Verdict(
            False,
            f"{config.ANS_RUN_VALID} 为 false 时必须填 {config.ANS_INVALID_REASON}")

    return Verdict(True, answer=payload)
