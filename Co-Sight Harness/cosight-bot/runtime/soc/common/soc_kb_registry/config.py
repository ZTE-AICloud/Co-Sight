#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SOC 多知识库默认配置。

没有内置知识库与站点来源：默认注册表为空，全部 KB 由用户通过
cosightbot-soc-kb-build 从本地源目录注册构建。
"""
from __future__ import annotations

from common.soc_kb_registry.models import KnowledgeBaseRegistry

# KB 类型权重（用于多 KB 检索融合）
# 写死在代码里，**不开放用户调整**
# 本地 KB 权重稍高，因为是用户主动上传的资料
DEFAULT_KB_WEIGHTS: dict[str, float] = {
    "builtin": 1.0,
    "team": 1.05,
    "local": 1.1,
}


def _build_default_registry() -> KnowledgeBaseRegistry:
    """构造默认注册表：默认为空（无任何内置 KB）。"""
    return KnowledgeBaseRegistry(version=1, knowledge_bases=())


DEFAULT_REGISTRY: KnowledgeBaseRegistry = _build_default_registry()


__all__ = [
    "DEFAULT_KB_WEIGHTS",
    "DEFAULT_REGISTRY",
]
