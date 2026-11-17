#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T7 JEV-A3：答案出口双向核验与字面量支持度闸门（verify-answer 子命令核心实现）。

定位（主方案 3.5 节 / 任务书 T7）：Step 3 最终答案交卷前的"确定性 + 语义"双保险闸门，
精准拦截四类成稿失误：

  1. ``MISSING_POINT``       —— 已读原文明明有某步骤/批准条件而答案漏写；
  2. ``FALSE_NEGATION``      —— 答案声称"某信息未找到/未规定"但已读原文其实有明确记录；
  3. ``UNSUPPORTED_LITERAL`` —— 配置键名/HTTP Header/CLI 标志/数值单位抄写变形与张冠李戴；
  4. ``UNREAD_CITATION``     —— 引用了未在本轮 read-doc 的节点编号（S-04 违规）。

执行铁律：
  - 48 分钟预算上限零延迟短路（``BUDGET_CAP_SECONDS``），让位第 10 节 50 分钟强制交卷红线；
  - 阶段一 Python 零延迟硬校验：正文/披露区智能切分 + S-04 引文集合对账 + 代码精确子串
    预筛省流（精确命中的标识符 0 个 JEV 问题直接放行）+ HTML 标签剥除兼容 + 多模态看图豁免；
  - 阶段二内网 JEV 正反双向并行核验：细粒度动态要素清单（题面拆解 + 被引章节列表项原子化，
    上限 15 项）+ 否定断言组 + 可疑字面量/数值绑定组，按 50K 字符预算拆批并发，
    跨批取 max 聚合（任一批次有支持即不误报）；
  - 最多打回修订 1 轮（``max_revisions = 1``），严禁二次调用 verify-answer 循环；
  - 内网严苛双边阈值（source_has >= 0.95 且 draft_covers <= 0.02 才报漏点），压制误打回率 <= 10%；
  - JEV 关闭或 ``JevUnavailable`` 时有痕软降级：阶段一硬检（短路与 S-04 引文对账）100% 生效，
    绝不阻断交卷。

CLI 契约（README.md 3.4 冻结）：
    verify-answer --question-file <path> --draft-file <path> --read-docs <id1,id2,...> [--elapsed-seconds <float>]
退码：参数合法且文件可读一律 exit 0（含 PASS/PASS_BUDGET_CAP/REVISE_ONCE）；
参数缺失或输入文件不存在时输出 ``{"ok": false, "error": ...}`` 并 exit 1。
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from common import jev_client as jc
from common.jev_questions import (
    A3_QUESTION_SET_VERSION as QUESTION_SET_VERSION,
    A3_THRESHOLDS,
)

__all__ = [
    "QUESTION_SET_VERSION",
    "A3_THRESHOLDS",
    "BATCH_CHAR_BUDGET",
    "BUDGET_CAP_SECONDS",
    "verify_answer",
    "run_cli",
    "evaluate_a3_replay_samples",
]

BATCH_CHAR_BUDGET = 50_000

#: 48 分钟预算上限默认值；允许用环境变量覆盖（每次调用动态读取，便于灰度调整）。
BUDGET_CAP_SECONDS = 2880.0

#: 送入阶段二的可疑变形标识符上限 / 数值断言上限 / 合计上限。
MAX_SUSPICIOUS_IDENTIFIERS = 6
MAX_NUMERIC_CLAIMS = 4
MAX_LITERAL_CLAIMS = 8

#: 细粒度动态核对要素清单上限（彻底解决固定粗标签抓不出局部漏步骤的缺陷）。
MAX_CHECKLIST_ITEMS = 15
MAX_QUESTION_ITEMS = 8
MAX_LIST_ITEMS_PER_SECTION = 8

#: 反向错误否认检测句子数上限。
MAX_NEGATION_SENTENCES = 5

#: 多模态纯图节点 kind 集合（R5 看图场景：兼容 slides_index/images_index 与 _infer_node_kind 归一化 kind）。
VISUAL_NODE_KINDS = {
    "ppt_slide",
    "ppt_slides",
    "slide",
    "doc_page",
    "page",
    "doc_mixed",
    "doc_chapter",
    "image",
}

#: 每篇被引文档装入 JEV state 的完整章节数上限，以及全部被引文档章节总数上限。
SECTIONS_PER_DOC = 3
MAX_SECTIONS_TOTAL = 12

_STAGE = "A3"


def _budget_cap_seconds() -> float:
    """读取 48 分钟预算上限（环境变量 ``COSIGHTBOT_VERIFY_BUDGET_CAP_S`` 可覆盖）。"""
    raw = os.environ.get("COSIGHTBOT_VERIFY_BUDGET_CAP_S", "")
    try:
        return float(raw) if raw.strip() else BUDGET_CAP_SECONDS
    except ValueError:
        return BUDGET_CAP_SECONDS


# ---------------------------------------------------------------------------
# 正文区 / 末尾披露区智能切分（防"未读披露"被误判成 S-04 违规）
# ---------------------------------------------------------------------------

_DISCLOSURE_HEADER_RE = re.compile(
    r"^\s*(?:"
    r"(?:#{1,6}\s+)?\**\s*(?:候选与读取披露|披露区|披露|coverage\s*&\s*disclosure|disclosure)\s*[:：]?\s*\**\s*$"
    r"|"
    r"(?:#{1,6}\s+)?\**\s*(?:候选与读取披露|披露区|coverage\s*&\s*disclosure)\s*\**\s*[:：]\s*\S"
    r")",
    re.IGNORECASE,
)

#: 合规未读披露行：同一行含 [f###] 且声明"未读/未选/未精读"等字样时予以豁免。
_UNREAD_DECLINE_RE = re.compile(
    r"未读|未选|未精读|unread|not\s+read|skipped|omitted", re.IGNORECASE
)

#: 节点引用提取：排除 Markdown 图片 ``![...]`` 与超链接 ``[...](url)``。
_CITATION_RE = re.compile(r"(?<!\!)\[([fF][0-9a-zA-Z_]+)\](?!\()")


def _split_main_body_and_disclosure(draft: str) -> tuple[str, str]:
    """把答案草稿切分为 (主体结论区, 末尾披露区)。

    按 retrieval-discipline R9，答案末尾通常带 ``## 披露`` / ``### 候选与读取披露``
    / ``**披露区**`` / ``## Coverage & Disclosure`` 等区块，其中会合法列出
    "未选/未读候选 [f099]（理由）"。不切分会把诚实披露误判成 S-04 违规。
    """
    lines = draft.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if _DISCLOSURE_HEADER_RE.match(lines[i]):
            main_body = "\n".join(lines[:i]).strip("\n")
            disclosure = "\n".join(lines[i:])
            return main_body, disclosure
    return draft, ""


def _collect_citations(main_body: str, disclosure: str) -> list[str]:
    """汇总需要 S-04 对账的节点引用（去重保序）。

    主体结论区全部计账；披露区中"同一行含 [f###] 且声明未读/未选/未精读"的
    合规未读披露行豁免，其余披露行照常计账。
    """
    raw: list[str] = []
    raw.extend(_CITATION_RE.findall(main_body))
    for line in disclosure.splitlines():
        if _CITATION_RE.search(line) and _UNREAD_DECLINE_RE.search(line):
            continue  # 合规未读披露，豁免
        raw.extend(_CITATION_RE.findall(line))
    seen: set[str] = set()
    ordered: list[str] = []
    for ref in raw:
        if ref not in seen:
            seen.add(ref)
            ordered.append(ref)
    return ordered


# ---------------------------------------------------------------------------
# overview_resolver 惰性复用（节点 ID 归一化与元数据/原文定位）
# ---------------------------------------------------------------------------


def _load_overview_resolver():
    """惰性加载 overview_resolver（避免模块级循环导入）。"""
    try:
        from common import overview_resolver as _or  # noqa: PLC0415
    except ImportError:  # 直接以脚本方式调用时的兜底
        import overview_resolver as _or  # type: ignore[no-redef]  # noqa: PLC0415
    return _or


def _try_build_node_index(routes: list[dict] | None):
    if not routes:
        return None
    try:
        _or = _load_overview_resolver()
        node_index, _ = _or._build_global_node_index(routes)
        return node_index
    except Exception:  # noqa: BLE001 - 归一化失败时退化为 .lower() 兜底
        return None


def _normalize_id(raw: str, node_index) -> str:
    """节点 ID 归一化：优先 ``_lookup_global_id``，路由不存在时按 ``.lower()`` 兜底。"""
    if node_index is not None:
        try:
            resolved = _load_overview_resolver()._lookup_global_id(node_index, raw)
            if resolved:
                return resolved.lower()
        except Exception:  # noqa: BLE001
            pass
    return raw.lower()


# ---------------------------------------------------------------------------
# HTML 标签剥除（对齐 R2：原文带 <span>/<s>/<u> 而草稿按剥标签书写时子串仍可命中）
# ---------------------------------------------------------------------------

_HTML_TAG_RE = re.compile(
    r"</?(?:span|s|u|b|strong|i|em|mark|sub|sup)(?:\s[^>]*)?>", re.IGNORECASE
)


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text)


# ---------------------------------------------------------------------------
# 技术字面量抽取与精确子串预筛
# ---------------------------------------------------------------------------

_BACKTICK_RE = re.compile(r"`([^`\n]{2,80})`")
_HEADER_LIKE_RE = re.compile(r"(?<![A-Za-z0-9-])(?:X-[A-Za-z0-9-]+|Content-[A-Za-z-]+)")
_CLI_FLAG_RE = re.compile(r"(?<!\w)--[a-zA-Z0-9][a-zA-Z0-9_-]{2,}")
_SNAKE_KEY_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+){1,}\b")
_UPPER_CODE_RE = re.compile(r"\b[A-Z]{2,}[_-][A-Z0-9_-]{2,}\b")
_NODE_ID_TOKEN_RE = re.compile(r"^[fF]\d+$")

#: 反引号内容中出现的常见普通英文词（不作为技术字面量送核验）。
_COMMON_WORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is",
    "are", "was", "were", "be", "been", "not", "no", "yes", "true", "false",
    "none", "null", "nil", "n/a", "na", "ok", "okay", "note", "todo", "tbd",
    "example", "sample", "test", "demo", "draft", "final", "read", "unread",
    "see", "ref", "refs", "step", "steps", "item", "items", "list", "all",
}

#: 精确数值 + 单位/百分号/金额（关键数值断言短句识别）。
_NUM_UNIT_RE = re.compile(
    r"\d[\d,._]*\s*(?:%|percent|百分点|元|美元|万美元|亿元|万|亿|"
    r"ms|毫秒|μs|秒|min(?:ute)?s?|分钟|小时|hours?|hrs?|days?|天|weeks?|周|"
    r"months?|月|years?|年|GB|MB|KB|TB|GiB|MiB|KiB|bps|Kbps|Mbps|Gbps|"
    r"倍|人|个|条|篇|次|层|级|名|台|核|席)",
    re.IGNORECASE,
)

_SENT_SPLIT_RE = re.compile(r"[。！？!?；;\n]")

#: R9/R10 检索过程元记账短语（如"共扫描 12 篇候选、已精读 4 篇文档"）：剥除后再测数值单位，防误判为正文领域字面量。
_RETRIEVAL_META_NUMERIC_RE = re.compile(
    r"(?:已?精读|已?选读|未选?读|共?扫描|检索|命中|候选池?|参考|综合|依据)"
    r"[^。！？!?；;\n\d]{0,18}\d+\s*(?:篇|个|条)(?:候选|相关|已读)?(?:文档|节点|文件)?|"
    r"共\s*\d+\s*篇(?:已读|相关|候选)?文档"
)


def _extract_identifiers(main_body: str) -> list[str]:
    """从主体结论区抽取硬技术标识符（去重保序，过滤普通英文词与节点 ID）。"""
    seen: set[str] = set()
    ordered: list[str] = []

    def add(token: str) -> None:
        token = token.strip()
        if not token or len(token) < 2 or len(token) > 80:
            return
        if _NODE_ID_TOKEN_RE.match(token):
            return
        if token.lower() in _COMMON_WORDS:
            return
        if token not in seen:
            seen.add(token)
            ordered.append(token)

    for token in _BACKTICK_RE.findall(main_body):
        add(token)
    for token in _HEADER_LIKE_RE.findall(main_body):
        add(token)
    for token in _CLI_FLAG_RE.findall(main_body):
        add(token)
    for token in _UPPER_CODE_RE.findall(main_body):
        add(token)
    for token in _SNAKE_KEY_RE.findall(main_body):
        add(token)
    return ordered


def _extract_numeric_claims(main_body: str, cap: int = MAX_NUMERIC_CLAIMS) -> list[str]:
    """抽取包含精确数值 + 单位/百分号/金额的核心断言短句（上限 4 条，排除检索元记账句）。"""
    claims: list[str] = []
    seen: set[str] = set()
    for sentence in _SENT_SPLIT_RE.split(main_body):
        sentence = sentence.strip()
        if not sentence or len(sentence) < 4:
            continue
        cleaned = _RETRIEVAL_META_NUMERIC_RE.sub("", sentence)
        if not re.search(r"\d", cleaned):
            continue
        if not _NUM_UNIT_RE.search(cleaned):
            continue
        key = sentence[:120]
        if key in seen:
            continue
        seen.add(key)
        claims.append(sentence[:240])
        if len(claims) >= cap:
            break
    return claims


def _extract_negation_sentences(
    main_body: str, cap: int = MAX_NEGATION_SENTENCES
) -> list[str]:
    """扫描主体结论区中的否定声明句（"未找到/未提及/无相关规定"等，上限 5 句）。"""
    negation_word_re = re.compile(
        r"未找到|未提及|未说明|无相关规定|没有相关记录|查不到|未覆盖|"
        r"not\s+found|not\s+specified|not\s+mentioned|no\s+record|does\s+not\s+specify",
        re.IGNORECASE,
    )
    claims: list[str] = []
    seen: set[str] = set()
    for sentence in _SENT_SPLIT_RE.split(main_body):
        sentence = sentence.strip()
        if not sentence or len(sentence) < 4:
            continue
        if not negation_word_re.search(sentence):
            continue
        key = sentence[:120]
        if key in seen:
            continue
        seen.add(key)
        claims.append(sentence[:240])
        if len(claims) >= cap:
            break
    return claims


def _filter_suspicious_identifiers(
    identifiers: list[str], corpus: dict, cap: int = MAX_SUSPICIOUS_IDENTIFIERS
) -> list[str]:
    """Python 精确子串零成本放行：原文（或剥 HTML 副本）精确命中的标识符直接通过。

    仅返回原文完全未命中精确子串的"可疑变形标识符"（上限 6 个）。
    """
    suspicious: list[str] = []
    for token in identifiers:
        hit = False
        for entry in corpus.values():
            if token in entry["raw"] or token in entry["stripped"]:
                hit = True
                break
        if not hit:
            suspicious.append(token)
        if len(suspicious) >= cap:
            break
    return suspicious


# ---------------------------------------------------------------------------
# Markdown 章节切分与词汇重叠度选段（装填被引文档完整相关章节，严禁单行 snippet）
# ---------------------------------------------------------------------------

_HEADING_LINE_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_ASCII_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]*")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")


def _content_tokens(text: str) -> set[str]:
    """轻量分词：ASCII 词（含连字符/下划线）+ 中文二元组，用于重叠度排序。"""
    tokens: set[str] = set()
    for word in _ASCII_WORD_RE.findall(text):
        if len(word) >= 2:
            tokens.add(word.lower())
    for run in _CJK_RUN_RE.findall(text):
        if len(run) == 1:
            tokens.add(run)
        for i in range(len(run) - 1):
            tokens.add(run[i : i + 2])
    return tokens


def _split_markdown_sections(text: str) -> list[dict]:
    """把 Markdown 全文按标题行切分为完整章节（1-based 行号，含 heading 到下一 heading 前）。"""
    lines = text.splitlines()
    sections: list[dict] = []
    stack: list[tuple[int, str]] = []
    cur_start = 1
    cur_header = ""
    cur_title = ""
    cur_lines: list[str] = []

    def flush(end_line: int) -> None:
        if cur_lines and any(line.strip() for line in cur_lines):
            sections.append(
                {
                    "start": cur_start,
                    "end": end_line,
                    "header_path": cur_header,
                    "title": cur_title,
                    "text": "\n".join(cur_lines),
                }
            )

    for idx, line in enumerate(lines, start=1):
        matched = _HEADING_LINE_RE.match(line)
        if matched:
            flush(idx - 1)
            level = len(matched.group(1))
            title = matched.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            cur_start = idx
            cur_header = " > ".join(t for _, t in stack)
            cur_title = title
            cur_lines = [line]
        else:
            cur_lines.append(line)
    flush(len(lines))
    return sections


def _select_sections(
    corpus: dict,
    doc_ids: list[str],
    query_text: str,
    per_doc: int = SECTIONS_PER_DOC,
    overall: int = MAX_SECTIONS_TOTAL,
) -> list[dict]:
    """按与题面 + 草稿的词汇重叠度挑选被引文档的完整章节（带 doc_id/行号元数据）。"""
    query_tokens = _content_tokens(query_text)
    selected: list[dict] = []
    for gid in doc_ids:
        entry = corpus.get(gid)
        if not entry:
            continue
        sections = entry.setdefault("sections", _split_markdown_sections(entry["raw"]))
        if not sections:
            continue
        scored = []
        for sec in sections:
            sec_tokens = _content_tokens(sec["text"])
            score = len(query_tokens & sec_tokens)
            scored.append((score, sec))
        scored.sort(key=lambda pair: (-pair[0], pair[1]["start"]))
        picked = 0
        for score, sec in scored:
            if picked >= per_doc:
                break
            if score <= 0 and picked > 0:
                break  # 零重叠章节只在文档完全无重叠时兜底取首节
            if score <= 0 and any(s["doc_id"] == gid for s in selected):
                break
            selected.append(
                {
                    "doc_id": gid,
                    "rel_path": entry.get("rel_path", ""),
                    "header_path": sec["header_path"],
                    "start": sec["start"],
                    "end": sec["end"],
                    "text": sec["text"],
                    "overlap": score,
                }
            )
            picked += 1
        if len(selected) >= overall:
            break
    if not selected:
        # 全部零重叠时兜底：每篇取第一节，保证原文上下文仍可核验
        for gid in doc_ids:
            entry = corpus.get(gid)
            if not entry:
                continue
            sections = entry.setdefault("sections", _split_markdown_sections(entry["raw"]))
            if sections:
                sec = sections[0]
                selected.append(
                    {
                        "doc_id": gid,
                        "rel_path": entry.get("rel_path", ""),
                        "header_path": sec["header_path"],
                        "start": sec["start"],
                        "end": sec["end"],
                        "text": sec["text"],
                        "overlap": 0,
                    }
                )
            if len(selected) >= overall:
                break
    return selected[:overall]


# ---------------------------------------------------------------------------
# 细粒度动态核对要素清单构造（题面拆解 + 被引章节列表项原子化，上限 15 项）
# ---------------------------------------------------------------------------

_ORDERED_STEP_RE = re.compile(r"^\s*\d+\.\s+\*{0,2}([^*\n:：]{3,80})")
_BOLD_BULLET_RE = re.compile(r"^\s*[-*+]\s+\*\*([^*\n:：]{3,80})\*\*")
_NUM_ITEM_MARK_RE = re.compile(r"(?:^|\s)(?:(?:[（(]\d{1,2}[）)])|(?:\d{1,2}[.、]))\s*")


def _split_question_items(question: str, cap: int = MAX_QUESTION_ITEMS) -> list[str]:
    """把问题按问号/分号/显式序号拆分为独立子问点（上限 8 项，去重保序）。"""
    subs: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        text = re.sub(r"\s+", " ", text).strip(" ：:，,。")
        if len(text) < 2:
            return
        text = text[:160]
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        subs.append(text)

    for part in re.split(r"[?？;；\n]", question):
        part = part.strip()
        if not part:
            continue
        pieces = [p for p in _NUM_ITEM_MARK_RE.split(part) if p and p.strip()]
        if len(pieces) <= 1:
            add(part)
        else:
            for piece in pieces:
                add(piece)
        if len(subs) >= cap:
            break
    return subs[:cap]


def _extract_list_items(section: dict, doc_id: str, cap: int = MAX_LIST_ITEMS_PER_SECTION) -> list[dict]:
    """从单个章节提取有序步骤首句与加粗键无序要点行（列表项原子要素）。"""
    items: list[dict] = []
    seen: set[str] = set()
    line_range = f"L{section['start']}-L{section['end']}"
    for line in section["text"].splitlines():
        matched = _ORDERED_STEP_RE.match(line)
        if not matched:
            matched = _BOLD_BULLET_RE.match(line)
        if not matched:
            continue
        text = re.sub(r"\s+", " ", matched.group(1)).strip(" ：:，,。")
        if len(text) < 3:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append({"text": text, "doc_id": doc_id, "line_range": line_range})
        if len(items) >= cap:
            break
    return items


def _build_checklist(
    question: str,
    main_body: str,
    sections: list[dict],
    cap: int = MAX_CHECKLIST_ITEMS,
) -> list[dict]:
    """合并题面子问点拆解与被引权威章节列表项两路确定性要素（去重后最多 15 项）。"""
    items: list[dict] = []
    seen: set[str] = set()

    def add(item: dict) -> None:
        key = re.sub(r"\s+", " ", item["text"]).strip().lower()
        if not key or key in seen:
            return
        seen.add(key)
        items.append(item)

    for sub in _split_question_items(question):
        add({"key": "", "text": sub, "doc_id": None, "line_range": None})
    # 被引章节：每个 doc_id 取重叠度最高的章节提取列表项
    top_by_doc: dict[str, dict] = {}
    for sec in sections:
        gid = sec["doc_id"]
        cur = top_by_doc.get(gid)
        if cur is None or sec["overlap"] > cur["overlap"]:
            top_by_doc[gid] = sec
    for gid in sorted(top_by_doc):
        for item in _extract_list_items(top_by_doc[gid], gid):
            if len(items) >= cap:
                break
            item["key"] = ""
            add(item)
        if len(items) >= cap:
            break
    for idx, item in enumerate(items):
        item["key"] = f"item_{idx}"
    return items[:cap]


# ---------------------------------------------------------------------------
# 阶段二：内网 JEV 正反双向并行核验
# ---------------------------------------------------------------------------


def _render_section(sec: dict) -> dict:
    """把章节渲染成带溯源头标的 state 条目：[f042 | rel_path | header_path | Ls-Le]。"""
    head = f"[{sec['doc_id']} | {sec.get('rel_path', '')} | {sec.get('header_path', '')} | L{sec['start']}-L{sec['end']}]"
    return {
        "doc_id": sec["doc_id"],
        "rel_path": sec.get("rel_path", ""),
        "header_path": sec.get("header_path", ""),
        "line_range": f"L{sec['start']}-L{sec['end']}",
        "text": f"{head}\n{sec['text']}",
    }


_SOURCE_HAS_CRITERIA = {
    "true": "已读文档原文明确规定了该项针对当前问题的有效要求/步骤/要点",
    "false": "原文未规定该项，或仅出现在已作废草案、示例或纯反例中",
}
_DRAFT_COVERS_CRITERIA = {
    "true": "草稿已实质写出或回答了该要点（允许合理同义转换）",
    "false": "草稿正文完全未写出该要点/步骤/条件",
}
_CONTRA_NEG_CRITERIA = {
    "true": "原文已明确给出被草稿声称未找到的具体信息或规定，草稿的错误否认成立",
    "false": "原文确实未给出该项信息，草稿的否认成立",
}
_LITERAL_SUP_CRITERIA = {
    "true": "原文直接支持该字面量/数值断言（拼写一致、数值与对象绑定准确）",
    "false": "原文不支持该断言：存在拼写变形、私自换算或跨对象张冠李戴",
}


def _batch_question_set(
    items: list[dict], negations: list[str], literal_claims: list[str]
) -> dict:
    """构造单批次全量并行问题集（一次请求内所有问题共享 state 并行求值）。"""
    questions: dict = {}
    for item in items:
        key = item["key"]
        questions[f"source_has_{key}"] = {
            "type": "noul",
            "instructions": (
                f"state.cited_sections 的已读文档原文中，是否明确规定了针对当前问题的"
                f"有效要求/步骤/要点「{item['text']}」（且不属于已作废草案或纯反例）？"
            ),
            "criteria": _SOURCE_HAS_CRITERIA,
        }
        questions[f"draft_covers_{key}"] = {
            "type": "noul",
            "instructions": (
                f"state.draft_answer 的正文中是否已经实质写出或回答了「{item['text']}」"
                f"这一要点/步骤/条件（表述措辞允许合理同义转换，只要核心事实或动作已包含即判 true）？"
            ),
            "criteria": _DRAFT_COVERS_CRITERIA,
        }
    for idx, claim in enumerate(negations):
        questions[f"contradicts_not_found_{idx}"] = {
            "type": "noul",
            "instructions": (
                f"草稿句子断言「{claim}」某信息未找到或未规定；请核对 state.cited_sections 原文："
                f"原文中是否实际上已经明确给出了该项被声称未找到的具体信息或规定？"
            ),
            "criteria": _CONTRA_NEG_CRITERIA,
        }
    for idx, claim in enumerate(literal_claims):
        questions[f"literal_supported_{idx}"] = {
            "type": "noul",
            "instructions": (
                f"state.cited_sections 的原文是否直接支持草稿中的技术字面量或数值断言「{claim}」"
                f"（要求标识符拼写一致、数值及单位与所修饰的目标对象/区域/环境准确对应，"
                f"不存在拼写变形、私自换算或跨对象张冠李戴）？"
            ),
            "criteria": _LITERAL_SUP_CRITERIA,
        }
    return questions


_BATCH_SUFFIX_RE = re.compile(r"__b\d+$")


def _batch_key(base: str, batch_index: int, batch_count: int) -> str:
    """多批次时给问题键名追加批次后缀，避免跨批键名冲突；单批保持裸名。"""
    if batch_count <= 1:
        return base
    return f"{base}__b{batch_index}"


def _aggregate_batch_probs(answers: dict) -> dict[str, float | None]:
    """跨批聚合：剥掉批次后缀后按基础问题名取 max（None 不得覆盖已得概率）。"""
    probs: dict[str, float | None] = {}
    for key, answer in answers.items():
        base = _BATCH_SUFFIX_RE.sub("", key)
        prob = jc.probability(answer)
        current = probs.get(base)
        if prob is None:
            probs.setdefault(base, None)
        elif current is None:
            probs[base] = prob
        else:
            probs[base] = max(current, prob)
    return probs


def _run_stage_two(
    *,
    question: str,
    draft: str,
    corpus: dict,
    cited_ids: list[str],
    items: list[dict],
    negations: list[str],
    literal_claims: list[str],
    has_visual_docs: bool,
    jev_answers: dict | None = None,
) -> dict:
    """阶段二执行器：装填被引文档完整相关章节 -> 拆批并发 JEV -> 跨批聚合 -> 触发判定。

    返回 {"issues": [...], "visual_notes": [...], "jev": <audit/diag>}。
    """
    empty = {"issues": [], "visual_notes": [], "jev": {}}
    sections = _select_sections(corpus, cited_ids, f"{question}\n{draft}")
    if not sections or (not items and not negations and not literal_claims):
        empty["jev"] = {
            "skipped": True,
            "stage": _STAGE,
            "reason": "无可核验章节或无可核验问题",
        }
        return empty

    if jev_answers is not None:
        # 离线回放 / 单测注入模式：不发起网络请求，直接按基础问题名取注入概率。
        base_names = [f"source_has_{it['key']}" for it in items]
        base_names += [f"draft_covers_{it['key']}" for it in items]
        base_names += [f"contradicts_not_found_{i}" for i in range(len(negations))]
        base_names += [f"literal_supported_{i}" for i in range(len(literal_claims))]
        probs = {name: jev_answers.get(name) for name in base_names}
        audit = {"injected": True, "question_set_version": QUESTION_SET_VERSION, "stage": _STAGE}
    else:
        base_questions = _batch_question_set(items, negations, literal_claims)
        questions_chars = len(
            json.dumps(jc.append_anti_injection(base_questions), ensure_ascii=False)
        )
        base_chars = min(
            BATCH_CHAR_BUDGET - 4000,
            len(question) + len(draft) + questions_chars + 400,
        )
        batches = jc.plan_batches(
            sections,
            budget_chars=BATCH_CHAR_BUDGET,
            base_state_chars=base_chars,
            per_item_chars=lambda sec: len(json.dumps(_render_section(sec), ensure_ascii=False)),
        )
        batch_count = len(batches)
        batch_pairs: list[tuple[dict, dict]] = []
        for batch_index, batch_sections in enumerate(batches, start=1):
            batch_state = {
                "question": question,
                "draft_answer": draft,
                "cited_sections": [_render_section(sec) for sec in batch_sections],
            }
            batch_questions = {
                _batch_key(name, batch_index, batch_count): spec
                for name, spec in base_questions.items()
            }
            batch_pairs.append((batch_state, batch_questions))
        response = jc.ask_batches_concurrent(
            batch_pairs, stage=_STAGE, question_set_version=QUESTION_SET_VERSION
        )
        probs = _aggregate_batch_probs(response.answers)
        audit = dict(response.audit)
        audit["question_set_version"] = QUESTION_SET_VERSION

    thresholds = A3_THRESHOLDS
    issues: list[dict] = []
    visual_notes: list[str] = []

    for item in items:
        p_source = probs.get(f"source_has_{item['key']}")
        p_draft = probs.get(f"draft_covers_{item['key']}")
        if (
            p_source is not None
            and p_source >= thresholds["source_has_min"]
            and p_draft is not None
            and p_draft <= thresholds["draft_covers_max"]
        ):
            doc_id = item.get("doc_id")
            line_range = item.get("line_range")
            loc = (
                f"（[{doc_id}]{' ' + line_range if line_range else ''}）"
                if doc_id
                else ""
            )
            issues.append(
                {
                    "type": "MISSING_POINT",
                    "severity": "hard",
                    "item": item["text"],
                    "doc_id": doc_id,
                    "line_range": line_range,
                    "p_source": p_source,
                    "p_draft": p_draft,
                    "detail": (
                        f"已读原文{loc}中存在有效要点"
                        f"「{item['text']}」，但答案草稿未实质写出；请定向补写后直接输出"
                    ),
                }
            )
    for idx, claim in enumerate(negations):
        p_contra = probs.get(f"contradicts_not_found_{idx}")
        if p_contra is not None and p_contra >= thresholds["contradicts_neg_min"]:
            issues.append(
                {
                    "type": "FALSE_NEGATION",
                    "severity": "hard",
                    "claim": claim,
                    "p_contradicts": p_contra,
                    "detail": (
                        f"答案声称「{claim}」但已读原文实际已明确给出该项信息，"
                        f"请修正错误否认或改写为引用原文"
                    ),
                }
            )
    for idx, claim in enumerate(literal_claims):
        p_sup = probs.get(f"literal_supported_{idx}")
        if p_sup is None:
            continue  # 缺失态按 uncertain 保守处理，不触发
        if p_sup <= thresholds["literal_supported_max"]:
            if has_visual_docs:
                visual_notes.append(
                    f"可疑字面量「{claim}」未获已读 .md 原文支持（p_supported={p_sup}），"
                    f"但本轮含多模态看图节点，图片内文字可能未入 .md 文本，请人工复核，不强制打回"
                )
            else:
                issues.append(
                    {
                        "type": "UNSUPPORTED_LITERAL",
                        "severity": "hard",
                        "claim": claim,
                        "p_supported": p_sup,
                        "detail": (
                            f"已读原文不支持草稿中的字面量/数值断言「{claim}」"
                            f"（疑似拼写变形、单位换算错误或跨对象张冠李戴），请对照原文修正"
                        ),
                    }
                )
    return {"issues": issues, "visual_notes": visual_notes, "jev": audit}


# ---------------------------------------------------------------------------
# 语料装载（read-docs 元数据与原文全文，含剥 HTML 副本）
# ---------------------------------------------------------------------------


def _load_corpus(
    read_docs: list[str],
    routes: list[dict] | None,
    read_doc_metas: list[dict] | None,
    doc_texts: dict[str, str] | None,
) -> tuple[list[dict], dict]:
    """返回 (metas, corpus)。corpus: norm_gid -> {raw, stripped, rel_path}。"""
    metas: list[dict] = []
    corpus: dict[str, dict] = {}

    if doc_texts:
        for gid, text in doc_texts.items():
            norm = gid.lower()
            corpus[norm] = {"raw": text, "stripped": _strip_html(text), "rel_path": ""}
        metas = [dict(m) for m in (read_doc_metas or [])]
        return metas, corpus

    if read_doc_metas is not None:
        metas = list(read_doc_metas)

    if not routes or not read_docs:
        return metas, corpus

    try:
        _or = _load_overview_resolver()
    except Exception:  # noqa: BLE001 - 解析器不可用时退化为纯 Python 硬检
        return metas, corpus

    for gid in read_docs:
        try:
            meta = _or._resolve_node_id_meta(gid, routes)
        except Exception:  # noqa: BLE001
            continue
        if not meta.get("ok"):
            continue
        metas.append(meta)
        norm = str(meta["node_id"]).lower()
        try:
            raw = Path(meta["abs_path"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        corpus[norm] = {
            "raw": raw,
            "stripped": _strip_html(raw),
            "rel_path": str(meta.get("rel_path", "")),
        }
    return metas, corpus


def _has_visual_docs(metas: list[dict]) -> bool:
    """关键保护：含 PPT/扫描页/图文混排节点时，图片文字未必存在于 .md 文本。"""
    for meta in metas:
        if str(meta.get("kind", "")) in VISUAL_NODE_KINDS:
            return True
        if (
            meta.get("images")
            or meta.get("image")
            or meta.get("image_relpath")
            or meta.get("slides")
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# 主入口：两阶段核验
# ---------------------------------------------------------------------------


def verify_answer(
    question: str,
    draft: str,
    read_docs: list[str],
    elapsed_seconds: float = 0.0,
    *,
    routes: list[dict] | None = None,
    read_doc_metas: list[dict] | None = None,
    doc_texts: dict[str, str] | None = None,
    jev_answers: dict | None = None,
) -> dict:
    """verify-answer 核心入口：返回结构化核验结论 dict（绝不抛异常阻断交卷语义）。"""
    cap_seconds = _budget_cap_seconds()
    if float(elapsed_seconds) >= cap_seconds:
        return {
            "ok": True,
            "action": "PASS_BUDGET_CAP",
            "issues": [],
            "max_revisions": 0,
            "reason": (
                f"elapsed_seconds >= {cap_seconds:g}s, approaching 50m deadline; "
                "skip verification and submit immediately"
            ),
            "elapsed_seconds": float(elapsed_seconds),
        }

    read_docs = [rid.strip() for rid in (read_docs or []) if rid and rid.strip()]
    main_body, disclosure = _split_main_body_and_disclosure(draft)
    citations = _collect_citations(main_body, disclosure)

    node_index = _try_build_node_index(routes)
    read_norm = {_normalize_id(rid, node_index) for rid in read_docs}

    issues: list[dict] = []
    for ref in citations:
        if _normalize_id(ref, node_index) not in read_norm:
            issues.append(
                {
                    "type": "UNREAD_CITATION",
                    "severity": "hard",
                    "citation": ref,
                    "detail": (
                        f"答案主体引用了未在 --read-docs 列表中的节点 [{ref}]（违反 S-04），"
                        f"请删除无依据引用或先调用 read-doc 实读核实"
                    ),
                }
            )

    metas, corpus = _load_corpus(read_docs, routes, read_doc_metas, doc_texts)
    has_visual = _has_visual_docs(metas)

    identifiers = _extract_identifiers(main_body)
    suspicious = _filter_suspicious_identifiers(identifiers, corpus)
    numeric_claims = _extract_numeric_claims(main_body)
    literal_claims = (suspicious + numeric_claims)[:MAX_LITERAL_CLAIMS]

    cited_norm = [_normalize_id(ref, node_index) for ref in citations]
    section_doc_ids = [gid for gid in cited_norm if gid in corpus]
    if not section_doc_ids:
        section_doc_ids = [gid for gid in ( _normalize_id(r, node_index) for r in read_docs ) if gid in corpus][:5]
    sections = _select_sections(corpus, section_doc_ids, f"{question}\n{main_body}")
    checklist = _build_checklist(question, main_body, sections)
    negations = _extract_negation_sentences(main_body)

    stage_draft = main_body if main_body.strip() else draft
    stage_two: dict = {"issues": [], "visual_notes": [], "jev": {}}
    if jev_answers is not None:
        # 注入模式（离线回放/单测）：绕过分阶段开关，直接按注入概率判定。
        stage_two = _run_stage_two(
            question=question,
            draft=stage_draft,
            corpus=corpus,
            cited_ids=section_doc_ids,
            items=checklist,
            negations=negations,
            literal_claims=literal_claims,
            has_visual_docs=has_visual,
            jev_answers=jev_answers,
        )
        jev_meta = stage_two["jev"]
    elif not jc.is_stage_enabled(_STAGE):
        # 有痕软降级：阶段一 Python 硬检已 100% 生效，绝不阻断交卷。
        jev_meta = jc.build_degraded_diag(
            _STAGE, "stage A3 disabled by COSIGHTBOT_JEV_ENABLED/COSIGHTBOT_JEV_STAGES"
        )
    else:
        try:
            stage_two = _run_stage_two(
                question=question,
                draft=stage_draft,
                corpus=corpus,
                cited_ids=section_doc_ids,
                items=checklist,
                negations=negations,
                literal_claims=literal_claims,
                has_visual_docs=has_visual,
            )
            jev_meta = stage_two["jev"]
        except Exception as exc:  # noqa: BLE001 - JevUnavailable 与意外异常均有痕软降级
            jev_meta = jc.build_degraded_diag(_STAGE, exc)

    all_issues = issues + stage_two["issues"]
    if all_issues:
        action = "REVISE_ONCE"
        max_revisions = 1
        reason = (
            f"检出 {len(all_issues)} 个硬性问题，请按 issues 定向修订 1 次后直接输出，"
            f"严禁第二次调用 verify-answer"
        )
    else:
        action = "PASS"
        max_revisions = 0
        reason = "未检出硬性问题，草稿可直接作为最终答案输出"

    result: dict = {
        "ok": True,
        "action": action,
        "issues": all_issues,
        "max_revisions": max_revisions,
        "reason": reason,
        "elapsed_seconds": float(elapsed_seconds),
        "read_docs": sorted(read_norm),
        "citations": citations,
        "checklist": [
            {"text": it["text"], "doc_id": it.get("doc_id"), "line_range": it.get("line_range")}
            for it in checklist
        ],
        "literal_claims": literal_claims,
        "negation_claims": negations,
        "visual_docs": has_visual,
        "visual_check_notes": stage_two["visual_notes"],
        "jev": jev_meta,
    }
    return result


# ---------------------------------------------------------------------------
# CLI 薄入口（overview_resolver.main() 的 verify-answer 分支转发到这里）
# ---------------------------------------------------------------------------


def run_cli(args, checked: list[dict]) -> int:
    """overview_resolver 的 verify-answer 子命令薄转发入口。

    退码约定（S-05）：参数合法且文件可读一律 exit 0；参数缺失或文件不存在 exit 1。
    """
    question_path = getattr(args, "question_file", None)
    draft_path = getattr(args, "draft_file", None)
    read_docs_raw = getattr(args, "read_docs", None)
    if not question_path or not draft_path or read_docs_raw is None:
        print(
            json.dumps(
                {"ok": False, "error": "missing required args: --question-file/--draft-file/--read-docs"},
                ensure_ascii=False,
            )
        )
        return 1
    try:
        elapsed_seconds = float(getattr(args, "elapsed_seconds", 0.0) or 0.0)
    except (TypeError, ValueError):
        elapsed_seconds = 0.0
    try:
        question = Path(question_path).read_text(encoding="utf-8", errors="replace")
        draft = Path(draft_path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(json.dumps({"ok": False, "error": f"input file unreadable: {exc}"}, ensure_ascii=False))
        return 1
    read_docs = [token.strip() for token in str(read_docs_raw).split(",") if token.strip()]
    result = verify_answer(
        question=question,
        draft=draft,
        read_docs=read_docs,
        elapsed_seconds=elapsed_seconds,
        routes=checked,
    )
    if sys.stdout.encoding is not None and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------------------
# 阶段 0 离线回放辅助：19 道 L4 错题检出率（目标 >= 60%）与 60 道对题误报率（门禁 <= 10%）
# ---------------------------------------------------------------------------


def evaluate_a3_replay_samples(samples: list[dict]) -> dict:
    """对离线快照样本批量回放 A3 核验，测算检出率与误打回率。

    每个 sample 字段：
      - ``question`` / ``draft`` / ``read_docs`` / ``elapsed_seconds``：核验输入；
      - ``doc_texts`` / ``read_doc_metas`` / ``routes``：可选语料注入（离线快照回放用）；
      - ``jev_answers``：可选注入概率表（基础问题名 -> 概率或 None），提供后不发起网络请求；
      - ``expected_issue_types``：错题样本声明的期望问题类型（如 ["MISSING_POINT"]）；
        对题样本留空。

    返回汇总：检出率 ``detection_rate``（错题池）与误打回率 ``false_positive_rate``（对题池）。
    """
    total = len(samples)
    detected = 0
    missed = 0
    false_positives = 0
    results: list[dict] = []
    for idx, sample in enumerate(samples):
        result = verify_answer(
            question=str(sample.get("question", "")),
            draft=str(sample.get("draft", "")),
            read_docs=list(sample.get("read_docs") or []),
            elapsed_seconds=float(sample.get("elapsed_seconds") or 0.0),
            routes=sample.get("routes"),
            read_doc_metas=sample.get("read_doc_metas"),
            doc_texts=sample.get("doc_texts"),
            jev_answers=sample.get("jev_answers"),
        )
        action = str(result.get("action"))
        got_types = sorted({issue.get("type") for issue in result.get("issues", [])})
        expected_types = sorted(set(sample.get("expected_issue_types") or []))
        if expected_types:
            hit = action == "REVISE_ONCE" and bool(set(got_types) & set(expected_types))
            if hit:
                detected += 1
            else:
                missed += 1
        elif action == "REVISE_ONCE":
            false_positives += 1
        results.append(
            {"index": idx, "action": action, "issue_types": got_types, "expected_issue_types": expected_types}
        )
    wrong_pool = detected + missed
    correct_pool = total - wrong_pool
    return {
        "total": total,
        "wrong_pool": wrong_pool,
        "correct_pool": correct_pool,
        "detected": detected,
        "missed": missed,
        "false_positives": false_positives,
        "detection_rate": round(detected / wrong_pool, 4) if wrong_pool else None,
        "false_positive_rate": round(false_positives / correct_pool, 4) if correct_pool else None,
        "results": results,
    }
