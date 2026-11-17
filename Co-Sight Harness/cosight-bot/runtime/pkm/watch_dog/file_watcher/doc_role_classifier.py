#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M1 构建期文档角色先验（小模型 Qwen 实现，T2 独占模块）。

两级漏斗（对应主方案第 3.6 节《节点 M1》）：
1. 高置信中英文静态规则快筛 `classify_by_static_rules`：零网络开销，只匹配
   文档标题与 H1 标题（严禁匹配父目录名，防止整个 `policies/` 目录下的闲聊
   草稿被误标）。M1 小模型未配置时也能立即解决中文权威文档 100% 失明问题。
2. 弱标题文档单篇一请求并发调用 OpenAI 兼容小模型（默认 Qwen3_6-35B-A3B）
   `classify_weak_docs`：读取首 token 的 logprobs 得到体裁字母概率与登记表
   Y/N 概率；模型未配置或不可用时记录降级日志并落默认空标签，绝不中断
   SectionIndex 构建主流程。

向量解耦红线：产出的角色标签只写 `doc_skeleton` 原生标量列与 `doc_meta`
JSON，绝不拼入 `structure_embedding_text` 或 `contextual_chunk_embedding_text`。
列名沿用 `jev_doc_type` / `jev_doc_type_conf` / `jev_is_registry`（Schema V3 已固化）。
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import requests

from common.logging_setup import log_event

logger = logging.getLogger("doc_role_classifier")

DOC_TYPES = (
    "policy_norm",        # 正式制度/管理规定/合规政策/手册
    "runbook_sop",        # 运维操作规程/应急预案/SOP/Playbook/十步法
    "architecture_spec",  # 技术规格/PRD/已批复ADR/验收标准
    "contract_sla",       # 签署合同/SOW/SLA/最终条款
    "incident_ticket",    # 单次故障复盘/Postmortem/工单
    "meeting_comm",       # 普通会议纪要/周报/邮件/群聊讨论
    "other",              # 其他普通资料
)
AUTHORITATIVE_DOC_TYPES = frozenset(
    {"policy_norm", "runbook_sop", "architecture_spec", "contract_sla"}
)

# 弱标题缓冲窗口：全量构建按 100 篇集中分类（与 BGE 向量化重叠执行）
WEAK_BUFFER_DOCS = 100
WEAK_FIRST_PARAGRAPH_CHARS = 400
WEAK_OUTLINE_MAX = 12

M1_QUESTION_SET_VERSION = "office-m1-llm-v1"
# 阈值取自 200 篇真实弱标题文档对内网 JEV 参照的标定：p_letter>=0.70 时覆盖约 75%、
# 与参照一致率约 93%；登记表无真实正例，0.50 仅由合成样本定下，且与静态规则取并集。
M1_THRESHOLDS: dict[str, float] = {
    "doc_type_choice_min": 0.70,
    "is_registry_min": 0.50,
}
M1_DEFAULT_WORKERS = 8
M1_DEFAULT_TIMEOUT_S = 60.0
M1_MAX_ATTEMPTS = 2

_LETTER_TO_TYPE = {
    "A": "policy_norm", "B": "runbook_sop", "C": "architecture_spec",
    "D": "contract_sla", "E": "incident_ticket", "F": "meeting_comm",
    "G": "other", "H": "unknown",
}
_M1_SYSTEM_PROMPT = (
    "你是企业文档体裁分类器。只根据给定的标题、路径、章节大纲和首段判断，不要臆测未给出的内容。\n"
    "体裁选项：\n"
    "A 正式制度或合规政策（正式制度、管理规定、合规政策、员工手册，以及明确“定义/规定”组织级规则与流程的规范性文档）\n"
    "B 规定具体线上操作、故障切换或应急处置流程的运维规程/SOP/Runbook\n"
    "C 技术规格、PRD 或 ADR（系统/产品设计、方案、评审、验收标准）\n"
    "D 合同、SOW 或 SLA\n"
    "E 单次故障复盘或工单\n"
    "F 普通会议纪要、周报或邮件/聊天讨论\n"
    "G 其他普通资料（个人笔记、草稿、调研、分析、基准测试、培训或增长类方案等）\n"
    "H 信息不足，无法判断\n"
    "另外判断该文档主体是否为“按行枚举多条同类实体的登记表/主台账”"
    "（如供应商名录、资产台账、服务清单、审批汇总表），是为 Y，否为 N。\n"
    "只输出两个字符，以空格分隔：体裁字母 和 Y/N，例如：F N。不要输出任何其他内容。"
)

# ---------------------------------------------------------------------------
# 第一级漏斗：高置信中英文静态规则快筛
# ---------------------------------------------------------------------------

# 草稿/废弃反例词：命中即交由 M1 小模型看正文首段（小模型未配置时标 ""），绝不静态判权威类
_NEGATIVE_EN_RE = re.compile(
    r"\b(draft|rfc|wip|proposal|deprecated|obsolete|template|sample)\b", re.IGNORECASE
)
_NEGATIVE_ZH_RE = re.compile(r"草案|征求意见稿|讨论稿|模板|作废|废弃")

# 高置信体裁词表：(doc_type, 英文词, 中文词)；英文词按词边界匹配，中文词子串匹配
_GENRE_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "runbook_sop",
        ("runbook", "playbook", "ten-step", "operating manual", "sop",
         "failover procedure"),
        ("操作规程", "应急预案", "运维手册", "处置规程", "作业指导书", "标准操作流程"),
    ),
    (
        "policy_norm",
        ("handbook", "policy", "compliance standard", "governance"),
        ("管理制度", "管理办法", "管理规定", "合规政策", "实施细则", "行为准则", "员工手册"),
    ),
    (
        "architecture_spec",
        ("prd", "product requirements", "acceptance criteria", "experiment lab",
         "architecture decision"),
        ("需求规格说明书", "技术规格书", "架构决议", "验收标准", "接口规范"),
    ),
    (
        "contract_sla",
        ("sla", "service level agreement", "final terms",
         "master services agreement", "sow"),
        ("服务等级协议", "签署合同", "补充协议", "最终条款", "采购合同"),
    ),
)

# 静态登记表（Registry）快筛词表：标题命中 + 骨架存在 row_count>=5 的表格才标记
_REGISTRY_EN_RE = re.compile(
    r"\b(registry|roster|master list|inventory|catalog)\b", re.IGNORECASE
)
_REGISTRY_ZH_RE = re.compile(r"名录|台账|花名册|汇总表|资产清单")

_GENRE_EN_RES: dict[str, tuple[re.Pattern, ...]] = {
    doc_type: tuple(
        re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)
        for term in terms
    )
    for doc_type, terms, _ in _GENRE_RULES
}
_GENRE_ZH_RES: dict[str, tuple[re.Pattern, ...]] = {
    doc_type: tuple(re.compile(re.escape(term)) for term in zh_terms)
    for doc_type, _, zh_terms in _GENRE_RULES
}


def _title_candidates(title: str, sk: Optional[dict]) -> list[str]:
    """构建匹配候选：文档标题（去 .md 后缀）+ H1 级章节标题；绝不取父目录名。"""
    candidates = [title.strip()]
    if title.lower().endswith(".md"):
        candidates.append(title[:-3].strip())
    for section in (sk or {}).get("sections", []) or []:
        if int(section.get("level", 0) or 0) == 1:
            name = str(section.get("title") or section.get("header_path") or "").strip()
            if name:
                candidates.append(name)
    return [c for c in candidates if c]


def classify_by_static_rules(rel_path: str, title: str, sk: Optional[dict]) -> Optional[dict]:
    """高置信中英文静态规则快筛；未命中返回 None（弱信号标题，进入小模型队列）。

    - 只匹配标题与 H1 标题，严禁匹配父目录名；
    - 含草稿/废弃反例词时不直接判权威类（返回 None）；
    - `sk` 缺省（标题预筛场景）时跳过登记表表格证据校验，登记表词命中视为未命中；
    - 静态命中（含登记表快筛）即视为被第一级漏斗消化，不再进入小模型队列。
    """
    candidates = _title_candidates(title, sk)
    joined = "\n".join(candidates)
    if _NEGATIVE_EN_RE.search(joined) or _NEGATIVE_ZH_RE.search(joined):
        return None

    matched_rule = ""
    for genre, _, _ in _GENRE_RULES:
        if any(p.search(c) for p in _GENRE_EN_RES[genre] for c in candidates):
            matched_rule = genre
            break
        if any(p.search(c) for p in _GENRE_ZH_RES[genre] for c in candidates):
            matched_rule = genre
            break
    doc_type = matched_rule

    is_registry = False
    if sk is not None and (
        any(p.search(c) for p in (_REGISTRY_EN_RE,) for c in candidates)
        or any(p.search(c) for p in (_REGISTRY_ZH_RE,) for c in candidates)
    ):
        if any(int(t.get("row_count", 0) or 0) >= 5 for t in sk.get("tables", []) or []):
            is_registry = True

    if not doc_type and not is_registry:
        return None
    return {
        "jev_doc_type": doc_type,
        "jev_doc_type_conf": 1.0 if doc_type else 0.0,
        "jev_is_registry": is_registry,
        "source": "rule",
        "matched_rule": matched_rule or ("registry" if is_registry else ""),
    }


def default_role_info(source: str = "skipped") -> dict:
    """默认空标签：未分类/降级/跳过时写入 doc_skeleton 的兜底角色。"""
    return {
        "jev_doc_type": "",
        "jev_doc_type_conf": 0.0,
        "jev_is_registry": False,
        "source": source,
    }


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def m1_config() -> Optional[dict]:
    """解析 M1 小模型配置；缺少模型名/端点/密钥或显式关闭时返回 None（M1 跳过）。

    端点与密钥缺省复用主配置 OPENAI_BASE_URL / OPENAI_API_KEY（同一内网网关），
    模型名必须单独配置（COSIGHTBOT_M1_MODEL），避免误用主 agent 的大模型做海量构建分类。
    """
    if _env("COSIGHTBOT_M1_ENABLED") in ("0", "false", "False", "off"):
        return None
    model = _env("COSIGHTBOT_M1_MODEL")
    base_url = _env("COSIGHTBOT_M1_BASE_URL") or _env("OPENAI_BASE_URL")
    api_key = _env("COSIGHTBOT_M1_API_KEY") or _env("OPENAI_API_KEY")
    if not (model and base_url and api_key):
        return None
    try:
        workers = max(1, int(_env("COSIGHTBOT_M1_WORKERS") or M1_DEFAULT_WORKERS))
    except ValueError:
        workers = M1_DEFAULT_WORKERS
    try:
        timeout = float(_env("COSIGHTBOT_M1_TIMEOUT_S") or M1_DEFAULT_TIMEOUT_S)
    except ValueError:
        timeout = M1_DEFAULT_TIMEOUT_S
    return {
        "model": model,
        "url": base_url.rstrip("/") + "/chat/completions",
        "api_key": api_key,
        "workers": workers,
        "timeout": timeout,
    }


def m1_stage_enabled() -> bool:
    """M1 开关：小模型三项配置齐全且未显式关闭。"""
    return m1_config() is not None


# ---------------------------------------------------------------------------
# 弱标题轻量骨架
# ---------------------------------------------------------------------------

def _strip_frontmatter(text: str) -> str:
    if text.lstrip().startswith("---"):
        lines = text.splitlines()
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return "\n".join(lines[i + 1:])
    return text


def _read_body_head(md_path: Optional[Path], limit_bytes: int = 4096) -> str:
    if md_path is None:
        return ""
    try:
        with open(md_path, "rb") as fh:
            raw = fh.read(limit_bytes)
        return _strip_frontmatter(raw.decode("utf-8", errors="replace"))
    except OSError:
        return ""


def build_weak_item(doc_key: str, rel_path: str, title: str, sk: dict,
                    md_path: Optional[Path] = None) -> dict:
    """抽取弱标题文档轻量骨架（严格控制在 ~550 字符内，绝不读取整篇长文）。"""
    body_head = _read_body_head(md_path)
    first_paragraph = body_head[:WEAK_FIRST_PARAGRAPH_CHARS]
    outline = [
        s["header_path"]
        for s in (sk.get("sections", []) or [])
        if 1 <= int(s.get("level", 0) or 0) <= 3
    ][:WEAK_OUTLINE_MAX]
    return {
        "doc_id": doc_key,
        "path": rel_path,
        "title": title,
        "h1_h3_outline": outline,
        "first_paragraph": first_paragraph,
    }


# ---------------------------------------------------------------------------
# 第二级漏斗：弱标题文档单篇一请求并发小模型分类
# ---------------------------------------------------------------------------

# 内网网关直连：显式忽略环境代理，避免企业代理改写或拦截内网 OpenAI 兼容请求。
_SESSION = requests.Session()
_SESSION.trust_env = False


class M1LlmUnavailable(RuntimeError):
    """小模型请求在重试后仍失败。"""


def _letter_distribution(top_logprobs: list, valid: set[str]) -> dict[str, float]:
    probs: dict[str, float] = {}
    for entry in top_logprobs or []:
        token = str(entry.get("token") or "").strip().upper()
        logprob = entry.get("logprob")
        if token in valid and isinstance(logprob, (int, float)):
            probs[token] = probs.get(token, 0.0) + math.exp(logprob)
    total = sum(probs.values())
    return {k: v / total for k, v in probs.items()} if total > 0 else {}


def _parse_chat_response(payload: dict) -> dict:
    """从 chat/completions 响应抽取体裁字母概率与登记表概率。

    无 logprobs 时无法给出置信度，conf 记 0.0 使体裁落 unknown（保守）。
    """
    choice = (payload.get("choices") or [{}])[0]
    text = str((choice.get("message") or {}).get("content") or "").strip().upper()
    tokens = ((choice.get("logprobs") or {}).get("content")) or []
    letter_probs: dict[str, float] = {}
    p_reg: Optional[float] = None
    if tokens:
        letter_probs = _letter_distribution(
            tokens[0].get("top_logprobs"), set(_LETTER_TO_TYPE)
        )
        for entry in tokens[1:]:
            if str(entry.get("token") or "").strip().upper() in ("Y", "N"):
                yn = _letter_distribution(entry.get("top_logprobs"), {"Y", "N"})
                p_reg = yn.get("Y")
                break
    match = re.match(r"\s*([A-H])", text)
    letter = match.group(1) if match else None
    if letter is None and letter_probs:
        letter = max(letter_probs, key=letter_probs.get)
    return {
        "letter": letter,
        "p_letter": letter_probs.get(letter) if letter else None,
        "p_reg": p_reg,
    }


def _result_from_parsed(parsed: dict) -> dict:
    letter = parsed.get("letter")
    p_letter = parsed.get("p_letter")
    doc_type = _LETTER_TO_TYPE.get(letter or "", "unknown")
    if (
        doc_type == "unknown"
        or p_letter is None
        or p_letter < M1_THRESHOLDS["doc_type_choice_min"]
    ):
        doc_type = "unknown"
    p_reg = parsed.get("p_reg")
    return {
        "jev_doc_type": doc_type,
        "jev_doc_type_conf": round(float(p_letter or 0.0), 4),
        "jev_is_registry": p_reg is not None and p_reg >= M1_THRESHOLDS["is_registry_min"],
        "source": "llm",
    }


def _post_chat(cfg: dict, item: dict) -> dict:
    """单篇弱标题文档请求；网络/5xx/429 重试，其余错误直接抛出。

    必须关闭思考模式：Qwen3 默认开启 thinking，会使单次延迟与 token 数暴涨一个数量级。
    """
    body = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": _M1_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(item, ensure_ascii=False)},
        ],
        "temperature": 0,
        "max_tokens": 8,
        "logprobs": True,
        "top_logprobs": 10,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    headers = {"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}
    last_exc: Exception = M1LlmUnavailable("no attempt")
    for attempt in range(M1_MAX_ATTEMPTS):
        try:
            resp = _SESSION.post(cfg["url"], headers=headers, json=body, timeout=cfg["timeout"])
            if resp.status_code in (429, 500, 502, 503, 504):
                last_exc = M1LlmUnavailable(f"HTTP {resp.status_code}")
            else:
                resp.raise_for_status()
                return resp.json()
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
        if attempt + 1 < M1_MAX_ATTEMPTS:
            time.sleep(1.0 + attempt)
    raise M1LlmUnavailable(f"{type(last_exc).__name__}: {last_exc}")


def _classify_one(cfg: dict, item: dict) -> dict:
    try:
        return _result_from_parsed(_parse_chat_response(_post_chat(cfg, item)))
    except Exception as exc:  # 单篇失败只影响自身，绝不中断构建
        log_event(
            logger, "m1:llm:degraded", level=logging.WARNING,
            doc_id=str(item.get("doc_id")), error=f"{type(exc).__name__}: {str(exc)[:200]}",
        )
        return default_role_info("degraded")


def classify_weak_docs(items: list[dict]) -> dict[str, dict]:
    """弱标题文档并发小模型分类；返回 {doc_key: role_info}。

    - 小模型未配置/显式关闭时返回默认空标签（source=skipped），零网络；
    - 每篇一请求，`COSIGHTBOT_M1_WORKERS` 并发（默认 8）；输入为 `build_weak_item`
      的 {title, path, h1-h3 大纲, 首段 400 字}；
    - 单篇失败记 `m1:llm:degraded` 并落默认空标签，绝不中断构建主流程。
    """
    if not items:
        return {}
    cfg = m1_config()
    if cfg is None:
        return {str(it["doc_id"]): default_role_info("skipped") for it in items}
    workers = min(cfg["workers"], len(items))
    if workers <= 1:
        results = [_classify_one(cfg, it) for it in items]
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="m1-llm") as pool:
            results = list(pool.map(lambda it: _classify_one(cfg, it), items))
    return {str(it["doc_id"]): role for it, role in zip(items, results)}
