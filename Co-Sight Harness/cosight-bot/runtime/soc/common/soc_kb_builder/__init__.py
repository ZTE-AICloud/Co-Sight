#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SOC 知识库构建器公共库。

仅支持**本地源**构建链：本地源目录 → vector_build 构建，
产物直落本地 data/workspace-soc/kbs/<kb_id>/。

主要模块：
  - config.py            配置模型（本地源 BuildConfig）
  - kb_admin.py          注册表/目录管理（kb_cli 直接调用）
  - vector_build/        向量库构建核心包（build_soc_vector + 各处理器）
"""
from __future__ import annotations

from common.soc_kb_builder.config import (
    BuildConfig,
    BuilderConfig,
    KBType,
    load_config_from_file,
)

__all__ = [
    "BuildConfig",
    "BuilderConfig",
    "KBType",
    "load_config_from_file",
]
