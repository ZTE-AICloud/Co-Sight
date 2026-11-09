#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""product_taxonomy.py：根据 01_Specs_PD 目录结构生成 product_taxonomy.json 内容。

从 build_soc_vector.py 抽出的纯函数模块（无模块级副作用），供两处复用：
  - build_soc_vector.py：全量训练后写 product_taxonomy.json
  - sync_soc_rag.py --build-overview-only：免重训单独刷新 product_taxonomy.json
    （直接 import build_soc_vector 会触发其模块级 logging/FileHandler 与
    common_processor 重依赖链，故抽到此独立模块）
"""
import time
from pathlib import Path

from common.soc_kb_builder.document_types import SUPPORTED_DOCUMENT_EXTS


def _find_common_ancestor_depth(path_components: list[list[str]]) -> int:
    """找到所有路径组件列表的公共祖先深度。"""
    if not path_components:
        return 0
    min_len = min(len(p) for p in path_components)
    depth = 0
    for i in range(min_len):
        comp = path_components[0][i]
        if all(p[i] == comp for p in path_components):
            depth = i + 1
        else:
            break
    return depth


# 文档用途目录：这些目录只表示文档类型/用途，不是产品分类，生成 taxonomy 时应向上归并。
_DOC_TYPE_DIRS = {
    "了解产品", "参考文档", "安装调测", "操作维护",
    "故障处理", "配置管理", "特性指导", "其他文档",
}


def _normalize_to_product_path(components: list[str]) -> list[str]:
    """把叶子目录归一化为产品分类路径。

    规则：
      1. 去掉末尾的 _extracted 解压目录（自解压包产物）
      2. 去掉末尾的文档用途目录（了解产品/参考文档/...）
    """
    if not components:
        return components

    # 去掉解压产物目录
    if components[-1].endswith("_extracted"):
        components = components[:-1]

    # 去掉文档用途层
    while components and components[-1] in _DOC_TYPE_DIRS:
        components = components[:-1]

    return components


def _discover_product_categories(specs_pd_dir: Path) -> list[dict]:
    """根据 01_Specs_PD 目录结构自动发现产品分类，支持任意目录层级。

    完全不依赖预定义的品牌、系列或产品关键词，只根据目录结构生成
    canonical_path 和别名。LLM 在 respond.py 中会读取完整的 taxonomy JSON
    并自主识别用户问题对应的产品分类。

    对真实资料目录的适配：
      - 同一产品系列下通常有 "了解产品/参考文档/安装调测/..." 等文档用途子目录，
        这些子目录会被归并到产品系列层，不会各自成为独立分类。
      - 自解压包残留的 *_extracted 目录会被忽略。
    """
    doc_extensions = {".md", ".txt", *SUPPORTED_DOCUMENT_EXTS}

    # 1. 收集所有有效叶子目录（含文档文件且无子目录）
    leaf_rels: list[str] = []
    for dir_path in sorted(specs_pd_dir.rglob("*")):
        if not dir_path.is_dir():
            continue
        if any(d.is_dir() for d in dir_path.iterdir()):
            continue
        has_doc = any(
            f.is_file() and f.suffix.lower() in doc_extensions
            for f in dir_path.iterdir()
        )
        if not has_doc:
            continue
        try:
            rel = dir_path.relative_to(specs_pd_dir).as_posix()
        except ValueError:
            continue
        if not rel:
            continue
        # 跳过自解压包残留目录内部的叶子（如 *_extracted/.../home/Web）
        if any(part.endswith("_extracted") for part in rel.split("/")):
            continue
        leaf_rels.append(rel)

    if not leaf_rels:
        return []

    # 2. 把叶子目录归一化到产品路径（去掉文档用途层和解压产物）
    product_paths: list[str] = []
    for rel in leaf_rels:
        components = rel.split("/")
        product_components = _normalize_to_product_path(components)
        if not product_components:
            continue
        product_paths.append("/".join(product_components))

    # 去重并排序
    product_paths = sorted(set(product_paths))
    if not product_paths:
        return []

    # 3. 计算所有产品路径的公共祖先深度
    path_components = [r.split("/") for r in product_paths]
    ancestor_depth = _find_common_ancestor_depth(path_components)

    # 4. 从公共祖先之后生成 category
    categories = []
    seen_paths: set[str] = set()

    for rel, components in zip(product_paths, path_components):
        canonical_components = components[ancestor_depth:]
        if not canonical_components:
            # 如果公共祖先就是产品路径本身，至少保留最后一级
            canonical_components = components[-1:]

        canonical_path = "/".join(canonical_components)
        if not canonical_path or canonical_path in seen_paths:
            continue
        seen_paths.add(canonical_path)

        # 生成别名：完整路径（/ 和空格两种分隔）、最后两级/三级组合
        aliases = {canonical_path, rel}
        aliases.add(canonical_path.replace("/", " "))
        aliases.add(canonical_components[-1])
        if len(canonical_components) >= 2:
            two_level = "/".join(canonical_components[-2:])
            aliases.add(two_level)
            aliases.add(two_level.replace("/", " "))
        if len(canonical_components) >= 3:
            three_level = "/".join(canonical_components[-3:])
            aliases.add(three_level)
            aliases.add(three_level.replace("/", " "))

        # level1/2/3 按公共祖先后的层级自动填充（通用结构，无固定语义）
        level1 = canonical_components[0] if len(canonical_components) > 0 else ""
        level2 = canonical_components[1] if len(canonical_components) > 1 else ""
        level3 = canonical_components[2] if len(canonical_components) > 2 else ""

        category_id = "cat_" + "_".join(
            c.replace(" ", "_").replace("/", "_") for c in canonical_components
        ).lower()

        categories.append({
            "category_id": category_id,
            "canonical_path": canonical_path,
            "display_name": canonical_path.replace("/", " "),
            "level1": level1,
            "level2": level2,
            "level3": level3,
            "aliases": sorted(aliases),
            "file_path_patterns": [f"%{canonical_path}%"],
            "priority": 100,
            "description": f"自动识别产品分类: {canonical_path}",
        })

    return categories


def generate_product_taxonomy(specs_pd_dir: Path) -> dict:
    """根据 source_download/01_Specs_PD 目录结构生成 product_taxonomy.json 内容。"""
    return {
        "taxonomy_version": "1.0",
        "last_updated": time.strftime("%Y-%m-%d"),
        "auto_generated": True,
        "categories": _discover_product_categories(specs_pd_dir),
    }
