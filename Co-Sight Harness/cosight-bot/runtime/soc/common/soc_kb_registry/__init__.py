#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SOC 多知识库注册表模块。

管理多个知识库（builtin / team / local）配置。注册表文件位于：
    data/workspace-soc/soc_kb_registry.json

默认注册表为空。
"""
from __future__ import annotations

from common.soc_kb_registry.config import (
    DEFAULT_KB_WEIGHTS,
    DEFAULT_REGISTRY,
)
from common.soc_kb_registry.load import load_registry, save_registry
from common.soc_kb_registry.models import (
    KbType,
    KnowledgeBase,
    KnowledgeBaseRegistry,
)
from common.soc_kb_registry.paths import (
    backup_path,
    kbs_root,
    registry_path,
    registry_path_for_agent,
    space_library_path,
)
from common.soc_kb_registry.sub_kb import (
    normalize_sub_path,
    sub_kb_id,
    sub_kb_name,
    sub_path_leaf,
)

__all__ = [
    "DEFAULT_KB_WEIGHTS",
    "DEFAULT_REGISTRY",
    "KbType",
    "KnowledgeBase",
    "KnowledgeBaseRegistry",
    "backup_path",
    "kbs_root",
    "load_registry",
    "normalize_sub_path",
    "registry_path",
    "registry_path_for_agent",
    "save_registry",
    "space_library_path",
    "sub_kb_id",
    "sub_kb_name",
    "sub_path_leaf",
]
