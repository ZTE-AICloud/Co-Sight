#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""node_sections.py：生成 node_sections.json（文件节点 → 章节标题列表）。

主 overview.md 只列目录与文件节点（大库章节全展开会超出 agent 上下文预算），
本模块产出每个主文档的"小节目录"，供 soc-general-qa-skill 的
`qa.py --sections F###` 按需下钻查看。产物落在 lan_dir 下、随 RAG zip 下发。

数据源：nodes.lance 每个 chunk 的 metadata.chapter_title，按文件聚合并
保序去重（chunk 存储序 ≈ 文档顺序）。选型实测（2026-08-20，生产库
1581 文件 / 58 万 chunks）：
  - chapter_title：全文件覆盖（中位 92 条/文件），但标题里嵌 `###` 前缀、
    含"法律声明/目录"等前言碎片 → 清洗后使用；
  - header_path 层级：仅 143/1581 文件有 → 不能作为主来源；
  - pre-processed 的 *_chapters/ 目录：存在换版残留（主 md 已删的切片
    目录）与命名不一致（主 md 名与目录名不总对应）两个坑 → 不用。

与 product_taxonomy.py 同模式：纯函数、无模块级副作用，供两处复用：
  - build_soc_vector.py：全量训练后写 node_sections.json
  - sync_soc_rag.py --build-overview-only：免重训单独刷新
"""
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# chapter_title 里嵌的 markdown 标题前缀（"# xxx" / "### xxx"）。
# 循环剥除：原始数据存在 7 个及以上 #（"####### 缩略语"）与前缀内嵌
# （"### ## 一、xxx"）两种情况，单次 #{1,6} 剥不干净（验证实测 dev 库残留 16 条）。
_HEADER_PREFIX_RE = re.compile(r"^(#+\s*)+")

# 预处理主 md 的文件名后缀（命名规则 f"{stem}_{ext}"：report.pdf → report_pdf.md）
_MAIN_DOC_SUFFIXES = ("_pdf", "_docx", "_doc", "_xlsx", "_pptx", "_ppt", "_md")


def _clean_chapter_title(raw: str) -> str:
    """剥 markdown 标题前缀 + 去空白。"""
    return _HEADER_PREFIX_RE.sub("", (raw or "").strip()).strip()


def _doc_stem(rel_path: str) -> str:
    """文件相对路径 → 文档名（剥掉预处理命名规则追加的 _<ext> 后缀）。

    用于剔除"章节标题 == 文档名"的自标题条目（多数文档的第一个
    chapter_title 就是文档自身标题）。
    """
    stem = Path(rel_path).stem
    lower = stem.lower()
    for suffix in _MAIN_DOC_SUFFIXES:
        if lower.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def generate_node_sections(lan_dir: Path) -> dict:
    """从 lan_dir/nodes.lance 生成 {rel_path: [章节标题, ...]}。

    文件集合以 node_index.json 为准（只有入树的文件才需要章节清单）；
    rel_path 从 chunk 的 file_path 绝对路径按 "/pre-processed/<lan_dir.name>/"
    锚点截取。返回 dict 覆盖 node_index 的全部文件（无章节的文件值为空 list）。
    """
    import lancedb  # 重依赖，延迟到调用时

    node_index_path = lan_dir / "node_index.json"
    node_index = json.loads(node_index_path.read_text(encoding="utf-8-sig"))
    rel_paths = list(node_index.values())
    sections: dict[str, list[str]] = {rel: [] for rel in rel_paths}
    valid = set(rel_paths)

    anchor = f"/pre-processed/{lan_dir.name}/"
    db = lancedb.connect(str(lan_dir))
    meta_col = (
        db.open_table("nodes")
        .to_lance()
        .to_table(columns=["metadata"])
        .column("metadata")
    )

    seen: dict[str, set] = {rel: set() for rel in rel_paths}
    skipped_no_anchor = 0
    skipped_not_in_tree = 0
    for md in meta_col.to_pylist():
        fp = (md.get("file_path") or "").replace("\\", "/")
        pos = fp.find(anchor)
        if pos < 0:
            skipped_no_anchor += 1
            continue
        rel = fp[pos + len(anchor):]
        if rel not in valid:
            skipped_not_in_tree += 1
            continue
        title = _clean_chapter_title(md.get("chapter_title") or "")
        if not title or title == _doc_stem(rel):
            continue
        if title not in seen[rel]:
            seen[rel].add(title)
            sections[rel].append(title)

    if skipped_no_anchor or skipped_not_in_tree:
        logger.warning(
            f"node_sections: skipped chunks (no_anchor={skipped_no_anchor}, "
            f"not_in_tree={skipped_not_in_tree}) lan_dir={lan_dir}"
        )
    nonempty = sum(1 for v in sections.values() if v)
    logger.info(
        f"node_sections: files={len(sections)} with_sections={nonempty} "
        f"total_titles={sum(len(v) for v in sections.values())}"
    )
    return sections


def write_node_sections(lan_dir: Path) -> Path:
    """生成并写 lan_dir/node_sections.json。

    用 indent=2 标准缩进（与 node_index.json 同风格）：文件要兼顾人工查阅，
    紧凑单行 JSON 打开没法读；空白字符在 RAG zip 里压缩率极高，体积代价可忽略。

    异常（nodes.lance 缺失、node_index.json 缺失等）向上抛，由调用方
    fail-soft 处理（不阻断向量库交付）。
    """
    sections = generate_node_sections(lan_dir)
    out_path = lan_dir / "node_sections.json"
    out_path.write_text(
        json.dumps(sections, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return out_path
