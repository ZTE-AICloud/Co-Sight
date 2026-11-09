#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""子库（sub-KB）kb_id / 命名推导 —— 全链路单一来源。

builder 的 add-sub（注册构建配置）与 manager 的 bind-sub（用户绑定）
都必须调这里的函数，规则只此一份，两侧不可能漂移。

规则（feature-record/soc_sub_kb_split_design.md）：
  kb_id = <parent>_sub_<md5(sub_path)[:8]>   （ASCII、稳定、同路径同 id）
  name  = <parent>·<L1>/<L2>                  （展示用）
"""
from __future__ import annotations

import hashlib


def normalize_sub_path(sub_path: str) -> str:
    """规范化产品路径：统一斜杠、去首尾斜杠与空白、折叠连续斜杠。

    "算力及核心网/服务器与存储" / "\\算力及核心网\\服务器与存储\\" /
    "算力及核心网//服务器与存储" 归一到同一个字符串，保证 kb_id 稳定。
    """
    cleaned = sub_path.strip().replace("\\", "/")
    parts = [seg.strip() for seg in cleaned.split("/")]
    parts = [seg for seg in parts if seg]
    return "/".join(parts)


def sub_kb_id(parent: str, sub_path: str) -> str:
    """推导子库 kb_id：<parent>_sub_<md5(规范化路径)[:8]>。"""
    parent_norm = parent.strip()
    if not parent_norm:
        raise ValueError("parent 不能为空")
    path_norm = normalize_sub_path(sub_path)
    if not path_norm:
        raise ValueError("sub_path 不能为空")
    digest = hashlib.md5(path_norm.encode("utf-8")).hexdigest()
    return f"{parent_norm}_sub_{digest[:8]}"


def sub_kb_name(parent: str, sub_path: str) -> str:
    """子库展示名：<parent>·<L1>/<L2>。"""
    return f"{parent.strip()}·{normalize_sub_path(sub_path)}"


def sub_path_leaf(sub_path: str) -> str:
    """路径最后一段（L2 名，如 算力及核心网/服务器与存储 -> 服务器与存储）。"""
    return normalize_sub_path(sub_path).rsplit("/", 1)[-1]


__all__ = [
    "normalize_sub_path",
    "sub_kb_id",
    "sub_kb_name",
    "sub_path_leaf",
]
