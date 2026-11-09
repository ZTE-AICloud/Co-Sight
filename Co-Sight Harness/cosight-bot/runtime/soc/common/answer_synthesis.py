#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
共享答案合成模块。

从 retrieve.py 的 _synthesize_answer 抽取，提供：
  - synthesize_cited_answer(query, nodes, llm, *, pre_dir, prompt_dump_dir)

构建树形 TOC + 上下文正文（带 [N] 引用标记），调 LLM 合成 Markdown 答案。
"""
from __future__ import annotations

import json
import logging
from collections import OrderedDict
from pathlib import Path
from typing import List, Optional

from llama_index.core import Response
from llama_index.core.schema import NodeWithScore

logger = logging.getLogger(__name__)


def _resolve_cosight_state_root() -> Path:
    """获取数据根目录（<workdir>/data，统一委托 port_resolver）。"""
    from common.port_resolver import cosight_state_root
    return cosight_state_root()


def _resolve_template() -> str:
    """获取 LLM 合成 prompt 模板"""
    try:
        from watch_dog.file_watcher.llamaindex_config import CITATION_QA_TEMPLATE_STR
        return CITATION_QA_TEMPLATE_STR
    except ImportError:
        return (
            "Context:\n{context_str}\n\n"
            "Question:\n{query_str}\n\n"
            "Answer the question using only the context above. "
            "Cite sources with [N] markers."
        )


def _resolve_file_mtime(metadata: dict, file_path: str = "") -> str:
    """三级回退获取 file_mtime：last_modified_date → file_mtime → st_mtime"""
    f_mtime = metadata.get("last_modified_date", "") or metadata.get("file_mtime", "")
    if f_mtime:
        return f_mtime
    fp = file_path or metadata.get("file_path", "")
    if fp and Path(fp).is_file():
        try:
            import datetime as _dt
            return _dt.datetime.fromtimestamp(
                Path(fp).stat().st_mtime
            ).strftime("%Y-%m-%d")
        except OSError:
            return ""
    return ""


def synthesize_cited_answer(
    query_text: str,
    source_nodes: List[NodeWithScore],
    llm,
    *,
    pre_dir: Optional[Path] = None,
    prompt_dump_dir: Optional[Path] = None,
    template_str: Optional[str] = None,
) -> Response:
    """
    用检索到的节点手动合成带引用的答案。

    Args:
        query_text: 用户原始问题
        source_nodes: 召回节点列表
        llm: 已配置的 LlamaIndex LLM 实例（显式注入，不读 Settings.llm）
        pre_dir: pre-processed 目录路径（用于压缩 file_path 显示）
        prompt_dump_dir: 提示词 dump 目录（默认 None 时不 dump）
        template_str: 自定义 prompt 模板（默认 CITATION_QA_TEMPLATE_STR）

    Returns:
        llama_index.core.Response 对象
    """
    if not source_nodes:
        return Response(response="未找到相关内容。", source_nodes=[])

    # =====================================================================
    # Step 1: 收集每个节点的元数据
    # =====================================================================
    node_infos = []
    for i, n in enumerate(source_nodes, 1):
        score = getattr(n, "score", 0.0)
        metadata = n.node.metadata or {}
        cid = metadata.get("chapter_id", "N/A")
        chapter_title = metadata.get("chapter_title", "")
        header_path = metadata.get("header_path", "").replace("\n", "").replace("\r", "")
        file_path = metadata.get("file_path", "")
        is_chapter = metadata.get("is_chapter_node", False)
        is_doc_level = metadata.get("is_doc_level", False)
        is_chapter_level = metadata.get("is_chapter_level", False)

        # 提取文档名（用于树形分组）
        doc_name = ""
        if file_path:
            doc_name = Path(file_path).stem
        elif header_path:
            parts = [p for p in header_path.split("/") if p.strip()]
            if parts:
                doc_name = parts[0]

        f_mtime = _resolve_file_mtime(metadata, file_path)

        node_infos.append({
            "idx": i,
            "score": score,
            "cid": cid,
            "chapter_title": chapter_title,
            "header_path": header_path,
            "file_path": file_path,
            "file_mtime": f_mtime,
            "doc_name": doc_name,
            "is_chapter": is_chapter,
            "is_doc_level": is_doc_level,
            "is_chapter_level": is_chapter_level,
            "content": n.node.get_content(),
        })

    # =====================================================================
    # Step 2: 构建树形目录索引
    # =====================================================================
    doc_groups = OrderedDict()
    for info in node_infos:
        doc = info["doc_name"] or "(未知文档)"
        if doc not in doc_groups:
            doc_groups[doc] = []
        doc_groups[doc].append(info)

    toc_lines = [
        "📚 资料目录索引",
        "",
        "【阅读指引】",
        "以下资料按文档分组，每组内按向量相关度（Score）降序排列。判断节点与问题的相关程度时，请优先关注以下元数据与问题的匹配度：",
        "1. Chapter Title（章节标题）：直接反映内容主题",
        "2. Header Path（文档路径）：反映该节点在知识库中的层级位置",
        "3. File Path（文件路径）：反映来源文档",
        "当这些元数据中的关键词与【问题】高度重合时，即使 Score 不是最高，也应作为高优先级信息来源重点关注。",
        "",
    ]

    for doc_name, infos in doc_groups.items():
        toc_lines.append(f"▸ {doc_name}")
        for info in infos:
            idx = info["idx"]
            score = info["score"]
            ch_title = info["chapter_title"] or "(无)"
            hp_display = info["header_path"] or ""

            fp = info["file_path"] or ""
            fp_display = ""
            if fp and pre_dir:
                pre_str = str(pre_dir)
                if pre_str in fp:
                    fp_display = fp.split(pre_str, 1)[1].lstrip("/\\")
                else:
                    fp_display = Path(fp).name
            elif fp:
                fp_display = Path(fp).name

            parts = [f"  ├── [{idx}] Score: {score:.4f}"]
            if fp_display:
                parts.append(f"File: {fp_display}")
            mtime = info.get("file_mtime", "")
            if mtime:
                parts.append(f"Modified: {mtime}")
            if hp_display:
                parts.append(f"Header: {hp_display}")
            parts.append(f"Chapter: {ch_title}")
            toc_lines.append(" | ".join(parts))
        toc_lines.append("")

    toc_lines.append("---")
    toc_lines.append("")
    toc_str = "\n".join(toc_lines)

    # =====================================================================
    # Step 3: 构建带引用标记的上下文正文
    # =====================================================================
    context_parts = []
    for info in node_infos:
        i = info["idx"]
        meta_lines = [
            f"- **Score**: {info['score']:.4f}",
            f"- **Chapter ID**: {info['cid']}",
        ]
        if info["chapter_title"]:
            meta_lines.append(f"- **Chapter Title**: {info['chapter_title']}")
        if info["header_path"]:
            meta_lines.append(f"- **Header Path**: {info['header_path']}")
        if info["file_path"]:
            meta_lines.append(f"- **File Path**: {info['file_path']}")
        if info.get("file_mtime"):
            meta_lines.append(f"- **Last Modified**: {info['file_mtime']}")
        meta_lines.append(
            f"- **Node Type**: {'Chapter (Aggregated)' if info['is_chapter'] else 'Small Chunk'}"
        )
        if info["is_doc_level"]:
            meta_lines.append("- **Doc Level**: true")
        if info["is_chapter_level"]:
            meta_lines.append("- **Chapter Level**: true")

        header = f"================ START OF SOURCE [{i}] ================\n"
        meta_str = "**[Metadata]**\n" + "\n".join(meta_lines)
        context_parts.append(
            f"{header}\n{meta_str}\n\n**[Content]**\n{info['content']}\n\n"
            f"================ END OF SOURCE [{i}] ================"
        )

    body_str = "\n\n".join(context_parts)
    context_str = toc_str + "\n" + body_str

    # =====================================================================
    # Step 4: 调 LLM 合成答案
    # =====================================================================
    template = template_str or _resolve_template()
    try:
        prompt = template.format(context_str=context_str, query_str=query_text)
    except (KeyError, IndexError) as e:
        logger.error(f"Prompt template format failed: {e}")
        return Response(response=f"答案合成失败: 模板格式错误 {e}", source_nodes=source_nodes)

    # Dump prompt 到文件（可选）
    if prompt_dump_dir is not None:
        try:
            prompt_dump_dir.mkdir(parents=True, exist_ok=True)
            prompt_path = prompt_dump_dir / "5_prompt.md"
            prompt_path.write_text(prompt, encoding="utf-8")
            logger.info(f"Saved final prompt to {prompt_path}")
        except Exception as e:
            logger.warning(f"Failed to save prompt: {e}")

    logger.info(f"Synthesizing answer with {len(source_nodes)} nodes via LLM...")
    try:
        llm_response = llm.complete(prompt)
        answer_text = str(llm_response)
        return Response(response=answer_text, source_nodes=source_nodes)
    except Exception as e:
        logger.error(f"LLM synthesis failed: {e}", exc_info=True)
        return Response(response=f"答案合成失败: {e}", source_nodes=source_nodes)
