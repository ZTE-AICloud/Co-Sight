#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""动态 overview 的通用小工具。"""
from __future__ import annotations

import math
import re

_CJK_RE = re.compile(r"[㐀-鿿豈-﫿]")


def estimate_tokens(text: str) -> int:
    """粗略 token 估算：CJK 按 1 token/字，其余按 4 字符/token。"""
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    return int(cjk + max(0, len(text) - cjk) / 4) + 1


def normalize_scores(values: list[float]) -> list[float]:
    """把任意范围的 rerank 分数压到 0~1。

    BGE rerank 服务可能返回 logits 或 [0,1] 概率：落在 [0,1] 时原样保留，
    否则用 sigmoid 映射。
    """
    if not values:
        return []
    if all(0.0 <= v <= 1.0 for v in values):
        return values
    return [1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, v)))) for v in values]


def truncate(text: str, max_chars: int) -> str:
    text = text or ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"
