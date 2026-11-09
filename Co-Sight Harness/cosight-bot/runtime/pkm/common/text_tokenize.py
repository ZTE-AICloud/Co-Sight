#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""索引与查询共用的分词。

- ASCII 标识符（ERR_401_02 / 192.168.1.1 / v2.3.1 / search.py）整体保留；
- 中文用 jieba（缺失时退化为整段中文，仍可建索引）；
- 统一小写 + 停用词过滤。

索引侧与查询侧必须调用同一个 tokenize_text()，否则 BM25 会系统性失配。
"""
from __future__ import annotations

import re

try:  # jieba 在 requirements 中显式声明；缺失时不阻断基础能力
    import jieba  # type: ignore
except Exception:  # pragma: no cover
    jieba = None

# 标识符必须以字母/数字/下划线开头和结尾；点/连字符只允许出现在中间，
# 避免把句末标点带进 token（"M3PROMOTED." 曾整词入库，查询 "M3PROMOTED" 命中不了）。
_ASCII_ID_RE = re.compile(r"[A-Za-z0-9_]+(?:[.\-][A-Za-z0-9_]+)*")
_CJK_RUN_RE = re.compile(r"[一-鿿]+|[^一-鿿]+")

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "been", "being", "this", "that",
    "these", "those", "it", "its", "as", "at", "by", "from", "we", "you",
    "they", "he", "she", "i", "not", "no", "yes", "do", "does", "did",
    "的", "了", "和", "与", "及", "是", "在", "有", "为", "对", "中",
    "上", "下", "个", "这", "那", "我们", "你们", "他们", "什么", "怎么",
}


def tokenize(text: str) -> list[str]:
    """把文本切成检索词序列（索引/查询共用）。"""
    tokens: list[str] = []
    for run in _CJK_RUN_RE.findall(text or ""):
        if not run:
            continue
        if re.match(r"[一-鿿]", run):
            if jieba is not None:
                tokens.extend(w.strip() for w in jieba.cut(run, HMM=False))
            else:
                tokens.append(run)
        else:
            # 保持旧行为：单字符 ASCII token 不入索引（噪声大于收益）。
            tokens.extend(
                t for t in _ASCII_ID_RE.findall(run.lower()) if len(t) >= 2
            )
    return [t for t in tokens if t and t not in _STOPWORDS]


def tokenize_text(text: str) -> str:
    """返回空格拼接的检索词串，供 tantivy 建索引/查询。"""
    return " ".join(tokenize(text))
