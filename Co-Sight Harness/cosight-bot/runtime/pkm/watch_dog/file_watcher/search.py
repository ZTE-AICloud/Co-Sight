#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LlamaIndex 索引构建与查询引擎

"""

import os
import time
import json
import asyncio
import threading
import logging
import hashlib
import re
from pathlib import Path
from typing import Any, List, Optional, Dict
from filelock import FileLock

from .config import get_route_key, get_llamaindex_storage_dirs, get_session_storage_dirs
from .llamaindex_config import CITATION_QA_TEMPLATE_STR, LLAMADINDEX_REFERENCE_BASE_DIR
from .embedding_model import OnlineBGEEmbedding, OnlineBGERerank, CHUNK_OVERLAP, CHUNK_SIZE
from .artifact_paths import PREPROCESSED_ARTIFACT_SUFFIXES

logger = logging.getLogger("search")

# Global cache for Query Engines
_engine_cache = {}
_cache_lock = threading.RLock()

# Per-route_key build lock to prevent concurrent LanceDB table creation
_build_locks: dict[str, threading.Lock] = {}
_build_locks_lock = threading.Lock()

def _get_ipc_lock(lancedb_dir: Path) -> FileLock:
    """获取跨进程文件锁，保护 LanceDB 的并发写入"""
    lancedb_dir.mkdir(parents=True, exist_ok=True)
    return FileLock(str(lancedb_dir / ".lancedb_write.lock"))


def clear_cache(agent_id: str = None):
    logger.info(f"LlamaIndex Search: Clearing engine cache (agent={agent_id})")
    with _cache_lock:
        _engine_cache.clear()


def clear_cache_for_route(route_key: str):
    logger.info(
        f"LlamaIndex Search: Clearing engine cache for route {route_key}")
    with _cache_lock:
        if route_key in _engine_cache:
            del _engine_cache[route_key]


# ======== [CoSight-START] feature: chapter-ppt-slides-cleanup-defense ========
def _is_indexable_pre_md(path: Path) -> bool:
    """判断 pre_dir 下的 .md 文件是否应该被 LlamaIndex 入库。

    返回 True 表示应纳入 nodes.lance / chapters.lance 的输入，False 表示排除。

    排除以下来源产物（避免重复内容或污染向量召回）：
      - references/                — Wiki 抓下来的 wiki 状态文件目录
      - <stem>_chapters/ 及其后代   — chapter_splitter 生成的章节子文件
      - <stem>_images/ 及其后代   — doc_image_extractor 生成的混排 PDF/Word 图片体系
                                    （图元数据由 overview_resolver 注入主 md 节点；
                                    若 _images/ 下出现 .md 描述，会与主 md 重复入库）
      - <stem>_pages/ 及其后代    — doc_image_extractor 生成的扫描件页面体系
                                    （Page_NNN.md 已被主 md merge 进全文；这里再入一次
                                    会让 Page 标题被多次切节点、得分叠加排序混乱）
      - <stem>_<ppt-ext>_slides/ 及其后代 — ppt_slide_extractor 生成的每页 .md
                                    （内容与 <stem>.pptx.md 重复，且含
                                    ![](Slide_NN_*.png) 形式的伪引用；
                                    per-slide 节点由 overview + read-doc 直接定位）

    Note: 现在 _images/ _pages/ 默认没有 .md（只有 png + images_index.json），
    实际不会触发这些规则；这里写明是**防御性兜底**——避免日后有人在子目录里
    写图描述/页文本时再次污染向量索引。
    """
    parts = path.parts
    if "references" in parts:
        return False
    if any(
        p.endswith(s)
        for p in parts
        for s in PREPROCESSED_ARTIFACT_SUFFIXES
    ):
        return False
    return True
# ======== [CoSight-END] feature: chapter-ppt-slides-cleanup-defense ========


def _export_debug_nodes(agent_id: str, msg_sn: str, query: str, step_name: str, nodes: List[Any]):
    """导出中间检索/聚合节点以供调试查看，使用 Markdown 格式以便于阅读"""
    if not msg_sn or not agent_id:
        return

    # 调试文件存放在 <state_root>/canvas/deep-search/<agent_id>/<msg_sn>/ 下
    # （state_root = 数据根（COSIGHTBOT_HOME > CLAUDE_PLUGIN_DATA > 官方默认，见 common/port_resolver.py））
    from .config import cosight_state_root
    debug_dir = cosight_state_root() / "canvas" / "deep-search" / agent_id / msg_sn
    debug_dir.mkdir(parents=True, exist_ok=True)

    md_lines = []
    separator = "*" * 55
    md_lines.append(f"{separator}\n")
    md_lines.append(f"# Semantic Search Debug Export - {step_name}")
    md_lines.append(f"- **Query**: {query}")
    md_lines.append(f"- **Step**: {step_name}")
    md_lines.append(f"- **Total Nodes**: {len(nodes)}")
    md_lines.append(f"\n{separator}\n")

    for i, n in enumerate(nodes):
        score = getattr(n, "score", 0.0)
        metadata = getattr(n.node, "metadata", {})
        cid = metadata.get("chapter_id", "N/A")
        chapter_title = metadata.get("chapter_title", "")
        header_path = metadata.get("header_path", "").replace(
            "\n", "").replace("\r", "")
        file_path = metadata.get("file_path", "")
        is_chapter = metadata.get("is_chapter_node", False)
        is_doc_level = metadata.get("is_doc_level", False)
        is_chapter_level = metadata.get("is_chapter_level", False)
        reason = metadata.get("aggregation_reason", "")

        md_lines.append(f"# Node {i+1}")
        md_lines.append(f"- **Score**: {score:.4f}")
        # 新增：暴露 LLM 重排后的元数据（来自 LLMRerank）
        vector_score = metadata.get("vector_score")
        if vector_score is not None:
            md_lines.append(f"- **Vector Score (原始)**: {float(vector_score):.4f}")
        md_lines.append(f"- **Chapter ID**: {cid}")
        if chapter_title:
            md_lines.append(f"- **Chapter Title**: {chapter_title}")
        if header_path:
            md_lines.append(f"- **Header Path**: {header_path}")
        if file_path:
            md_lines.append(f"- **File Path**: {file_path}")
        md_lines.append(
            f"- **Node Type**: {'Chapter (Aggregated)' if is_chapter else 'Small Chunk'}")
        if is_doc_level:
            md_lines.append("- **Doc Level**: true")
        if is_chapter_level:
            md_lines.append("- **Chapter Level**: true")
        if reason:
            md_lines.append(f"- **Aggregation Reason**: {reason}")

        content = n.node.get_content()
        md_lines.append("\n**Content**:")
        md_lines.append(f"\n{content}")
        md_lines.append("\n---\n")

    md_content = "\n".join(md_lines)
    filename = f"{step_name}.md"
    filepath = debug_dir / filename

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(md_content)
        logger.info(f"已保存调试节点信息到文件: {filepath}")
    except Exception as e:
        logger.error(f"保存调试信息失败: {e}")


class LoggingRetriever:
    """包装 Retriever 以记录检索出的内容"""

    def __init__(self, base_retriever):
        self._base_retriever = base_retriever

    def retrieve(self, str_or_query_bundle):
        try:
            nodes = self._base_retriever.retrieve(str_or_query_bundle)
        except Warning as w:
            # 空索引场景：LanceDBVectorStore.query 在索引无节点时会 raise
            # Warning("query results are empty..")（llama_index/vector_stores/
            # lancedb/base.py:563）。这是合法空结果而非错误，应返回空列表让上层
            # 走 "未找到相关内容" 或 Session 级 fallback，而不是中断整个搜索流程。
            logger.warning(
                f"LoggingRetriever: empty index, treating as no results: {w}")
            return []
        logger.info(
            f"LoggingRetriever: Retrieved {len(nodes)} chunks from LanceDB.")
        return nodes


try:
    from llama_index.core.postprocessor.types import BaseNodePostprocessor
    from llama_index.core.schema import NodeWithScore, TextNode
except ImportError:
    BaseNodePostprocessor = object
    NodeWithScore = object
    TextNode = object


class ChapterAggregationPostprocessor(BaseNodePostprocessor):
    """根据章节 ID 聚合节点的后处理器。"""

    def __init__(self, chapter_table: Any, agent_id: str = "", msg_sn: str = "", query: str = ""):
        super().__init__()
        self._chapter_table = chapter_table
        self._agent_id = agent_id
        self._msg_sn = msg_sn
        self._query = query

    def _is_incomplete_table(self, text: str) -> bool:
        """简单的启发式规则判断 Markdown 表格是否不完整。"""
        lines = text.split('\n')
        in_code_block = False
        table_blocks, current_block = [], []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('```'):
                in_code_block = not in_code_block
                if current_block:
                    table_blocks.append(current_block)
                    current_block = []
                continue
            if in_code_block:
                continue
            if '|' in line:
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 3 and any(p for p in parts):
                    current_block.append(line)
                elif current_block:
                    table_blocks.append(current_block)
                    current_block = []
            elif current_block:
                table_blocks.append(current_block)
                current_block = []
        if current_block:
            table_blocks.append(current_block)

        if not table_blocks:
            return False

        for block in table_blocks:
            if len(block) < 2:
                return True
            has_separator = any(
                re.match(r'^\s*\|?\s*:?-+:?\s*\|', line) for line in block)
            col_counts = [len([p for p in line.split('|') if p.strip()])
                          for line in block]
            if len(set(col_counts)) > 1 or not has_separator:
                return True
        return False

    def _postprocess_nodes(self, nodes: List[NodeWithScore], query_bundle: Optional[Any] = None) -> List[NodeWithScore]:
        """对召回的节点按章节聚合。"""
        chapter_groups: Dict[str, List[NodeWithScore]] = {}
        for n in nodes:
            cid = n.node.metadata.get("chapter_id")
            if cid:
                chapter_groups.setdefault(cid, []).append(n)

        final_nodes, processed_chapters = [], set()
        for node_with_score in nodes:
            chapter_id = node_with_score.node.metadata.get("chapter_id")
            if not chapter_id:
                final_nodes.append(node_with_score)
                continue
            if chapter_id in processed_chapters:
                continue

            group = chapter_groups[chapter_id]
            # 检查 group 中是否有文档级扩展节点（已含完整文档内容）
            doc_level_node = next(
                (n for n in group if n.node.metadata.get("is_doc_level")),
                None
            )
            # 聚合条件：chunk 数量 >= 3 或者 包含不完整的表格
            has_incomplete = any(self._is_incomplete_table(
                n.node.get_content()) for n in group)
            if len(group) >= 3 or has_incomplete:
                # 优先使用文档级扩展节点（已含完整文档内容，不替换为 chapters 表原文）
                if doc_level_node:
                    final_nodes.append(doc_level_node)
                    processed_chapters.add(chapter_id)
                    continue
                try:
                    result = self._chapter_table.search().where(
                        f"id = '{chapter_id}'").limit(1).to_list()
                    if result:
                        chapter_data = result[0]
                        metadata = dict(chapter_data["metadata"])
                        # 从组内 chunk 中获取最小的 start_char_idx 作为章节节点的位置信息
                        # 用于引文按原始位置排序
                        start_char_indices = [
                            getattr(n.node, 'start_char_idx', None)
                            for n in group
                            if getattr(n.node, 'start_char_idx', None) is not None
                        ]
                        if start_char_indices:
                            metadata['start_char_idx'] = min(
                                start_char_indices)
                        metadata.update({
                            "is_chapter_node": True,
                            "aggregation_reason": "incomplete table" if has_incomplete else "chunk count >= 3"
                        })
                        chapter_node = TextNode(
                            text=chapter_data["text"], id_=chapter_data["id"], metadata=metadata)
                        final_nodes.append(NodeWithScore(
                            node=chapter_node, score=max(n.score for n in group)))
                        processed_chapters.add(chapter_id)
                        continue
                except Exception as e:
                    logger.warning(
                        f"Failed to aggregate chapter {chapter_id}: {e}")

            # 不满足聚合条件，保留原样
            for n in group:
                final_nodes.append(n)
            processed_chapters.add(chapter_id)

        # 导出聚合后的调试信息
        if self._msg_sn:
            _export_debug_nodes(self._agent_id, self._msg_sn,
                                self._query, "2_aggregated_nodes", final_nodes)

        return final_nodes


def get_query_engine(material_source_dir: Path, agent_id: str = "", llm_client: Any = None, msg_sn: str = "", query_text: str = "", session_key_hash: str = "", pre_dir: Path = None, lan_dir: Path = None, allow_preprocessing: bool = True):
    # 调用方可直接传入路径，绕过 material_source_dir 的路径哈希计算
    if pre_dir is None or lan_dir is None:
        if session_key_hash:
            _, pre_dir, lan_dir = get_session_storage_dirs(agent_id, session_key_hash)
        else:
            pre_dir, lan_dir = get_llamaindex_storage_dirs(material_source_dir, agent_id)

    rk = get_route_key(material_source_dir, agent_id=agent_id, session_key_hash=session_key_hash)

    with _cache_lock:
        if rk in _engine_cache:
            logger.info(
                f"LlamaIndex Search: Using cached query engine for {material_source_dir.name}")
            return _engine_cache[rk][0]

    # 使用跨进程文件锁保护 LanceDB 的并发初始化和表创建逻辑
    with _get_ipc_lock(lan_dir):
        # 再次检查缓存
        with _cache_lock:
            if rk in _engine_cache:
                logger.info(
                    f"LlamaIndex Search: Using cached query engine for {material_source_dir.name}")
                return _engine_cache[rk][0]
        return _do_get_query_engine(material_source_dir, agent_id, llm_client, rk, msg_sn=msg_sn, query_text=query_text, session_key_hash=session_key_hash, pre_dir=pre_dir, lan_dir=lan_dir, allow_preprocessing=allow_preprocessing)


def _do_get_query_engine(material_source_dir: Path, agent_id: str, llm_client: Any, rk: str, msg_sn: str = "", query_text: str = "", session_key_hash: str = "", pre_dir: Path = None, lan_dir: Path = None, allow_preprocessing: bool = True):
    logger.info(
        f"LlamaIndex Search: Initializing new query engine for {material_source_dir}")

    from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings, StorageContext, PromptTemplate
    from llama_index.core.query_engine import CitationQueryEngine
    from llama_index.llms.openai_like import OpenAILike
    from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter
    from llama_index.vector_stores.lancedb import LanceDBVectorStore
    import lancedb

    # Extract config from client
    if isinstance(llm_client, dict):
        model_name = llm_client.get(
            "model", "") or llm_client.get("model_name", "")
        api_url = llm_client.get(
            "base_url", "") or llm_client.get("api_url", "")
        api_key = llm_client.get("api_key", "")
        max_tokens = llm_client.get("max_tokens")
        context_window = llm_client.get(
            "context_window") or llm_client.get("max_in_tokens")
    else:
        model_name = getattr(llm_client, 'model_name', '')
        api_url = getattr(llm_client, 'api_url', None)
        api_key = getattr(llm_client, 'api_key', None)
        max_tokens = getattr(llm_client, 'max_tokens', None)
        context_window = getattr(llm_client, 'context_window', None) or getattr(
            llm_client, 'max_in_tokens', None)
    if not model_name or not api_url:
        raise RuntimeError("Failed to get llm model config.")

    if not api_key:
        for attr_name in dir(llm_client):
            if attr_name.lower() == 'authorization':
                api_key = getattr(llm_client, attr_name, None)
                break

    # 清理 api_url
    if api_url and "/chat/completions" in api_url:
        api_url = api_url.rsplit("/chat/completions", 1)[0]

    # 清理 api_key
    if api_key and isinstance(api_key, str) and api_key.lower().startswith("bearer "):
        api_key = api_key[7:]

    logger.info(
        f"LlamaIndex Search: Using LLM model={model_name}, api_base={api_url}")

    llm = OpenAILike(
        model=model_name, api_key=api_key, api_base=api_url,
        # max_tokens 保留 None 让 LlamaIndex 自行决定；
        # contextWindow 与新安装/升级规范（256000）保持一致。
        max_tokens=max_tokens,
        context_window=context_window or 256000,
        is_chat_model=True, timeout=300.0
    )
    embed_model = OnlineBGEEmbedding()

    Settings.llm = llm
    Settings.embed_model = embed_model
    Settings.chunk_size = CHUNK_SIZE
    Settings.chunk_overlap = CHUNK_OVERLAP

    if pre_dir is None or lan_dir is None:
        if session_key_hash:
            _, pre_dir, lan_dir = get_session_storage_dirs(agent_id, session_key_hash)
        else:
            pre_dir, lan_dir = get_llamaindex_storage_dirs(
                material_source_dir, agent_id)
    if not pre_dir or not lan_dir:
        raise RuntimeError("Failed to get LlamaIndex storage directories.")

    # 先探查并清理无效/损坏的 nodes.lance 目录（存在但不是有效表，如构建刚建目录就被 kill）。
    # LanceDBVectorStore.__init__ 的 _table_exists() 用 table_names() 会把空目录误报为
    # 有表，随后 open_table 抛 "Table 'nodes' was not found"——必须在创建 vector_store 前清掉。
    import lancedb as _lancedb
    _db_probe = _lancedb.connect(str(lan_dir))
    try:
        _db_probe.open_table("nodes")
        has_index = True
    except Exception:
        has_index = False
    if not has_index:
        _stale = lan_dir / "nodes.lance"
        if _stale.exists():
            try:
                import shutil as _sh
                _sh.rmtree(_stale, ignore_errors=True)
                logger.info(
                    f"LlamaIndex Search: removed stale nodes.lance dir for rebuild "
                    f"in {material_source_dir.name}"
                )
            except Exception:
                pass

    db = lancedb.connect(str(lan_dir))
    vector_store = LanceDBVectorStore(uri=str(lan_dir), table_name="nodes")
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    if not has_index:
        logger.info(
            f"LlamaIndex Search: Building new index for {material_source_dir.name}")
        # ======== [CoSight-START] feature: chapter-cleanup-defense ========
        # 过滤规则见 _is_indexable_pre_md：跳过 references/、*_chapters/、
        # *_pptx_slides/ 下的 .md，避免重复内容或污染向量召回。
        valid_md_files = [
            f for f in pre_dir.glob("**/*.md")
            if _is_indexable_pre_md(f)
        ]
        if not valid_md_files and not session_key_hash and allow_preprocessing:
            logger.info(
                f"LlamaIndex Search: No valid pre-processed files found, triggering pre-processor for {material_source_dir.name}")
            from .preprocessor import process_directory
            process_directory(material_source_dir, pre_dir)
            valid_md_files = [
                f for f in pre_dir.glob("**/*.md")
                if _is_indexable_pre_md(f)
            ]
        elif not valid_md_files and session_key_hash:
            # session 模式下不扫描 workspace，pre_dir 为空时直接创建空索引，
            # 后续由增量更新流程逐个文件插入。
            logger.info(
                f"LlamaIndex Search: Session mode, no pre-processed files in {pre_dir}, "
                f"initializing empty index for session {session_key_hash}")

        t_load = time.perf_counter()
        logger.info(f"LlamaIndex Search: Loading documents from {pre_dir}")

        if valid_md_files:
            # required_exts=[".md"] 过滤掉 wiki 状态文件 (.json)、assets 图片等
            # 跟 sync_chapters_table 保持一致：nodes 和 chapters 都只索引 .md
            documents = SimpleDirectoryReader(
                str(pre_dir), recursive=True, filename_as_id=True,
                exclude_hidden=False, required_exts=[".md"],
            ).load_data()

            # --- 路径标准化核心修复：强制转为 POSIX 风格 ---
            for doc in documents:
                # 统一 doc.id_ (这是 LlamaIndex 的内部标识符)
                doc.id_ = Path(doc.id_).resolve().as_posix()
                # 统一 metadata 中的路径
                if "file_path" in doc.metadata:
                    doc.metadata["file_path"] = Path(doc.metadata["file_path"]).resolve().as_posix()
            # ---------------------------------------------

            # ======== [CoSight-START] feature: chapter-cleanup-defense ========
            # 过滤规则与上面的 valid_md_files 保持一致（见 _is_indexable_pre_md）。
            documents = [
                doc for doc in documents
                if _is_indexable_pre_md(Path(doc.metadata.get("file_path", doc.id_)))
            ]
            # ======== [CoSight-END] feature: chapter-cleanup-defense ========
            logger.info(
                f"LlamaIndex Search: [Timing] Document loading took {time.perf_counter() - t_load:.2f}s, loaded {len(documents)} documents.")

            t_parse = time.perf_counter()
            md_parser = MarkdownNodeParser()
            chapter_nodes = md_parser.get_nodes_from_documents(documents)
            logger.info(
                f"LlamaIndex Search: [Timing] Markdown parsing took {time.perf_counter() - t_parse:.2f}s, parsed into {len(chapter_nodes)} chapter nodes.")

            t_split = time.perf_counter()
            splitter = SentenceSplitter(chunk_size=1024, chunk_overlap=128)
            chapter_data_list, final_nodes = [], []

            for c_node in chapter_nodes:
                content = c_node.get_content().replace('\r', '')
                cid = f"chap_{hashlib.md5(content.encode()).hexdigest()[:12]}"
                c_node.metadata["chapter_id"] = cid

                # --- 确保 c_node 自身的 metadata 也被标准化 ---
                if "file_path" in c_node.metadata:
                    c_node.metadata["file_path"] = Path(c_node.metadata["file_path"]).resolve().as_posix()

                chapter_data_list.append({
                    "id": cid,
                    "text": content,
                    "metadata": c_node.metadata,
                    "vector": [0.0] * 1024  # placeholder for compatibility
                })

                small_nodes = splitter.get_nodes_from_documents([c_node])
                # 提取章节标题（content 的第一行，如 "# 需求："）
                first_line = content.split('\n', 1)[0].strip()
                chapter_title = first_line if first_line.startswith(
                    '#') else ""
                for s_node in small_nodes:
                    s_node.metadata["chapter_id"] = cid
                    s_node.metadata["chapter_title"] = chapter_title
                    # s_node 继承 c_node 的 metadata，已包含标准化的 file_path
                    final_nodes.append(s_node)

            logger.info(
                f"LlamaIndex Search: [Timing] Node splitting took {time.perf_counter() - t_split:.2f}s, final node count: {len(final_nodes)}.")
            if chapter_data_list:
                db.create_table(
                    "chapters", data=chapter_data_list, mode="overwrite")
            elif "chapters" in db.list_tables().tables:
                db.drop_table("chapters")
        else:
            logger.info(
                f"LlamaIndex Search: No documents found in {pre_dir}, initializing empty index.")
            final_nodes = []
            if "chapters" in db.list_tables().tables:
                db.drop_table("chapters")

        t_build = time.perf_counter()
        index = VectorStoreIndex(final_nodes, storage_context=storage_context)
        logger.info(
            f"LlamaIndex Search: [Timing] Index building took {time.perf_counter() - t_build:.2f}s.")

        # 初始全量构建完成后，进行合并和版本清理，防止首次构建后就遗留多个事务碎片
        optimize_table(lan_dir, "nodes")
        if "chapters" in db.list_tables().tables:
            optimize_table(lan_dir, "chapters")
    else:
        t_load_idx = time.perf_counter()
        logger.info(
            f"LlamaIndex Search: Loading existing LanceDB index from {lan_dir}")
        index = VectorStoreIndex.from_vector_store(
            vector_store, storage_context=storage_context)
        logger.info(
            f"LlamaIndex Search: [Timing] Existing index loading took {time.perf_counter() - t_load_idx:.2f}s.")

    vector_retriever = index.as_retriever(similarity_top_k=50)
    logging_retriever = LoggingRetriever(vector_retriever)
    citation_qa_tmpl = PromptTemplate(CITATION_QA_TEMPLATE_STR)

    # chapters 表仅在 pre_dir 存在可索引文档时才会被创建;空目录/全量清理场景下
    # 不存在,open_table 会抛 "Table 'chapters' was not found",导致空目录绑定
    # 时整个 build 流程失败。这里按需装配 postprocessor:
    #   - 表存在:用真实表,启用章节聚合
    #   - 表不存在:不挂 postprocessor,CitationQueryEngine 退化为纯向量检索
    #     (节点 metadata 无 chapter_id 时 ChapterAggregationPostprocessor 本来就是 no-op)
    node_postprocessors = []
    try:
        existing_tables = db.list_tables().tables
    except Exception as e:
        logger.warning(
            f"LlamaIndex Search: list_tables failed, skipping chapter aggregation: {e}")
        existing_tables = []
    if "chapters" in existing_tables:
        try:
            chapter_tbl = db.open_table("chapters")
            node_postprocessors.append(
                ChapterAggregationPostprocessor(
                    chapter_tbl, agent_id, msg_sn, query_text)
            )
        except Exception as e:
            logger.warning(
                f"LlamaIndex Search: open chapters table failed, skipping chapter aggregation: {e}")
    else:
        logger.info(
            f"LlamaIndex Search: chapters table not present in {material_source_dir.name}, "
            f"skipping chapter aggregation postprocessor."
        )

    engine = CitationQueryEngine.from_args(
        index,
        retriever=logging_retriever,
        node_postprocessors=node_postprocessors,
        citation_qa_template=citation_qa_tmpl,
        citation_chunk_size=100000,  # Large chunk size as requested in skills
    )
    # CitationQueryEngine.from_args 不会把 index 存为属性（仅用于创建 retriever），
    # 手动挂上以便 retrieve.py 等调用方通过 engine._index 获取向量库实例
    engine._index = index

    # 缓存策略：
    # - 有 postprocessors：缓存 engine + index（完整构建）
    # - session 模式：缓存 engine + index（空索引需用于后续 insert_nodes）
    # - 非 session 无 postprocessors：仍缓存 index（增量更新路径调
    #   get_cached_index 拿 index.insert_nodes 必须能命中），不缓存 engine。
    #   后续查询因缺少章节聚合会在 get_query_engine 里 rebuild engine。
    if len(node_postprocessors) > 0 or session_key_hash:
        with _cache_lock:
            _engine_cache[rk] = (engine, index)
    else:
        with _cache_lock:
            # 只缓存 index，不缓存 engine（避免查询走无 postprocessor 的旧 engine）
            existing = _engine_cache.get(rk)
            if existing is None:
                _engine_cache[rk] = (engine, index)
            else:
                # 已有缓存 entry，仅刷新 index 部分
                old_engine, _ = existing
                _engine_cache[rk] = (old_engine, index)
        logger.info(
            f"LlamaIndex Search: node_postprocessors is empty for {material_source_dir.name}, "
            f"cached index only — engine will rebuild on next query once "
            f"chapters table is populated."
        )
    logger.info(
        f"LlamaIndex Search: Query engine ready for {material_source_dir.name}")
    return engine


def get_cached_index(material_source_dir: Path, agent_id: str = "", session_key_hash: str = ""):
    """获取已缓存的 VectorStoreIndex，供增量更新使用。"""
    rk = get_route_key(material_source_dir, agent_id=agent_id, session_key_hash=session_key_hash)
    with _cache_lock:
        if rk in _engine_cache:
            return _engine_cache[rk][1]
    return None


async def async_llamaindex_search(
    query: str,
    material_source_dir: Path,
    agent_id: str = "",
    message_serial_number: str = None,
    locale: str = "zh",
    llm_client: Any = None,
) -> Dict[str, Any]:
    """
    异步执行 LlamaIndex 检索。
    """
    logger.info(
        f"LlamaIndex Search: [Query] Starting search for: '{query[:50]}...' in {material_source_dir.name}")
    try:
        if not message_serial_number:
            import uuid
            message_serial_number = str(uuid.uuid4())

        engine = get_query_engine(material_source_dir, agent_id=agent_id, llm_client=llm_client,
                                  msg_sn=message_serial_number, query_text=query)

        # Skill-like retrieved chunks debugging
        if message_serial_number:
            retriever = engine.retriever
            retrieved_nodes = retriever.retrieve(query)
            _export_debug_nodes(agent_id, message_serial_number,
                                query, "1_retrieved_chunks", retrieved_nodes)

        logger.info("LlamaIndex Search: Executing engine query...")
        t_query = time.perf_counter()
        response = await asyncio.to_thread(engine.query, query)
        logger.info(
            f"LlamaIndex Search: [Timing] Query execution took {time.perf_counter() - t_query:.2f}s")

        answer = str(response)
        source_nodes = getattr(response, "source_nodes", [])
        logger.info(
            f"LlamaIndex Search: [Query] Received answer (len={len(answer)}) and {len(source_nodes)} source nodes.")

        # Debug export for final source nodes
        if message_serial_number:
            _export_debug_nodes(agent_id, message_serial_number,
                                query, "3_final_source_nodes", source_nodes)

        # TODO: citation 持久化待后续实现
        citation_urls = []

        return {
            "answer": answer,
            "source_nodes": [
                {
                    "content": node.node.get_content(),
                    "metadata": node.node.metadata,
                    "score": getattr(node, "score", 0)
                } for node in source_nodes
            ],
            "citation_urls": citation_urls
        }
    except Exception as e:
        logger.error(f"LlamaIndex Search: Search failed: {e}", exc_info=True)
        return {"answer": "", "source_nodes": [], "citation_urls": [], "error": str(e)}


def sync_chapters_table(
    material_source_dir: Path,
    agent_id: str,
    session_key_hash: str = "",
) -> bool:
    """扫描 pre_dir 当前所有 md，按 MarkdownNodeParser 重建 chapters 表。

    与 _do_get_query_engine 中的章节构建逻辑一致，但仅写 chapters 表，
    不重建 nodes（nodes 由调用方通过 index.insert/update_ref_doc/delete_ref_doc 处理）。

    成本：仅 markdown 解析 + MD5 哈希，**不跑 embedding**，因此可以频繁调用。

    适用场景：
    - watchdog 文件事件后调用，让 chapters 与 pre_dir 状态对齐
    - wiki 等外部源爬取/删除后的索引同步

    并发：handler 的 ThreadPoolExecutor 会在每个文件事件后调用本函数重建 chapters,
    同一 route 的并发调用会触发 db.drop_table + db.create_table 之间的临时目录竞争,
    导致 LanceError(IO): 系统找不到指定的路径 (os error 3)。使用与
    ``get_query_engine`` 相同的 ``_build_locks[rk]`` 串行化,避免多线程同时
    在同一个 chapters.lance 目录上 create_table。
    """
    import lancedb
    from llama_index.core import SimpleDirectoryReader
    from llama_index.core.node_parser import MarkdownNodeParser
    from datetime import timedelta

    t_total_start = time.perf_counter()

    # 使用跨进程文件锁,防止不同子进程并发 drop+create 触发 LanceDB 临时文件路径竞争或抛出 Retryable commit conflict。
    if session_key_hash:
        _, pre_dir, lan_dir = get_session_storage_dirs(agent_id, session_key_hash)
    else:
        pre_dir, lan_dir = get_llamaindex_storage_dirs(
            material_source_dir, agent_id
        )
    if not pre_dir or not lan_dir:
        logger.error(
            f"sync_chapters_table: failed to get storage dirs "
            f"(material={material_source_dir}, agent={agent_id})"
        )
        return False

    with _get_ipc_lock(lan_dir):
        db = lancedb.connect(str(lan_dir))
        chapter_data_list: list = []
        n_md_files = 0
        t_parse_start = time.perf_counter()

        try:
            if pre_dir.exists():
                # ======== [CoSight-START] feature: chapter-cleanup-defense ========
                # 过滤掉 chapter_splitter 生成的 _chapters 子目录下的章节子文件，
                # 以及 ppt_slide_extractor 生成的 _pptx_slides/ 下的每页 .md。
                # 规则集中到 _is_indexable_pre_md；本函数在 chapter_splitter /
                # handler 漏清理时是防御性兜底。
                md_files = [
                    f for f in pre_dir.glob("**/*.md")
                    if f.is_file() and _is_indexable_pre_md(f)
                ]
                n_md_files = len(md_files)
                # ======== [CoSight-END] feature: chapter-cleanup-defense ========
            if n_md_files > 0:
                # required_exts limits to .md so the wiki state file
                # (.wiki_state.json) doesn't get parsed as a chapter.
                documents = SimpleDirectoryReader(
                    str(pre_dir), recursive=True, filename_as_id=True,
                    exclude_hidden=False, required_exts=[".md"],
                ).load_data()

                # --- 路径标准化核心修复：强制转为 POSIX 风格 ---
                for doc in documents:
                    # 统一 doc.id_ (这是 LlamaIndex 的内部标识符)
                    doc.id_ = Path(doc.id_).resolve().as_posix()
                    # 统一 metadata 中的路径
                    if "file_path" in doc.metadata:
                        doc.metadata["file_path"] = Path(doc.metadata["file_path"]).resolve().as_posix()
                # ---------------------------------------------

                # ======== [CoSight-START] feature: chapter-cleanup-defense ========
                # 过滤规则与上面的 md_files 保持一致（见 _is_indexable_pre_md）。
                documents = [
                    doc for doc in documents
                    if _is_indexable_pre_md(Path(doc.metadata.get("file_path", doc.id_)))
                ]
                # ======== [CoSight-END] feature: chapter-cleanup-defense ========

                md_parser = MarkdownNodeParser()
                for c_node in md_parser.get_nodes_from_documents(documents):
                    content = c_node.get_content().replace("\r", "")
                    cid = f"chap_{hashlib.md5(content.encode()).hexdigest()[:12]}"
                    c_node.metadata["chapter_id"] = cid

                    # --- 确保 c_node 自身的 metadata 也被标准化 ---
                    if "file_path" in c_node.metadata:
                        c_node.metadata["file_path"] = Path(c_node.metadata["file_path"]).resolve().as_posix()

                    first_line = content.split('\n', 1)[0].strip()
                    c_node.metadata["chapter_title"] = first_line if first_line.startswith(
                        '#') else ""
                    chapter_data_list.append({
                        "id": cid,
                        "text": content,
                        "metadata": c_node.metadata,
                        # placeholder for compatibility
                        "vector": [0.0] * 1024,
                    })
        except Exception as e:
            logger.error(
                f"sync_chapters_table: failed to parse pre_dir {pre_dir}: {e}", exc_info=True)
            return False

        t_parse = time.perf_counter() - t_parse_start

        try:
            t_write_start = time.perf_counter()
            if "chapters" in db.list_tables().tables:
                db.drop_table("chapters")
            if chapter_data_list:
                table = db.create_table(
                    "chapters", data=chapter_data_list, mode="overwrite")
                # 增量更新后立即优化，防止文件爆炸
                table.optimize()
                table.cleanup_old_versions(older_than=timedelta(0))
            t_write = time.perf_counter() - t_write_start
        except Exception as e:
            logger.error(
                f"sync_chapters_table: failed to write chapters table: {e}", exc_info=True)
            return False

        t_total = time.perf_counter() - t_total_start
        logger.info(
            f"sync_chapters_table: agent={agent_id} material={material_source_dir.name} "
            f"md_files={n_md_files} chapters={len(chapter_data_list)} "
            f"timing=[parse={t_parse:.3f}s, write={t_write:.3f}s, total={t_total:.3f}s]"
        )

        return True


def optimize_table(lan_dir: Path, table_name: str):
    """优化 LanceDB 表：合并小文件并清理旧版本。

    调用频率建议：在处理完大批量的增删操作后调用。
    """
    import lancedb
    from datetime import timedelta
    try:
        db = lancedb.connect(str(lan_dir))
        if table_name in db.list_tables().tables:
            table = db.open_table(table_name)
            table.optimize()
            table.cleanup_old_versions(older_than=timedelta(0))
            logger.info(
                f"LlamaIndex Search: Table '{table_name}' optimized in {lan_dir}")
    except Exception as e:
        logger.warning(
            f"LlamaIndex Search: Failed to optimize table '{table_name}': {e}")
