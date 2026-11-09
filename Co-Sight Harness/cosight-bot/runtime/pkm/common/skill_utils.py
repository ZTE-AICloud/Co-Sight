#!/usr/bin/env python3
"""
Shared utilities for Cosight skill scripts.

This module is designed to be importable from skill scripts without requiring
the runtime root to be on sys.path first. It provides:

  - _resolve_runtime_root()     : Locate runtime root directory
  - cosight_state_root()        : 数据根的 Path（COSIGHTBOT_HOME > CLAUDE_PLUGIN_DATA > 官方默认，见 port_resolver）
  - state_paths(agent_id)       : (state_dir, state_file) for material_dir.json
  - load_state(agent_id)        : Load material_dir.json as dict
  - validate_dir(path)          : Validate an absolute directory path
  - setup_skill_logging(name)   : Configure stderr logger for skill scripts

Usage in skill scripts:
    from common.skill_utils import _resolve_runtime_root, cosight_state_root
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional


def _resolve_runtime_root() -> Path:
    """定位 runtime 根目录（本模块位于 <workdir>/runtime/common/，parents[1] 即 runtime）。"""
    return Path(__file__).resolve().parents[1]


def cosight_state_root() -> Path:
    """数据根目录（工作目录下 data/，COSIGHTBOT_HOME 覆盖）。

    单一来源在 common.port_resolver；此处委托，保持既有调用方零改动。
    """
    from .port_resolver import cosight_state_root as _root
    return _root()


def state_paths(agent_id: str) -> tuple[Path, Path]:
    """Returns (state directory, state file path) for material_dir.json.

    落位：data/workspace-<agent_id>/material_dir.json。
    """
    state_root = cosight_state_root()
    d = state_root / f"workspace-{agent_id}"
    f = d / "material_dir.json"
    return d, f


def load_state(agent_id: str) -> dict | None:
    """Load material_dir.json state for the given agent_id."""
    _, f = state_paths(agent_id)
    if not f.is_file():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def validate_dir(p: str) -> tuple[bool, str]:
    """
    Validate that *p* is an absolute path to an existing directory.

    Returns:
        (True, resolved_path_str) on success.
        (False, error_message) on failure.
    """
    path = Path(p)
    if not path.is_absolute():
        return False, "Path must be absolute (e.g., Windows: C:\\Users\\...\\Materials or D:\\data)."
    try:
        resolved = path.expanduser().resolve()
    except OSError as e:
        return False, f"Invalid path: {e}"
    if not resolved.exists():
        return False, f"Path does not exist: {resolved}"
    if not resolved.is_dir():
        return False, f"Not a directory: {resolved}"
    return True, str(resolved)


class _FlushingStderrHandler(logging.StreamHandler):
    """Flushes after every log entry for real-time display in gateway console."""

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self.flush()


def attach_skill_file_handler(logger: logging.Logger, filename: str) -> Optional[Path]:
    """给 skill logger 追加文件 Handler，写到 <state_root>/logs/<filename>。

    - state_root = 工作目录下 data/（与 asset_center.json 等状态同根），
      与运行日志 logs/cosightbot.log 同目录，便于一处查看。
    - 目录创建 / 文件打开失败时静默跳过并返回 None（stderr 日志不受影响）。
    - 同一 logger 对同一文件重复调用不叠加 Handler（模块被多次 import 安全）。

    Args:
        logger: 已存在的 logger（通常是 setup_skill_logging 的返回值，
                或其父 logger 名以聚合子模块日志，如 "common.asset_center"）。
        filename: 日志文件名，如 "asset_center_manager.log"。

    Returns:
        日志文件路径；失败返回 None。
    """
    try:
        log_dir = cosight_state_root() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / filename
        for h in logger.handlers:
            if isinstance(h, logging.FileHandler) and Path(h.baseFilename) == log_file:
                return log_file
        fh = logging.FileHandler(str(log_file), encoding="utf-8", mode="a")
        fh.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(name)s][%(levelname)s] %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        logger.addHandler(fh)
        return log_file
    except OSError:
        return None


def setup_skill_logging(name: str, debug_env_var: str = "COSIGHTBOT_DEBUG") -> logging.Logger:
    """
    Configure a stderr logger for skill scripts.

    Args:
        name: Logger name (e.g. "cosightbot_material").
        debug_env_var: Environment variable name that enables DEBUG level
                       when set to "1", "true", or "yes".

    Returns:
        Configured logger instance.
    """
    # 技能脚本也写统一的 cosightbot.log（不只是 stderr）
    try:
        from .logging_setup import setup_logging

        setup_logging()
    except Exception:
        pass

    logger = logging.getLogger(name)
    level = logging.DEBUG if os.environ.get(debug_env_var, "").strip().lower() in (
        "1",
        "true",
        "yes",
    ) else logging.INFO
    logger.setLevel(level)
    root = logging.getLogger()
    if root.handlers:
        # 统一走 root 的 stderr + cosightbot.log，避免技能日志只停在 stderr
        logger.propagate = True
        for handler in list(logger.handlers):
            if isinstance(handler, _FlushingStderrHandler):
                logger.removeHandler(handler)
    else:
        # 极端兜底：root 未配置时保留 stderr
        h = _FlushingStderrHandler(sys.stderr)
        h.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(name)s][%(levelname)s] %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        logger.addHandler(h)
        logger.propagate = False
    return logger


# =====================================================================
# LLM JSON 抽取（容错）
# =====================================================================
#
# LLM 经常不严格按 prompt 输出纯 JSON，常见偏离：
#   1. 在 JSON 前后加解释文字（"让我分析一下..."、"以上是我的打分"）
#   2. 用 markdown fence 包裹（```json ... ```）
#   3. 输出空字符串（流式截断 / 模型拒绝 / 网络返回空 body）
#   4. 嵌入未转义引号或控制字符
# 旧代码做"剥 fence 再 json.loads"，遇到 (1)(3)(4) 就报 "Expecting value" 然后
# except 兜底丢原始顺序，损失质量。这两个 helper 按"最常见 → 次常见 → 兜底"
# 三段式抽取，失败返回空 dict / None，由 caller 决定如何降级。


def extract_first_json(text: str) -> dict:
    """渐进式 JSON 对象抽取：整段 → markdown fence → 非贪婪正则。

    Returns:
        抽取到的 dict；失败返回 {}。
    """
    # 1) 整段直接 parse（LLM 严格按 prompt 输出纯 JSON）
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # 2) markdown code fence ```json ... ```
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        try:
            data = json.loads(fence.group(1))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    # 3) 非贪婪正则找第一个 {...} 块
    brace = re.search(r"\{.*?\}", text, re.DOTALL)
    if brace:
        try:
            data = json.loads(brace.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    return {}


def extract_first_json_array(text: str) -> Optional[list]:
    """渐进式 JSON 数组抽取：整段 → markdown fence → 非贪婪正则。

    Returns:
        抽取到的 list；失败返回 None。
    """
    # 1) 整段直接 parse
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    # 2) markdown code fence ```json ... ```
    fence = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if fence:
        try:
            data = json.loads(fence.group(1))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    # 3) 非贪婪正则找第一个 [...] 块
    bracket = re.search(r"\[.*?\]", text, re.DOTALL)
    if bracket:
        try:
            data = json.loads(bracket.group(0))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    return None
