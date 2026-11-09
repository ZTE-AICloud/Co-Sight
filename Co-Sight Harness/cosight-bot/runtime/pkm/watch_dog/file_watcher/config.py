#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
file_watcher 公共配置与工具函数

包含常量、路径计算、归一化等纯计算函数。
"""

import hashlib
import os
import json
import time
from pathlib import Path
from typing import Optional, Tuple

logger = __import__("logging").getLogger("file_watcher")


# ---------------------------------------------------------------------------
# LLM 配置
# ---------------------------------------------------------------------------

def resolve_build_llm_config(tag: str = "") -> dict | None:
    """统一的构建期 LLM 配置解析（纯环境变量，无配置文件）。

    直接委托 common.cosight_runtime.resolve_runtime_llm_config
    （OPENAI_* 主配置优先，ANTHROPIC_* 会话继承回退，详见该模块 docstring）。
    返回字段形态保持：model/base_url/api_key/max_tokens/context_window/provider。
    """
    try:
        from common.cosight_runtime import resolve_runtime_llm_config
    except ImportError:
        from cosight_runtime import resolve_runtime_llm_config  # type: ignore
    cfg = resolve_runtime_llm_config(tag)
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
# route key（用于缓存索引的键）
# ---------------------------------------------------------------------------

def get_route_key(
    material_source_dir: Path,
    agent_id: str = "",
    session_key_hash: str = "",
) -> str:
    if agent_id and session_key_hash:
        return hashlib.md5(f"{agent_id}:{session_key_hash}".encode()).hexdigest()
    abs_path = str(material_source_dir.expanduser().resolve())
    return hashlib.md5(abs_path.encode('utf-8')).hexdigest()


# ---------------------------------------------------------------------------
# 存储目录计算
# ---------------------------------------------------------------------------

def cosight_state_root() -> Path:
    """数据根目录（工作目录下 data/，COSIGHTBOT_HOME 覆盖）。

    单一来源在 common.port_resolver；此处委托，保持既有调用方零改动。
    """
    try:
        from common.port_resolver import cosight_state_root as _root
    except ImportError:
        from port_resolver import cosight_state_root as _root  # type: ignore
    return _root()


def get_llamaindex_storage_dirs(
    material_source_dir: Path,
    agent_id: str,
) -> Tuple[Optional[Path], Optional[Path]]:
    """
    Generate unique LlamaIndex storage directories based on agent_id and folder path.
    Isolates pre-processed Markdown and LanceDB vector store under
    <state_root>/workspace-{agent_id}/llamaindex_data/
    (state_root = 数据根（COSIGHTBOT_HOME > CLAUDE_PLUGIN_DATA > 官方默认，见 common/port_resolver.py）).
    """
    workspace_root = cosight_state_root() / f"workspace-{agent_id}"
    path_md5 = get_route_key(material_source_dir)
    dir_name = material_source_dir.name
    prefix = f"{dir_name}_{path_md5[:8]}"

    pre_processed_dir = workspace_root / "llamaindex_data" / "pre-processed" / prefix
    lancedb_dir = workspace_root / "llamaindex_data" / "lancedb" / prefix

    logger.info(
        f"LlamaIndex: Storage dirs for {material_source_dir.name} "
        f"(agent={agent_id}) -> pre={pre_processed_dir.name}, db={lancedb_dir.name}"
    )
    return pre_processed_dir, lancedb_dir


def get_session_storage_dirs(
    agent_id: str,
    session_key_hash: str,
) -> Tuple[Path, Path, Path]:
    """Session 级别的存储路径，返回 (upload_dir, pre_dir, lan_dir)。

    与 get_llamaindex_storage_dirs 不同，目录名直接使用 session_key_hash
    （16 位 hex），不附加路径哈希后缀。
    """
    workspace_root = cosight_state_root() / f"workspace-{agent_id}"
    upload_dir = workspace_root / "llamaindex_data" / "upload_files" / session_key_hash
    pre_dir = workspace_root / "llamaindex_data" / "pre-processed" / session_key_hash
    lan_dir = workspace_root / "llamaindex_data" / "lancedb" / session_key_hash
    logger.info(
        f"LlamaIndex: Session storage dirs (agent={agent_id}, session={session_key_hash}) "
        f"-> upload={upload_dir.name}, pre={pre_dir.name}, db={lan_dir.name}"
    )
    return upload_dir, pre_dir, lan_dir


# ---------------------------------------------------------------------------
# 安全检查
# ---------------------------------------------------------------------------

def is_under_pre_processed_dir(path: Path) -> bool:
    """检查路径是否位于 llamaindex_data/pre-processed/ 目录下。"""
    try:
        resolved = path.resolve()
        parts = [p.lower() for p in resolved.parts]
        for i in range(len(parts) - 1):
            if parts[i] == "llamaindex_data" and parts[i + 1] == "pre-processed":
                return True
        return False
    except (OSError, ValueError):
        return False
