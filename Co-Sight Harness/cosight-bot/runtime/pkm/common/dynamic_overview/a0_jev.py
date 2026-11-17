#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""节点 JEV-E1：A0 命中三档快筛与去预览污染（T3 独占模块）。

用内网 JEV（Ntele-decision-V1）单次并行求值：
- ``hit_quality``（choice，仅 FULL_HIT / PARTIAL_HIT / MISS 三档，不判 INTENT_CORRECTION）；
- ``direct_answer_ready``（noul，内网二值极化下快速停跳门槛 0.95）；
- 动态要素覆盖组 ``clue_{idx}``（noul，上限 8 个）。

全部条件同时满足时 ~300ms 秒停（完全不调用生成式大模型）；否则仅让轻量
LLM 生成二跳检索词 ``next_queries_Q1``，并强制清空 ``intermediate_result_A``
（答案草稿预览），从根源上消除未读全文前的幻觉锚定污染（S-03）。

降级纪律：JEV 不可用时有痕软降级回退 legacy LLM A0（预览同样清空）；
轻量 Q1 LLM 失败时用 missing_clues 构造确定性兜底检索词，绝不退化为盲目单跳。
"""
from __future__ import annotations

import logging
import os
import re
import time

from common import jev_client
from common.jev_questions import (
    E1_QUESTION_SET_VERSION as QUESTION_SET_VERSION,
    E1_THRESHOLDS,
)
from common.logging_setup import log_event

from .models import QueryPack

logger = logging.getLogger("dynamic_overview.a0_jev")

#: 阶段 0 离线标定期可用环境变量无侵入微调（缺省取内网安全刻度）。
_ENV_READY_MIN = "COSIGHTBOT_JEV_E1_READY_MIN"
_ENV_CLUE_MIN = "COSIGHTBOT_JEV_E1_CLUE_MIN"
_ENV_FULL_HIT_MIN = "COSIGHTBOT_JEV_E1_FULLHIT_MIN"

#: 动态要素上限与证据包截断上限（state 侧防超限，不截断单条候选语义）。
MAX_CLUES = 8
MAX_EVIDENCE_CHARS = 45_000
MAX_DIR_MAP_CHARS = 6_000

#: 纯标点/符号噪声（无任何字母数字汉字词字符）。
_PUNCT_NOISE_RE = re.compile(r"^[\W_]+$", re.UNICODE)

_ALLOWED_HOP_QUALITY = ("FULL_HIT", "PARTIAL_HIT", "MISS")


def _thresholds() -> dict:
    """每次调用动态读取阈值（支持阶段 0 标定期环境变量微调）。"""
    th = dict(E1_THRESHOLDS)
    for key, env_name in (
        ("choice_full_hit_min", _ENV_FULL_HIT_MIN),
        ("direct_ready_min", _ENV_READY_MIN),
        ("clue_covered_min", _ENV_CLUE_MIN),
    ):
        raw = (os.environ.get(env_name) or "").strip()
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        if 0.0 <= value <= 1.0:
            th[key] = value
    return th


def _is_noise(text: str) -> bool:
    """长度 < 2 或纯标点符号的字符串视为噪声要素。"""
    return len(text) < 2 or bool(_PUNCT_NOISE_RE.match(text))


def _extract_clues(q_orig: QueryPack) -> list[tuple[str, str]]:
    """按 identifier -> entity -> constraint 优先级抽取动态要素（去重、限 8 个）。

    边界保护：若调用方只传了 ``--question`` 而未传任何槽位（clues 为空），
    自动从 ``positive_terms()`` 中选取前 4 个长度 >= 3 的高区分度实词/标识符
    作为兜底要素检查项，防止空要素列表放水导致复杂单句多问提前假停。
    """
    clues: list[tuple[str, str]] = []
    seen: set[str] = set()
    for kind, values in (
        ("identifier", q_orig.identifiers),
        ("entity", q_orig.entities),
        ("constraint", q_orig.constraints),
    ):
        for value in values or []:
            text = (value or "").strip()
            if _is_noise(text):
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            clues.append((kind, text))
            if len(clues) >= MAX_CLUES:
                return clues
    if not clues:
        for term in q_orig.positive_terms():
            text = (term or "").strip()
            if len(text) < 3 or _PUNCT_NOISE_RE.match(text):
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            clues.append(("term", text))
            if len(clues) >= 4:
                break
    return clues


def _e1_jev_timeout(timeout: float) -> float:
    """E1 单批次 JEV 超时：默认取 min(调用方超时, COSIGHTBOT_JEV_TIMEOUT_S)。"""
    try:
        env_timeout = float(os.environ.get("COSIGHTBOT_JEV_TIMEOUT_S", "15"))
    except ValueError:
        env_timeout = 15.0
    if env_timeout <= 0:
        env_timeout = 15.0
    try:
        caller_timeout = float(timeout)
    except (TypeError, ValueError):
        caller_timeout = 15.0
    return max(0.1, min(caller_timeout, env_timeout))


def _ask_e1_jev(
    q_orig: QueryPack,
    evidence: str,
    directory_map: str,
    clues: list[tuple[str, str]],
    timeout: float,
) -> jev_client.JevAnswer:
    """组装单次并行 E1 请求（choice 三档 + direct_answer_ready + clue_* 组）。"""
    state = {
        "question": "；".join(q_orig.questions) if q_orig.questions else q_orig.primary_question,
        "query_slots": {
            "entities": list(q_orig.entities or []),
            "constraints": list(q_orig.constraints or []),
            "identifiers": list(q_orig.identifiers or []),
            "exclude": list(q_orig.exclude or []),
        },
        "directory_map": (directory_map or "")[:MAX_DIR_MAP_CHARS],
        "evidence_pack": (evidence or "")[:MAX_EVIDENCE_CHARS],
    }
    questions: dict = {
        "hit_quality": {
            "type": "choice",
            "instructions": (
                "仅依据 state.evidence_pack 中已展示的文档章节原文，判断其相对 "
                "state.question 的命中完备档位（严禁引入未展示内容做间接推理）。"
            ),
            "criteria": {
                "FULL_HIT": "证据包中的命中章节原文已直接、完整包含回答 state.question 全部核心问点所需的具体事实、数值或步骤依据。",
                "PARTIAL_HIT": "证据包已命中目标实体或部分子问题，但仍缺少特定限定条件、时间范围、具体配置值或对比方信息。",
                "MISS": "证据包与问题核心目标无关，仅命中泛泛背景词或同名异物对象。",
            },
        },
        "direct_answer_ready": {
            "type": "noul",
            "instructions": (
                "仅依据 state.evidence_pack 中已展示的文档章节原文（不脑补未展示章节），"
                "是否已经直接、完整地给出了回答 state.question 全部问点与限定条件"
                "所需的具体事实、数值或完整步骤？"
            ),
            "criteria": {
                "true": "已完整包含回答全部问点所需的直接原文依据，无需再检索其他文档",
                "false": "仍缺少部分问点、特定限定条件、对比方、完整流程步骤或权威定稿依据",
            },
        },
    }
    for idx, (kind, clue_text) in enumerate(clues):
        questions[f"clue_{idx}"] = {
            "type": "noul",
            "instructions": (
                f"state.evidence_pack 的文档章节原文中是否明确出现并实质讨论了"
                f"查询要素「{clue_text}」（类型：{kind}）？"
            ),
            "criteria": {
                "true": "原文明确出现并围绕该要素给出实质信息",
                "false": "原文未出现该要素，或仅在不相关的背景/目录名中擦边提及",
            },
        }
    return jev_client.ask(
        stage="E1",
        question_set_version=QUESTION_SET_VERSION,
        state=state,
        questions=questions,
        timeout=_e1_jev_timeout(timeout),
    )


def call_a0_q1_only(
    q_orig: QueryPack,
    evidence: str,
    *,
    doc_count: int,
    directory_map: str,
    jev_quality: str,
    missing_clues: list[str],
    timeout: float = 120.0,
) -> tuple[dict | None, str, float, int, dict]:
    """轻量二跳检索词生成（Q1 Generator）。

    只输出 ``unresolved_knowledge_gaps`` 与 ``next_queries_Q1`` 两个顶层键，
    严禁生成任何试答草稿或结论预览（输出 token 量较原 A0 下降 60%+）。

    Returns:
        (data, error, elapsed_ms, prompt_tokens, meta)
        data 为 None 时 error 说明原因，由调用方走确定性兜底或 legacy 回退。
    """
    from .a0 import _request_llm_json
    from .prompts import A0_Q1_ONLY_SYSTEM, build_a0_q1_only_user_prompt

    max_tokens = max(256, int(os.environ.get("COSIGHTBOT_DYNAMIC_A0_Q1_MAX_TOKENS", "1024")))
    user_prompt = build_a0_q1_only_user_prompt(
        q_orig, evidence,
        doc_count=doc_count, directory_map=directory_map,
        jev_quality=jev_quality, missing_clues=missing_clues,
    )
    return _request_llm_json(
        A0_Q1_ONLY_SYSTEM, user_prompt,
        tag="dynamic-a0-q1", default_max_tokens=max_tokens, timeout=timeout,
    )


def _parse_q1_payload(data: dict) -> tuple[list[str], dict]:
    """解析轻量 Q1 JSON；强制丢弃任何违规混入的 intermediate_result_A。"""
    gaps = [str(x) for x in (data.get("unresolved_knowledge_gaps") or []) if str(x).strip()]
    q1 = data.get("next_queries_Q1") if isinstance(data.get("next_queries_Q1"), dict) else {}
    return gaps, {
        "sub_questions": [str(x) for x in (q1.get("sub_questions") or []) if str(x).strip()],
        "key_terms": [str(x) for x in (q1.get("key_terms") or []) if str(x).strip()],
    }


def _merge_gaps(llm_gaps: list[str], missing_clues: list[str]) -> list[str]:
    """合并 LLM 缺口与 JEV 兜底缺失要素（保序去重）。"""
    merged: list[str] = []
    seen: set[str] = set()
    for item in [*llm_gaps, *missing_clues]:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            merged.append(item.strip())
    return merged


def _fallback_q1(q_orig: QueryPack, missing_clues: list[str]) -> dict:
    """missing_clues 确定性兜底二跳检索词（不依赖任何生成式大模型）。"""
    primary = (q_orig.primary_question or "").strip()
    tail = " ".join(missing_clues[:3]).strip()
    sub_questions = [f"{primary} {tail}".strip()] if (primary or tail) else []
    return {"sub_questions": sub_questions, "key_terms": list(missing_clues)}


def call_a0_jev(
    q_orig: QueryPack,
    evidence: str,
    *,
    doc_count: int,
    directory_map: str,
    timeout: float = 120.0,
) -> tuple[dict | None, str, float, int]:
    """E1 开关开启时的 ``call_a0`` 透明实现（返回四元组契约与 legacy 完全一致）。

    Returns:
        (payload, error, elapsed_ms, prompt_tokens)
        payload 为 None 时 error 说明原因，调用方走 degraded 单跳。
    """
    total_start = time.perf_counter()

    def elapsed_total() -> float:
        return round((time.perf_counter() - total_start) * 1000, 1)

    clues = _extract_clues(q_orig)
    clue_texts = [text for _, text in clues]

    # 分支 C：JEV 异常有痕软降级（回退 legacy LLM A0，仍清空预览草稿）。
    def degraded_to_legacy(exc: Exception) -> tuple[dict | None, str, float, int]:
        diag = jev_client.build_degraded_diag("E1", exc)
        log_event(logger, "a0:jev:degraded", level=logging.WARNING, **diag)
        from .a0 import _call_a0_legacy_llm
        payload, error, elapsed, tokens = _call_a0_legacy_llm(
            q_orig, evidence,
            doc_count=doc_count, directory_map=directory_map, timeout=timeout,
        )
        if payload is None:
            combined_err = (
                f"{error}; jev_e1_degraded: {exc}"
                if error else f"jev_e1_degraded: {exc}"
            )
            return None, combined_err, elapsed_total(), tokens
        payload = dict(payload)
        payload["intermediate_result_A"] = ""
        payload["jev"] = diag
        return payload, "", elapsed_total(), tokens

    # 证据包为空短路：无需请求 JEV，直接按 MISS 进入二跳词生成。
    if not (evidence or "").strip():
        log_event(logger, "a0:jev:empty_evidence", missing_clues=len(clue_texts))
        return _hop2_branch(
            q_orig, evidence, doc_count=doc_count, directory_map=directory_map,
            jev_quality="MISS", missing_clues=list(clue_texts),
            jev_base={
                "degraded": False,
                "stage": "E1",
                "question_set_version": QUESTION_SET_VERSION,
                "mode": "empty_evidence",
            },
            timeout=timeout,
            total_start=total_start,
        )

    try:
        ans = _ask_e1_jev(q_orig, evidence, directory_map, clues, timeout)
    except jev_client.JevUnavailable as exc:
        return degraded_to_legacy(exc)
    except Exception as exc:  # noqa: BLE001 - 任何未预期异常都走有痕软降级
        return degraded_to_legacy(exc)

    th = _thresholds()
    winner, winner_prob = jev_client.choice_winner(
        ans.answers.get("hit_quality"), allowed=_ALLOWED_HOP_QUALITY
    )
    p_ready = jev_client.probability(ans.answers.get("direct_answer_ready"))
    missing_clues: list[str] = []
    for idx, (_kind, clue_text) in enumerate(clues):
        p_clue = jev_client.probability(ans.answers.get(f"clue_{idx}"))
        if p_clue is None or p_clue < th["clue_covered_min"]:
            missing_clues.append(clue_text)

    # 分支 A：快速收敛秒停（三条件缺一不可，绝不调用生成式大模型）。
    fast_stop = (
        winner == "FULL_HIT"
        and winner_prob is not None
        and winner_prob >= th["choice_full_hit_min"]
        and p_ready is not None
        and p_ready >= th["direct_ready_min"]
        and not missing_clues
    )
    jev_base = {
        "degraded": False,
        "stage": "E1",
        "question_set_version": QUESTION_SET_VERSION,
        "winner": winner,
        "winner_prob": winner_prob,
        "direct_answer_ready": p_ready,
        "missing_clues": missing_clues,
        "latency_ms": ans.audit.get("latency_ms"),
    }
    if fast_stop:
        payload = {
            "hit_quality": "FULL_HIT",
            "intermediate_result_A": "",
            "unresolved_knowledge_gaps": [],
            "next_queries_Q1": {"sub_questions": [], "key_terms": []},
            "jev": {"mode": "fast_stop", **jev_base},
        }
        log_event(
            logger, "a0:jev:fast_stop",
            winner=winner, winner_prob=winner_prob,
            direct_answer_ready=p_ready, clue_count=len(clues),
            latency_ms=ans.audit.get("latency_ms"),
            duration_ms=elapsed_total(),
        )
        return payload, "", elapsed_total(), 0

    # 分支 B：二跳续检。FULL_HIT 但未达秒停三条件时强制降档为 PARTIAL_HIT，
    # 防止 engine.py 在 HOP2_SKIP_FULL_HIT=True 配置下被 FULL_HIT 误触发停跳。
    if winner in ("PARTIAL_HIT", "MISS"):
        effective_quality = winner
    else:
        effective_quality = "PARTIAL_HIT"
    log_event(
        logger, "a0:jev:hop2",
        winner=winner, winner_prob=winner_prob,
        direct_answer_ready=p_ready, effective_quality=effective_quality,
        missing_clues=len(missing_clues),
        missing_clues_preview=",".join(missing_clues[:4]),
    )
    return _hop2_branch(
        q_orig, evidence, doc_count=doc_count, directory_map=directory_map,
        jev_quality=effective_quality, missing_clues=missing_clues,
        jev_base={"mode": "hop2_q1", **jev_base}, timeout=timeout,
        total_start=total_start,
    )


def _hop2_branch(
    q_orig: QueryPack,
    evidence: str,
    *,
    doc_count: int,
    directory_map: str,
    jev_quality: str,
    missing_clues: list[str],
    jev_base: dict,
    timeout: float,
    total_start: float,
) -> tuple[dict | None, str, float, int]:
    """二跳续检：轻量 Q1 生成 + LLM 故障时的 missing_clues 确定性兜底。"""

    def elapsed_total() -> float:
        return round((time.perf_counter() - total_start) * 1000, 1)

    q1_data: dict | None = None
    q1_tokens = 0
    try:
        q1_data, q1_error, _q1_elapsed, q1_tokens, _q1_meta = call_a0_q1_only(
            q_orig, evidence,
            doc_count=doc_count, directory_map=directory_map,
            jev_quality=jev_quality, missing_clues=missing_clues, timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 - LLM 侧任何异常都走兜底
        log_event(logger, "a0:jev:q1:error", level=logging.WARNING,
                  error=f"{type(exc).__name__}: {exc}")
        q1_data = None
    if q1_data is None and missing_clues:
        # 二级兜底：生成式 LLM 拥塞/超时也不退化为盲目单跳，彻底消灭 degraded:a0。
        log_event(logger, "a0:jev:q1:fallback", level=logging.WARNING,
                  missing_clues=len(missing_clues),
                  missing_clues_preview=",".join(missing_clues[:4]))
        payload = {
            "hit_quality": jev_quality,
            "intermediate_result_A": "",
            "unresolved_knowledge_gaps": list(missing_clues),
            "next_queries_Q1": _fallback_q1(q_orig, missing_clues),
            "jev": {**jev_base, "q1_llm_fallback": True},
        }
        return payload, "", elapsed_total(), 0
    if q1_data is None:
        # missing_clues 也为空且 Q1 LLM 失败：回退 legacy LLM A0（仍清空预览），
        # 避免空 Q1 触发 engine 的 empty_Q1 单跳假停。
        from .a0 import _call_a0_legacy_llm
        payload, error, _elapsed, tokens = _call_a0_legacy_llm(
            q_orig, evidence,
            doc_count=doc_count, directory_map=directory_map, timeout=timeout,
        )
        if payload is None:
            return None, error, elapsed_total(), tokens
        payload = dict(payload)
        payload["intermediate_result_A"] = ""
        payload["jev"] = {**jev_base, "q1_llm_fallback": True, "legacy_llm_fallback": True}
        return payload, "", elapsed_total(), tokens

    llm_gaps, q1_payload = _parse_q1_payload(q1_data)
    payload = {
        "hit_quality": jev_quality,
        "intermediate_result_A": "",  # 强制恒为空串：彻底拔除答案草稿预览污染
        "unresolved_knowledge_gaps": _merge_gaps(llm_gaps, missing_clues),
        "next_queries_Q1": q1_payload,
        "jev": {**jev_base},
    }
    log_event(
        logger, "a0:jev:q1:done",
        quality=jev_quality, gaps=len(payload["unresolved_knowledge_gaps"]),
        q1_questions=len(q1_payload["sub_questions"]),
        q1_terms=len(q1_payload["key_terms"]),
        duration_ms=elapsed_total(), prompt_tokens=q1_tokens,
    )
    return payload, "", elapsed_total(), q1_tokens


def evaluate_e1_replay_samples(samples: list[dict]) -> dict:
    """阶段 0 离线回放假停率校验辅助（纯只读统计，不写任何索引）。

    样本字段：``q_orig``（QueryPack）、``evidence``、``directory_map``、
    ``need_hop2_ground_truth``（该样本真实需要二跳的人工标注真值）。

    门禁：``false_stop_rate``（真实需要二跳却被判 fast_stop 的比例）<= 3%。
    """
    total = 0
    errors = 0
    fast_stops = 0
    false_stops = 0
    p_ready_list: list[float] = []
    for sample in samples or []:
        try:
            payload, _error, _elapsed, _tokens = call_a0_jev(
                sample["q_orig"],
                sample.get("evidence") or "",
                doc_count=int(sample.get("doc_count") or 0),
                directory_map=sample.get("directory_map") or "",
                timeout=float(sample.get("timeout") or 15.0),
            )
        except Exception:  # noqa: BLE001 - 单样本异常只计数不中断回放
            errors += 1
            continue
        if payload is None:
            errors += 1
            continue
        total += 1
        jev = payload.get("jev") if isinstance(payload.get("jev"), dict) else {}
        if jev.get("mode") == "fast_stop":
            fast_stops += 1
            if sample.get("need_hop2_ground_truth"):
                false_stops += 1
        p_ready = jev.get("direct_answer_ready")
        if isinstance(p_ready, (int, float)) and not isinstance(p_ready, bool):
            p_ready_list.append(float(p_ready))
    p_ready_sorted = sorted(p_ready_list)

    def quantile(q: float) -> float | None:
        if not p_ready_sorted:
            return None
        pos = min(len(p_ready_sorted) - 1, max(0, round(q * (len(p_ready_sorted) - 1))))
        return round(p_ready_sorted[pos], 4)

    fast_stop_rate = fast_stops / total if total else 0.0
    false_stop_rate = false_stops / total if total else 0.0
    return {
        "samples": len(samples or []),
        "evaluated": total,
        "errors": errors,
        "fast_stop_count": fast_stops,
        "fast_stop_rate": round(fast_stop_rate, 4),
        "false_stop_count": false_stops,
        "false_stop_rate": round(false_stop_rate, 4),
        "false_stop_gate_pass": false_stop_rate <= 0.03,
        "p_ready_quantiles": {
            "p05": quantile(0.05), "p25": quantile(0.25), "p50": quantile(0.5),
            "p75": quantile(0.75), "p95": quantile(0.95),
        },
        "question_set_version": QUESTION_SET_VERSION,
        "thresholds": _thresholds(),
    }
