#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SOC RAG 共享 helpers（common_processor / historical_processor 共用）。

- compute_md_path: 源文件 → pre_dir 下预处理 .md 的路径
- chapter_id_for: 章节 ID = md5(content)[:12]，与 handler._parse_md_to_chapter_nodes 同算式

所有 helper 假定 workspace_root 是单根语义（rel = file.relative_to(workspace_root)），
与 build_soc_vector.py 当前的 specs_pd_dir / hist_dir 架构对齐。
"""
import hashlib
from pathlib import Path


def compute_md_path(src_p: Path, pre_dir: Path, workspace_root: Path) -> Path:
    """计算源文件 src_p 在 pre_dir 下预处理产物的 .md 路径（返回 Path）。

    命名规则（与 watch_dog.preprocessor.process_single_file 完全对齐）：
        md_name = f"{stem}_{ext}".replace(".", "_") + ".md"
        # 例: foo.docx → foo_docx.md; a.b.c.txt → a_b_c_txt.md

    路径布局：
        workspace_root = specs_pd_dir（或 hist_dir）
        rel = src_p.relative_to(workspace_root)  # POSIX 相对路径
        md_file = pre_dir / rel.parent / md_name

    若 src_p 不在 workspace_root 下（ValueError），fallback 到 src_p.name 当 rel，
    此时 md_file 落在 pre_dir / md_name（无子目录）。
    """
    stem = src_p.stem
    ext = src_p.suffix.lstrip(".")
    md_name = f"{stem}_{ext}".replace(".", "_") + ".md"
    try:
        rel_under_workspace = src_p.relative_to(workspace_root)
    except ValueError:
        rel_under_workspace = Path(src_p.name)
    return pre_dir / rel_under_workspace.parent / md_name


def chapter_id_for(content: str) -> str:
    """计算章节 ID：内容 md5 前 12 位 + "chap_" 前缀。

    幂等：相同内容天然产生相同 cid，便于按 file_path 删旧行后重新插入时
    自然对齐。算式与 watch_dog.handler._parse_md_to_chapter_nodes 完全一致。
    """
    return f"chap_{hashlib.md5(content.encode()).hexdigest()[:12]}"