#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SOC Agent 普通文档（pd_spec_vector_library）文件事件处理器。

对外只暴露一个公共函数：
    handle_common_file_event(src_path, event_type, dest_path, lancedb_dir,
                            pre_dir, workspace_root, llm_config)

事件分发与 handle_historical_file_event（historical_processor.py）
的 API 形态保持一致，但走的是**增量更新**路径：

    - created/modified: preprocess 单文件 → 解析 → 删旧 nodes/chapters 行
      （按 .md 路径精确匹配）→ 插入新行 → 写指纹
    - deleted: 按 .md 路径删 nodes/chapters 行 + 删 pre_dir/<rel>.md + 删指纹
    - moved: 先按旧路径 cleanup（同 deleted），再按新路径 upsert（同 created）

实现要点：
- nodes/chapters 表的 metadata.file_path 列存的是 .md 文件的绝对路径（POSIX），
  不是源文件路径。所有删除都按 .md 路径走，命名规则与
  preprocessor.process_single_file 一致：f"{stem}_{ext}".replace(".", "_") + ".md"
- 指纹通过 common.index_api 直接调（独立脚本下也生效，不再走 global_progress IPC）
- 跨进程文件锁 _get_ipc_lock 与 watchdog 复用同一把
"""
import logging
import sys
from datetime import datetime as _dt
from pathlib import Path

# Module-level helpers used by handle_common_file_event.
# 与本文件 _build_common_index / historical_processor.py
# 共享 fingerprint 算式和命名规则。
from watch_dog.file_watcher.preprocessor import _calculate_file_hash
from watch_dog.file_watcher.embedding_model import EmbeddingServiceError

# 本文件内部共用的预处理 helper（与 historical_processor.py 共用）。
from common.soc_kb_builder.vector_build.soc_rag_helpers import chapter_id_for, compute_md_path
from common.soc_kb_builder.document_types import (
    IMAGE_EXTS,
    SUPPORTED_DOCUMENT_EXTS,
)

# 复用 handler.py 内的鲁棒辅助：
#   - _strip_reader_metadata: 清洗 SimpleDirectoryReader 注入的 reader 字段
#     （避免 LanceDB schema mismatch: file_type / file_size / creation_date 等）
from watch_dog.file_watcher.handler import _strip_reader_metadata

# 与 watchdog / search.py 路径过滤规则对齐（references/ + _chapters/_images/
# _pages/_pptx_slides）：build_common_index 全量重建路径下也用同一规则，
# 防漂移。`_insert_source` 走单文件 SimpleDirectoryReader，不经过 glob，无需此 helper。
from watch_dog.file_watcher.search import _is_indexable_pre_md

logger = logging.getLogger("soc_rag.common_processor")


def _is_office_temp(path: str) -> bool:
    """检测 Office 临时文件（从 handler.LlamaIndexIncrementalHandler._is_office_temp 复制）。

    比 build_soc_vector.py 里的 `f.name.startswith("~$")` 更全：覆盖 .tmp / .bak /
    .ds_store / .tmp- / ~*.tmp 等场景。返回 True 时 caller 应跳过该文件
    （不插入、不计入失败）。

    为什么不直接 import LlamaIndexIncrementalHandler 然后调实例方法：
    handler.__init__ 会创建 ThreadPoolExecutor(4 线程) + watchdog FileSystemEventHandler
    基类 + debounce 状态 dict 等重依赖，仅为调一个 9 行方法不值。直接复制逻辑更轻。
    handler.py 那边如果改了 _is_office_temp，需要手动同步这里的逻辑。
    """
    p = Path(path)
    name = p.name.lower()
    if (
        name.startswith("~$")
        or (name.startswith("~") and (".tmp" in name or ".bak" in name))
        or name.endswith(".tmp")
        or name == ".ds_store"
    ):
        return True
    for part in p.parts:
        if ".tmp-" in part.lower():
            return True
    return False


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _posix_path(p: Path) -> str:
    return p.expanduser().resolve().as_posix()


def _get_rel_path(p: Path, workspace_root: Path) -> str:
    try:
        return p.relative_to(workspace_root).as_posix()
    except ValueError:
        return p.name


def _delete_by_file_path(lancedb_dir: Path, file_path_posix: str) -> None:
    """按 file_path 精确 + 子路径匹配，删除 nodes / chapters 表中相关行。

    与 handler.py::_brutal_purge_db 的多片段 LIKE 模式对齐，但按 file_path 直接过滤。
    每条 SQL 独立 try，遇到 "列不存在" 时跳过该列（chapters 没有 doc_id）。
    """
    if not file_path_posix:
        return
    try:
        from watch_dog.file_watcher.search import _get_ipc_lock
        with _get_ipc_lock(lancedb_dir):
            db = _connect_lancedb(lancedb_dir)
            try:
                res = db.list_tables()
                existing = res.tables if hasattr(res, "tables") else res
            except Exception:
                existing = []
            safe_path = file_path_posix.replace("'", "''")
            for table_name in ("nodes", "chapters"):
                if table_name not in existing:
                    continue
                try:
                    table = db.open_table(table_name)
                    table.delete(
                        f"metadata.file_path = '{safe_path}' OR "
                        f"metadata.file_path LIKE '{safe_path}/%'"
                    )
                except Exception as e:
                    msg = str(e)
                    # chapters 表没有 doc_id 列——按列查不存在的列会整条失败，
                    # 所以这里只对 nodes 表查 doc_id，对 chapters 表不查
                    if table_name == "chapters" and ("not found in struct" in msg or "No field" in msg):
                        continue
                    logger.warning(
                        f"common_processor: delete from {table_name} failed: {e}"
                    )
    except Exception as e:
        logger.warning(f"common_processor: failed to delete rows for {file_path_posix}: {e}")


def _delete_pre_md(pre_dir: Path, source_file: Path, workspace_root: Path) -> None:
    """删除 pre_dir/<rel>.md 预处理产物（命名规则见 soc_rag_helpers.compute_md_path）。

    workspace_root 即 specs_pd_dir（即 source_dir / 01_Specs_PD），是 preprocessor
    用的 specs_input_root。
    """
    try:
        md_file = compute_md_path(Path(source_file), pre_dir, workspace_root)
        if md_file.exists():
            md_file.unlink()
    except Exception as e:
        logger.warning(f"common_processor: failed to remove pre-md: {e}")


def _remove_fingerprint(lancedb_dir: Path, file_path: Path, workspace_root: Path) -> None:
    rel = _get_rel_path(file_path, workspace_root)
    try:
        from common.index_api import remove_file_info, remove_directory_info
        remove_file_info(lancedb_dir, rel)
        remove_directory_info(lancedb_dir, rel)
    except Exception as e:
        logger.warning(f"common_processor: failed to remove fingerprint for {rel}: {e}")


def _write_fingerprint(lancedb_dir: Path, file_path: Path, workspace_root: Path,
                       status: str = "success", error: str = "") -> None:
    rel = _get_rel_path(file_path, workspace_root)
    try:
        from common.index_api import update_file_info
        if status == "success":
            stat = file_path.stat()
            update_file_info(lancedb_dir, rel, {
                "mtime": stat.st_mtime,
                "size": stat.st_size,
                "hash": _calculate_file_hash(file_path),
                "status": "success",
                "error": ""
            })
        else:
            update_file_info(lancedb_dir, rel, {
                "mtime": 0,
                "size": 0,
                "status": "failed",
                "error": error,
            })
    except Exception as e:
        logger.warning(f"common_processor: failed to write fingerprint for {rel}: {e}")


def _connect_lancedb(lancedb_dir: Path):
    import lancedb
    lancedb_dir.mkdir(parents=True, exist_ok=True)
    return lancedb.connect(str(lancedb_dir))


# ---------------------------------------------------------------------------
# core: batch (full) rebuild of nodes + chapters from a pre-processed dir
# ---------------------------------------------------------------------------

def _build_common_index(pre_dir: Path, lan_dir: Path, llm_config: dict) -> bool:
    """全量构建 nodes + chapters 表。

    从 search._do_get_query_engine 抽取的纯构建逻辑，接受显式路径。
    与 _insert_source 的区别：本函数是**批量全量重建**（覆盖现有表），而
    _insert_source 是**单文件增量 upsert**（按 file_path 删旧行 + insert 新行）。
    build_soc_vector.py 当前走增量路径（每文件 _insert_source），本函数保留
    以备未来切换到全量构建模式时使用。
    """
    from llama_index.core import (
        VectorStoreIndex,
        SimpleDirectoryReader,
        Settings,
        StorageContext,
    )
    from llama_index.llms.openai_like import OpenAILike
    from llama_index.core.node_parser import MarkdownNodeParser
    from llama_index.core.schema import TextNode
    from common.table_aware_splitter import split_table_aware
    from llama_index.vector_stores.lancedb import LanceDBVectorStore
    from watch_dog.file_watcher.embedding_model import (
        OnlineBGEEmbedding,
        CHUNK_SIZE,
        CHUNK_OVERLAP,
    )
    from watch_dog.file_watcher.search import optimize_table
    import lancedb

    model_name = llm_config.get("model", "") or llm_config.get("model_name", "")
    api_url = llm_config.get("base_url", "") or llm_config.get("api_url", "")
    api_key = llm_config.get("api_key", "")
    max_tokens = llm_config.get("max_tokens")
    context_window = llm_config.get("context_window") or llm_config.get("max_in_tokens")

    if not model_name or not api_url:
        logger.error("Failed to get LLM model config.")
        return False

    if api_url and "/chat/completions" in api_url:
        api_url = api_url.rsplit("/chat/completions", 1)[0]

    if api_key and isinstance(api_key, str) and api_key.lower().startswith("bearer "):
        api_key = api_key[7:]

    logger.info(f"Using LLM model={model_name}, api_base={api_url}")

    llm = OpenAILike(
        model=model_name,
        api_key=api_key,
        api_base=api_url,
        max_tokens=max_tokens,
        context_window=context_window or 100000,
        is_chat_model=True,
        timeout=300.0,
    )
    embed_model = OnlineBGEEmbedding()

    Settings.llm = llm
    Settings.embed_model = embed_model
    Settings.chunk_size = CHUNK_SIZE
    Settings.chunk_overlap = CHUNK_OVERLAP

    lan_dir.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(lan_dir))
    vector_store = LanceDBVectorStore(uri=str(lan_dir), table_name="nodes")
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    # 与 watchdog / search.py 路径规则对齐：除了 references/ 之外，
    # chapter_splitter 生成的 _chapters/、doc_image_extractor 生成的
    # _images/_pages/、ppt_slide_extractor 生成的 _pptx_slides/ 也应排除。
    logger.info(f"Building new index from {pre_dir}")
    valid_md_files = [
        f for f in pre_dir.glob("**/*.md") if _is_indexable_pre_md(f)
    ]
    if not valid_md_files:
        logger.warning(f"No valid pre-processed files found in {pre_dir}")
        return False

    t_load = time.perf_counter()
    logger.info(f"Loading documents from {pre_dir}")

    documents = SimpleDirectoryReader(
        str(pre_dir),
        recursive=True,
        filename_as_id=True,
        exclude_hidden=False,
        required_exts=[".md"],
    ).load_data()

    for doc in documents:
        doc.id_ = Path(doc.id_).resolve().as_posix()
        if "file_path" in doc.metadata:
            doc.metadata["file_path"] = Path(doc.metadata["file_path"]).resolve().as_posix()
        # 记录源文件最后修改时间，供查询端展示资料新旧
        _fp = doc.metadata.get("file_path", doc.id_)
        try:
            doc.metadata["file_mtime"] = _dt.fromtimestamp(
                Path(_fp).stat().st_mtime
            ).isoformat(timespec="seconds")
        except OSError:
            doc.metadata["file_mtime"] = ""

    documents = [
        doc
        for doc in documents
        if _is_indexable_pre_md(Path(doc.metadata.get("file_path", doc.id_)))
    ]
    logger.info(
        f"Document loading took {time.perf_counter() - t_load:.2f}s, "
        f"loaded {len(documents)} documents."
    )

    t_parse = time.perf_counter()
    md_parser = MarkdownNodeParser()
    chapter_nodes = md_parser.get_nodes_from_documents(documents)
    logger.info(
        f"Markdown parsing took {time.perf_counter() - t_parse:.2f}s, "
        f"parsed into {len(chapter_nodes)} chapter nodes."
    )

    t_split = time.perf_counter()
    chapter_data_list, final_nodes = [], []

    for c_node in chapter_nodes:
        content = c_node.get_content().replace("\r", "")
        cid = chapter_id_for(content)
        c_node.metadata["chapter_id"] = cid

        if "file_path" in c_node.metadata:
            c_node.metadata["file_path"] = Path(c_node.metadata["file_path"]).resolve().as_posix()

        chapter_data_list.append(
            {
                "id": cid,
                "text": content,
                "metadata": c_node.metadata,
                "vector": [0.0] * 1024,
            }
        )

        # 表格感知切分：所有 md 都走这份切分器——表格按行切（每块带表头、绝不切断行），
        # 非表格文本仍走 SentenceSplitter。详见 common.table_aware_splitter。
        first_line = content.split("\n", 1)[0].strip()
        chapter_title = first_line if first_line.startswith("#") else ""
        for chunk_text in split_table_aware(
            content, chunk_size=1024, chunk_overlap=128,
            target_rows_per_chunk=50,
        ):
            s_node = TextNode(text=chunk_text, metadata=dict(c_node.metadata))
            s_node.metadata["chapter_id"] = cid
            s_node.metadata["chapter_title"] = chapter_title
            final_nodes.append(s_node)

    logger.info(
        f"Node splitting took {time.perf_counter() - t_split:.2f}s, "
        f"final node count: {len(final_nodes)}."
    )

    if chapter_data_list:
        db.create_table("chapters", data=chapter_data_list, mode="overwrite")
    elif "chapters" in db.list_tables().tables:
        db.drop_table("chapters")

    t_build = time.perf_counter()
    index = VectorStoreIndex(final_nodes, storage_context=storage_context)
    logger.info(f"Index building took {time.perf_counter() - t_build:.2f}s.")

    optimize_table(lan_dir, "nodes")
    if "chapters" in db.list_tables().tables:
        optimize_table(lan_dir, "chapters")

    return True


# ---------------------------------------------------------------------------
# core: insert one source file (created / modified / moved)
# ---------------------------------------------------------------------------

def _insert_source(src_p: Path, lancedb_dir: Path, pre_dir: Path,
                   workspace_root: Path, llm_config: dict,
                   skip_vision: bool = False) -> bool:
    """对 src_p 跑 preprocess → 解析 → 切分 → embed → 删旧行 → 插入新行 → 写指纹。

    返回 True 表示成功，False 表示 preprocess 或 embed 失败。

    顺序约定（与 historical_processor 对齐）：所有 embedding 网络调用都在
    删旧行之前完成。删旧行之后的窗口只剩本地 LanceDB 写入，失败概率极低；
    且删除后任何失败都会把指纹置为 failed，保证下次构建重处理该文件，
    不会出现"旧行已删 + 指纹仍 success → 指纹跳过 → 永久丢失"。

    skip_vision: True 时跳 PDF/DOC/DOCX 的图片多模态识别，直接走 legacy 文本转换。
    """
    from watch_dog.file_watcher.preprocessor import process_single_file
    from watch_dog.file_watcher.progress_ui import global_progress

    # workspace_root 即 specs_pd_dir，是 preprocessor 的 input_root。同一根走完
    # 指纹 key（_get_rel_path → file.relative_to(workspace_root)）、md_path 计算
    # （rel_under_specs 同根）、preprocessor.process_single_file 入参三处，无双根。
    specs_input_root = workspace_root

    # 进度面板通知：与 historical_processor.py:655 同模式
    global_progress.start_processing(src_p.name)
    task_failed = False
    error_msg = ""
    # Fix A: 标记旧行是否已删除。删除后任何失败出口都必须把指纹置为 failed，
    # 否则旧指纹仍是 success，下次构建会 fingerprint-skip，导致旧行已删的
    # 内容永久从向量库丢失（.md 产物还在，_is_fingerprint_match 的产物完整性
    # 检查兜不住向量行缺失）。
    old_rows_deleted = False
    try:
        # 1) preprocess 单文件
        if not process_single_file(src_p, pre_dir, specs_input_root,
                                   skip_vision=skip_vision):
            task_failed = True
            error_msg = "preprocess failed"
            _write_fingerprint(lancedb_dir, src_p, workspace_root,
                               status="failed", error=error_msg)
            return False

        # 2) 解析 .md → chapter_nodes
        #   src_p 必须落在 workspace_root 下；否则记 failed 早返回（不静默 fallback）。
        try:
            src_p.relative_to(specs_input_root)
        except ValueError:
            logger.warning(f"common_processor: src_p not under workspace_root: {src_p}")
            task_failed = True
            error_msg = "path not under workspace_root"
            _write_fingerprint(lancedb_dir, src_p, workspace_root,
                               status="failed", error=error_msg)
            return False

        md_file = compute_md_path(src_p, pre_dir, specs_input_root)
        if not md_file.exists():
            logger.warning(f"common_processor: pre-md not found for {src_p} (looked at {md_file})")
            task_failed = True
            error_msg = "pre-md missing"
            _write_fingerprint(lancedb_dir, src_p, workspace_root,
                               status="failed", error=error_msg)
            return False

        try:
            from llama_index.core import Settings
            from llama_index.core.node_parser import MarkdownNodeParser
            from llama_index.core.schema import TextNode
            from common.table_aware_splitter import split_table_aware
            from llama_index.vector_stores.lancedb import LanceDBVectorStore
            from llama_index.core import SimpleDirectoryReader
            from llama_index.llms.openai_like import OpenAILike
            from watch_dog.file_watcher.embedding_model import OnlineBGEEmbedding
        except ImportError as e:
            logger.error(f"common_processor: llama_index import failed: {e}")
            task_failed = True
            error_msg = str(e)
            return False

        # 3) 配置模型（cache 到 Settings，避免每个文件重新构造）
        model_name = llm_config.get("model", "") or llm_config.get("model_name", "")
        api_url = llm_config.get("base_url", "") or llm_config.get("api_url", "")
        api_key = llm_config.get("api_key", "")
        if api_url and "/chat/completions" in api_url:
            api_url = api_url.rsplit("/chat/completions", 1)[0]
        if api_key and isinstance(api_key, str) and api_key.lower().startswith("bearer "):
            api_key = api_key[7:]

        Settings.llm = OpenAILike(
            model=model_name, api_key=api_key, api_base=api_url,
            max_tokens=llm_config.get("max_tokens"),
            context_window=llm_config.get("context_window") or llm_config.get("max_in_tokens") or 100000,
            is_chat_model=True, timeout=300.0,
        )
        if not hasattr(Settings, "_embed_model") or Settings._embed_model is None:
            Settings.embed_model = OnlineBGEEmbedding()

        # 4) 解析 .md → chapter_nodes
        docs = SimpleDirectoryReader(input_files=[str(md_file)]).load_data()
        for doc in docs:
            # 清洗 SimpleDirectoryReader 注入的 reader 字段，避免 LanceDB schema mismatch
            # （rebuild 阶段走 MarkdownNodeParser 不带这些字段，所以 schema 也没有对应列）。
            # 复用 handler._strip_reader_metadata。
            _strip_reader_metadata(doc)
            doc.id_ = md_file.resolve().as_posix()
            if "file_path" in doc.metadata:
                doc.metadata["file_path"] = Path(doc.metadata["file_path"]).resolve().as_posix()

        md_parser = MarkdownNodeParser()
        chapter_nodes = md_parser.get_nodes_from_documents(docs)

        # 5) 构造 chapters 记录 + nodes 记录（先切分，先 embed，全部成功后再动库）
        file_path_posix = md_file.resolve().as_posix()
        chapter_data_list = []
        final_nodes = []
        try:
            file_mtime = _dt.fromtimestamp(md_file.stat().st_mtime).isoformat(timespec="seconds")
        except OSError:
            file_mtime = ""

        for c_node in chapter_nodes:
            content = c_node.get_content().replace("\r", "")
            cid = chapter_id_for(content)
            c_node.metadata["chapter_id"] = cid
            c_node.metadata["file_path"] = file_path_posix
            c_node.metadata["file_mtime"] = file_mtime

            chapter_data_list.append({
                "id": cid,
                "text": content,
                "metadata": c_node.metadata,
                "vector": [0.0] * 1024,
            })

            first_line = content.split("\n", 1)[0].strip()
            chapter_title = first_line if first_line.startswith("#") else ""
            # 表格感知切分：所有 md 都走这份切分器。与 _build_common_index 同一份
            # helper，保证全量 / 增量两条路径切分行为一致。
            for chunk_text in split_table_aware(
                content, chunk_size=1024, chunk_overlap=128,
                target_rows_per_chunk=50,
            ):
                s_node = TextNode(text=chunk_text, metadata=dict(c_node.metadata))
                s_node.metadata["chapter_id"] = cid
                s_node.metadata["chapter_title"] = chapter_title
                s_node.metadata["file_path"] = file_path_posix
                s_node.metadata["file_mtime"] = file_mtime
                final_nodes.append(s_node)

        # 6.5) 规模日志：超大文档（如 1.1 万页性能计数器参考）的解析+切分可能
        # 持续几十分钟且默认全程静默，这里给出规模画像避免被误判为卡死。
        try:
            md_size_mb = md_file.stat().st_size / 1024 / 1024
        except OSError:
            md_size_mb = -1.0
        logger.info(
            "common_processor: %s 切分完成: %d chapters, %d nodes (md %.1f MB)",
            src_p.name, len(chapter_data_list), len(final_nodes), md_size_mb,
        )

        # 6) 预生成全部节点向量（删除旧行之前完成所有 embedding 网络调用）。
        # 历史路径（historical_processor）同款顺序：embed 全部成功后才删旧行，
        # 把"删了旧行却写不进新行"的丢失窗口从整个 embedding 时长压缩到
        # 本地 LanceDB 写入本身。分批打进度日志，超大文件的 embedding 可能
        # 持续很久，避免构建日志长时间静默。
        embed_model = Settings.embed_model
        if final_nodes:
            batch_size = 500
            total = len(final_nodes)
            for i in range(0, total, batch_size):
                batch_nodes = final_nodes[i:i + batch_size]
                batch_vectors = embed_model._get_text_embeddings(
                    [n.text for n in batch_nodes]
                )
                for node, vector in zip(batch_nodes, batch_vectors):
                    node.embedding = vector
                logger.info(
                    "common_processor: %s embedding %d/%d nodes",
                    src_p.name,
                    min(i + batch_size, total),
                    total,
                )

        # 7) 按 file_path 删旧行（nodes + chapters）。embedding 已全部就绪，
        # 此后的失败只剩本地 DB 写入错误。
        _delete_by_file_path(lancedb_dir, file_path_posix)
        old_rows_deleted = True

        # 8) 写入 LanceDB
        try:
            from watch_dog.file_watcher.search import _get_ipc_lock, optimize_table
            with _get_ipc_lock(lancedb_dir):
                db = _connect_lancedb(lancedb_dir)

                # chapters: 单文件范围写入。用 append 模式追加到现有表
                try:
                    res = db.list_tables()
                    existing = res.tables if hasattr(res, "tables") else res
                except Exception:
                    existing = []
                if "chapters" in existing:
                    db.open_table("chapters").add(chapter_data_list)
                else:
                    db.create_table("chapters", data=chapter_data_list, mode="create")

                # nodes: 向量已预生成，直接走 vector_store.add（跳过 VectorStoreIndex
                # 的 embed 阶段，避免删除后再次发起网络调用）。
                if final_nodes:
                    vector_store = LanceDBVectorStore(uri=str(lancedb_dir), table_name="nodes")
                    vector_store.add(final_nodes)

                optimize_table(lancedb_dir, "nodes")
                if "chapters" in db.list_tables().tables:
                    optimize_table(lancedb_dir, "chapters")
        except EmbeddingServiceError as e:
            logger.error(f"common_processor: embedding failed while writing LanceDB: {e}")
            task_failed = True
            error_msg = str(e)
            if old_rows_deleted:
                _write_fingerprint(lancedb_dir, src_p, workspace_root,
                                   status="failed", error=error_msg)
            raise
        except Exception as e:
            logger.error(f"common_processor: failed to write LanceDB: {e}")
            task_failed = True
            error_msg = str(e)
            if old_rows_deleted:
                _write_fingerprint(lancedb_dir, src_p, workspace_root,
                                   status="failed", error=error_msg)
            return False

        # 9) 写指纹
        _write_fingerprint(lancedb_dir, src_p, workspace_root, status="success")
        return True

    except EmbeddingServiceError as e:
        logger.error(f"common_processor: embedding failed for {src_p}: {e}", exc_info=True)
        task_failed = True
        error_msg = str(e)
        if old_rows_deleted:
            _write_fingerprint(lancedb_dir, src_p, workspace_root,
                               status="failed", error=error_msg)
        raise
    except Exception as e:
        logger.error(f"common_processor: insert failed for {src_p}: {e}", exc_info=True)
        task_failed = True
        error_msg = str(e)
        if old_rows_deleted:
            _write_fingerprint(lancedb_dir, src_p, workspace_root,
                               status="failed", error=error_msg)
        return False
    finally:
        # 进度面板收尾（与 historical_processor.py:881-885 同模式）
        if task_failed:
            global_progress.fail_processing(src_p.name, str(src_p), error_msg)
        else:
            global_progress.finish_processing(src_p.name)


# ---------------------------------------------------------------------------
# 公共入口：handle_common_file_event
# ---------------------------------------------------------------------------

# deleted 分支的兼容清单：历史上任何构建版本可能摄入过的格式并集。
# 必须是"曾经可入库"的超集——比如独立图片在 documents-only 政策前是可摄入的，
# 清残留时要能删到它们的向量行 + pre-md，而不是只清指纹。清单之外的类型
# （从未入过库）只清指纹即可。
SUPPORTED_EXTS = (
    *SUPPORTED_DOCUMENT_EXTS,
    *sorted(IMAGE_EXTS),
    ".html", ".htm",
    ".mhtml", ".mht", ".txt", ".csv", ".json",
    ".xml", ".md", ".markdown", ".yml", ".yaml", ".log",
    ".ini", ".properties",
)


def handle_common_file_event(
    src_path: str,
    event_type: str,
    dest_path: str,
    lancedb_dir: Path,
    pre_dir: Path,
    workspace_root: Path,
    llm_config: dict,
    skip_vision: bool = False,
) -> bool:
    """处理单个普通文档文件事件（created/modified/deleted/moved）。

    模仿 handle_historical_file_event 的事件分发 API，但针对普通文档走
    增量更新：先按 file_path 删旧 nodes/chapters 行，再插入新行。
    不会触发全量重建。

    skip_vision: 透传到 _insert_source → process_single_file，跳过 PDF/DOC/DOCX
    的图片多模态识别（仅跑文本转换）。sync_soc_rag 批量构建场景默认 True，
    大文件图多时可避免 vision_client 把整晚耗光。

    Returns:
        True 表示处理成功（或因为文件类型不支持而跳过），
        False 表示处理失败需要 caller 标记 fingerprint 为 failed。

    Notes:
        - created/modified 行为相同（都是按 src_path upsert）：
          不存在的 file_path → insert；已存在的 → 删旧 + insert 新
        - moved: 先按 src_path（旧路径）删，再按 dest_path（新路径）upsert
        - deleted: 按 src_path 删 nodes/chapters 行 + 删 pre_dir .md + 删指纹
        - chapter_id 是内容 hash，相同内容天然产生相同 cid，幂等
    """
    src_p = Path(src_path)
    dest_p = Path(dest_path) if dest_path else None

    # Office 临时文件（~$xxx / .tmp / .bak / .ds_store / .tmp-）直接跳过：
    # 不插入、不标记失败、不计入进度面板。复用 handler._is_office_temp。
    if _is_office_temp(str(src_p)):
        logger.debug(f"common_processor: skipping office temp file: {src_p}")
        return True

    # ========== deleted ==========
    if event_type == "deleted":
        from watch_dog.file_watcher.progress_ui import global_progress
        if src_p.suffix.lower() not in SUPPORTED_EXTS:
            # 不支持类型的残留记录（如解包标记 .extracted_ok/.extract_failed）：
            # 没有索引行可删，但指纹必须清掉，否则每次全量同步都被当成孤儿。
            _remove_fingerprint(lancedb_dir, src_p, workspace_root)
            return True
        # 进度面板通知（与 historical_processor.py:655 同模式）
        global_progress.start_processing(src_p.name)
        task_failed = False
        error_msg = ""
        try:
            # nodes/chapters 表的 file_path 列存的是 .md 路径（不是源文件路径）。
            # 必须按 .md 路径删，否则删不到。命名规则见 soc_rag_helpers.compute_md_path。
            # workspace_root 即 specs_pd_dir，rel 即去掉 specs_pd_dir 前缀的 POSIX 路径。
            try:
                md_abs = compute_md_path(src_p, pre_dir, workspace_root).resolve().as_posix()
            except ValueError:
                md_abs = _posix_path(src_p)
            _delete_by_file_path(lancedb_dir, md_abs)
            _delete_pre_md(pre_dir, src_p, workspace_root)
            _remove_fingerprint(lancedb_dir, src_p, workspace_root)
            return True
        except Exception as e:
            task_failed = True
            error_msg = str(e)
            logger.error(f"common_processor: delete failed for {src_p}: {e}")
            return False
        finally:
            if task_failed:
                global_progress.fail_processing(src_p.name, str(src_p), error_msg)
            else:
                global_progress.finish_processing(src_p.name)

    # ========== moved ==========
    # 先删旧路径的所有产物，再处理新路径。
    # 注意：nodes/chapters 表的 file_path 列存的是 pre-md 文件路径（不是源文件路径），
    # 所以 _delete_by_file_path 必须用 .md 路径，否则删不掉。
    if event_type == "moved" and dest_p:
        # workspace_root 即 specs_pd_dir，单根语义：rel = file.relative_to(workspace_root)
        try:
            old_md_abs = compute_md_path(src_p, pre_dir, workspace_root).resolve().as_posix()
        except ValueError:
            old_md_abs = _posix_path(src_p)
        _delete_by_file_path(lancedb_dir, old_md_abs)
        _delete_pre_md(pre_dir, src_p, workspace_root)
        _remove_fingerprint(lancedb_dir, src_p, workspace_root)
        src_p = dest_p
        # fallthrough to created/modified 处理

    # ========== created / modified / moved（src_p 已是最终路径） ==========
    if event_type in ("created", "modified", "moved"):
        try:
            return _insert_source(src_p, lancedb_dir, pre_dir, workspace_root, llm_config,
                                  skip_vision=skip_vision)
        except EmbeddingServiceError:
            raise
        except Exception as e:
            logger.error(f"common_processor: insert failed for {src_p}: {e}", exc_info=True)
            return False

    return False
