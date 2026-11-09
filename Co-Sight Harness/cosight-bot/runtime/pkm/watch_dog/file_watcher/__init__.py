#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
file_watcher 包

基于 watchdog 监听本地资料目录文件变更，增量执行文档预处理并维护
overview 产物（overview.md / node_index.json / .llamaindex_status）。
"""

# 使用 __getattr__ 实现延迟导入，避免在 import file_watcher 时就触发
# handler → search → embedding_model 等重量级依赖链。


def __getattr__(name):
    if name == "LlamaIndexIncrementalHandler":
        from .handler import LlamaIndexIncrementalHandler
        return LlamaIndexIncrementalHandler
    if name == "get_route_key":
        from .config import get_route_key
        return get_route_key
    if name == "get_llamaindex_storage_dirs":
        from .config import get_llamaindex_storage_dirs
        return get_llamaindex_storage_dirs
    if name == "is_under_pre_processed_dir":
        from .config import is_under_pre_processed_dir
        return is_under_pre_processed_dir
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "LlamaIndexIncrementalHandler",
    "get_route_key",
    "get_llamaindex_storage_dirs",
    "is_under_pre_processed_dir",
]
