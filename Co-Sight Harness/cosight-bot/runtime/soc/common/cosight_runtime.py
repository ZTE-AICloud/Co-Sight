#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM 配置解析器（纯环境变量，无配置文件）。

所有需要大模型配置的入口统一通过 resolve_runtime_llm_config() 获取。

解析优先级（从高到低）：
  P1. 环境变量 ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN / ANTHROPIC_MODEL
      （与 Claude Code 兼容——用户已为 CC 配置则零成本复用）
  P2. 环境变量 OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL（回退）

调用方 explicit_model 可在环境配置基础上覆盖模型名（explicit_provider 仅
作记录，无 provider 注册表）。

注意：技能内部调用协议为 OpenAI chat/completions 兼容。若 ANTHROPIC_BASE_URL
指向仅支持 Anthropic 协议的端点，需经代理转换（README 有说明）。

可选微调环境变量：
  COSIGHTBOT_MODEL_CONTEXT_WINDOW  上下文窗口（默认 256000）
  COSIGHTBOT_MODEL_MAX_TOKENS      最大输出 token（默认不限制）

技能脚本启动时会先加载 <数据目录>/.env（见 common.skill_utils），
用户也可以直接在 shell 里 export。
"""
from __future__ import annotations

import logging
import os
from typing import Optional


logger = logging.getLogger("cosight_runtime")

# 同进程内只解析一次（subprocess 生命周期内模型不会变）
_RESOLVED_CACHE: dict | None = None

_DEFAULT_CONTEXT_WINDOW = 256000


def _env(*names: str) -> str:
    """取第一个非空环境变量值。"""
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def _resolve_from_env() -> Optional[dict]:
    """OPENAI_*（data/.env 主配置）优先，ANTHROPIC_*（Claude Code 会话继承）回退。

    顺序不可调换：data/.env 是用户为本专家显式配置的服务端点，必须压过
    从宿主 Claude Code 会话环境继承来的 ANTHROPIC_*（后者只是零配置兜底，
    且其端点可能仅支持 Anthropic 协议，与技能内的 OpenAI 兼容调用不匹配）。
    """
    base_url = _env("OPENAI_BASE_URL")
    api_key = _env("OPENAI_API_KEY")
    model = _env("OPENAI_MODEL")
    source = "env-openai"

    if not (base_url and api_key):
        base_url = _env("ANTHROPIC_BASE_URL")
        api_key = _env("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")
        model = _env("ANTHROPIC_MODEL")
        source = "env-anthropic"

    if not (base_url and api_key):
        return None

    context_window = _DEFAULT_CONTEXT_WINDOW
    cw_env = _env("COSIGHTBOT_MODEL_CONTEXT_WINDOW")
    if cw_env.isdigit():
        context_window = int(cw_env)

    max_tokens: Optional[int] = None
    mt_env = _env("COSIGHTBOT_MODEL_MAX_TOKENS")
    if mt_env.isdigit():
        max_tokens = int(mt_env)

    return {
        "provider":       source,
        "provider_id":    source,
        "model_id":       model or "",
        "model":          model or "",
        "base_url":       base_url,
        "api_key":        api_key,
        # 技能内部统一走 OpenAI chat/completions 兼容协议
        "api_protocol":   "openai-completions",
        "context_window": context_window,
        "max_tokens":     max_tokens,
        "_source":        source,
    }


# ---------------------------------------------------------------------------
# 公开 API：resolve_runtime_llm_config
# ---------------------------------------------------------------------------
def resolve_runtime_llm_config(
    tag: str = "",
    *,
    explicit_provider: Optional[str] = None,
    explicit_model:    Optional[str] = None,
    session_key:       Optional[str] = None,  # noqa: ARG001 — 签名兼容（无 sessions.json 配置）
    agent_id:          Optional[str] = None,  # noqa: ARG001 — 签名兼容
    use_cache:         bool = True,
) -> Optional[dict]:
    """统一的 LLM 配置解析入口（纯环境变量版）。

    Args:
        tag:               调试/日志用标签，可空
        explicit_provider: 仅记录（无 provider 注册表）
        explicit_model:    在环境配置基础上覆盖模型名
        session_key/agent_id: 签名兼容保留，不参与解析
        use_cache:         同进程内是否缓存结果（默认 True）

    Returns:
        dict：provider / provider_id / model_id / model / base_url / api_key /
              api_protocol / context_window / max_tokens / _source / _tag；
        或 None（环境变量未配置时）
    """
    global _RESOLVED_CACHE

    if use_cache and not tag and _RESOLVED_CACHE is not None:
        return _RESOLVED_CACHE

    resolved = _resolve_from_env()

    if resolved and explicit_model:
        resolved["model_id"] = explicit_model
        resolved["model"] = explicit_model
        if explicit_provider:
            resolved["provider"] = explicit_provider
            resolved["provider_id"] = explicit_provider

    if resolved:
        resolved["_tag"] = tag
        if use_cache and not tag:
            _RESOLVED_CACHE = resolved
        logger.info(
            f"cosight_runtime: resolved tag={tag or '(none)'} "
            f"source={resolved['_source']} model={resolved.get('model_id') or '(unset)'}"
        )
        return resolved

    logger.warning(
        f"cosight_runtime: no LLM config in env (tag={tag}). "
        f"Set OPENAI_BASE_URL/OPENAI_API_KEY/OPENAI_MODEL (data/.env 主配置) "
        f"or ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN/ANTHROPIC_MODEL (会话继承回退)."
    )
    return None


# ---------------------------------------------------------------------------
# 向后兼容：旧的 resolve_build_llm_config 接口
# ---------------------------------------------------------------------------

def resolve_build_llm_config(tag: str = "") -> Optional[dict]:
    """向后兼容：旧 watch_dog/handler.py 调用的入口，转发到新接口。

    保持与旧实现相同的返回 key 形态：
      {"model", "base_url", "api_key", "max_tokens", "context_window", "provider"}
    """
    cfg = resolve_runtime_llm_config(tag=tag)
    if not cfg:
        return None

    return {
        "model":          cfg["model"],
        "base_url":       cfg["base_url"],
        "api_key":        cfg["api_key"],
        "max_tokens":     cfg["max_tokens"],
        "context_window": cfg["context_window"],
        "provider":       cfg["provider"],
    }


# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------

def reset_cache() -> None:
    """清空模块级缓存。供测试使用，生产代码不应调用。"""
    global _RESOLVED_CACHE
    _RESOLVED_CACHE = None
