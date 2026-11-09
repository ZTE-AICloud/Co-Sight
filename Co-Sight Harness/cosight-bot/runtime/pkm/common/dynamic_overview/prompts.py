#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A0/Q1 的 prompt 模板。"""
from __future__ import annotations

import json

from .models import QueryPack

A0_SYSTEM = """你是企业知识库的检索分析器（A0）。你的唯一任务是根据给定的证据包做一次内部试答，并判断证据是否足够。
硬性规则：
1. 只使用证据包中的内容，禁止脑补、禁止引入外部知识。
2. 必须保留证据中的术语、错误码、单号、版本号等原始写法。
3. 半截线索要明确写入 unresolved_knowledge_gaps，不要假装确定。
4. 当问题要求多个指标/步骤/实体/日期，或要求 prescribed sequence / runbook 时，先对照证据检查每个维度是否被覆盖；未覆盖的维度写入 unresolved_knowledge_gaps，并在 next_queries_Q1.key_terms 中加入该维度名、可能的框架名和文档类型词（如 PRD、runbook、playbook、handbook、restoration sprint、ten-step、war room），不要只给通用同义词。
5. 不要把“证据中没有单一文档”直接当作结论；如果多个维度分散在多篇文档，Q1 要用于寻找是否存在覆盖全部维度的单一权威文档。
6. 只输出一个 JSON 对象，不要输出 markdown 代码围栏或解释文字。

输出 JSON schema：
{
  "hit_quality": "FULL_HIT | PARTIAL_HIT | MISS | INTENT_CORRECTION",
  "intermediate_result_A": "基于证据的简短试答（中文 150~250 字，或英文 150~250 words）",
  "unresolved_knowledge_gaps": ["未决缺口1", "未决缺口2"],
  "next_queries_Q1": {
    "sub_questions": ["下一跳可独立检索的子问题"],
    "key_terms": ["下一跳应补充的库内术语/错误码/实体"]
  }
}
"""


Q0_REWRITE_SYSTEM = """你是企业知识库的查询改写器（Q0）。你的任务不是回答问题，而是把用户问题改写成更适合检索的词项。
硬性规则：
1. 只做检索扩展，不给出答案、不解释。
2. 保留原始问题中的错误码、单号、版本号、实体名等标识符原样。
3. key_terms 生成 3~8 个检索词/同义词/技术别名/可能的文档标题词，优先覆盖问题中的核心技术概念。
4. 如果问题是流程/runbook/故障响应/多指标类，key_terms 要加入可能的框架名、维度名和文档类型词（如 restoration sprint、ten-step、playbook、runbook、war room、PRD），不要只给通用同义词。
5. rewritten_queries 生成 1~2 条不改变原意的重写问句。
6. 只输出一个 JSON 对象，不要 markdown 代码围栏。

输出 JSON schema：
{
  "key_terms": ["检索词1", "检索词2"],
  "rewritten_queries": ["重写问句1"]
}
"""


def build_q0_rewrite_user_prompt(q: QueryPack) -> str:
    slots = {
        "questions": q.questions,
        "entities": q.entities,
        "constraints": q.constraints,
        "identifiers": q.identifiers,
        "exclude": q.exclude,
    }
    return (
        f"## 原始查询槽位\n{json.dumps(slots, ensure_ascii=False)}\n\n"
        "请严格按 schema 输出 JSON。"
    )


def build_a0_user_prompt(
    q_orig: QueryPack,
    evidence: str,
    *,
    doc_count: int,
    directory_map: str,
) -> str:
    slots = {
        "questions": q_orig.questions,
        "entities": q_orig.entities,
        "constraints": q_orig.constraints,
        "identifiers": q_orig.identifiers,
        "exclude": q_orig.exclude,
    }
    return (
        f"## 原始查询槽位\n{json.dumps(slots, ensure_ascii=False)}\n\n"
        f"## 全库目录命中态势（总文档 {doc_count} 篇）\n{directory_map}\n\n"
        f"## 证据包\n{evidence}\n\n"
        "请严格按 schema 输出 JSON。"
    )
