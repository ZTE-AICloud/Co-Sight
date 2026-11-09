#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Q0 查询改写：复用当前 LLM 做检索词/问句扩展。

只做检索扩展，不回答问题；失败时返回 None，调用方保留原 QueryPack。
"""
from __future__ import annotations

import json
import logging
import time

import requests

from common.cosight_runtime import resolve_runtime_llm_config
from common.logging_setup import log_event, preview_items

from .models import QueryPack
from .prompts import Q0_REWRITE_SYSTEM, build_q0_rewrite_user_prompt

logger = logging.getLogger("dynamic_overview.query_rewrite")


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


def _extract_json(text: str) -> dict | None:
    text = (text or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    decoder = json.JSONDecoder()
    for start in reversed([i for i, ch in enumerate(text) if ch == "{"]):
        try:
            data, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and (
            "key_terms" in data or "rewritten_queries" in data
        ):
            return data
    return None


def _clean_list(values, *, limit: int, max_chars: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        value = str(raw or "").strip()
        if not value or len(value) > max_chars:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
        if len(out) >= limit:
            break
    return out


def rewrite_query(q: QueryPack, *, timeout: float = 30.0) -> QueryPack | None:
    """调用 LLM 扩展 QueryPack；失败返回 None（不抛异常）。"""
    config = resolve_runtime_llm_config(tag="dynamic-q0")
    if not config:
        return None
    base_url = config.get("base_url") or ""
    api_key = config.get("api_key") or ""
    model = config.get("model") or ""
    if not (base_url and api_key and model):
        return None

    user_prompt = build_q0_rewrite_user_prompt(q)
    anthropic = "anthropic" in str(config.get("_source") or "").lower()
    url = _chat_url(base_url, anthropic)
    headers = {"Content-Type": "application/json"}
    if anthropic:
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
        body = {
            "model": model,
            "max_tokens": 800,
            "temperature": 0,
            "system": Q0_REWRITE_SYSTEM,
            "messages": [{"role": "user", "content": user_prompt}],
        }
    else:
        headers["Authorization"] = f"Bearer {api_key}"
        body = {
            "model": model,
            "max_tokens": 800,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": Q0_REWRITE_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }

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
        log_event(
            logger, "q0:rewrite:error", level=logging.WARNING,
            error=f"{type(exc).__name__}: {exc}",
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return None

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
        log_event(
            logger, "q0:rewrite:parse:error", level=logging.WARNING,
            content_chars=len(content),
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return None

    extra_terms = _clean_list(data.get("key_terms"), limit=8, max_chars=120)
    extra_questions = _clean_list(
        data.get("rewritten_queries"), limit=2, max_chars=500
    )
    exclude = {x.lower() for x in q.exclude if x}
    extra_terms = [x for x in extra_terms if x.lower() not in exclude]
    if not extra_terms and not extra_questions:
        return None

    questions = list(dict.fromkeys([*q.questions, *extra_questions]))
    terms = list(dict.fromkeys([*q.terms, *extra_terms]))
    rewritten = QueryPack(
        questions=questions,
        terms=terms,
        entities=q.entities,
        constraints=q.constraints,
        identifiers=q.identifiers,
        exclude=q.exclude,
    )
    log_event(
        logger, "q0:rewrite:done",
        added_terms=len(extra_terms), added_questions=len(extra_questions),
        added_terms_preview=preview_items(extra_terms, 8),
        added_questions_preview=preview_items(extra_questions, 2),
        total_terms=len(terms), total_questions=len(questions),
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
        model=model, source=config.get("_source"),
    )
    return rewritten
