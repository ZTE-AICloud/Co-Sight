#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SOC 多知识库注册表加载与保存。

load_registry 是入口函数：
  - 注册表存在 → 直接加载
  - 注册表不存在 → 写入并返回默认（空）注册表
  - 注册表损坏 → 备份损坏文件后写默认注册表

"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from common.soc_kb_registry.config import DEFAULT_REGISTRY
from common.soc_kb_registry.models import KnowledgeBaseRegistry
from common.soc_kb_registry.paths import SOC_AGENT_ID, registry_path_for_agent

logger = logging.getLogger(__name__)


def _atomic_write_json(path: Path, payload: dict) -> Path:
    """原子写入 JSON（先写 .tmp 再 rename）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path


def save_registry(
    registry: KnowledgeBaseRegistry,
    agent_id: str = SOC_AGENT_ID,
) -> Path:
    """原子写入注册表到 disk。"""
    path = registry_path_for_agent(agent_id)
    _atomic_write_json(path, registry.to_payload())
    return path


def load_registry(agent_id: str = SOC_AGENT_ID) -> KnowledgeBaseRegistry:
    """加载注册表；不存在则写默认（空）注册表。

    行为：
      1. 注册表存在 → 直接加载
      2. 注册表不存在 → 写入默认（空）注册表并返回
      3. 注册表损坏 → 备份损坏文件 + 写默认注册表
    """
    path = registry_path_for_agent(agent_id)

    # Case 1: 注册表存在
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                return KnowledgeBaseRegistry.from_payload(payload)
            logger.warning("soc_kb_registry.json 内容不是字典，将写默认注册表")
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning("soc_kb_registry.json 损坏 (%s)，备份后写默认注册表", exc)
            backup = path.with_name(
                f"{path.name}.corrupt-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            )
            try:
                os.replace(path, backup)
                logger.warning("已将损坏的注册表备份到 %s", backup)
            except OSError as backup_exc:
                logger.warning("备份失败: %s", backup_exc)

    # Case 2/3: 不存在或已损坏 → 写默认（空）注册表
    logger.info("为 agent=%s 写入默认（空）注册表", agent_id)
    save_registry(DEFAULT_REGISTRY, agent_id=agent_id)
    return DEFAULT_REGISTRY


__all__ = ["load_registry", "save_registry"]
