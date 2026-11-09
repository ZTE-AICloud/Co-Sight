"""Model capability helpers（纯环境变量 + 模型名启发式）。

Answers the question "does the active model support image input?", without
making any network call.

解析优先级：
  1. 环境变量 ``COSIGHTBOT_MODEL_SUPPORTS_IMAGES`` 显式声明（"1/true/yes" 或
     "0/false/no"）——最权威，推荐用户在 data/.env 里写死；
  2. 模型名启发式：当前模型 id（经 cosight_runtime 解析）命中已知多模态
     模型族（claude / gpt-4o / gpt-5 / gemini / qwen-vl / glm-4v / doubao-vision
     / kimi 等）→ True；
  3. 否则 False（保守：不支持图像的端点不会因误发图片请求而报错；
     需要读图时用户可用第 1 条显式打开）。
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("file_watcher.model_capability")

# 已知多模态模型族（小写子串匹配）
_VISION_MODEL_HINTS = (
    "claude", "sonnet", "opus", "haiku", "fable",
    "gpt-4o",
    "gpt-5",
    "gemini",
    "qwen-vl",
    "qwen2-vl",
    "qwen3-vl",
    "glm-4v",
    "doubao-vision",
    "kimi",
    "internvl",
    "llava",
)

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _env_declares_support() -> Optional[bool]:
    raw = (os.environ.get("COSIGHTBOT_MODEL_SUPPORTS_IMAGES") or "").strip().lower()
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    return None


def _resolve_active_model_id(
    session_key: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> Optional[str]:
    """解析当前生效的模型 id（经 cosight_runtime 的纯环境变量链）。

    session_key / agent_id 参数为签名兼容保留（无 sessions.json 配置）。
    """
    try:
        from common.cosight_runtime import resolve_runtime_llm_config
    except ImportError:
        try:
            from cosight_runtime import resolve_runtime_llm_config  # type: ignore
        except ImportError:
            return None
    cfg = resolve_runtime_llm_config("model_capability")
    if not cfg:
        return None
    mid = cfg.get("model_id") or cfg.get("model")
    if isinstance(mid, str) and mid.strip():
        return mid.strip()
    return None


def current_model_supports_images(
    session_key: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> bool:
    """Return True if the current model accepts image input.

    Args:
        session_key / agent_id: 签名兼容保留（不参与解析）。
    """
    declared = _env_declares_support()
    if declared is not None:
        return declared

    model_id = _resolve_active_model_id(session_key=session_key, agent_id=agent_id)
    if not model_id:
        return False
    lowered = model_id.lower()
    return any(hint in lowered for hint in _VISION_MODEL_HINTS)
