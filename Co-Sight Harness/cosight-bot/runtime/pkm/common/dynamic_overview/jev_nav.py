#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JEV-E2：候选池切线灰区穿透晋升与 Tier1 优先精读导航（T4 独占模块）。

职责（对应主方案节点 ★ JEV-E2）：
  1. 离线 Top100/300 召回差测算辅助（``--eval-recall-gap`` CLI）；
  2. 从 ``doc_skeleton`` 批量挂载构建期 M1 角色先验（零延迟、免问在线 doc_role）；
  3. 回读命中章节整段原文（严禁只喂 first_sentence 或残截 Chunk）；
  4. 分批（单批 <= 20 篇且 <= 50K 字符）并发请求内网 JEV 打标；
  5. 零物理删除的灰区穿透晋升重排与 ``★ 优先精读建议`` / 行尾徽标组装。

铁律：只提权排序、零物理删除——``filtered`` 总池与 ``candidate_pool`` 篇数一字不删，
绝不误杀深层 needle 金标；JEV 异常一律有痕软降级，绝不令 ``resolve`` 失败。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from common.jev_client import (
    JevUnavailable,
    ask_batches_concurrent,
    build_degraded_diag,
    choice_winner,
    expected_score,
    is_stage_enabled,
    plan_batches,
    probability,
)
from common.jev_questions import (
    E2_QUESTION_SET_VERSION as QUESTION_SET_VERSION,
    E2_THRESHOLDS,
)
from common.logging_setup import log_event

from .models import DocScore, QueryPack

logger = logging.getLogger("dynamic_overview.jev_nav")

MAX_PROMOTE_DOCS = 15
MAX_RECOMMEND_DOCS = 12
DOC_SECTION_CHAR_BUDGET = 1_600
BATCH_CHAR_BUDGET = 50_000
MAX_DOCS_PER_BATCH = 20
# 内网 SystemOne 服务端对单请求执行 state × question_count 序列展开：
# 默认每批 1 篇（2~3 问）彻底消除跨文档交叉乘积冗余（较 20 篇/批节省 ~94% input_tokens），
# 单次耗时 ~800ms，200+ 篇全扫描 ~30s 完成且零超时；可通过 COSIGHTBOT_JEV_E2_BATCH_DOCS 调整。
DEFAULT_DOCS_PER_BATCH = 1
DEFAULT_E2_WORKERS = 6
# 每篇候选最多 3 个原子问题（含反注入安全后缀与 criteria JSON 开销，约 ~420 字/问）。
_PER_ITEM_QUESTION_CHARS = 3 * 420

# M1 细粒度类型 -> E2 角色确定性映射（有高置信先验时免问在线 doc_role）。
_DOC_TYPE_TO_ROLE = {
    "policy_norm": "normative",
    "runbook_sop": "normative",
    "architecture_spec": "normative",
    "contract_sla": "normative",
    "incident_ticket": "factual_record",
}
# 行尾徽标权威角色中文名（README.md 3.3 节冻结映射，T2/T4 共用，严禁改动）。
_DOC_TYPE_TO_BADGE = {
    "policy_norm": "正式制度规范",
    "runbook_sop": "运维规程SOP",
    "architecture_spec": "架构技术规格",
    "contract_sla": "合同协议SLA",
}
ROLE_CHOICE_OPTIONS = ("normative", "factual_record", "tentative", "other")

_AUTHORITATIVE_ROLES = ("normative", "factual_record")

_TARGET_TMPL = (
    "`candidates[{pos}]`（doc_id={doc_id}）的章节正文实际讨论的主体对象"
    "（项目、系统组件、具名客户、制度或事件单）是否正是 `question` 询问的目标主体"
    "（而非其他项目/客户、同名外围包装组件或无关泛背景）？"
)
_FIT_INSTRUCTIONS = (
    "评估 `candidates[{pos}]`（doc_id={doc_id}）的命中章节正文与 `question` 要求的"
    "具体业务场景/限定条件的契合档位。"
)
# SystemOne 协议中 score 类型的 criteria 必须为从低到高的有序字符串数组（list[str]）。
_FIT_CRITERIA = [
    "0: 仅出现表面主题词，完全未涉及 question 询问的具体业务场景、指标或动作",
    "1: 涉及目标系统或业务流程的通用背景说明，但未命中问题要求的特定限定条件或细项",
    "2: 明确命中 question 要求的特定限定维度（如特定区域/环境、时间窗口、"
    "错误码、配置项、审批阈值或操作步骤）",
]
_ROLE_INSTRUCTIONS = "判断 `candidates[{pos}]`（doc_id={doc_id}）所属文档的实际权威体裁角色。"
_ROLE_CRITERIA = {
    "normative": "正式规范/政策/手册/SLA/PRD/已批复 ADR/Runbook",
    "factual_record": "工单/事故复盘/项目周报/变更记录/签署合同",
    "tentative": "草案/RFC/提案/示例默认值说明",
    "other": "其他普通资料",
}


# ---------------------------------------------------------------------------
# 环境开关
# ---------------------------------------------------------------------------
def _scan_limit() -> int:
    """穿透扫描窗口大小（默认 300，对应主方案 [0 : min(300, len(filtered))]）。"""
    raw = (os.environ.get("COSIGHTBOT_JEV_E2_SCAN_LIMIT") or "").strip()
    try:
        value = int(raw) if raw else 300
    except ValueError:
        value = 300
    return max(0, value)


def _tag_only_mode() -> bool:
    """tag_only 模式：仅扫描 tier1 + tier2[:50] 做导航打标，不做池外灰区晋升。"""
    return (os.environ.get("COSIGHTBOT_JEV_E2_MODE") or "").strip().lower() == "tag_only"


def _docs_per_batch() -> int:
    """单批最大文档数（默认 1，受硬上限 MAX_DOCS_PER_BATCH=20 约束）。"""
    raw = (os.environ.get("COSIGHTBOT_JEV_E2_BATCH_DOCS") or "").strip()
    try:
        value = int(raw) if raw else DEFAULT_DOCS_PER_BATCH
    except ValueError:
        value = DEFAULT_DOCS_PER_BATCH
    return max(1, min(value, MAX_DOCS_PER_BATCH))


def _e2_workers() -> int:
    """E2 批次并发线程数（默认 6，上限 8）。"""
    raw = (os.environ.get("COSIGHTBOT_JEV_E2_WORKERS") or "").strip()
    try:
        value = int(raw) if raw else DEFAULT_E2_WORKERS
    except ValueError:
        value = DEFAULT_E2_WORKERS
    return max(1, min(value, 8))


# ---------------------------------------------------------------------------
# doc_skeleton M1 角色先验挂载（纯本地、零 JEV 延迟）
# ---------------------------------------------------------------------------
def _engine_ref():
    # 延迟导入：engine.py 顶部 import 区与本模块零冲突（跨任务行区隔离铁律）。
    from . import engine as engine_module

    return engine_module


def _fetch_doc_rows(table: Any, local_ids: list[str]) -> list[dict]:
    """读 doc_skeleton 角色列；旧 v2 表无 jev_* 列时自动回退 doc_meta JSON。"""
    engine_module = _engine_ref()
    rows = engine_module._fetch_rows(
        table,
        engine_module._filter_in("doc_key", local_ids),
        ["doc_key", "jev_doc_type", "jev_doc_type_conf", "jev_is_registry", "doc_meta"],
    )
    if rows and isinstance(rows[0], dict) and "jev_doc_type" in rows[0]:
        return rows
    # v2 回退：仅读 doc_key + doc_meta，从 JSON 镜像键恢复先验。
    fallback = engine_module._fetch_rows(
        table,
        engine_module._filter_in("doc_key", local_ids),
        ["doc_key", "doc_meta"],
    )
    return fallback


def _prior_from_row(row: dict) -> tuple[str, float, bool]:
    doc_type = str(row.get("jev_doc_type") or "")
    try:
        conf = float(row.get("jev_doc_type_conf") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    is_registry = bool(row.get("jev_is_registry") or False)
    if not doc_type:
        try:
            meta = json.loads(str(row.get("doc_meta") or "{}"))
        except (ValueError, TypeError):
            meta = {}
        if isinstance(meta, dict):
            doc_type = str(meta.get("jev_doc_type") or "")
            try:
                conf = float(meta.get("jev_doc_type_conf") or 0.0)
            except (TypeError, ValueError):
                conf = 0.0
            is_registry = is_registry or bool(meta.get("jev_is_registry") or False)
    return doc_type, conf, is_registry


def mount_m1_priors(docs: dict[str, DocScore], contexts: list) -> dict[str, float]:
    """把构建期 M1 先验填入 doc.jev_doc_type / jev_is_registry 并预渲染徽标。

    返回 {doc_id: conf} 置信度映射；即使 JEV 在线服务关闭，只要索引含 M1
    先验也能零延迟渲染 ``[权威角色:...]`` 徽标。列缺失/全空时静默跳过。
    """
    conf_map: dict[str, float] = {}
    by_route: dict[int, list[DocScore]] = {}
    for doc in docs.values():
        by_route.setdefault(doc.route_index, []).append(doc)
    for route_index, items in by_route.items():
        ctx = contexts[route_index] if contexts and route_index < len(contexts) else None
        table = getattr(getattr(ctx, "index", None), "doc_table", None) if ctx else None
        if table is None:
            continue
        local_ids = sorted({doc.local_doc_id for doc in items})
        if not local_ids:
            continue
        try:
            rows = _fetch_doc_rows(table, local_ids)
        except Exception:  # noqa: BLE001 - 先验挂载失败绝不阻断主链路
            rows = []
        row_map = {str(row.get("doc_key")): row for row in rows if isinstance(row, dict)}
        for doc in items:
            row = row_map.get(doc.local_doc_id)
            if not row:
                continue
            doc_type, conf, is_registry = _prior_from_row(row)
            has_valid_type = bool(doc_type) and doc_type != "unknown"
            if not has_valid_type and not is_registry:
                continue
            if has_valid_type:
                doc.jev_doc_type = doc_type
                conf_map[doc.doc_id] = conf
            if is_registry:
                doc.jev_is_registry = True
                conf_map.setdefault(doc.doc_id, conf)
            if _doc_role_display(doc):
                doc.jev_badge = format_doc_badge(doc)
    if conf_map:
        log_event(logger, "jev_e2:m1_priors", docs=len(conf_map))
    return conf_map


def _prior_is_high_conf(doc: DocScore, conf_map: dict[str, float]) -> bool:
    return (
        bool(doc.jev_doc_type)
        and doc.jev_doc_type != "unknown"
        and conf_map.get(doc.doc_id, 0.0) >= E2_THRESHOLDS["m1_prior_conf_min"]
    )


# ---------------------------------------------------------------------------
# 命中章节整段原文回读（严禁只喂 first_sentence / 残截 Chunk）
# ---------------------------------------------------------------------------
def _fetch_section_spans(table: Any, doc_key: str, section_ids: list[str]) -> dict:
    if not section_ids:
        return {}
    engine_module = _engine_ref()
    section_filter = (
        f"doc_key = '{doc_key.replace(chr(39), chr(39) * 2)}' AND "
        + engine_module._filter_in("section_id", sorted(set(section_ids)))
    )
    rows = engine_module._fetch_rows(
        table, section_filter,
        ["doc_key", "section_id", "header_path", "start_line", "end_line"],
    )
    spans: dict[str, tuple[int, int, str]] = {}
    for row in rows or []:
        try:
            start = int(row.get("start_line") or 0)
            end = int(row.get("end_line") or 0)
        except (TypeError, ValueError):
            continue
        if end >= start > 0:
            spans[str(row.get("section_id"))] = (start, end, str(row.get("header_path") or ""))
    return spans


def _center_window(lines: list[str], center_start: int, center_end: int, budget: int) -> str:
    """以命中行号为中心向两侧扩展，取不超过 budget 字符的连续行窗口。"""
    if not lines:
        return ""
    n = len(lines)
    lo = max(1, min(center_start, n) - 2)
    hi = min(n, max(1, min(center_end, n)) + 2)
    total = sum(len(lines[i - 1]) for i in range(lo, hi + 1))
    while total < budget and (lo > 1 or hi < n):
        prefer_hi = hi < n and (lo <= 1 or (hi - center_end) <= (center_start - lo))
        if prefer_hi:
            hi += 1
        else:
            lo -= 1
        total += len(lines[(hi if prefer_hi else lo) - 1])
    return "\n".join(lines[lo - 1:hi])


def _fit_section_text(header_path: str, text: str, hit_start: int, hit_end: int, cap: int) -> str:
    """单节文本适配预算：整节优先；超长时保留标题行 + 命中行中心窗口。"""
    prefix = f"{header_path}\n" if header_path else ""
    lines = text.splitlines()
    if not lines:
        return ""
    total_chars = len(prefix) + sum(len(line) + 1 for line in lines)
    if total_chars <= cap:
        return prefix + text
    title = lines[0]
    window = _center_window(lines[1:], max(1, hit_start - 1), max(1, hit_end - 1),
                            max(0, cap - len(prefix) - len(title) - 1))
    out = f"{prefix}{title}\n{window}" if window else f"{prefix}{title}"
    if len(out) > cap:
        out = out[:cap]
    return out


def _extract_full_hit_sections(doc: DocScore, ctx: Any) -> str:
    """取命中章节整段原文（合计 <= 1,600 字符），供 JEV 评估实体吻合与限定契合。

    优先从 section_table 查整节 (start_line, end_line) 后经 ctx.read_lines 取
    完整小节文本；查不到时回退 Candidate 已还原文本。超长小节保留标题行 +
    以命中行号为中心的连续窗口，确保绝不丢失表格表头与前置主语。
    """
    picked: list = []
    seen: set[str] = set()
    for candidate in sorted(doc.candidates, key=lambda c: c.score, reverse=True):
        section_id = candidate.section_id or ""
        if section_id and section_id in seen:
            continue
        picked.append(candidate)
        if section_id:
            seen.add(section_id)
        if len(picked) >= 2:
            break
    if not picked:
        return ""

    spans: dict[str, tuple[int, int, str]] = {}
    table = getattr(getattr(ctx, "index", None), "section_table", None) if ctx else None
    if table is not None:
        try:
            spans = _fetch_section_spans(
                table, doc.local_doc_id,
                [c.section_id for c in picked if c.section_id],
            )
        except Exception:  # noqa: BLE001 - 回退候选自带文本
            spans = {}

    parts: list[str] = []
    remaining = DOC_SECTION_CHAR_BUDGET
    read_lines = getattr(ctx, "read_lines", None) if ctx else None
    for candidate in picked:
        if remaining <= 0:
            break
        span = spans.get(candidate.section_id or "")
        if span and read_lines is not None:
            sec_start, sec_end, header_path = span
            try:
                text = read_lines(doc.rel_path, sec_start, sec_end)
            except Exception:  # noqa: BLE001
                text = ""
            hit_start = max(1, candidate.start_line - sec_start + 1)
            hit_end = max(hit_start, candidate.end_line - sec_start + 1)
        else:
            text = candidate.text or ""
            header_path = candidate.header_path or ""
            hit_start = hit_end = 1
        if not text:
            continue
        block = _fit_section_text(header_path, text, hit_start, hit_end, remaining)
        if not block:
            continue
        parts.append(block)
        remaining -= len(block)
    return "\n...\n".join(parts)


# ---------------------------------------------------------------------------
# 问题集构造与分批
# ---------------------------------------------------------------------------
def build_questions(entries: list[dict], conf_map: dict[str, float]) -> dict:
    """每篇候选并行生成 target_match / constraint_fit / doc_role 原子问题。

    注意：问题字典键使用全局唯一 ``idx``（跨批次合并 answers 不碰撞），
    而 ``instructions`` 中引用的 ``candidates[{pos}]`` 使用本批局部数组下标 ``0..len-1``！
    """
    questions: dict[str, dict] = {}
    for pos, entry in enumerate(entries):
        idx = entry["idx"]
        doc_id = entry["doc_id"]
        questions[f"target_match_{idx}"] = {
            "type": "noul",
            "instructions": _TARGET_TMPL.format(pos=pos, doc_id=doc_id),
        }
        questions[f"constraint_fit_{idx}"] = {
            "type": "score",
            "instructions": _FIT_INSTRUCTIONS.format(pos=pos, doc_id=doc_id),
            "criteria": _FIT_CRITERIA,
        }
        doc_type = str(entry.get("doc_type_prior") or "unknown")
        conf = float(conf_map.get(doc_id, 0.0))
        if not doc_type or doc_type == "unknown" or conf < E2_THRESHOLDS["m1_prior_conf_min"]:
            # 无高置信 M1 先验才在线询问 doc_role（省去约 70%+ 冗余角色问题）。
            questions[f"doc_role_{idx}"] = {
                "type": "choice",
                "instructions": _ROLE_INSTRUCTIONS.format(pos=pos, doc_id=doc_id),
                "criteria": _ROLE_CRITERIA,
            }
    return questions


def build_batches(
    q_orig: QueryPack,
    entries: list[dict],
    conf_map: dict[str, float],
) -> list[tuple[dict, dict]]:
    """单批 <= 20 篇且 <= 50,000 字符自动拆批（不截断单条内容）。"""
    if not entries:
        return []
    question = "；".join(q_orig.questions) if q_orig.questions else q_orig.primary_question
    state_header = {
        "question": question,
        "entities": list(q_orig.entities),
        "constraints": list(q_orig.constraints),
        "identifiers": list(q_orig.identifiers),
        "candidates": [],
    }
    base_chars = max(500, len(json.dumps(state_header, ensure_ascii=False)) + 200)
    batch_cap = _docs_per_batch()
    groups = [
        entries[i:i + batch_cap]
        for i in range(0, len(entries), batch_cap)
    ]
    batches: list[tuple[dict, dict]] = []
    for group in groups:
        for sub_batch in plan_batches(
            group,
            budget_chars=BATCH_CHAR_BUDGET,
            base_state_chars=base_chars,
            per_item_chars=lambda entry: len(json.dumps(entry, ensure_ascii=False)),
            per_item_question_chars=_PER_ITEM_QUESTION_CHARS,
        ):
            state = {
                "question": question,
                "entities": list(q_orig.entities),
                "constraints": list(q_orig.constraints),
                "identifiers": list(q_orig.identifiers),
                "candidates": list(sub_batch),
            }
            batches.append((state, build_questions(sub_batch, conf_map)))
    return batches


def _constraint_fit_score(answer: object) -> float | None:
    """委托公共 expected_score（兼容 SystemOne probabilities 与 score 字典）。"""
    return expected_score(answer, scale=("0", "1", "2"))


def _apply_answers(
    docs_by_idx: dict[int, DocScore],
    priors: dict[int, tuple[bool, str]],
    answers: dict,
) -> None:
    for idx, doc in docs_by_idx.items():
        doc.jev_target_match = probability(answers.get(f"target_match_{idx}"))
        doc.jev_constraint_fit = _constraint_fit_score(answers.get(f"constraint_fit_{idx}"))
        has_prior, prior_type = priors[idx]
        if has_prior:
            # 高置信 M1 先验：本地确定性映射，免问在线 doc_role。
            doc.jev_doc_role = _DOC_TYPE_TO_ROLE.get(prior_type, "other")
        else:
            winner, conf = choice_winner(
                answers.get(f"doc_role_{idx}"), allowed=ROLE_CHOICE_OPTIONS
            )
            if winner and (conf is None or conf >= E2_THRESHOLDS["role_choice_min"]):
                doc.jev_doc_role = winner


# ---------------------------------------------------------------------------
# 优先分 J(d) 与零物理删除重排
# ---------------------------------------------------------------------------
def priority_score(doc: DocScore) -> float:
    """J(d) = 0.55*p_target + 0.35*(e_fit/2) + 0.10*role_bonus。

    缺失概率保守计 0.5 / 1.0，仅参与排序，绝不触发晋升或降级。
    """
    p = doc.jev_target_match if doc.jev_target_match is not None else 0.5
    e = doc.jev_constraint_fit if doc.jev_constraint_fit is not None else 1.0
    role_bonus = 1.0 if _is_authoritative(doc) else 0.0
    return 0.55 * p + 0.35 * (e / 2.0) + 0.10 * role_bonus


def _is_authoritative(doc: DocScore) -> bool:
    return doc.jev_doc_role in _AUTHORITATIVE_ROLES or doc.jev_is_registry


def rerank_and_promote_tiers(
    filtered: list[DocScore],
    tier1: list[DocScore],
    tier2: list[DocScore],
    scan_limit: int,
) -> tuple[list[DocScore], list[DocScore], list[str], list[str]]:
    """灰区穿透晋升 + 零物理删除顺移（filtered 总池一字不删）。"""
    engine_module = _engine_ref()
    tier1_limit = int(getattr(engine_module, "TIER1_LIMIT", 100))
    tier2_limit = int(getattr(engine_module, "TIER2_LIMIT", 150))
    tier1_ids = {d.doc_id for d in tier1}
    cut = 0
    while cut < len(filtered) and filtered[cut].doc_id in tier1_ids:
        cut += 1
    grey = filtered[cut:max(cut, scan_limit)]
    qualifying = [
        doc for doc in grey
        if doc.jev_target_match is not None
        and doc.jev_target_match >= E2_THRESHOLDS["promote_target_min"]
        and doc.jev_constraint_fit is not None
        and doc.jev_constraint_fit >= E2_THRESHOLDS["promote_constraint_min"]
    ]
    promoted = sorted(
        qualifying, key=lambda d: (priority_score(d), d.score), reverse=True
    )[:MAX_PROMOTE_DOCS]
    promoted_ids = {d.doc_id for d in promoted}
    for doc in promoted:
        doc.jev_promoted = True
        doc.tier = 1

    new_tier1 = [*tier1, *promoted]
    new_tier2 = [d for d in tier2 if d.doc_id not in promoted_ids]
    demoted_ids: list[str] = []
    # 原 Tier 1 末尾极低相关（p_target < 0.02 且非权威/非登记表）顺移至 Tier 2 头部；
    # 缺失概率（None）保守不误伤，绝不顺移。
    cursor = len(tier1) - 1
    while len(new_tier1) > tier1_limit and cursor >= 0:
        doc = tier1[cursor]
        cursor -= 1
        if (
            doc.jev_target_match is not None
            and doc.jev_target_match < E2_THRESHOLDS["tier1_demote_max"]
            and not _is_authoritative(doc)
        ):
            new_tier1.remove(doc)
            new_tier2.insert(0, doc)
            doc.tier = 2
            demoted_ids.append(doc.doc_id)
    # Tier 2 展示上限：顺移溢出只影响展示截断计数，总池不删。
    if len(new_tier2) > tier2_limit:
        new_tier2 = new_tier2[:tier2_limit]
    return new_tier1, new_tier2, [d.doc_id for d in promoted], demoted_ids


# ---------------------------------------------------------------------------
# 行尾徽标（README.md 3.3 节冻结契约）与顶部导航清单
# ---------------------------------------------------------------------------
def _doc_role_display(doc: DocScore) -> str:
    name = _DOC_TYPE_TO_BADGE.get(doc.jev_doc_type, "")
    if doc.jev_is_registry:
        name = f"{name}/汇总登记表" if name else "汇总登记表"
    if not name:
        if doc.jev_doc_role == "normative":
            name = "正式规范"
        elif doc.jev_doc_role == "tentative":
            name = "草案/示例"
    return name


def format_doc_badge(doc: DocScore) -> str:
    """组装紧凑方括号行尾徽标；无有效评分且无权威角色时返回空串。"""
    parts: list[str] = []
    p = doc.jev_target_match
    if p is not None and p >= 0.30:
        parts.append("实体吻合:高" if p >= 0.90 else "实体吻合:中")
    e = doc.jev_constraint_fit
    if e is not None and e >= 0.70:
        parts.append("限定:2档" if e >= 1.5 else "限定:1档")
    role_name = _doc_role_display(doc)
    if role_name:
        parts.append(f"权威角色:{role_name}")
    if doc.jev_promoted:
        parts.append("↑灰区晋升")
    return f"[{' | '.join(parts)}]" if parts else ""


def select_priority_recommendations(tier1: list[DocScore]) -> list[DocScore]:
    """从更新后的 Tier 1 选顶部导航清单；不足 3 篇只展示实际满足篇数。"""
    picked: list[DocScore] = []
    for doc in tier1:
        p = doc.jev_target_match
        if p is None or p < E2_THRESHOLDS["recommend_target_min"]:
            continue
        j = doc.jev_score if doc.jev_score is not None else priority_score(doc)
        if j >= E2_THRESHOLDS["recommend_score_min"] or _is_authoritative(doc):
            picked.append(doc)
    picked.sort(key=lambda d: (d.jev_score if d.jev_score is not None else priority_score(d), d.score),
                reverse=True)
    return picked[:MAX_RECOMMEND_DOCS]


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def apply_e2_navigation(
    q_orig: QueryPack,
    all_docs: dict[str, DocScore],
    tier1: list[DocScore],
    tier2: list[DocScore],
    contexts: list | None = None,
) -> tuple[list[DocScore], list[DocScore], list[DocScore], dict]:
    """engine.run 在 _apply_tiers 之后调用；JEV 异常有痕软降级，绝不令 resolve 失败。"""
    contexts = contexts or []
    diag: dict[str, Any] = {"stage": "E2", "question_set_version": QUESTION_SET_VERSION}
    try:
        conf_map = mount_m1_priors(all_docs, contexts)
        if not is_stage_enabled("E2"):
            diag.update({"skipped": True, "reason": "stage_disabled", "m1_prior_docs": len(conf_map)})
            log_event(logger, "jev_e2:skipped", reason="stage_disabled", m1_prior_docs=len(conf_map))
            return tier1, tier2, [], diag

        engine_module = _engine_ref()
        ordered = sorted(all_docs.values(), key=lambda d: d.score, reverse=True)
        filtered = [d for d in ordered if d.score >= engine_module.TAU_NOISE]
        if not all(d.doc_id in {x.doc_id for x in filtered} for d in [*tier1, *tier2]):
            filtered = ordered
        tier1_ids = {d.doc_id for d in tier1}
        cut = 0
        while cut < len(filtered) and filtered[cut].doc_id in tier1_ids:
            cut += 1
        if _tag_only_mode():
            scan_limit = 0
            eval_docs = [*tier1, *tier2[:50]]
        else:
            scan_limit = min(_scan_limit(), len(filtered))
            grey = filtered[cut:scan_limit]
            eval_docs = [*tier1, *grey]
        seen: set[str] = set()
        unique_docs: list[DocScore] = []
        for doc in eval_docs:
            if doc.doc_id in seen:
                continue
            seen.add(doc.doc_id)
            unique_docs.append(doc)
        if not unique_docs:
            diag.update({"skipped": True, "reason": "no_candidates"})
            return tier1, tier2, [], diag

        entries: list[dict] = []
        docs_by_idx: dict[int, DocScore] = {}
        priors: dict[int, tuple[bool, str]] = {}
        for idx, doc in enumerate(unique_docs):
            ctx = contexts[doc.route_index] if doc.route_index < len(contexts) else None
            try:
                best_sections_text = _extract_full_hit_sections(doc, ctx)
            except Exception:  # noqa: BLE001 - 单篇回读失败不影响整批
                best_sections_text = ""
            entries.append({
                "idx": idx,
                "doc_id": doc.doc_id,
                "path": doc.rel_path,
                "title": doc.title,
                "doc_type_prior": doc.jev_doc_type or "unknown",
                "is_registry_prior": doc.jev_is_registry,
                "best_sections_text": best_sections_text,
            })
            docs_by_idx[idx] = doc
            priors[idx] = (
                _prior_is_high_conf(doc, conf_map),
                doc.jev_doc_type or "unknown",
            )

        batches = build_batches(q_orig, entries, conf_map)
        log_event(
            logger, "jev_e2:start", docs=len(unique_docs), batches=len(batches),
            scan_limit=scan_limit, tag_only=_tag_only_mode(),
        )
        answer_pack = ask_batches_concurrent(
            batches,
            stage="E2",
            question_set_version=QUESTION_SET_VERSION,
            max_workers=_e2_workers(),
        )
        _apply_answers(docs_by_idx, priors, answer_pack.answers)
        for doc in unique_docs:
            doc.jev_score = priority_score(doc)

        if _tag_only_mode():
            new_tier1, new_tier2, promoted_ids, demoted_ids = tier1, tier2, [], []
        else:
            new_tier1, new_tier2, promoted_ids, demoted_ids = rerank_and_promote_tiers(
                filtered, tier1, tier2, scan_limit
            )
        # 徽标在晋升/顺移定案后统一组装，确保 ↑灰区晋升 标记不丢。
        for doc in unique_docs:
            doc.jev_badge = format_doc_badge(doc)
        recommendations = select_priority_recommendations(new_tier1)
        audit = answer_pack.audit or {}
        diag.update({
            "skipped": False,
            "evaluated_docs": len(unique_docs),
            "batch_count": audit.get("batch_count"),
            "question_count": audit.get("question_count"),
            "payload_chars": audit.get("payload_chars"),
            "latency_ms": audit.get("latency_ms"),
            "model": audit.get("model"),
            "promoted": promoted_ids,
            "demoted": demoted_ids,
            "recommendations": [d.doc_id for d in recommendations],
        })
        log_event(
            logger, "jev_e2:done", docs=len(unique_docs), batches=len(batches),
            promoted=len(promoted_ids), demoted=len(demoted_ids),
            recommendations=len(recommendations),
            latency_ms=audit.get("latency_ms"),
        )
        return new_tier1, new_tier2, recommendations, diag
    except JevUnavailable as exc:
        log_event(logger, "degraded:jev_e2", level=logging.WARNING, error=str(exc))
        return tier1, tier2, [], build_degraded_diag("E2", exc)


# ---------------------------------------------------------------------------
# 离线 Top100/300 召回差测算辅助（主方案 3.2 节硬门禁）
# ---------------------------------------------------------------------------
def compute_recall_gap_report(
    ranked_doc_ids: list[str],
    gold_ids: list[str] | set[str],
    windows: tuple[int, ...] = (100, 150, 250, 300, 350),
) -> dict:
    """对单一候选池快照计算 Recall@k 与 ΔRecall(pp) = Recall@300 - Recall@100。"""
    gold = {str(g) for g in gold_ids}
    pool = [str(d) for d in ranked_doc_ids]

    def recall_at(k: int) -> float:
        if not gold:
            return 0.0
        hit = len(gold & set(pool[:max(0, k)]))
        return hit / len(gold)

    report: dict[str, Any] = {
        "gold_total": len(gold),
        "pool_size": len(pool),
    }
    for window in windows:
        report[f"recall@{window}"] = round(recall_at(window), 4)
    report["recall@full"] = round(recall_at(len(pool)), 4)
    delta = report["recall@300"] - report["recall@100"]
    report["delta_pp"] = round(delta * 100, 2)
    report["recommend_scan_limit"] = 300 if delta * 100 >= 2.0 else "tag_only"
    return report


def _iter_eval_records(path: str):
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            gold = record.get("gold") or record.get("gold_doc_ids") or []
            filtered = record.get("filtered") or record.get("ranked") or []
            doc_ids = [
                item.get("doc_id") or item.get("id") if isinstance(item, dict) else item
                for item in filtered
            ]
            yield str(record.get("question_id") or record.get("qid") or ""), gold, [
                d for d in doc_ids if d
            ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="JEV-E2 离线 Top100/300 召回差测算辅助",
    )
    parser.add_argument(
        "--eval-recall-gap", dest="eval_path", required=True,
        help="评测候选分数快照 JSONL（每行含 question_id/gold/filtered）",
    )
    args = parser.parse_args(argv)

    reports: list[dict] = []
    mean_recall100 = 0.0
    mean_recall300 = 0.0
    count = 0
    for qid, gold, filtered in _iter_eval_records(args.eval_path):
        report = compute_recall_gap_report(filtered, gold)
        report["question_id"] = qid
        reports.append(report)
        mean_recall100 += report["recall@100"]
        mean_recall300 += report["recall@300"]
        count += 1
    summary = {
        "question_count": count,
        "mean_recall@100": round(mean_recall100 / count, 4) if count else 0.0,
        "mean_recall@300": round(mean_recall300 / count, 4) if count else 0.0,
        "mean_delta_pp": round(
            (mean_recall300 - mean_recall100) * 100 / count, 2
        ) if count else 0.0,
        "recommend_scan_limit": (
            300 if count and (mean_recall300 - mean_recall100) * 100 / count >= 2.0
            else "tag_only"
        ),
        "per_question": reports,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
