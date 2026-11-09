#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SOC 多知识库注册表路径计算。

注册表与 KB 运行时数据统一收敛到工作目录下：
    data/workspace-soc/soc_kb_registry.json
    data/workspace-soc/kbs/<kb_id>/
"""
from __future__ import annotations

import re
from pathlib import Path


_REGISTRY_FILENAME = "soc_kb_registry.json"
_SPACE_LIBRARY_FILENAME = "space_library.json"
_BACKUP_FILENAME_TEMPLATE = "soc_kb_registry.json.bak-{ts}"

_AGENT_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,128}")

# SOC 域固定 agent_id（单 SOC 域，无多智能体概念）
SOC_AGENT_ID = "soc"


def state_root() -> Path:
    """数据根目录（工作目录下 data/，COSIGHTBOT_HOME 覆盖）。"""
    from common.port_resolver import cosight_state_root

    return cosight_state_root()


def _check_agent_id(agent_id: str) -> None:
    if not isinstance(agent_id, str) or not _AGENT_ID_RE.fullmatch(agent_id):
        raise ValueError(f"非法 agent_id: {agent_id!r}")


def registry_path_for_agent(agent_id: str) -> Path:
    """注册表路径：data/workspace-<agent_id>/soc_kb_registry.json。

    落位与 skill_utils.state_paths 同一层级；SOC 域固定 agent_id="soc" → data/workspace-soc/。
    """
    _check_agent_id(agent_id)
    return state_root() / f"workspace-{agent_id}" / _REGISTRY_FILENAME


def registry_path() -> Path:
    """SOC 域默认注册表路径：data/workspace-soc/soc_kb_registry.json。"""
    return registry_path_for_agent(SOC_AGENT_ID)


def kbs_root(agent_id: str = SOC_AGENT_ID) -> Path:
    """多 KB 模式的运行时根目录：data/workspace-<agent_id>/kbs/。

    规范定义在 common.soc_vector_paths.kbs_root，这里委托过去（单一来源），
    保证 from 两处 import 得到的路径一致。
    """
    from common.soc_vector_paths import kbs_root as _canonical_kbs_root

    return _canonical_kbs_root(agent_id)


def space_library_path(agent_id: str) -> Path:
    """旧版 space_library.json 路径（仅保留 API 兼容，无迁移场景）。"""
    _check_agent_id(agent_id)
    return state_root() / f"workspace-{agent_id}" / _SPACE_LIBRARY_FILENAME


def backup_path(agent_id: str, timestamp: str) -> Path:
    """注册表备份文件路径。"""
    _check_agent_id(agent_id)
    return state_root() / f"workspace-{agent_id}" / _BACKUP_FILENAME_TEMPLATE.format(
        ts=timestamp
    )


__all__ = [
    "SOC_AGENT_ID",
    "backup_path",
    "kbs_root",
    "registry_path",
    "registry_path_for_agent",
    "space_library_path",
    "state_root",
]
