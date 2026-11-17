#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check-authority 权威候选三源合一提取（T2 独占模块）。

从 `merged_overview` 文本确定性提取权威候选，三源命中：
- 来源 A（标题词匹配）：中英文双语权威词表（原 15 个英文词一字不漏保留，
  确保英文评测集 100% 向后兼容；新增 24 个中文词消除中文失明）；
- 来源 B（概览行尾徽标捕获）：识别行尾 `[权威角色:...]` 徽标（README 3.3 契约，
  T4 渲染），提取 authority_role 加入命中原因；
- 来源 C（`doc_skeleton` 原生标量列兜底）：调用方传入批量查询器，对概览中
  出现的全部 `[f###]` 查询 `(jev_doc_type, jev_doc_type_conf, jev_is_registry)`，
  即使 E2 未开启，只要索引带 M1 先验列，弱标题权威文档与汇总登记表仍 100% 命中。

返回 JSON 向后兼容：保留 `ok` / `authority_total` / `authority_candidates`
（每项 `node_id` / `tier` / `score` / `title` / `matched_terms`）、`terms`、
`hint`，新增可选字段 `jev_doc_type` / `jev_is_registry` / `match_sources` /
`authority_role`。只做提取，不做"已读/未读"判定——已读状态只有 agent 自己
掌握（read-doc 记录），由 agent 对照本清单逐条标记。
"""
from __future__ import annotations

import re
from typing import Callable, Optional

# 原 15 个英文权威词一字不漏（英文评测集向后兼容红线）
AUTHORITY_TERMS_EN = (
    "manual", "handbook", "operating", "sla", "policy", "prd",
    "acceptance", "experiment lab", "runbook", "playbook", "ten-step",
    "final", "approval", "decision", "terms",
)
# 新增中文权威词（消除中文办公文档 100% 失明）
AUTHORITY_TERMS_ZH = (
    "手册", "制度", "规范", "办法", "规定", "政策", "规程", "预案", "指南",
    "操作指引", "需求规格", "技术规格", "架构决议", "验收标准", "服务等级",
    "协议", "合同", "最终条款", "决议", "批复", "名录", "台账", "花名册", "汇总表",
)
AUTHORITY_TERMS = AUTHORITY_TERMS_EN + AUTHORITY_TERMS_ZH

# 权威体裁枚举（与 doc_role_classifier.AUTHORITATIVE_DOC_TYPES 契约冻结值一致；
# common 层不反向依赖 watch_dog，故此处按 README 3.2 契约独立固化）
AUTHORITATIVE_DOC_TYPES = frozenset(
    {"policy_norm", "runbook_sop", "architecture_spec", "contract_sla"}
)

# 权威角色中文显示名映射（README 3.3 契约，T2 与 T4 共用）
ROLE_DISPLAY_NAMES = {
    "policy_norm": "正式制度规范",
    "runbook_sop": "运维规程SOP",
    "architecture_spec": "架构技术规格",
    "contract_sla": "合同协议SLA",
}
# 正向权威/登记徽标白名单（含 T4 E2 在线 normative 显示名「正式规范」）；
# 显式排除 T4 对 tentative 输出的警示徽标「草案/示例」等非权威角色。
POSITIVE_BADGE_ROLES = frozenset({
    *ROLE_DISPLAY_NAMES.values(),
    "汇总登记表",
    "正式规范",
})

_TIER1_DOC_RE = re.compile(
    r"^│\s*├── \[(?P<gid>f[0-9a-z]+)\] (?P<title>.*?)  \(命中 \d+ 处 \| 综合分: (?P<score>[0-9.]+)\)"
)
_TIER2_DOC_RE = re.compile(
    r"^- \[(?P<gid>f[0-9a-z]+)\] (?P<title>.*?) \(score=(?P<score>[0-9.]+)"
)
_DIR_RE = re.compile(r"^├── \[DIR\] (?P<path>.+?)/$")
_STAR_HEADER_RE = re.compile(r"^#+.*优先精读建议")
_ANY_HEADER_RE = re.compile(r"^#+\s")
_STAR_LINE_RE = re.compile(r"^-\s*\[(?P<gid>f[0-9a-z]+)\]\s+(?P<rest>.+)$")
_BADGE_TOKEN_RE = re.compile(r"\[[^\[\]]*\]")
_ROLE_BADGE_RE = re.compile(r"权威角色[:：]\s*([^|\[\]]+)")
_KNOWN_BADGE_KEYS = ("权威角色", "实体吻合", "限定", "灰区晋升")


def _strip_badge_tail(rest: str) -> str:
    """剥掉行尾的紧凑方括号徽标（含 权威角色/实体吻合/限定/灰区晋升 键的尾随 token）。"""
    title = rest.strip()
    while True:
        tokens = _BADGE_TOKEN_RE.findall(title)
        if not tokens:
            break
        last = tokens[-1]
        if not title.endswith(last):
            break
        if not any(k in last for k in _KNOWN_BADGE_KEYS):
            break
        title = title[: len(title) - len(last)].rstrip()
    return title


def _is_authoritative_badge_role(role_text: str) -> bool:
    if not role_text:
        return False
    parts = [p.strip() for p in role_text.split("/") if p.strip()]
    return bool(parts) and all(p in POSITIVE_BADGE_ROLES for p in parts)


def _extract_badge_role(line: str) -> str:
    m = _ROLE_BADGE_RE.search(line)
    if not m:
        return ""
    role = m.group(1).strip()
    return role if _is_authoritative_badge_role(role) else ""


def parse_overview_docs(text: str) -> tuple[list[dict], set[str]]:
    """解析 merged_overview 文本中的全部文档行；返回 (记录列表, 出现过的 gid 集合)。

    记录字段：node_id / tier(0=★优先精读建议, 1=Tier1, 2=Tier2) / score /
    title(已剥徽标尾巴) / authority_role(行尾徽标权威角色，可空) / path(Tier1)。
    """
    records: list[dict] = []
    star_records: list[dict] = []
    seen: set[str] = set()
    cur_dir = ""
    in_star = False
    for line in text.splitlines():
        if _STAR_HEADER_RE.match(line):
            in_star = True
            continue
        if _ANY_HEADER_RE.match(line):
            in_star = False
        dir_m = _DIR_RE.match(line)
        if dir_m:
            cur_dir = dir_m.group("path")
            continue
        tier = None
        m = _TIER1_DOC_RE.match(line)
        if m:
            tier = 1
        else:
            m = _TIER2_DOC_RE.match(line)
            if m:
                tier = 2
        if m and tier is not None:
            gid = m.group("gid")
            if gid in seen:
                continue
            seen.add(gid)
            records.append({
                "node_id": gid,
                "tier": tier,
                "score": float(m.group("score")),
                "title": m.group("title").strip(),
                "authority_role": _extract_badge_role(line),
                "path": cur_dir if tier == 1 else "",
            })
            continue
        if in_star:
            star_m = _STAR_LINE_RE.match(line)
            if star_m:
                star_records.append({
                    "node_id": star_m.group("gid"),
                    "tier": 0,
                    "score": 0.0,
                    "title": _strip_badge_tail(star_m.group("rest")),
                    "authority_role": _extract_badge_role(line),
                    "path": "",
                })
    # ★ 优先精读建议行放最前，但不覆盖已解析到的 Tier1/Tier2 富信息条目：
    # 先解析正文行（带命中数/综合分/路径），星标区仅补充未出现过的 gid
    star_seen: set[str] = set()
    for rec in star_records:
        if rec["node_id"] in seen or rec["node_id"] in star_seen:
            continue
        star_seen.add(rec["node_id"])
        records.insert(0, rec)
    return records, seen | star_seen


def _skeleton_hit(role: Optional[dict]) -> tuple[bool, str, bool]:
    """来源 C 判定：返回 (是否命中, jev_doc_type, jev_is_registry)。"""
    if not role:
        return False, "", False
    doc_type = str(role.get("jev_doc_type") or "")
    is_registry = bool(role.get("jev_is_registry") or False)
    return doc_type in AUTHORITATIVE_DOC_TYPES or is_registry, doc_type, is_registry


def _role_display(doc_type: str, is_registry: bool) -> str:
    parts = []
    if doc_type in ROLE_DISPLAY_NAMES:
        parts.append(ROLE_DISPLAY_NAMES[doc_type])
    if is_registry:
        parts.append("汇总登记表")
    return "/".join(parts)


def extract_authority_candidates(
    text: str,
    *,
    skeleton_lookup: Optional[Callable[[list[str]], dict[str, dict]]] = None,
) -> dict:
    """三源合一提取权威候选；skeleton_lookup 为 doc_ids -> {doc_key: 角色列} 批量查询器。

    输入为空时返回 {"ok": False, "error": "empty input: ..."}，与原命令行为一致。
    """
    if not (text or "").strip():
        return {
            "ok": False,
            "error": "empty input: pass --file or pipe merged_overview",
        }

    records, all_ids = parse_overview_docs(text)
    skeleton_roles: dict[str, dict] = {}
    if skeleton_lookup is not None and all_ids:
        try:
            skeleton_roles = skeleton_lookup(sorted(all_ids)) or {}
        except Exception:  # 来源 C 是可选兜底，任何失败都不影响 A/B 两源
            skeleton_roles = {}

    candidates: list[dict] = []
    for rec in records:
        title = rec["title"]
        # 只匹配标题：目录名带 runbooks/policies 是常态，目录匹配会把整目录
        # 文档灌进清单（评测实测噪声），path 仅作输出参考不参与命中
        matched = [t for t in AUTHORITY_TERMS if t in title.lower()]
        sources: list[str] = []
        if matched:
            sources.append("title_term")
        sk_role = skeleton_roles.get(rec["node_id"])
        sk_hit, sk_doc_type, sk_registry = _skeleton_hit(sk_role)
        if sk_hit:
            sources.append("doc_skeleton")
        if rec["authority_role"]:
            sources.append("badge")
        if not sources:
            continue
        entry = {
            "node_id": rec["node_id"],
            "tier": rec["tier"],
            "score": rec["score"],
            "title": title,
            "matched_terms": matched,
            "jev_doc_type": sk_doc_type,
            "jev_is_registry": sk_registry,
            "match_sources": sources,
        }
        if rec["authority_role"]:
            entry["authority_role"] = rec["authority_role"]
        elif sk_hit:
            entry["authority_role"] = _role_display(sk_doc_type, sk_registry)
        if rec["path"]:
            entry["path"] = rec["path"]
        candidates.append(entry)

    # ★/Tier1 优先、同 Tier 按分数降序——与 resolve 的展示顺序对齐，便于逐条对账
    candidates.sort(key=lambda c: (c["tier"], -c["score"]))
    return {
        "ok": True,
        "authority_total": len(candidates),
        "authority_candidates": candidates,
        "terms": list(AUTHORITY_TERMS),
        "hint": (
            "逐条对照 read-doc 记录标记已读/未读；未读条目必须 read-doc "
            "或逐条给出不读理由后才可进入 Step 3"
        ),
    }
