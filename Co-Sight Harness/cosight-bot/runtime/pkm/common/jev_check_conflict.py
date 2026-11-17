#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T6 JEV-A2：R11 多文档冲突维度覆盖矩阵与主来源确定性裁决（check-conflict 子命令）。

对应主方案节点 ◆ JEV-A2（Step 2.5 Agent 辅助层）。解决 L4（已读全金标仍答错）中
最顽固的失分源：多篇已读文档给出冲突数值/日期/SLA 时的主次采信错误，以及把
draft / illustrative / example defaults 非正式数值混入主结论。

职责边界（严守）：
- JEV 只判「字面属性」：逐维度显式覆盖、5 档权威档位、显式 supersedes 声明、细节完整度；
- 日期先后一律由本模块的 Python 确定性正则解析器处理，**绝不让 JEV 比日期**；
- R11 三步裁决在 Python 中确定性执行，与 `.claude/rules/retrieval-discipline.md`
  第四节 R11《冲突证据采信》逐条同构；
- 判为草案/示例默认值的文档输出 DISCLOSURE_ONLY 硬隔离警告；
- 纯只读（S-01）：仅读 pre-processed 原文与调用内网 JEV，不写任何索引；
- JEV 输出的概率与档位绝不直接作为知识事实写入用户答案（S-03），本命令输出
  只是裁决辅助信号，最终事实仍须来自 read-doc 实读原文。

CLI（与 tasks/README.md 第 3.4 节冻结签名一致）：
    python overview_resolver.py --agent-id main check-conflict \
      --question-json '{"question": "...", "dimensions": ["...", "..."]}' \
      --doc-ids f014,f052,f109
    # --question-json 也可传本地 JSON 文件路径（防复杂引号转义问题）
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path

from common.jev_client import (
    JevUnavailable,
    ask_batches_concurrent,
    build_degraded_diag,
    choice_winner,
    is_jev_enabled,
    is_stage_enabled,
    plan_batches,
    probability,
)
from common.jev_questions import (
    A2_QUESTION_SET_VERSION as QUESTION_SET_VERSION,
    A2_THRESHOLDS,
)
from common.logging_setup import log_event

logger = logging.getLogger("jev_check_conflict")

STAGE = "A2"

AUTHORITY_TIERS = (
    "signed_or_published",   # 正式发布/已签署：带 Published/Final/Approved/Signed 状态或正式手册/制度/SLA/PRD
    "approved_decision",     # 已批复决议：已批准的 ADR、架构决议或变更审批单
    "informal_note",         # 非正式沟通记录：邮件、会议纪要、Slack/群聊公告、周报或状态未明普通文档
    "draft_or_proposal",     # 未定稿草案：显式标有 Draft/RFC/WIP/Initial Proposal/征求意见稿/待审批提案
    "illustrative_example",  # 示例默认值：显式标有 illustrative/example defaults/sample/mock/仅供参考示例
)
AUTHORITY_RANK = {
    "signed_or_published": 5,
    "approved_decision": 4,
    "informal_note": 3,
    "draft_or_proposal": 2,
    "illustrative_example": 1,
}
NON_AUTHORITATIVE_TIERS = frozenset({"draft_or_proposal", "illustrative_example"})

AUTHORITY_CRITERIA = {
    "signed_or_published": (
        "正式发布/已签署：带 Published/Final/Approved/Signed 状态的正式手册、制度、"
        "SLA、PRD 或生产 Runbook（有 sign-off/版本号/发布栏更佳）"
    ),
    "approved_decision": (
        "已批复决议：明确标有 Approved/Accepted 状态的架构决议（ADR）或已批准的变更审批单"
    ),
    "informal_note": (
        "非正式沟通记录：邮件往来、会议纪要发言、Slack/群聊公告、周报，"
        "或未标注任何状态、无法判断正式性的普通文档"
    ),
    "draft_or_proposal": (
        "未定稿草案：显式标有 Draft/RFC/WIP/Initial Proposal/征求意见稿/待审批提案/讨论稿"
    ),
    "illustrative_example": (
        "示例默认值：明确说明为 illustrative/example defaults/sample config/mock/"
        "placeholder/仅供参考示例的参考片段"
    ),
}

DISCLOSURE_ONLY_WARNING = (
    "DISCLOSURE_ONLY: 严禁将其数值作为主结论并列陈述，"
    "仅可在文末披露区用一句话说明存在未生效草案/示例值"
)

TIE_GUIDANCE = (
    "两篇候选权威状态与证据完整度相同且均无显式 supersedes 声明；按 R11 严禁直接假定"
    "新日期覆盖旧日期，请核对原文内部自洽性，若仍无法区分则并列呈现冲突值并说明缺乏"
    "权威替代依据（同时列出已解析日期供参考）。"
)

# ---- 文档证据三段式提取常量 ----
EVIDENCE_CHAR_CAP = 6000   # 单篇证据总字符上限（保住文首/文末签署与日期栏）
HEAD_LINES = 60            # 头部元数据与导言区固定保留行数
HEAD_CHAR_CAP = 1500
TAIL_LINES = 35            # 尾部签署与变更记录区固定保留行数
TAIL_CHAR_CAP = 800
MIDDLE_BUDGET = EVIDENCE_CHAR_CAP - HEAD_CHAR_CAP - TAIL_CHAR_CAP  # 3700

# ---- 输入规模上限 ----
MAX_DIMENSIONS = 10
MIN_DOCS = 2
MAX_DOCS = 15

# ---- JEV 单批字符预算（07 手册：50K 分批规范，按单篇文档粒度切批） ----
BATCH_BUDGET_CHARS = 50000
_BATCH_BASE_STATE_CHARS = 2000
_PER_QUESTION_CHARS = 320

# ---- 确定性草案/示例词（Python 正则，用于低置信回退与降级提示，绝不依赖 JEV） ----
_DRAFT_WORD_RE = re.compile(
    r"(?i)\b(?:draft|drafts|drafting|wip|rfc|proposed|proposal|initial\s+proposal|draft\s+rfc)\b"
    r"|草案|征求意见稿|待审批|讨论稿|未定稿"
)
_EXAMPLE_WORD_RE = re.compile(
    r"(?i)\b(?:illustrative|example\s+defaults|example\s+values|sample\s+config|sample|mock|placeholder)\b"
    r"|示例默认值|仅供参考示例|示例值"
)

# ---- 确定性日期解析（优先级 1：正文显式生效/发布字段） ----
_DATE_FIELD_RE = re.compile(
    r"(?i)(?:effective(?:\s+date)?|published(?:\s+on|\s+date)?|approved(?:\s+on|\s+date)?"
    r"|last\s+updated|date|生效日期|发布日期|批准日期|更新日期)\s*[:：]\s*("
    r"\d{4}[-/]\d{1,2}[-/]\d{1,2}"
    r"|\d{4}年\d{1,2}月\d{1,2}日"
    r"|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}\s+[A-Za-z]{3,9}\.?,?\s+\d{4}"
    r")"
)
# 优先级 2：文档标题或文件名日期前缀
_FILENAME_DATE_RE = re.compile(
    r"(20\d{2})[-_/](0[1-9]|1[0-2])[-_/](0[1-9]|[12]\d|3[01])"
)
# 优先级 3：文首/文末独立 ISO 日期
_ISO_DATE_RE = _FILENAME_DATE_RE

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6,
    "jul": 7, "july": 7, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_MONTH_NAME_RE = re.compile(r"^([A-Za-z]{3,9})\.?$")


# ---------------------------------------------------------------------------
# Python 确定性日期解析器（绝不让 JEV 比日期）
# ---------------------------------------------------------------------------


def _valid_date(year: int, month: int, day: int) -> date | None:
    """校验 1990<=year<=2099 且为合法日历日期；非法（如 2026-02-30）返回 None。"""
    if not (1990 <= year <= 2099):
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _parse_date_token(token: str) -> date | None:
    """解析单枚日期片段为 date；不合法返回 None（安全忽略，继续扫描下一候选）。"""
    token = token.strip()
    m = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", token)
    if m:
        return _valid_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日", token)
    if m:
        return _valid_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.fullmatch(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})", token)
    if m:
        month = _MONTHS.get(_MONTH_NAME_RE.match(m.group(1)).group(1).lower())  # type: ignore[union-attr]
        if month:
            return _valid_date(int(m.group(3)), month, int(m.group(2)))
        return None
    m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})", token)
    if m:
        month = _MONTHS.get(_MONTH_NAME_RE.match(m.group(2)).group(1).lower())  # type: ignore[union-attr]
        if month:
            return _valid_date(int(m.group(3)), month, int(m.group(1)))
        return None
    return None


def _iso(date_obj: date | None) -> str | None:
    return date_obj.isoformat() if date_obj else None


def extract_canonical_date(rel_path: str, title: str, full_text: str) -> dict:
    """从完整文档全文/标题/文件名按三级优先级解析标准化日期。

    优先级 1（header_field）：正文显式生效/发布字段（Effective Date / Published /
        Approved / 生效日期 / 发布日期 / 批准日期 / 更新日期等），支持
        YYYY-MM-DD、YYYY/MM/DD、YYYY年M月D日、Nov 27, 2026 / November 27, 2026 / 27 Nov 2026；
    优先级 2（filename）：文档标题或文件名中的 `YYYY-MM-DD` / `YYYY_MM_DD` / `YYYY/MM/DD` 前缀；
    优先级 3（body_edge）：文首 40 行与文末 30 行中的首个合法独立 ISO 日期。

    Returns:
        {"iso_date": "YYYY-MM-DD" | None, "date_source": "header_field"|"filename"|"body_edge"|None}
    """
    # 优先级 1：正文显式生效/发布字段
    for m in _DATE_FIELD_RE.finditer(full_text):
        parsed = _parse_date_token(m.group(1))
        if parsed:
            return {"iso_date": _iso(parsed), "date_source": "header_field"}

    # 优先级 2：文档标题或文件名日期前缀
    for text in (Path(rel_path).name or "", title or ""):
        m = _FILENAME_DATE_RE.search(text)
        if m:
            parsed = _valid_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if parsed:
                return {"iso_date": _iso(parsed), "date_source": "filename"}

    # 优先级 3：文首/文末独立 ISO 日期
    lines = full_text.splitlines()
    for line in list(lines[:40]) + list(lines[-30:]):
        m = _ISO_DATE_RE.search(line)
        if m:
            parsed = _valid_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if parsed:
                return {"iso_date": _iso(parsed), "date_source": "body_edge"}

    return {"iso_date": None, "date_source": None}


def deterministic_tier_hints(title: str, full_text: str) -> dict:
    """确定性正则命中标题/正文中的草稿词与示例默认值词（不依赖 JEV）。"""
    combined = f"{title or ''}\n{full_text or ''}"
    return {
        "draft": bool(_DRAFT_WORD_RE.search(combined)),
        "example": bool(_EXAMPLE_WORD_RE.search(combined)),
    }


# ---------------------------------------------------------------------------
# 文档原文三段式保真提取（上限 6,000 字/篇，保住文首/文末签署与日期栏）
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^#{1,6}\s")
_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$")
_TERM_RE = re.compile(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}")


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for tok in _TERM_RE.findall((text or "").lower()):
        if tok not in tokens:
            tokens.append(tok)
    return tokens[:60]


def _split_middle_sections(lines: list[str]) -> list[tuple[int, str]]:
    """把中间正文按 Markdown 标题切分为完整小节（返回 [(起始行号, 小节全文)]）。"""
    sections: list[tuple[int, str]] = []
    start = 0
    buf: list[str] = []
    for idx, line in enumerate(lines):
        if _HEADING_RE.match(line) and buf:
            sections.append((start, "\n".join(buf).strip()))
            start, buf = idx, [line]
        else:
            if not buf:
                start = idx
            buf.append(line)
    if buf:
        sections.append((start, "\n".join(buf).strip()))
    return [(s, t) for s, t in sections if t]


def _infer_title(full_text: str, rel_path: str) -> str:
    for line in full_text.splitlines()[:20]:
        m = _TITLE_RE.match(line)
        if m:
            return m.group(1).strip()
    for line in full_text.splitlines()[:5]:
        if line.strip():
            return line.strip()[:120]
    return Path(rel_path).stem


def extract_conflict_doc_evidence(
    abs_path: Path, rel_path: str, question: str, dimensions: list[str]
) -> dict:
    """读取完整 .md 原文并做三段式保真提取（不经 read-doc 的 30K 盖帽）。

    - 全文 <= 6,000 字符：100% 原样保留整篇全文；
    - 全文 > 6,000 字符：头部 60 行（<=1,500 字）+ 尾部 35 行（<=800 字）+
      中间按小节与 question+dimensions 词项重叠得分降序精选完整小节（预算 3,700 字，
      严禁只摘单行句子）。
    同时用 Python 确定性正则解析标准化日期与草案/示例词命中。

    Returns:
        dict: {doc_id 占位由调用方补, rel_path, title, evidence_text, evidence_chars,
               full_chars, evidence_mode, iso_date, date_source, draft_example_hints}
    """
    full_text = abs_path.read_text(encoding="utf-8", errors="replace")
    lines = full_text.splitlines()
    title = _infer_title(full_text, rel_path)

    if len(full_text) <= EVIDENCE_CHAR_CAP:
        evidence_text = full_text
        evidence_mode = "full"
    else:
        head = "\n".join(lines[:HEAD_LINES])[:HEAD_CHAR_CAP]
        tail = "\n".join(lines[-TAIL_LINES:])[-TAIL_CHAR_CAP:]
        used = len(head) + len(tail) + 4  # 两个拼接空行
        budget = max(0, EVIDENCE_CHAR_CAP - used)
        terms_text = question + "\n" + "\n".join(dimensions)
        terms = _tokenize(terms_text)
        # 中间小节只在头/尾固定窗口之间切分，避免与头部/尾部内容重复占预算
        mid_start = HEAD_LINES
        mid_end = max(HEAD_LINES, len(lines) - TAIL_LINES)
        scored: list[tuple[int, int, str]] = []
        for idx, (start, text) in enumerate(_split_middle_sections(lines[mid_start:mid_end])):
            hits = sum(1 for t in terms if t in text.lower())
            scored.append((hits, -(start + mid_start), text))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        picked: list[tuple[int, str]] = []
        total = 0
        for hits, neg_start, text in scored:
            if total + len(text) + 2 <= budget:
                picked.append((-neg_start, text))
                total += len(text) + 2
        picked.sort(key=lambda item: item[0])
        middle = "\n\n".join(text for _start, text in picked)
        evidence_text = f"{head}\n\n{middle}\n\n{tail}"
        evidence_mode = "three_segment"

    date_info = extract_canonical_date(rel_path, title, full_text)
    return {
        "rel_path": rel_path,
        "title": title,
        "evidence_text": evidence_text,
        "evidence_chars": len(evidence_text),
        "full_chars": len(full_text),
        "evidence_mode": evidence_mode,
        "iso_date": date_info["iso_date"],
        "date_source": date_info["date_source"],
        "draft_example_hints": deterministic_tier_hints(title, full_text),
    }


# ---------------------------------------------------------------------------
# 内网 JEV 并行冲突属性矩阵请求（50K 字符分批，按单篇文档粒度切批）
# ---------------------------------------------------------------------------


def build_conflict_batch(
    batch_entries: list[tuple[int, dict]], question: str, dimensions: list[str]
) -> tuple[dict, dict]:
    """构造一个批次的 (state, questions)。

    batch_entries: [(全局文档下标 i, 文档证据 dict), ...]（同一批内按顺序编号 j）。
    问题键使用全局下标 i 保证跨批次唯一；instructions 用批内下标 j 定位
    state.docs[j]（通常 3-6 篇在 1 批内完成，j == i）。
    问题集全部为字面属性判断（覆盖/档位/替代声明/完整度），**不含任何日期早晚比较**。
    """
    state = {
        "question": question,
        "dimensions": list(dimensions),
        "docs": [
            {
                "index": j,
                "doc_id": doc.get("doc_id", ""),
                "rel_path": doc.get("rel_path", ""),
                "title": doc.get("title", ""),
                "evidence": doc.get("evidence_text", ""),
            }
            for j, (_i, doc) in enumerate(batch_entries)
        ],
    }
    questions: dict = {}
    for j, (i, _doc) in enumerate(batch_entries):
        for k, dim in enumerate(dimensions):
            questions[f"covers_dim_{i}_{k}"] = {
                "type": "noul",
                "instructions": (
                    f"docs[{j}] 的正文中是否针对问题「{question}」明确给出了维度「{dim}」"
                    "的具体规定、拆分口径或特定数值（而非完全未提及该维度，"
                    "或仅给出未按该维度拆分的笼统全局默认值）？"
                ),
                "criteria": {
                    "true": "明确涵盖并规定了该具体维度",
                    "false": "未涵盖该维度，或仅提供未区分该维度的泛化全局说明",
                },
            }
        questions[f"authority_tier_{i}"] = {
            "type": "choice",
            "instructions": (
                f"综合 docs[{j}] 的状态标注（Published/Draft/Approved 等）、体裁与正文语气，"
                "判断该文档的权威档位。"
            ),
            "criteria": dict(AUTHORITY_CRITERIA),
        }
        questions[f"authority_clear_{i}"] = {
            "type": "noul",
            "instructions": (
                f"docs[{j}] 的正文与标题是否足以明确判定其权威档位（而非特征模糊难以判断）？"
            ),
            "criteria": {
                "true": "权威档位特征明确可判定",
                "false": "特征模糊难以判定",
            },
        }
        questions[f"explicit_supersedes_{i}"] = {
            "type": "noul",
            "instructions": (
                f"docs[{j}] 的正文中是否包含显式的版本替代或废止声明"
                "（例如明确写出 supersedes、replaces、obsoletes、overrides prior policy、"
                "废止旧版、替代原规定、以本版为准）？"
            ),
            "criteria": {
                "true": "原文有显式的替代或废止旧文档/旧条款声明",
                "false": "无显式替代声明（注意：仅仅日期较新但未写替代声明一律判 false）",
            },
        }
        questions[f"detail_completeness_{i}"] = {
            "type": "noul",
            "instructions": (
                f"围绕问题「{question}」，docs[{j}] 是否提供了高完整度的具体证据"
                "（例如包含完整日期+星期/时区、完整维度阈值表、自动决策算法、"
                "精确配置键名或可执行命令示例，而非只有一句简短口头结论）？"
            ),
            "criteria": {
                "true": "提供高完整度结构化细节/参数表/可执行示例",
                "false": "仅有一句话概述或缺乏上下文支撑的孤立数字",
            },
        }
    return state, questions


# ---------------------------------------------------------------------------
# Python 严格执行 R11 三步裁决算法
# ---------------------------------------------------------------------------


def _non_date_key(doc: dict) -> tuple[int, int, int, int]:
    """前四级非时间键：(覆盖维度数, 权威档位, 显式 supersedes, 细节完整度)。"""
    return (
        int(doc.get("covered_dim_count") or 0),
        AUTHORITY_RANK.get(doc.get("authority_tier") or "informal_note", 0),
        1 if doc.get("explicit_supersedes") else 0,
        1 if doc.get("detail_complete") else 0,
    )


def _date_rank(doc: dict) -> tuple[int, int]:
    """日期排序键（升序排列即得到：日期新者在前，无日期殿后）。

    ISO 日期转整数取负实现降序：2026-10-05 → -(20261005) 排在 2026-03-01 之前。
    """
    iso = doc.get("iso_date")
    if not iso:
        return (1, 0)
    year, month, day = iso.split("-")
    return (0, -(int(year) * 10000 + int(month) * 100 + int(day)))


_DECISIVE_VERDICTS = {
    0: "PRIMARY_BY_COVERAGE",       # 覆盖维度数差异决定（扩展位：R11 第一步未短路时的覆盖差）
    1: "PRIMARY_BY_AUTHORITY",      # 权威档位差异决定
    2: "PRIMARY_BY_SUPERSEDES",     # 显式替代声明差异决定
    3: "PRIMARY_BY_COMPLETENESS",   # 证据完整度差异决定（R11 best-supported）
}


def adjudicate_r11(evals: list[dict], dimensions: list[str]) -> dict:
    """R11 三步裁决（与 retrieval-discipline.md 第四节 R11 逐条同构）。

    Returns:
        {"verdict", "primary_doc_id", "r11_guidance", "docs"}（docs 为带 handling/warning 的副本）
    """
    docs = [dict(e) for e in evals]
    for doc in docs:
        if doc.get("authority_tier") in NON_AUTHORITATIVE_TIERS:
            doc["handling"] = "DISCLOSURE_ONLY"
            doc["warning"] = DISCLOSURE_ONLY_WARNING
        else:
            doc["handling"] = "CANDIDATE"
            doc["warning"] = None

    n_dims = max(1, len(dimensions))
    non_draft = [d for d in docs if d.get("authority_tier") not in NON_AUTHORITATIVE_TIERS]
    # R11 第一步：唯一精确覆盖全部维度者直接胜出（不受新旧与篇数干扰）
    exact_full = [d for d in non_draft if int(d.get("covered_dim_count") or 0) >= n_dims]

    all_tentative = False
    if len(exact_full) == 1:
        primary = exact_full[0]
        verdict = "PRIMARY_EXACT_MATCH"
        guidance = (
            "唯一精确覆盖题面全部维度的文档为主来源（R11 第一步）：即使它分数更低、"
            "数量更少或发布时间更早也直接胜出；其余文档仅可补充或在披露区列冲突值。"
        )
    else:
        # R11 第二步：多篇全覆盖或无单一全覆盖时的优先级裁决
        pool = exact_full if len(exact_full) >= 2 else non_draft
        if not pool:
            # 极端情况：全部候选都是草案/示例
            pool = docs
            all_tentative = True
        # 稳定两段排序合成：非时间键降序为主键，段内按 Python 解析日期降序（None 殿后）
        date_ordered = sorted(pool, key=_date_rank)
        ordered = sorted(date_ordered, key=lambda d: tuple(-v for v in _non_date_key(d)))

        primary = ordered[0]
        if len(ordered) >= 2:
            key1, key2 = _non_date_key(primary), _non_date_key(ordered[1])
        else:
            key1, key2 = _non_date_key(primary), None

        if key2 is not None and key1 == key2:
            # R11 第三步：时间戳兜底与无 supersedes 红线保护
            verdict = "TIE_NO_SUPERSEDES_PARALLEL_OR_DATE_TIEBREAK"
            guidance = TIE_GUIDANCE
        else:
            decisive = next(
                (idx for idx, (a, b) in enumerate(zip(key1, key2 or ())) if a != b),
                None,
            )
            verdict = _DECISIVE_VERDICTS.get(decisive, "PRIMARY_BY_AUTHORITY")
            if verdict == "PRIMARY_BY_SUPERSEDES":
                guidance = (
                    "胜出依据：原文显式 supersedes/替代声明（R11：有显式替代依据才允许"
                    "以新代旧）；其余文档转入补充或披露。"
                )
            elif verdict == "PRIMARY_BY_COMPLETENESS":
                guidance = (
                    "胜出依据：同等权威状态下证据完整度更高（R11 best-supported）；"
                    "答案先给 best-supported 值，再在披露区列其他冲突值。"
                )
            elif verdict == "PRIMARY_BY_COVERAGE":
                guidance = (
                    "胜出依据：覆盖题面维度更多（R11 逐文档覆盖标注）；其余文档仅可"
                    "补充或在披露区列冲突值。"
                )
            else:
                guidance = (
                    "胜出依据：权威档位更高（R11 状态优先级 Published/Approved > "
                    "非正式 > 草案 > 示例）；其余文档转入补充或披露。"
                )
        if all_tentative:
            verdict = "ALL_TENTATIVE_DISCLOSE_NATURE"
            guidance = (
                "全部候选均为草案/示例默认值，无正式可用主来源：严禁把任一候选数值"
                "作为主结论并列陈述，仅可在文末披露区用一句话说明存在未生效草案/示例值。"
            )

    primary_doc_id = primary.get("doc_id") if primary else None
    for doc in docs:
        if primary_doc_id is not None and doc.get("doc_id") == primary_doc_id:
            if all_tentative:
                # 全部候选均为草案/示例：主候选保持 DISCLOSURE_ONLY，不得升格主来源
                continue
            doc["handling"] = "PRIMARY_SOURCE"
        elif doc.get("handling") != "DISCLOSURE_ONLY":
            doc["handling"] = "SUPPLEMENT_OR_CONFLICT_DISCLOSURE"
    return {
        "verdict": verdict,
        "primary_doc_id": primary_doc_id,
        "r11_guidance": guidance,
        "docs": docs,
    }


# ---------------------------------------------------------------------------
# JEV 评估执行与答案解析
# ---------------------------------------------------------------------------


def _parse_doc_evals(answers: dict, docs: list[dict], dimensions: list[str]) -> list[dict]:
    """把 JEV answers 解析为逐文档评估结果（None 概率一律按 uncertain 保守分支）。"""
    evals: list[dict] = []
    for i, doc in enumerate(docs):
        hints = doc.get("draft_example_hints") or {"draft": False, "example": False}
        covered: dict[str, dict] = {}
        for k, dim in enumerate(dimensions):
            p = probability(answers.get(f"covers_dim_{i}_{k}"))
            covered[dim] = {
                "p": p,
                "covered": bool(p is not None and p >= A2_THRESHOLDS["dim_covered_min"]),
            }
        covered_dim_count = sum(1 for v in covered.values() if v["covered"])

        tier_label, tier_prob = choice_winner(answers.get(f"authority_tier_{i}"), AUTHORITY_TIERS)
        clear_p = probability(answers.get(f"authority_clear_{i}"))
        tier = tier_label
        authority_fallback = False
        if (
            tier not in AUTHORITY_TIERS
            or tier_prob is None
            or tier_prob < A2_THRESHOLDS["authority_choice_min"]
            or clear_p is None
            or clear_p < A2_THRESHOLDS["authority_clear_min"]
        ):
            # 低置信/缺失保守回退 informal_note；除非正文/标题确定性命中草稿/示例词
            authority_fallback = True
            if hints["draft"]:
                tier = "draft_or_proposal"
            elif hints["example"]:
                tier = "illustrative_example"
            else:
                tier = "informal_note"

        sup_p = probability(answers.get(f"explicit_supersedes_{i}"))
        det_p = probability(answers.get(f"detail_completeness_{i}"))
        evals.append(
            {
                "doc_id": doc.get("doc_id", ""),
                "rel_path": doc.get("rel_path", ""),
                "title": doc.get("title", ""),
                "evidence_mode": doc.get("evidence_mode", ""),
                "evidence_chars": doc.get("evidence_chars", 0),
                "full_chars": doc.get("full_chars", 0),
                "covered": covered,
                "covered_dim_count": covered_dim_count,
                "authority_tier": tier,
                "authority_clear": clear_p,
                "authority_prob": tier_prob,
                "authority_fallback": authority_fallback,
                "explicit_supersedes": bool(
                    sup_p is not None and sup_p >= A2_THRESHOLDS["supersedes_min"]
                ),
                "explicit_supersedes_p": sup_p,
                "detail_complete": bool(
                    det_p is not None and det_p >= A2_THRESHOLDS["detail_complete_min"]
                ),
                "detail_completeness_p": det_p,
                "iso_date": doc.get("iso_date"),
                "date_source": doc.get("date_source"),
                "draft_example_hints": hints,
            }
        )
    return evals


def _degraded_docs(docs: list[dict]) -> list[dict]:
    """JEV 不可用时的确定性降级输出：仅保留 Python 可得信息。"""
    out: list[dict] = []
    for doc in docs:
        hints = doc.get("draft_example_hints") or {"draft": False, "example": False}
        entry = {
            "doc_id": doc.get("doc_id", ""),
            "rel_path": doc.get("rel_path", ""),
            "title": doc.get("title", ""),
            "evidence_mode": doc.get("evidence_mode", ""),
            "evidence_chars": doc.get("evidence_chars", 0),
            "full_chars": doc.get("full_chars", 0),
            "iso_date": doc.get("iso_date"),
            "date_source": doc.get("date_source"),
            "draft_example_hints": hints,
            "covered": None,
            "covered_dim_count": None,
            "authority_tier": None,
            "explicit_supersedes": None,
            "detail_complete": None,
        }
        if hints["draft"] or hints["example"]:
            entry["handling"] = "DISCLOSURE_ONLY"
            entry["warning"] = DISCLOSURE_ONLY_WARNING
        else:
            entry["handling"] = "UNADJUDICATED"
            entry["warning"] = None
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def run_check_conflict(
    question: str, dimensions: list[str], docs: list[dict], timeout: float | None = None
) -> dict:
    """执行 check-conflict 主流程；JEV 不可用时确定性软降级（ok=True, jev_degraded=True）。"""
    result: dict = {
        "ok": True,
        "command": "check-conflict",
        "question": question,
        "dimensions": list(dimensions),
        "question_set_version": QUESTION_SET_VERSION,
        "thresholds": dict(A2_THRESHOLDS),
        "hint": (
            "check-conflict 输出是裁决辅助信号（S-03）：最终事实与数值仍须来自 read-doc "
            "实读原文；DISCLOSURE_ONLY 文档的数值严禁作为主结论并列陈述。"
        ),
    }
    jev_ready = is_jev_enabled() and is_stage_enabled(STAGE)
    if jev_ready:
        try:
            per_question_chars = _PER_QUESTION_CHARS * (len(dimensions) + 4)
            batches = plan_batches(
                list(enumerate(docs)),
                budget_chars=BATCH_BUDGET_CHARS,
                base_state_chars=_BATCH_BASE_STATE_CHARS,
                per_item_chars=lambda item: len(item[1].get("evidence_text", "")) + 200,
                per_item_question_chars=per_question_chars,
            )
            batch_requests = []
            for batch in batches:
                state, questions = build_conflict_batch(batch, question, dimensions)
                batch_requests.append((state, questions))
            answer = ask_batches_concurrent(
                batch_requests,
                stage=STAGE,
                question_set_version=QUESTION_SET_VERSION,
                timeout=timeout,
            )
            evals = _parse_doc_evals(answer.answers, docs, dimensions)
            adjudication = adjudicate_r11(evals, dimensions)
            result.update(adjudication)
            result["diagnostics"] = {"jev": dict(answer.audit)}
            log_event(
                logger, "check-conflict:done",
                verdict=adjudication["verdict"],
                primary=adjudication["primary_doc_id"],
                doc_count=len(docs),
                batch_count=(answer.audit or {}).get("batch_count"),
                question_count=(answer.audit or {}).get("question_count"),
            )
            return result
        except JevUnavailable as exc:
            log_event(
                logger, "check-conflict:degraded", level=logging.WARNING,
                error=str(exc),
            )
            result["diagnostics"] = {"jev": build_degraded_diag(STAGE, exc)}
        except ValueError as exc:
            # 批次间问题键名冲突等装配缺陷：按有痕软降级处理，绝不静默放行
            log_event(
                logger, "check-conflict:degraded", level=logging.WARNING,
                error=f"ValueError: {exc}",
            )
            result["diagnostics"] = {"jev": build_degraded_diag(STAGE, exc)}

    # 确定性软降级：仍返回 Python 解析出的日期与草案/示例词提示
    result["jev_degraded"] = True
    result["verdict"] = "JEV_DEGRADED_MANUAL_ADJUDICATION"
    result["primary_doc_id"] = None
    result["r11_guidance"] = (
        "内网 JEV 不可用或未启用，已确定性软降级：维度覆盖矩阵与权威档位未生成；"
        "请按 retrieval-discipline R11 三步人工裁决（先题面维度拆解，唯一精确覆盖者"
        "即主来源；无显式 supersedes 严禁假定新日期覆盖旧日期），并参考下方各文档的"
        "确定性解析日期与草案/示例词提示。"
    )
    result["docs"] = _degraded_docs(docs)
    if "diagnostics" not in result:
        result["diagnostics"] = {
            "jev": build_degraded_diag(STAGE, "JEV disabled or stage A2 not enabled")
        }
    log_event(
        logger, "check-conflict:done",
        verdict=result["verdict"], doc_count=len(docs), degraded=True,
    )
    return result


# ---------------------------------------------------------------------------
# CLI 入口（由 overview_resolver.py 薄转发调用）
# ---------------------------------------------------------------------------


def parse_question_json(raw: str) -> tuple[str | None, list[str] | None, str]:
    """双形态 --question-json 解析：以 `{` 开头按内联 JSON，否则按本地文件路径。

    Returns:
        (question, dimensions, error)；error 非空表示解析失败。
    """
    raw_stripped = (raw or "").strip()
    if not raw_stripped:
        return None, None, "--question-json 为空：请传内联 JSON 或本地 JSON 文件路径"
    if raw_stripped.startswith("{"):
        try:
            obj = json.loads(raw_stripped)
        except ValueError as exc:
            return None, None, f"--question-json 不是合法 JSON：{exc}"
    else:
        path = Path(raw_stripped)
        if not path.is_file():
            return None, None, f"--question-json 文件不存在：{raw_stripped}"
        try:
            obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError) as exc:
            return None, None, f"--question-json 文件读取/解析失败：{exc}"
    if not isinstance(obj, dict):
        return None, None, "--question-json 必须是 JSON 对象（含 question 字段）"
    question = obj.get("question")
    if not isinstance(question, str) or not question.strip():
        return None, None, '--question-json 需含非空字符串字段 "question"'
    question = question.strip()
    raw_dims = obj.get("dimensions")
    dimensions: list[str] = []
    if isinstance(raw_dims, list):
        for dim in raw_dims:
            if isinstance(dim, str) and dim.strip() and dim.strip() not in dimensions:
                dimensions.append(dim.strip())
    dimensions = dimensions[:MAX_DIMENSIONS]
    if not dimensions:
        dimensions = [question]
    return question, dimensions, ""


def cmd_check_conflict(args, checked: list[dict]) -> int:
    """check-conflict 子命令处理器（在 overview_resolver.main() 分发处薄转发到这里）。"""
    question, dimensions, error = parse_question_json(getattr(args, "question_json", ""))
    if error:
        print(json.dumps({"ok": False, "error": error}, ensure_ascii=False, indent=2))
        return 1

    raw_ids: list[str] = []
    for part in (getattr(args, "doc_ids", "") or "").split(","):
        part = part.strip()
        if part and part not in raw_ids:
            raw_ids.append(part)
    if len(raw_ids) < MIN_DOCS:
        print(json.dumps(
            {"ok": False, "error": f"--doc-ids 去重后至少需要 {MIN_DOCS} 篇文档，收到 {len(raw_ids)} 篇"},
            ensure_ascii=False, indent=2,
        ))
        return 1
    if len(raw_ids) > MAX_DOCS:
        print(json.dumps(
            {"ok": False, "error": f"--doc-ids 去重后最多支持 {MAX_DOCS} 篇文档，收到 {len(raw_ids)} 篇"},
            ensure_ascii=False, indent=2,
        ))
        return 1

    # 延迟导入避免模块级循环依赖（overview_resolver 亦仅在分发处延迟导入本模块）
    from common.overview_resolver import _build_global_node_index, _lookup_global_id

    global_node_index, _remap = _build_global_node_index(checked)
    resolved: list[dict] = []
    missing: list[str] = []
    seen: set[str] = set()
    for raw in raw_ids:
        gid = _lookup_global_id(global_node_index, raw)
        if gid is None:
            missing.append(raw)
            continue
        if gid in seen:
            continue
        seen.add(gid)
        entry = global_node_index[gid]
        resolved.append({
            "raw_id": raw,
            "doc_id": gid,
            "rel_path": entry["rel_path"],
            "abs_path": Path(entry["pre_dir"]) / entry["rel_path"],
        })
    if missing:
        print(json.dumps(
            {"ok": False, "error": f"以下 node_id 在任何路由的 node_index 中均未找到：{', '.join(missing)}"},
            ensure_ascii=False, indent=2,
        ))
        return 1
    if len(resolved) < MIN_DOCS:
        print(json.dumps(
            {"ok": False, "error": f"--doc-ids 归一化去重后有效篇数不足 {MIN_DOCS} 篇"},
            ensure_ascii=False, indent=2,
        ))
        return 1

    docs: list[dict] = []
    read_errors: list[dict] = []
    for item in resolved:
        abs_path: Path = item["abs_path"]
        if not abs_path.is_file():
            read_errors.append({"doc_id": item["doc_id"], "error": f"原文文件不存在：{abs_path}"})
            continue
        evidence = extract_conflict_doc_evidence(abs_path, item["rel_path"], question, dimensions)
        evidence["doc_id"] = item["doc_id"]
        docs.append(evidence)
    if len(docs) < MIN_DOCS:
        detail = "; ".join(e["error"] for e in read_errors) or "无"
        print(json.dumps(
            {"ok": False, "error": f"可读取的有效文档不足 {MIN_DOCS} 篇（读取失败：{detail}）"},
            ensure_ascii=False, indent=2,
        ))
        return 1

    result = run_check_conflict(question, dimensions, docs)
    if read_errors:
        result["read_errors"] = read_errors
    log_event(
        logger, "check-conflict:request",
        agent=getattr(args, "agent_id", ""),
        doc_ids=resolved and [item["doc_id"] for item in resolved],
        dims=len(dimensions),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1
