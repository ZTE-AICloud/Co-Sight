#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
共享检索增强、重排与聚合模块。

被 `skills/semantic-search/scripts/retrieve.py` 和
`agents/soc-agent/workspace/skills/soc-single-responder-skill/scripts/respond.py` 共用。

提供：
  - RerankStrategy 抽象接口
  - BGERerank（BGE 在线 rerank API 实现，respond.py 默认）
  - LLMRerank（LLM 相关度重评估，retrieve.py 默认）
  - 薄节点扩展三件套（is_thin_node / is_document_level_node / expand_thin_nodes）
  - 章节聚合 apply_chapter_aggregation
"""
from __future__ import annotations

import json
import os
import re
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Sequence, Optional, Any

from llama_index.core.schema import NodeWithScore, TextNode

from common.skill_utils import extract_first_json_array

# =====================================================================
# 常量
# =====================================================================

# 初始召回数（与 retrieve.py 保持一致）
RETRIEVE_TOP_K = 50
# LLM 重排每批 chunk 数
RERANK_BATCH_SIZE = 10
# BGE 重排默认 top_n
RERANK_TOP_N = 20

# 喂给 Step 3 合成的最大 chunk 数;超过这个数的低分 chunk 不进 LLM 合成 prompt,
# 但仍会出现在最终回答的 [N] 引用之前(见 _filter_by_relevance 注释)。
SYNTHESIS_TOP_N = 15

# 最小相关度阈值;top-N 里低于这个分数的也剔除。
# 改进 rerank prompt 后,真正含答案的 chunk 应该 ≥0.7,低于 0.3 的基本是关键词错配或场景不符。
SYNTHESIS_MIN_RELEVANCE = 0.3

# Tier → 分数映射(模块级常量,便于调参)
# 设计 4 档(HIGH/MID/LOW/NONE),通用、不绑领域:
#   A (0.92) → HIGH — 直接、完整、具体回答了问题核心(满足 3 条判定全部)
#   B (0.62) → MID  — 高度相关,提供主要背景或部分具体信息(满足部分)
#   C (0.32) → LOW  — 话题擦边,只触及问题某个侧面(不满足 3 条任一)
#   D (0.10) → NONE — 完全无关,或仅关键词匹配但场景错配
# 用户在 UI 上看到的仍是 0.10/0.32/0.62/0.92 这种具体分数,只是 LLM 评判时用的是 A/B/C/D。
TIER_SCORES = {'A': 0.92, 'B': 0.62, 'C': 0.32, 'D': 0.10}


def _parse_tier(tier_raw) -> str:
    """防御性解析 LLM 返回的 tier,统一成 A/B/C/D。
    无效或缺失时回退到 C(中庸档,避免被 0 分错杀)。"""
    if not tier_raw:
        return 'C'
    s = str(tier_raw).strip().upper()
    for ch in s:
        if ch in 'ABCD':
            return ch
    return 'C'


def _get_logger():
    import logging
    return logging.getLogger(__name__)


# 从 skill_utils 复用 JSON 抽取 helper（之前本地定义已删除）：
#   - extract_first_json_array: 三段式抽取 JSON 数组，用于 LLMRerank 重排结果解析
# 见 common/skill_utils.py 详细 docstring。


# per-item 容错正则,匹配最小可解析单元 {"idx":N,"tier":"X"}
# (reason 字段因为里面可能含未转义字符(JSON 整体被截断时常出现),不参与匹配,
#  拿到 tier 后 reason 走固定的 partial-recovery 标记,不强行从原文抠。)
_PARTIAL_ITEM_RE = re.compile(
    r'\{\s*"idx"\s*:\s*(\d+)\s*,\s*"tier"\s*:\s*"([A-Da-d])"',
    re.DOTALL,
)

# 推理模型的思考块标签正则(同时覆盖闭合 + 未闭合两种情形):
#   闭合   形态 1:  <think...>...</think>      -- 由 _THINK_BLOCK_PAIR_RE 处理
#   闭合   形态 2:  <mm:think>...</mm:think>   -- 同上
#   未闭合 形态:    <think> 之后没有结束标签(max_tokens 截断 / 模型根本没
#                 输出 JSON) -- 由 _THINK_BLOCK_UNCLOSED_RE 兜底
_THINK_BLOCK_PAIR_RE = re.compile(
    r'<(?:think|mm:think)\b[^>]*>.*?</(?:think|mm:think)>',
    re.DOTALL,
)
_THINK_BLOCK_UNCLOSED_RE = re.compile(
    r'<(?:think|mm:think)\b[^>]*>.*$',
    re.DOTALL,
)


def strip_thinking_tags(text: str) -> str:
    """把推理模型输出的 <think>/<mm:think> 思考块整体删除,
    包括被 max_tokens 截断、没闭合的残余思考文本。

    Args:
        text: LLM 原始输出。

    Returns:
        去掉所有思考块后的字符串;re.DOTALL 模式下处理跨行。
    """
    if not text:
        return ''
    out = _THINK_BLOCK_PAIR_RE.sub('', text)
    out = _THINK_BLOCK_UNCLOSED_RE.sub('', out)
    return out.strip()


def _extract_partial_scores(text: str, batch_size: int) -> Optional[list]:
    """整批 JSON 解析失败时的 per-item 容错。

    只挑出能从原始文本里正则匹配到 idx+tier 的最小单元;
    剩余 index 用默认 tier C 填充,避免整批 vector_score 被丢。

    Returns:
        ``[{"idx": N+1, "tier": "X", "reason": "..."}, ...]`` 形态的 list,
        走与 LLM 正常输出相同的主循环(避免被 ``isinstance(scores, dict)``
        检查误判为包对象 dict)。完全抽不到时返回 ``None``,由 caller 决定
        是降级还是报错。
    """
    if not text:
        return None
    # idx_in_batch -> (tier, reason),先收集再去重
    by_idx: dict = {}
    seen_idx: set = set()
    for m in _PARTIAL_ITEM_RE.finditer(text):
        try:
            idx_one_based = int(m.group(1))
            tier_letter = m.group(2).upper()
        except (TypeError, ValueError):
            continue
        idx_in_batch = idx_one_based - 1
        if idx_in_batch in seen_idx:
            continue
        if 0 <= idx_in_batch < batch_size and tier_letter in 'ABCD':
            by_idx[idx_in_batch] = (
                tier_letter,
                'partial-recovery (full parse failed, regex fallback)',
            )
            seen_idx.add(idx_in_batch)
    # 剩余 index 兜底 C(避免整批 vector_score 因解析失败被丢)
    for i in range(batch_size):
        if i not in by_idx:
            by_idx[i] = ('C', 'partial-recovery (item missing from LLM output)')
    # 转回 list,主循环可直接复用(避免被 isinstance dict 分支误判)
    return [
        {'idx': i + 1, 'tier': tier, 'reason': reason}
        for i, (tier, reason) in sorted(by_idx.items())
    ] if by_idx else None


# =====================================================================
# RerankStrategy 抽象接口
# =====================================================================


class RerankStrategy(ABC):
    """可插拔重排策略。

    接受 nodes + query，返回【重排 + 重打分】后的 nodes。

    约定：
      - 返回值按相关性降序
      - node.score 必须被重写为新分数
      - 原 vector score 写入 node.node.metadata['vector_score']，用于
        citation "Vector Score (原始)" 行
      - 任何异常必须降级：返回原 nodes（或按 score 截断的原 nodes），不抛出
    """

    name: str = "abstract"

    @abstractmethod
    def rerank(self, query: str, nodes: Sequence[NodeWithScore]) -> List[NodeWithScore]:
        ...


# =====================================================================
# BGERerank：BGE 在线 rerank API 实现
# =====================================================================

# BGE Rerank API 配置（与 respond.py 一致）
# 只从环境变量读取，不再提供硬编码默认；未配置时 BGERerank 直接降级（不打请求）。
_RERANK_API_URL_DEFAULT = os.environ.get("COSIGHTBOT_RERANK_API_URL")
_EMBEDDING_API_KEY_DEFAULT = os.environ.get("COSIGHTBOT_EMBEDDING_API_KEY")


class BGERerank(RerankStrategy):
    """包装 BGE 在线 rerank API。name='bge'"""

    name = "bge"

    def __init__(
        self,
        top_n: int = RERANK_TOP_N,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.top_n = top_n
        self.api_url = api_url or _RERANK_API_URL_DEFAULT
        self.api_key = api_key or _EMBEDDING_API_KEY_DEFAULT

    def rerank(self, query: str, nodes: Sequence[NodeWithScore]) -> List[NodeWithScore]:
        if not nodes or not query:
            return list(nodes)[:self.top_n]
        if not self.api_url:
            _get_logger().info(
                "[BGERerank] Rerank API 未配置（缺少 COSIGHTBOT_RERANK_API_URL），跳过重排"
            )
            return list(nodes)[:self.top_n]

        try:
            import requests
        except ImportError:
            return list(nodes)[:self.top_n]

        texts = [n.node.get_content() for n in nodes]
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {"query": query, "documents": texts, "model": "reranker"}

        try:
            response = requests.post(
                self.api_url, headers=headers, json=payload, timeout=300
            )
            res_json = response.json()
            results = res_json.get("results", []) if isinstance(res_json, dict) else res_json

            if not isinstance(results, list):
                return list(nodes)[:self.top_n]

            new_nodes = []
            for item in results:
                if isinstance(item, dict):
                    idx = item.get("index")
                    score = item.get("relevance_score") or item.get("score")
                    if idx is not None and score is not None:
                        node = nodes[idx]
                        # 保留原 vector score
                        meta = dict(node.node.metadata or {})
                        if "vector_score" not in meta:
                            meta["vector_score"] = float(getattr(node, "score", 0.0) or 0.0)
                        node.node.metadata = meta
                        node.score = float(score)
                        new_nodes.append(node)

            return new_nodes[:self.top_n] if new_nodes else list(nodes)[:self.top_n]
        except Exception as e:
            _get_logger().warning(
                f"[BGERerank] Failed (non-critical, keeping original order): {e}"
            )
            return list(nodes)[:self.top_n]


# =====================================================================
# LLMRerank：LLM 相关度重评估
# =====================================================================


class LLMRerank(RerankStrategy):
    """用 LLM 重评估每条 chunk 相关度，覆盖 node.score。失败时静默降级。name='llm'"""

    name = "llm"

    def __init__(self, llm, batch_size: int = RERANK_BATCH_SIZE):
        self.llm = llm
        self.batch_size = batch_size

    def _score_batch(self, query: str, batch: Sequence[NodeWithScore], batch_idx: int, logger):
        """单批打分（线程安全）：只构造 prompt、调用 LLM、解析响应，不修改任何 node。
        返回 {idx_in_batch: (tier, reason)}；失败返回空 dict。
        """
        try:
            items = []
            for i, n in enumerate(batch, 1):
                meta = n.node.metadata or {}
                try:
                    # 预览窗口从 500 扩到 1500:500 字符截断了表格主体,LLM 看不到含具体型号/数字的那一行
                    # 1500 字符能覆盖一个标准 markdown 表格 + 上下文段落
                    preview = (n.node.get_content() or "")[:1500]
                except Exception:
                    preview = ""
                items.append({
                    "idx": i,
                    "title": meta.get("chapter_title", "") or meta.get("title", ""),
                    "file_name": meta.get("file_name", ""),
                    "header_path": meta.get("header_path", ""),
                    "content_preview": preview,
                    "vector_score": round(float(getattr(n, "score", 0.0) or 0.0), 4),
                })

            prompt = (
                "你是严格的【相关性评估器】。给定用户问题与若干候选文档片段，"
                "对每条片段**独立**分到 A/B/C/D 四档之一。\n\n"
                "**分档标准(满足「答案型」3 条判定的为 A)**:\n"
                "  A — **直接、完整、具体地回答了问题核心**,同时满足以下 3 条:\n"
                "    (a) 含**可引用的客观事实**(具体数字/型号/名称/日期/ID/表格行等),非泛指描述;\n"
                "    (b) **主题一致**:片段所属章节/文档的主题与用户问题主题一致(同场景/同对象/同领域);\n"
                "    (c) **答案显式存在**:不需推理或外推,直接抽取即可得到答案。\n"
                "  B — **高度相关**,提供主要背景或部分具体信息,但**未同时满足 A 的 3 条**(缺 1 或 2 条)。\n"
                "  C — **话题擦边**,只触及问题的某个侧面,无具体事实,不是问题的答案。\n"
                "  D — **完全无关**,或仅关键词匹配但场景/对象错配(同关键词但不同对象/不同领域)。\n\n"
                "**关键指令**:\n"
                "1. **3 条判定全部满足才能给 A**,任一不满足最多给 B,不要因为『答案看着像』就放宽。\n"
                "2. **避免给 D 太多分(0.10)**:D 就是真的不相关,不是『勉强有点关系』。\n"
                "3. **B 的边界**:A vs B 的关键是『是否同时满足 3 条』。背景介绍给 B,不要因为『相关』就升 A。\n"
                "4. **C vs D 的边界**:C 是『同话题但答非所问』,D 是『根本不是这个话题』。\n\n"
                "**Few-shot 示例(跨域演示分档模式,不要过拟合到示例的具体领域)**:\n\n"
                "#### 示例 1 — 期望: A\n"
                "  问题: 「项目 X 的核心指标 Y 是多少?」\n"
                "  片段: 「项目 X 报告:Y = 0.95,同比 +12%(2025Q3)」\n"
                "  → (a) 含数字+时间+对比; (b) 主题=项目 X; (c) Y 显式存在 → A\n\n"
                "#### 示例 2 — 期望: B\n"
                "  问题: 「项目 X 的核心指标 Y 是多少?」\n"
                "  片段: 「项目 X 的整体复盘,讨论 Q3 各维度的进展,但未量化 Y」\n"
                "  → 满足 (b) 主题一致,缺 (a) 数字 和 (c) 显式答案 → B\n\n"
                "#### 示例 3 — 期望: D\n"
                "  问题: 「项目 X 的核心指标 Y 是多少?」\n"
                "  片段: 「项目 W 与 X 同期的指标 Z 报告:Z = 0.88」\n"
                "  → 含『项目』『指标』关键词,但项目/指标都不同 → D\n\n"
                f"【用户问题】\n{query}\n\n"
                f"【候选片段】\n{json.dumps(items, ensure_ascii=False, indent=2)}\n\n"
                "【输出要求】严格输出 JSON 数组，每个元素 {\"idx\": N, \"tier\": \"A|B|C|D\", \"reason\": \"...\"}。"
                "tier 必须是 A / B / C / D 之一(单个大写字母),不要输出小写或其他字符。"
                "不要输出 markdown 包裹，不要输出其他内容。"
            )

            t0 = time.time()
            response = self.llm.complete(prompt)
            elapsed = time.time() - t0
            text = str(response).strip()
            logger.info(
                f"[LLMRerank] Batch {batch_idx} ({len(batch)} chunks) LLM call done in {elapsed:.2f}s"
            )

            # 1) 剥离推理模型的思考块(两种思考标签同步处理):
            #    - 标签-A 对应的内部推理模型使用 `<think...>` ... `<\\/think>`
            #    - 标签-B 对应的内部推理模型使用 `<mm:think...>` ... `<\\/mm:think>`
            #    实际的标签字符由 strip_thinking_tags() 内部通过 chr() 拼接;
            #    这里写注释时不再嵌入字面量,以避免 cp936 / heredoc 等环境把
            #    `<` / `>` 吞掉留下乱码。
            #
            #    同时覆盖"标签被 max_tokens 截断、还没来得及闭合"的情形
            #    ——这种情形下模型根本没有机会输出 JSON,必须把残留思考文本
            #    整段丢掉,否则会污染后续的 JSON 抽取。
            text_no_think = strip_thinking_tags(text)

            # 2) 三段式 JSON 抽取(整段 → markdown fence → 非贪婪 [...]),
            #    复用 skill_utils.extract_first_json_array,新旧模型共用一条路径
            #    (取代原来的内联 find('[')/rfind(']') 兜底,后者遇到
            #    "思考文本里有方括号" 或 "思考里完全没有 [" 都会崩)。
            scores = extract_first_json_array(text_no_think)
            if scores is None:
                # 3) 整批解析失败 → per-item 正则兜底:只挑出
                #    {"idx":N,"tier":"X"} 能配上的,剩余 index 用默认 tier C。
                #    不再抛整批失败,尽量保留 LLM 已经给出的部分结论。
                #    _extract_partial_scores 返回 list(不是 dict),与正常
                #    LLM 输出共用同一段主循环,避免被 isinstance(dict) 分支误判。
                scores = _extract_partial_scores(text_no_think, len(batch))
                if scores is None:
                    # 一条 idx+tier 都抽不到 → 留给外层 except 走 vector_score 兜底
                    logger.error(
                        f"[LLMRerank] Batch {batch_idx} JSON parse failed and "
                        f"per-item fallback empty. LLM raw output (first 500 chars): "
                        f"{text[:500]!r}"
                    )
                    raise ValueError(
                        f"[LLMRerank] Batch {batch_idx} parse failed: "
                        f"no parseable item in LLM output"
                    )
                recovered = sum(
                    1 for item in scores
                    if 'regex fallback' in item.get('reason', '')
                )
                logger.warning(
                    f"[LLMRerank] Batch {batch_idx} full-parse failed; "
                    f"per-item fallback recovered {recovered}/{len(batch)} items "
                    f"(rest defaulted to tier C). "
                    f"LLM raw output (first 500 chars): {text[:500]!r}"
                )
            if isinstance(scores, dict):
                # LLM 返回 dict 包数组(常见格式 {"results": [...]} / {"data": [...]})
                # 取第一个 list 类型的字段
                for v in scores.values():
                    if isinstance(v, list):
                        scores = v
                        break
                else:
                    raise ValueError(f"LLM 返回的是 dict 但找不到数组字段: {list(scores.keys())}")
            if not isinstance(scores, list):
                raise ValueError(f"LLM 返回的不是数组: {type(scores)}")

            # 只返回结果，不修改 nodes（让主线程统一应用，避免并发写）
            result = {}
            for item in scores:
                try:
                    idx_in_batch = int(item.get("idx", 0)) - 1
                except (TypeError, ValueError):
                    continue
                if 0 <= idx_in_batch < len(batch):
                    tier = _parse_tier(item.get("tier"))
                    reason = str(item.get("reason", ""))[:500]
                    result[idx_in_batch] = (tier, reason)
            return result

        except Exception as e:
            logger.error(
                f"[LLMRerank] Batch {batch_idx} failed (this batch keeps vector scores): {e}"
            )
            return {}

    def rerank(self, query: str, nodes: Sequence[NodeWithScore]) -> List[NodeWithScore]:
        if not nodes or self.llm is None:
            return list(nodes)

        logger = _get_logger()
        try:
            total = len(nodes)
            logger.info(
                f"[LLMRerank] Re-evaluating {total} chunks, "
                f"batch_size={self.batch_size}"
            )

            # 构造所有批（保留 batch_idx 用于并行结果回填到 nodes）
            batches = []
            for batch_start in range(0, total, self.batch_size):
                batches.append((batch_start, nodes[batch_start:batch_start + self.batch_size]))

            # 并行调度：max_workers 上限 8，跟 batch_size=10 配套
            max_workers = max(1, min(len(batches), 8))
            t0 = time.time()
            all_results = {}  # {batch_start: {idx_in_batch: (tier, reason)}}
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(
                        self._score_batch, query, batch, batch_idx, logger
                    ): batch_idx
                    for batch_idx, batch in batches
                }
                for future in as_completed(futures):
                    batch_idx = futures[future]
                    try:
                        all_results[batch_idx] = future.result()
                    except Exception as e:
                        logger.error(f"[LLMRerank] Batch {batch_idx} future exception: {e}")
                        all_results[batch_idx] = {}

            parallel_elapsed = time.time() - t0
            logger.info(
                f"[LLMRerank] All {len(batches)} batches parallel-done in {parallel_elapsed:.2f}s "
                f"(max_workers={max_workers})"
            )

            # 主线程串行应用结果到 nodes（避免并发改同一对象；Python GIL 下赋值原子但 dict 更新不原子）
            for batch_start, batch in batches:
                result = all_results.get(batch_start, {})
                for idx_in_batch, n in enumerate(batch):
                    if idx_in_batch not in result:
                        continue
                    tier, reason = result[idx_in_batch]
                    new_score = TIER_SCORES[tier]
                    new_score = max(0.0, min(1.0, new_score))
                    meta = dict(n.node.metadata or {})
                    if 'vector_score' not in meta:
                        meta['vector_score'] = float(getattr(n, "score", 0.0) or 0.0)
                    n.node.metadata = meta
                    n.score = new_score
                    n.node.metadata['llm_relevance_score'] = new_score
                    n.node.metadata['llm_relevance_tier'] = tier
                    n.node.metadata['llm_relevance_reason'] = reason

            logger.info(f"[LLMRerank] Done: {total} chunks re-evaluated")
            return list(nodes)
        except Exception as e:
            logger.warning(
                f"[LLMRerank] Failed (non-critical, keeping original order): {e}"
            )
            return list(nodes)


# =====================================================================
# 薄节点扩展
# =====================================================================


def is_thin_node(node_with_score) -> bool:
    """
    判断节点是否为"无实质内容"的薄节点（如仅含标题和目录的 chunk）。

    典型薄节点示例：
      # 智算一体机配置规划——2025Q3在研版本
      [TOC]

    判断规则（满足任一即视为薄节点）：
    1. 去除 [TOC]、空行、标题行后，有效内容少于 50 字符
    2. 去除 [TOC] 和空行后，剩余内容全部是 Markdown 标题行（# 开头）
    """
    text = node_with_score.node.get_content().strip()
    cleaned = re.sub(r'\[TOC\]', '', text)
    lines = cleaned.split('\n')
    non_heading_lines = [
        line for line in lines
        if line.strip() and not line.strip().startswith('#')
    ]
    effective_text = '\n'.join(non_heading_lines).strip()
    if len(effective_text) < 50:
        _get_logger().info(
            f"[IsThinNode] Effective text length less than 50 characters: {effective_text}"
        )
        return True
    has_any_content = any(
        line.strip() and not line.strip().startswith('#')
        for line in cleaned.split('\n')
    )
    if not has_any_content:
        _get_logger().info(
            f"[IsThinNode] No content other than heading lines: {cleaned}"
        )
        return True
    return False


def is_document_level_node(node_with_score) -> bool:
    """
    判断薄节点是否为文档级节点（文档标题 + TOC），而非章节级节点。

    判断规则（满足任一即视为文档级）：
    1. 文本包含 [TOC] 标记
    2. 标题文本与 file_name（去掉 .md 后缀）匹配
    """
    text = node_with_score.node.get_content().strip()
    if '[TOC]' in text:
        return True
    meta = node_with_score.node.metadata or {}
    file_name = meta.get("file_name", "")
    if file_name:
        doc_title = Path(file_name).stem
        first_line = text.split('\n', 1)[0].strip().lstrip('#').strip()
        if first_line and first_line == doc_title:
            return True
    return False


def expand_thin_nodes(index, retrieved_nodes: list) -> list:
    """
    薄节点扩展：区分文档级和章节级，采用不同策略。
    - 文档级薄节点（标题 + TOC）：读取 file_path 对应的完整文档内容，追加到节点
    - 章节级薄节点（仅含章节标题）：按 chapter_id 从 LanceDB 拉取该章节全部 chunk
    """
    if not retrieved_nodes or index is None:
        return retrieved_nodes

    doc_level_nodes = []
    chapter_ids_to_expand = set()

    for n in retrieved_nodes:
        if not is_thin_node(n):
            continue
        if is_document_level_node(n):
            doc_level_nodes.append(n)
        else:
            cid = (n.node.metadata or {}).get("chapter_id", "")
            if cid:
                chapter_ids_to_expand.add(cid)

    if not doc_level_nodes and not chapter_ids_to_expand:
        return retrieved_nodes

    _get_logger().info(
        f"[ExpandThinNodes] Document-level: {len(doc_level_nodes)}, "
        f"Chapter-level: {len(chapter_ids_to_expand)}"
    )

    try:
        # 策略 1：文档级节点 → 读取完整文档内容追加到节点
        for n in doc_level_nodes:
            meta = n.node.metadata or {}
            file_path = meta.get("file_path", "")
            if not file_path or not Path(file_path).exists():
                _get_logger().warning(f"[ExpandDocLevel] file_path not found: {file_path}")
                continue
            try:
                full_content = Path(file_path).read_text(encoding="utf-8")
                n.node.text = full_content
                n.node.metadata["is_doc_level"] = True
                _get_logger().info(
                    f"[ExpandDocLevel] Enriched node with full document "
                    f"({len(full_content)} chars): {Path(file_path).name}"
                )
            except Exception as e:
                _get_logger().error(f"[ExpandDocLevel] Failed to read {file_path}: {e}")

        # 策略 2：章节级节点 → 按 chapter_id 查询 LanceDB 拉取该章节全部 chunk
        if chapter_ids_to_expand:
            table = index.vector_store._table
            seen_ids = {n.node.node_id for n in retrieved_nodes}

            for cid in chapter_ids_to_expand:
                rows = table.search().where(
                    f"metadata.chapter_id LIKE '%{cid}%'"
                ).limit(100).to_list()
                expanded = 0
                for row in rows:
                    rid = row.get("id", "")
                    if rid in seen_ids:
                        continue
                    row_meta = row.get("metadata", {})
                    if isinstance(row_meta, str):
                        try:
                            row_meta = json.loads(row_meta)
                        except Exception:
                            row_meta = {}
                    if row_meta.get("chapter_id", "") != cid:
                        continue
                    row_meta["is_chapter_level"] = True
                    node = TextNode(text=row.get("text", ""), id_=rid, metadata=row_meta)
                    retrieved_nodes.append(NodeWithScore(node=node, score=0.4))
                    seen_ids.add(rid)
                    expanded += 1
                _get_logger().info(f"[ExpandChapter] '{cid}' → {expanded} additional chunks")

        return retrieved_nodes
    except Exception as e:
        _get_logger().error(f"Thin node expansion failed (non-critical): {e}")
        return retrieved_nodes


# =====================================================================
# 章节聚合
# =====================================================================


def apply_chapter_aggregation(nodes, engine) -> list:
    """尝试对检索结果应用章节聚合后处理（如果 engine 上挂载了 ChapterAggregationPostprocessor）"""
    from llama_index.core.schema import QueryBundle

    postprocessors = getattr(engine, '_node_postprocessors', None) or []
    _get_logger().debug(f"[ApplyChapterAggregation] Node postprocessors: {postprocessors}")
    if not postprocessors:
        return nodes
    try:
        try:
            from watch_dog.file_watcher.search import ChapterAggregationPostprocessor
        except ImportError:
            return nodes
        dummy_bundle = QueryBundle(query_str="")
        for pp in postprocessors:
            if isinstance(pp, ChapterAggregationPostprocessor):
                nodes = pp.postprocess_nodes(nodes, dummy_bundle)
                _get_logger().info(
                    f"[ApplyChapterAggregation] Chapter aggregation applied: {len(nodes)} nodes after"
                )
                break
    except Exception as e:
        _get_logger().error(f"[ApplyChapterAggregation] Chapter aggregation skipped: {e}")
    return nodes


# =====================================================================
# Step 2.5: Relevance Pre-filter (before Step 3 synthesis)
# =====================================================================


def _filter_by_relevance(
    nodes: List[Any],
    top_n: int = SYNTHESIS_TOP_N,
    min_relevance: float = SYNTHESIS_MIN_RELEVANCE,
) -> List[Any]:
    """按 LLM Relevance 预筛,挡住明显低于答案 chunk 的噪音,减少 LLM 合成 prompt 的 token 浪费。

    筛选策略(双重保险):
      1. 取 llm_relevance_score 降序的 top_n(无则回退到 score)
      2. 在 top_n 里再过滤掉 < min_relevance 的

    设计原则(不破坏引文评分语义):
      - 筛选依据是 LLM 自己在 Step 1.6 给的相关度评分(满足"评分依据 = LLM 评估")
      - 绝不引用答案中的 [N] 引用状态(满足"不引入'答案引用'二次筛选")
      - 过滤后的集合就是"喂给 LLM 的素材",citations 自然反映这一点

    实现细节:
      - **保持输入顺序**:返回的节点顺序与入参一致,这样后续
        `enumerate(source_nodes, 1)` 出来的 [N] 编号与 citations/*.md 一一对应。
      - **空集保护**:若过滤后为空(异常情况),返回原集合,避免 LLM 收到空 prompt。
      - **不修改 n.score**:只挑选节点,不重写分数,保留原始数据可追溯。
    """
    if not nodes:
        return nodes

    logger = _get_logger()

    def _eff_score(n):
        meta = getattr(n.node, "metadata", None) or {}
        llm_s = meta.get("llm_relevance_score")
        if llm_s is not None:
            try:
                return float(llm_s)
            except (TypeError, ValueError):
                pass
        try:
            return float(getattr(n, "score", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    # 1. 按 effective score 降序,记录 (node, score, original_index)
    indexed = [(_eff_score(n), i, n) for i, n in enumerate(nodes)]
    indexed.sort(key=lambda x: (-x[0], x[1]))  # score desc, 然后按原顺序稳定排序

    # 2. 取 top_n
    top = indexed[:top_n]

    # 3. 在 top_n 里再过滤掉 < min_relevance 的
    kept = [(s, i, n) for (s, i, n) in top if s >= min_relevance]

    # 4. 空集保护:若过滤后为空,回退到原集合(避免 LLM 收到空 prompt)
    if not kept:
        logger.warning(
            f"[FilterByRelevance] Filtered to empty set (top_n={top_n}, min_relevance={min_relevance}); "
            f"falling back to original {len(nodes)} nodes."
        )
        return list(nodes)

    # 5. 按 original_index 升序排回去,保持输入顺序 → [N] 编号稳定
    kept.sort(key=lambda x: x[1])
    return [n for (_, _, n) in kept]
