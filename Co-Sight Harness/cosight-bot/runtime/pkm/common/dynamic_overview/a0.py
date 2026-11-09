#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内部 A0 模型调用（黑盒）：OpenAI 兼容协议优先，Anthropic 回退。"""
from __future__ import annotations

import json
import logging
import os
import time

import requests

from common.cosight_runtime import resolve_runtime_llm_config
from common.logging_setup import log_event, preview_items, preview_text

from .models import QueryPack
from .prompts import A0_SYSTEM, build_a0_user_prompt
from .utils import estimate_tokens

logger = logging.getLogger("dynamic_overview.a0")

_ALLOWED_QUALITY = {"FULL_HIT", "PARTIAL_HIT", "MISS", "INTENT_CORRECTION"}


def _extract_json(text: str) -> dict | None:
    text = (text or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    # 推理模型可能在 JSON 前后输出大段 think 文本，且 think 里也含花括号；
    # 从后往前尝试 raw_decode，取第一个带 hit_quality 的完整对象。
    decoder = json.JSONDecoder()
    positions = [i for i, ch in enumerate(text) if ch == "{"]
    for start in reversed(positions):
        try:
            data, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and (
            "hit_quality" in data or "next_queries_Q1" in data
        ):
            return data
    return None


def _chat_url(base_url: str, anthropic: bool) -> str:
    base = (base_url or "").rstrip("/")
    if anthropic:
        if base.endswith("/messages"):
            return base
        if base.endswith("/v1"):
            return base + "/messages"
        return base + "/v1/messages"
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def _parse_payload(data: dict) -> dict:
    quality = str(data.get("hit_quality") or "PARTIAL_HIT").upper()
    if quality not in _ALLOWED_QUALITY:
        quality = "PARTIAL_HIT"
    q1 = data.get("next_queries_Q1")
    if not isinstance(q1, dict):
        q1 = {}
    return {
        "hit_quality": quality,
        "intermediate_result_A": str(data.get("intermediate_result_A") or ""),
        "unresolved_knowledge_gaps": [
            str(x) for x in (data.get("unresolved_knowledge_gaps") or []) if str(x).strip()
        ],
        "next_queries_Q1": {
            "sub_questions": [
                str(x) for x in (q1.get("sub_questions") or []) if str(x).strip()
            ],
            "key_terms": [
                str(x) for x in (q1.get("key_terms") or []) if str(x).strip()
            ],
        },
    }


def call_a0(
    q_orig: QueryPack,
    evidence: str,
    *,
    doc_count: int,
    directory_map: str,
    timeout: float = 120.0,
) -> tuple[dict | None, str, float, int]:
    """调用 A0。

    Returns:
        (payload, error, elapsed_ms, prompt_tokens)
        payload 为 None 时 error 说明原因，调用方走 degraded 单跳。
    """
    config = resolve_runtime_llm_config(tag="dynamic-a0")
    if not config:
        log_event(logger, "a0:config:error", level=logging.WARNING,
                  reason="config_unavailable")
        return None, "A0 LLM config unavailable (OPENAI_*/ANTHROPIC_* unset)", 0.0, 0
    base_url = config.get("base_url") or ""
    api_key = config.get("api_key") or ""
    model = config.get("model") or ""
    if not (base_url and api_key and model):
        log_event(logger, "a0:config:error", level=logging.WARNING,
                  reason="config_incomplete", source=config.get("_source"),
                  has_base_url=bool(base_url), has_api_key=bool(api_key), has_model=bool(model))
        return None, "A0 LLM config incomplete", 0.0, 0

    user_prompt = build_a0_user_prompt(
        q_orig, evidence, doc_count=doc_count, directory_map=directory_map
    )
    prompt_tokens = estimate_tokens(A0_SYSTEM + user_prompt)
    anthropic = "anthropic" in str(config.get("_source") or "").lower()
    url = _chat_url(base_url, anthropic)
    # 推理型模型会在 JSON 前输出大段思考文本，900 tokens 常被截断；
    # 默认给 3000，可用 COSIGHTBOT_DYNAMIC_A0_MAX_TOKENS 覆盖。
    max_tokens = max(512, int(os.environ.get("COSIGHTBOT_DYNAMIC_A0_MAX_TOKENS", "3000")))
    if config.get("max_tokens"):
        max_tokens = min(max_tokens, int(config["max_tokens"]))

    headers = {"Content-Type": "application/json"}
    if anthropic:
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": 0,
            "system": A0_SYSTEM,
            "messages": [{"role": "user", "content": user_prompt}],
        }
    else:
        headers["Authorization"] = f"Bearer {api_key}"
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": A0_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
        }
        # 支持 OpenAI json_object 的服务会直接返回 JSON，避免推理文本吃掉
        # max_tokens 导致截断；不支持的端点回退为普通请求。
        if os.environ.get("COSIGHTBOT_DYNAMIC_A0_JSON_MODE", "1") != "0":
            body["response_format"] = {"type": "json_object"}

    log_event(
        logger, "a0:request:start", model=model, source=config.get("_source"),
        protocol="anthropic" if anthropic else "openai",
        prompt_tokens=prompt_tokens, max_tokens=max_tokens, timeout_s=timeout,
        evidence_chars=len(evidence), directory_map_chars=len(directory_map),
        doc_count=doc_count, json_mode=("response_format" in body),
    )
    started = time.perf_counter()
    try:
        response = requests.post(
            url, headers=headers, json=body, timeout=(5, timeout), proxies=None
        )
        if (
            not anthropic
            and response.status_code == 400
            and "response_format" in body
        ):
            body.pop("response_format", None)
            response = requests.post(
                url, headers=headers, json=body, timeout=(5, timeout), proxies=None
            )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        log_event(logger, "a0:error", level=logging.WARNING,
                  error=f"{type(exc).__name__}: {exc}", duration_ms=elapsed,
                  url=url, status_code=getattr(getattr(exc, "response", None), "status_code", None))
        return None, f"A0 request failed: {type(exc).__name__}: {exc}", elapsed, prompt_tokens

    elapsed = round((time.perf_counter() - started) * 1000, 1)
    content = ""
    if anthropic:
        blocks = payload.get("content") if isinstance(payload, dict) else None
        if isinstance(blocks, list):
            content = "".join(
                str(b.get("text") or "") for b in blocks if isinstance(b, dict)
            )
    else:
        choices = payload.get("choices") if isinstance(payload, dict) else None
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(message, dict):
                content = str(message.get("content") or "")
            if not content and isinstance(choices[0], dict):
                content = str(choices[0].get("text") or "")

    data = _extract_json(content)
    if not data:
        log_event(logger, "a0:parse:error", level=logging.WARNING,
                  duration_ms=elapsed, content_chars=len(content),
                  content_preview=preview_text(content, 200))
        return None, "A0 returned empty/invalid JSON", elapsed, prompt_tokens

    parsed = _parse_payload(data)
    log_event(
        logger, "a0:done",
        quality=parsed["hit_quality"],
        gaps=len(parsed["unresolved_knowledge_gaps"]),
        gaps_preview=preview_items(parsed["unresolved_knowledge_gaps"], 4),
        q1_questions=len(parsed["next_queries_Q1"]["sub_questions"]),
        q1_terms=len(parsed["next_queries_Q1"]["key_terms"]),
        q1_questions_preview=preview_items(parsed["next_queries_Q1"]["sub_questions"], 2),
        q1_terms_preview=preview_items(parsed["next_queries_Q1"]["key_terms"], 8),
        answer_chars=len(parsed["intermediate_result_A"]),
        answer_preview=preview_text(parsed["intermediate_result_A"], 160),
        duration_ms=elapsed, prompt_tokens=prompt_tokens,
        model=model, source=config.get("_source"),
    )
    return parsed, "", elapsed, prompt_tokens
