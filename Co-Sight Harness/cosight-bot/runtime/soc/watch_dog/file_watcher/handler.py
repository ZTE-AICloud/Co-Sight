#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LlamaIndex 增量索引处理器

基于 watchdog 监听文件变更，增量更新 LlamaIndex 向量索引。

只经技能 CLI 显式触发（全量构建 / 单文件增量），不启动监听进程。
"""

import os
import shutil
import threading
import time
import logging
import hashlib
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

from watchdog.events import FileSystemEventHandler

from .config import (
    get_route_key,
    get_llamaindex_storage_dirs,
    get_session_storage_dirs,
    is_under_pre_processed_dir,
)
from common.cosight_runtime import resolve_runtime_llm_config
from .preprocessor import is_supported_file, process_single_file, process_directory, _calculate_file_hash, is_office_temp, is_under_excluded_dir
from .search import get_cached_index, get_query_engine
from .progress_ui import global_progress
from .overview_builder import write_overview_md, clear_overview_md
from common.document_types import OFFICE_DOCUMENT_EXTS

logger = logging.getLogger("file_watcher")


# SimpleDirectoryReader 给 Document.metadata 注入的 reader 字段。
# 初次构建走 MarkdownNodeParser + SentenceSplitter,产出的节点 metadata 不含这些字段,
# 因此 LanceDB 的 nodes 表 schema 也没有对应列。
# 增量更新时若直接把 Document 塞进 index.insert(doc) / index.update_ref_doc(doc),
# 新写入的 batch 会携带这些字段,LanceDB 严格 schema 直接报错:
#   ValueError: Invalid input, field 'file_type' does not exist in table schema
# 在 insert / update 前清洗这些字段,保证新增节点的 schema 与旧 nodes 表一致。
_READER_INJECTED_METADATA_KEYS = (
    "file_type",
    "file_size",
    "creation_date",
    "last_modified_date",
    "filename",
    "directory",
)

# P0 单文件预处理软超时（秒）。as_completed 流水线里用 future.result(timeout=)
# 取每个文件的结果；超时则标记 failed 并继续其余文件（线程因 GIL 仍短暂残留，
# 由 OCR 累计总超时 VISION_TOTAL_TIMEOUT 兜底）。
# env 可覆盖（测试缩短）。
PER_FILE_HARD_TIMEOUT = float(os.environ.get("COSIGHTBOT_PER_FILE_HARD_TIMEOUT", "600"))

# P3 按页增量 ingest 间隔：首页后每 N 页 ingest 一次（平衡"边处理边可查"与重复 embed 开销）。
# 300 页大文件 -> 首页 + 每 25 页 ≈ 13 次增量 ingest。
PAGE_INGEST_INTERVAL = int(os.environ.get("COSIGHTBOT_PAGE_INGEST_INTERVAL", "25"))


def _strip_reader_metadata(doc):
    """去掉 SimpleDirectoryReader 注入的、可能与 nodes.lance schema 不兼容的字段。"""
    if doc is None:
        return doc
    metadata = getattr(doc, "metadata", None)
    if not metadata:
        return doc
    for k in _READER_INJECTED_METADATA_KEYS:
        if k in metadata:
            try:
                del metadata[k]
            except (TypeError, KeyError):
                metadata.pop(k, None)
    return doc


def _parse_md_to_chapter_nodes(pre_path: Path):
    """读取 pre_dir 下的 .md 文件,产出带 chapter_id 的 TextNode 列表。"""
    from llama_index.core import SimpleDirectoryReader
    from llama_index.core.node_parser import MarkdownNodeParser
    from llama_index.core.schema import NodeRelationship, RelatedNodeInfo, TextNode
    from common.table_aware_splitter import split_table_aware

    if pre_path is None or not pre_path.exists() or pre_path.suffix.lower() != ".md":
        return []

    docs = SimpleDirectoryReader(
        input_files=[str(pre_path)], filename_as_id=True, encoding="utf-8-sig"
    ).load_data()
    if not docs:
        return []

    # --- 路径标准化核心修复：强制转为 POSIX 风格 ---
    for doc in docs:
        # 统一 doc.id_ (这是 LlamaIndex 的内部标识符)
        doc.id_ = Path(doc.id_).resolve().as_posix()
        # 统一 metadata 中的路径
        if "file_path" in doc.metadata:
            doc.metadata["file_path"] = Path(doc.metadata["file_path"]).resolve().as_posix()
    # ---------------------------------------------

    _strip_reader_metadata(docs[0])

    md_parser = MarkdownNodeParser()
    chapter_nodes = md_parser.get_nodes_from_documents([docs[0]])

    ref_doc_id = Path(pre_path).resolve().as_posix()
    final_nodes = []
    for c_node in chapter_nodes:
        content = c_node.get_content().replace("\r", "")
        cid = f"chap_{hashlib.md5(content.encode()).hexdigest()[:12]}"
        c_node.metadata["chapter_id"] = cid

        # --- 确保 c_node 自身的 metadata 也被标准化 ---
        if "file_path" in c_node.metadata:
            c_node.metadata["file_path"] = Path(c_node.metadata["file_path"]).resolve().as_posix()

        # 表格感知切分：所有 md 都走这份切分器（表格按行切、每块带表头、绝不切断行），
        # 非表格文本仍走 SentenceSplitter。详见 common.table_aware_splitter。
        # max_chars_per_chunk 用模块默认值（与 embed 输入上限对齐的余量定义）。
        for chunk_text in split_table_aware(
            content, chunk_size=1024, chunk_overlap=128,
            target_rows_per_chunk=50,
        ):
            s_node = TextNode(text=chunk_text, metadata=dict(c_node.metadata))
            s_node.metadata["chapter_id"] = cid
            # 显式设置 SOURCE 关系指向 pre_path 绝对路径,
            # 与 delete 路径(用 str(pre_path.resolve()) 作为 ref_doc_id)一致
            s_node.relationships[NodeRelationship.SOURCE] = RelatedNodeInfo(node_id=ref_doc_id)
            final_nodes.append(s_node)
    return final_nodes


def _brutal_purge_db(lan_dir: Path, rel_path: str, pre_dir: Optional[Path] = None, is_directory: bool = False):
    """直接操作 LanceDB 物理删除相关节点，确保清理彻底。"""
    try:
        import lancedb
        from .search import _get_ipc_lock

        db = lancedb.connect(str(lan_dir))
        try:
            res = db.list_tables()
            tables = res.tables if hasattr(res, 'tables') else res
        except Exception:
            tables = []

        if "nodes" in tables:
            table = db.open_table("nodes")

            std_rel = rel_path.replace("\\", "/")
            std_rel_win = std_rel.replace("/", "\\")
            path_stem_record = std_rel.replace(".", "_")

            absolute_pre_path_fragment = ""
            if pre_dir:
                p = Path(rel_path)
                if is_directory:
                    absolute_pre_path_fragment = (pre_dir / p).resolve().as_posix()
                else:
                    stem = p.stem
                    ext = p.suffix.lstrip('.')
                    md_name = f"{stem}_{ext}".replace(".", "_") + ".md"
                    absolute_pre_path_fragment = (pre_dir / p.parent / md_name).resolve().as_posix()

            suffix = "%"
            fragments = [std_rel, std_rel_win, path_stem_record]
            if absolute_pre_path_fragment:
                fragments.append(absolute_pre_path_fragment)
            if not is_directory:
                fragments.append(path_stem_record + "_md")

            conditions = []
            for frag in fragments:
                if not frag: continue
                conditions.append(f"metadata.file_path LIKE '%{frag}{suffix}'")
                conditions.append(f"metadata.doc_id LIKE '%{frag}{suffix}'")

            if not conditions:
                return

            expr = " OR ".join(conditions)
            with _get_ipc_lock(lan_dir):
                table.delete(expr)
            logger.info(f"LlamaIndex Watchdog: LanceDB brutal purge executed: {expr}")
    except Exception as e:
        logger.warning(f"LlamaIndex Watchdog: LanceDB brutal purge failed: {e}")


class LlamaIndexIncrementalHandler(FileSystemEventHandler):
    def __init__(self, src_root: Path, agent_id: str = "", executor: ThreadPoolExecutor | None = None, session_key_hash: str = "", session_key: str = ""):
        self.src_root = src_root.resolve()
        self.agent_id = agent_id
        self.session_key_hash = session_key_hash
        # ======== [CoSight-START] feature: session-aware-llm-config ========
        # 完整 session_key（不是 hash），用于从 sessions.json 读出当前会话选中的大模型。
        # hash 仅用于索引存储目录命名；session_key 用于 LLM config 解析。
        self.session_key = session_key
        # ======== [CoSight-END] feature: session-aware-llm-config ========
        self._owns_executor = executor is None
        self._executor = executor or ThreadPoolExecutor(max_workers=4, thread_name_prefix="llamaindex-incr")
        self._timers: dict[str, threading.Timer] = {}
        self._last_mtimes: dict[str, float] = {}
        self._event_lock = threading.RLock()
        self.debounce_seconds = 2.0

    def _notify_ppt_fallback(self, payload: dict) -> None:
        """Forward a non-fatal LibreOffice fallback warning to the active chat."""
        if not self.session_key:
            logger.info(
                "LlamaIndex Watchdog: PPT fallback warning skipped because "
                "no session_key is associated with this watcher"
            )
            return
        message = dict(payload)
        message.update({
            "agent_id": self.agent_id,
            "session_key": self.session_key,
            "session_key_hash": self.session_key_hash,
        })
        try:
            global_progress.chat_warning(message)
        except Exception as e:
            logger.warning(f"LlamaIndex Watchdog: failed to queue PPT warning: {e}")

    def shutdown(self, wait: bool = True):
        """取消所有待处理的防抖定时器并关闭执行器。"""
        with self._event_lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
        if self._owns_executor:
            self._executor.shutdown(wait=wait, cancel_futures=True)

    def _get_storage_dirs(self):
        """返回 (pre_dir, lan_dir)：session 模式走 get_session_storage_dirs，
        否则走 agent 级别（绑定目录/inbox 路由）路径。"""
        if self.session_key_hash:
            _, pre_dir, lan_dir = get_session_storage_dirs(self.agent_id, self.session_key_hash)
            return pre_dir, lan_dir
        return get_llamaindex_storage_dirs(self.src_root, self.agent_id)

    def _is_office_temp(self, path: str) -> bool:
        return is_office_temp(path)

    def _is_excluded_event_path(self, path) -> bool:
        """事件路径是否落在监听根目录**内部**的排除目录（.cosightpro）之下。

        排除规则的本意是剪掉绑定资料目录里嵌套的 .cosightpro 状态子树，
        因此必须按 src_root 的相对路径判断。session 上传 watcher 的
        src_root 本身就位于 .cosightpro 下（upload_files/<hash>），
        若按绝对路径判断会把该 watcher 的所有事件静默丢弃（上传文件
        不触发增量构建，且无任何日志）。
        """
        try:
            rel = Path(path).resolve().relative_to(self.src_root)
        except (ValueError, OSError):
            return False
        return is_under_excluded_dir(rel)

    def _is_office_file(self, path: str) -> bool:
        return Path(path).suffix.casefold() in OFFICE_DOCUMENT_EXTS

    def _has_office_lock(self, src_path: str) -> bool:
        p = Path(src_path)
        lock_file = p.with_name(f"~${p.name}")
        return lock_file.exists()

    def _get_original_file_from_lock(self, lock_path: str) -> Optional[str]:
        p = Path(lock_path)
        if p.name.startswith("~$"):
            original_name = p.name[2:]
            original_path = p.with_name(original_name)
            if original_path.exists():
                return str(original_path)
        return None

    def _process_event(self, src_path: str, event_type: str, dest_path: str = None, is_directory: bool = False):
        """处理文件事件的核心调度器，分发给独立的 llamaindex_task_runner 子进程。"""
        # ======== [CoSight-START] feature: file-upload ========
        effective_path = dest_path if (event_type == "moved" and dest_path) else src_path
        if effective_path and Path(effective_path).name.endswith(".uploading"):
            logger.debug(f"LlamaIndex Watchdog: [SKIP] 忽略上传中的临时文件 {effective_path}")
            return
        # ======== [CoSight-END] feature: file-upload ========

        logger.info(f"LlamaIndex Watchdog: [EVENT] {event_type} src={src_path} dest={dest_path} is_dir={is_directory}")

        # 仅处理文件，忽略目录事件（操作系统会发出文件级别的事件）
        if is_directory:
            logger.info(f"LlamaIndex Watchdog: [SKIP] Ignoring directory event (operating on file granularity)")
            return

        try:
            global_progress.add_waiting(1)
            def _run_normal_task():
                # 无中央调度器：直接 spawn llamaindex_task_runner 子进程执行
                # common_update（与 material_cli.run_update 同一链路，异步不等待）。
                try:
                    import subprocess as _sp
                    import sys as _sys
                    runner = (
                        Path(__file__).resolve().parent.parent
                        / "llamaindex_task_runner.py"
                    )
                    cmd = [
                        _sys.executable, str(runner), "common_update",
                        "--agent_id", self.agent_id,
                        "--path", str(self.src_root),
                        "--src_path", src_path,
                        "--event_type", event_type,
                        # ======== [CoSight-START] feature: session-aware-llm-config ========
                        # 把完整 session_key 透传给 worker，让 handler.py 解析 LLM config 时
                        # 能从 sessions.json 取到当前会话选中的大模型
                        "--session_key_hash", self.session_key_hash or "",
                        "--session_key", self.session_key or "",
                        # ======== [CoSight-END] feature: session-aware-llm-config ========
                    ]
                    if dest_path:
                        cmd += ["--dest_path", dest_path]
                    _sp.Popen(
                        cmd,
                        stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                        start_new_session=True,
                    )
                except Exception as e:
                    logger.error(f"LlamaIndex Watchdog: Failed to dispatch index update task: {e}", exc_info=True)
            self._executor.submit(_run_normal_task)
        except Exception as e:
            logger.warning(f"LlamaIndex Watchdog: Failed to dispatch index update event: {e}")

    def ingest_one_md(self, md_path: Path, lan_dir: Path) -> int:
        """把单个预处理产物 .md 解析->切块->插入索引（幂等）。返回插入节点数。

        供 run_common_build_sync 逐文件流水线调用：每文件预处理完立即入库，
        使其可被查询。delete_ref_doc + insert_nodes 保证幂等（重复调用不重复）。

        向量入库条件化（design prod-outside §4.3 方案 A）：COSIGHTBOT_EMBEDDING_API_URL
        未配置时整体跳过 LanceDB 写入，不发起任何 embedding 连接；overview.md 由
        预处理产物独立生成，ensure_ready 在该情形下只要求 overview.md。
        """
        from .embedding_model import embedding_configured
        if not embedding_configured():
            logger.info(
                f"LlamaIndex Watchdog: embedding 未配置（缺少 COSIGHTBOT_EMBEDDING_API_URL），"
                f"跳过向量入库 {md_path.name}"
            )
            return 0
        from .search import _get_ipc_lock, get_cached_index, clear_cache_for_route
        nodes = _parse_md_to_chapter_nodes(md_path)
        if not nodes:
            logger.info(f"LlamaIndex Watchdog: ingest_one_md no nodes for {md_path.name}")
            return 0
        # 获取已缓存索引；首次或缓存被清时由 get_query_engine 建立/廉价加载
        index = get_cached_index(self.src_root, self.agent_id, session_key_hash=self.session_key_hash)
        if index is None:
            llm_config = resolve_runtime_llm_config("full_build", session_key=self.session_key, agent_id=self.agent_id)
            if not llm_config:
                logger.warning(f"ingest_one_md: no llm_config, skip insert for {md_path.name}")
                return 0
            try:
                get_query_engine(self.src_root, self.agent_id, llm_client=llm_config, session_key_hash=self.session_key_hash)
            except Exception as e:
                logger.warning(f"ingest_one_md: get_query_engine failed for {md_path.name}: {e}")
                return 0
            index = get_cached_index(self.src_root, self.agent_id, session_key_hash=self.session_key_hash)
            if index is None:
                logger.warning(f"ingest_one_md: index still None for {md_path.name}")
                return 0
        doc_id = md_path.resolve().as_posix()
        inserted = 0
        with _get_ipc_lock(lan_dir):
            for variant in (doc_id, doc_id.replace("/", "\\")):
                try:
                    index.delete_ref_doc(variant, delete_from_docstore=True)
                except Exception:
                    pass
            try:
                index.insert_nodes(nodes)
                inserted = len(nodes)
            except Exception as e:
                logger.error(f"ingest_one_md: insert_nodes failed for {md_path.name}: {e}", exc_info=True)
        # 失效引擎缓存，让后续查询重建 engine 读到新节点
        rk = get_route_key(self.src_root, agent_id=self.agent_id, session_key_hash=self.session_key_hash)
        clear_cache_for_route(rk)
        logger.info(f"LlamaIndex Watchdog: ingest_one_md inserted {inserted} nodes for {md_path.name}")
        return inserted

    def _pipeline_handle_success(self, file_path: Path, md_path: Path, lan_dir: Path) -> bool:
        """P1-5 辅助：单文件入库成功路径。返回 True/False 便于测试。"""
        from common.index_api import update_file_info, ensure_ready
        from .overview_builder import write_overview_md
        rel = file_path.relative_to(self.src_root).as_posix()
        try:
            self.ingest_one_md(md_path, lan_dir)
            f_stat = file_path.stat()
            update_file_info(lan_dir, rel, {
                "mtime": f_stat.st_mtime, "size": f_stat.st_size,
                "hash": _calculate_file_hash(file_path), "status": "success",
            })
        except Exception as e:
            logger.error(f"LlamaIndex Watchdog: ingest failed for {rel}: {e}", exc_info=True)
            try:
                f_stat = file_path.stat()
                update_file_info(lan_dir, rel, {
                    "mtime": f_stat.st_mtime, "size": f_stat.st_size,
                    "hash": _calculate_file_hash(file_path), "status": "failed",
                    "error": str(e)[:200],
                })
            except Exception:
                pass
            return False
        try:
            write_overview_md(lan_dir, self.pre_dir)
        except Exception as oe:
            logger.warning(f"LlamaIndex Watchdog: overview refresh failed (non-fatal): {oe}")
        try:
            ensure_ready(lan_dir, self.src_root)
        except Exception:
            pass
        return True

    def _pipeline_mark_failed(self, file_path: Path, rel: str, lan_dir: Path, err: str) -> None:
        """P1-5 辅助：标记失败 + 进度框通知。"""
        from common.index_api import update_file_info
        try:
            global_progress.fail_processing(file_path.name, str(file_path), err)
        except Exception:
            pass
        try:
            f_stat = file_path.stat()
            update_file_info(lan_dir, rel, {
                "mtime": f_stat.st_mtime, "size": f_stat.st_size,
                "hash": _calculate_file_hash(file_path), "status": "failed",
                "error": err[:200],
            })
        except Exception:
            pass

    def _build_on_page_done(self, md_path: Path, lan_dir: Path, pre_dir: Path):
        """P3：构建按页增量 ingest 回调——首页 + 每 PAGE_INGEST_INTERVAL 页把已生成的
        部分 .md 入库 + 刷新 overview + ensure_ready，让大文件"边处理边可查"。
        供 _preprocess_one（批量 run_common_build_sync）与 _update_for_event（增量单文件）共用。"""
        def _on_page_done(page_index, total):
            try:
                if page_index == 1 or page_index % PAGE_INGEST_INTERVAL == 0:
                    from .overview_builder import write_overview_md
                    from common.index_api import ensure_ready
                    if md_path.exists():
                        self.ingest_one_md(md_path, lan_dir)
                        write_overview_md(lan_dir, pre_dir)
                        ensure_ready(lan_dir, self.src_root)
            except Exception as _e:
                logger.warning(f"on_page_done ingest failed page {page_index}: {_e}")
        return _on_page_done

    def run_common_build_sync(self, force: bool = False):
        """逐文件流水线构建：每文件预处理完即入库即查询，单文件失败不阻塞其余。

        替代原"全量预处理 -> 一次性建索引"的批处理：用 as_completed 逐文件消费，
        每完成一个就 ingest_one_md + 刷新 overview + ensure_ready，使其立即可问答。
        超时/异常的文件标记 failed 并继续；sync_chapters_table/optimize 批末跑一次。
        单文件 OCR hang 由 VISION_TOTAL_TIMEOUT 兜住；未覆盖的 hang 由
        VISION_TOTAL_TIMEOUT 兜底。
        """
        logger.info(f"LlamaIndex Watchdog: run_common_build_sync material={self.src_root.name}, agent={self.agent_id}, force={force}")

        from .search import clear_cache, sync_chapters_table, optimize_table
        from common.index_api import _update_status, update_file_info, get_full_status_data, ensure_ready
        from .preprocessor import _is_fingerprint_match, EXT_PDF, EXT_MARKITDOWN, EXT_MHTML, EXT_TEXT, EXT_IMAGES
        from concurrent.futures import as_completed

        if force:
            clear_cache(self.agent_id)

        pre_dir, lan_dir = self._get_storage_dirs()
        if not pre_dir or not lan_dir:
            return
        # _pipeline_handle_success / _on_page_done 等嵌套函数需访问 pre_dir/lan_dir
        self.pre_dir = pre_dir
        self.lan_dir = lan_dir

        llm_config = resolve_runtime_llm_config("full_build", session_key=self.session_key, agent_id=self.agent_id)
        if not llm_config:
            # 无 LLM 配置时构建必然空跑（逐文件 ingest 也依赖它）：必须抛错让
            # runner 非零退出，否则上层会把"什么都没入库"误报为构建成功。
            _update_status(lan_dir, "failed", source_dir=self.src_root, error="LLM 未配置")
            raise RuntimeError(
                "LLM 未配置（ANTHROPIC_* 或 OPENAI_*，见 data/.env），无法构建索引"
            )
        from .embedding_model import embedding_configured
        if not embedding_configured():
            # embedding 是向量索引的硬前提；缺失时同样不能静默成功。
            _update_status(lan_dir, "failed", source_dir=self.src_root, error="embedding 未配置")
            raise RuntimeError(
                "embedding 未配置（COSIGHTBOT_EMBEDDING_API_URL/API_KEY，见 data/.env），无法构建向量索引"
            )

        # 加载指纹表（force 时跳过；非 force 时用于跳过未变更文件）
        recorded_files = None
        if not force:
            try:
                status_data = get_full_status_data(lan_dir)
                if status_data and isinstance(status_data.get("files"), dict):
                    recorded_files = status_data["files"]
            except Exception as e:
                logger.warning(f"LlamaIndex Watchdog: Failed to load recorded files for fingerprint skip: {e}")

        _update_status(lan_dir, "initializing", source_dir=self.src_root)
        global_progress.set_system_status("正在更新知识库索引 (请耐心等待)...")

        try:
            # 扫描 + 过滤（与 process_directory 一致的规则）
            # ======== [CoSight-START] feature: exclude-cosightpro-from-preprocessing ========
            # .cosightpro 子树直接剪掉，避免递归 rglob 让预处理永远跑不完。
            # 按 src_root 相对路径判断：session 上传目录本身就在 .cosightpro 下，
            # 用绝对路径会把 session 兜底全量构建的所有文件误剪。
            all_files = [
                f for f in self.src_root.glob("**/*")
                if f.is_file() and not is_under_excluded_dir(f.relative_to(self.src_root))
            ]
            # ======== [CoSight-END] feature: exclude-cosightpro-from-preprocessing ========
            supported_exts = EXT_PDF | EXT_MARKITDOWN | EXT_MHTML | EXT_TEXT | EXT_IMAGES
            supported_files = [f for f in all_files if f.suffix.lower() in supported_exts and not is_office_temp(f)]
            if recorded_files:
                supported_files = [
                    f for f in supported_files
                    if not _is_fingerprint_match(f, self.src_root, recorded_files, pre_dir,
                                                 session_key=self.session_key, agent_id=self.agent_id)
                ]
            logger.info(f"LlamaIndex Watchdog: pipeline {len(supported_files)} file(s) to process (force={force}).")
            global_progress.add_waiting(len(supported_files))

            # 预建索引（nodes.lance 存在则廉价加载，不存在则用 pre_dir 现有 .md 全量建；
            # 全新会话 pre_dir 为空 -> 空 index，后续逐文件 insert）。
            try:
                get_query_engine(self.src_root, self.agent_id, llm_client=llm_config, session_key_hash=self.session_key_hash, allow_preprocessing=False)
            except Exception as e:
                logger.warning(f"LlamaIndex Watchdog: initial get_query_engine failed (will retry per-file): {e}")

            def _preprocess_one(file_path: Path):
                """预处理单个文件，返回 md_path 或 None。处理进度上报。"""
                filename = file_path.name
                global_progress.start_processing(filename)
                last_stage = [None]
                def _vision_cb(current, total, stage):
                    try:
                        if last_stage[0] != stage:
                            global_progress.start_file_subprogress(filename, total, stage)
                            global_progress.update_file_subprogress(filename, 0)
                            last_stage[0] = stage
                        else:
                            global_progress.start_file_subprogress(filename, total, stage)
                        global_progress.update_file_subprogress(filename, current)
                    except Exception:
                        pass
                # P3：按页增量 ingest——首页 + 每 PAGE_INGEST_INTERVAL 页把已生成的
                # 部分 .md 入库 + 刷新 overview + ensure_ready，让大文件"边处理边可查"。
                md_name = f"{file_path.stem}_{file_path.suffix.lstrip('.')}".replace(".", "_") + ".md"
                md_path = pre_dir / file_path.relative_to(self.src_root).with_name(md_name)
                _on_page_done = self._build_on_page_done(md_path, lan_dir, pre_dir)
                try:
                    ok = process_single_file(
                        file_path, pre_dir, self.src_root,
                        on_ppt_fallback=self._notify_ppt_fallback,
                        progress_callback=_vision_cb,
                        on_page_done=_on_page_done,
                    )
                    if ok:
                        global_progress.finish_processing(filename)
                        return md_path if md_path.exists() else None
                    global_progress.fail_processing(filename, str(file_path), "文件格式解析失败或已被跳过")
                    return None
                except Exception as e:
                    global_progress.fail_processing(filename, str(file_path), f"异常: {e}")
                    return None
                finally:
                    try:
                        global_progress.finish_file_subprogress(filename)
                    except Exception:
                        pass

            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="preprocess") as ex:
                # P1-5: 失败重试表（file_path -> 失败原因）。批批结束时统一重试一次。
                failed_to_retry: dict[Path, str] = {}
                futures = {ex.submit(_preprocess_one, f): f for f in supported_files}
                for fut in as_completed(futures):
                    file_path = futures[fut]
                    rel = file_path.relative_to(self.src_root).as_posix()
                    try:
                        md_path = fut.result(timeout=PER_FILE_HARD_TIMEOUT)
                    except Exception as e:
                        # 超时/异常：先记入重试表，批末统一重试一次
                        logger.warning(f"LlamaIndex Watchdog: pipeline file {rel} failed (first try): {e}")
                        failed_to_retry[file_path] = str(e)[:200]
                        continue
                    if md_path is None:
                        failed_to_retry[file_path] = "preprocess returned returned None"
                        continue
                    if self._pipeline_handle_success(file_path, md_path, lan_dir):
                        # 成功路径：入 overhead 队 else 在函数内处理
                        pass

                # P1-5: 批末统一重试 1 次（短退避 5s）
                if failed_to_retry:
                    logger.info(
                        f"LlamaIndex Watchdog: retrying {len(failed_to_retry)} failed file(s) once after 5s backoff"
                    )
                    time.sleep(5)
                    retry_paths = list(failed_to_retry.keys())
                    retry_results = {f: _preprocess_one(f) for f in retry_paths}
                    for fp in retry_paths:
                        rel = fp.relative_to(self.src_root).as_posix()
                        md = retry_results[fp]
                        if md:
                            logger.info(f"LlamaIndex Watchdog: retry succeeded for {rel}")
                            self._pipeline_handle_success(fp, md, lan_dir)
                        else:
                            err = failed_to_retry[fp]
                            logger.warning(f"LlamaIndex Watchdog: retry still failed for {rel}: {err}")
                            self._pipeline_mark_failed(fp, rel, lan_dir, f"预处理失败/超时 (重试 1 次仍失败): {err}")
                    try:
                        write_overview_md(lan_dir, pre_dir)
                    except Exception as oe:
                        logger.warning(f"LlamaIndex Watchdog: overview refresh failed (non-fatal): {oe}")
                    try:
                        ensure_ready(lan_dir, self.src_root)
                    except Exception:
                        pass

            # 批末收尾：章节表 + 优化 + overview + ready
            try:
                sync_chapters_table(self.src_root, self.agent_id, session_key_hash=self.session_key_hash)
                optimize_table(lan_dir, "nodes")
                optimize_table(lan_dir, "chapters")
            except Exception as e:
                logger.warning(f"LlamaIndex Watchdog: batch finalize (sync/optimize) failed (non-fatal): {e}")
            try:
                write_overview_md(lan_dir, pre_dir)
            except Exception as oe:
                logger.warning(f"LlamaIndex Watchdog: overview finalize failed (non-fatal): {oe}")
            try:
                ensure_ready(lan_dir, self.src_root)
            except Exception:
                pass
            global_progress.set_system_status("")
        except Exception as e:
            global_progress.set_system_status("")
            _update_status(lan_dir, "failed", source_dir=self.src_root, error=str(e))
            logger.error(f"LlamaIndex Watchdog: run_common_build_sync failed: {e}", exc_info=True)
            raise

    def _update_for_event(self, src_path: str, event_type: str, dest_path: Optional[str], is_directory: bool = False):
        pre_dir, lan_dir = self._get_storage_dirs()
        if not pre_dir or not lan_dir:
            return "success"

        rel = Path(src_path).relative_to(self.src_root)
        std_rel = rel.as_posix()
        md_name = f"{Path(src_path).stem}_{Path(src_path).suffix.lstrip('.')}".replace(".", "_") + ".md"

        # 构建二级进度回调：vision/PPT 处理的 per-page/per-slide 进度
        # （OCR 识别中 / 图片识别中 / PPT 切页中）
        # 调用方传 src_path；实际拿 .name 就行
        target_filename = Path(src_path).name
        def _vision_cb(current: float, total: int, stage: str):
            try:
                global_progress.start_file_subprogress(target_filename, total, stage)
                global_progress.update_file_subprogress(target_filename, current)
            except Exception:
                pass

        if event_type in ("moved", "deleted"):
            logger.info(f"LlamaIndex Watchdog: Cleaning up {std_rel} due to {event_type}")
            try:
                from common.index_api import remove_directory_info, remove_file_info
                remove_file_info(lan_dir, std_rel)
                remove_directory_info(lan_dir, std_rel)
            except Exception: pass

            _brutal_purge_db(lan_dir, std_rel, pre_dir=pre_dir, is_directory=is_directory)

            if is_directory:
                pre_target_dir = pre_dir / rel
                if is_under_pre_processed_dir(pre_target_dir):
                    shutil.rmtree(pre_target_dir, ignore_errors=True)
            else:
                pre_target_file = pre_dir / rel.with_name(md_name)
                pre_target_file.unlink(missing_ok=True)

                # ======== [CoSight-START] feature: chapter-cleanup ========
                # 同步删除 chapter_splitter 生成的 _chapters 子目录。
                # 否则 sync_chapters_table 的 pre_dir.glob("**/*.md") 递归扫描
                # 会把章节子文件当根级 .md，导致 chapters.lance / overview.md /
                # node_index.json 全部错位。
                chapters_dir = pre_target_file.parent / f"{pre_target_file.stem}_chapters"
                if chapters_dir.is_dir():
                    shutil.rmtree(chapters_dir, ignore_errors=True)
                    logger.info(
                        f"LlamaIndex Watchdog: removed orphan chapters dir {chapters_dir.name}"
                    )
                # ======== [CoSight-END] feature: chapter-cleanup ========

                # ======== [CoSight-START] feature: ppt-slides ========
                # PowerPoint 还会产生 <stem>_<ext>_slides/ 工作目录,删除源文件时同步清理
                # 注意：preprocessor.py:389/671 的 doc_base 用 `.replace(".", "_")` 把
                # 文件名里的点全替换成下划线（例如 "DSV4...V1.0.pptx" → "DSV4...V1_0_pptx_slides"）。
                # 之前直接用 src_stem（保留 "."）拼目录名，与实际产物名不匹配，rmtree
                # 命中一个不存在的路径，静默 no-op，导致 <_slides> 目录残留。
                if src_path.lower().endswith((".ppt", ".pptx", ".pptm")):
                    src_stem = Path(src_path).stem
                    src_ext = Path(src_path).suffix.lstrip(".")
                    doc_base = f"{src_stem}_{src_ext}".replace(".", "_")
                    slides_dir = pre_dir / rel.parent / f"{doc_base}_slides"
                    shutil.rmtree(slides_dir, ignore_errors=True)
                # ======== [CoSight-END] feature: ppt-slides ========

                # ======== [CoSight-START] feature: pdf-word-image-vision ========
                # PDF/Word 的图片产物目录同步清理：
                #   新命名 <stem>_<ext>_images / <stem>_<ext>_pages（与主 md 对齐）
                #   旧命名 <stem>_images / <stem>_pages（历史产物，一并清）
                if src_path.lower().endswith((".pdf", ".doc", ".docx", ".docm")):
                    src_stem = Path(src_path).stem
                    src_ext = Path(src_path).suffix.lstrip(".")
                    doc_base = f"{src_stem}_{src_ext}".replace(".", "_")
                    for dir_name in (
                        f"{doc_base}_images", f"{doc_base}_pages",
                        f"{src_stem}_images", f"{src_stem}_pages",
                    ):
                        target = pre_dir / rel.parent / dir_name
                        if target.is_dir():
                            shutil.rmtree(target, ignore_errors=True)
                            logger.info(
                                f"LlamaIndex Watchdog: removed doc image dir {dir_name}"
                            )
                # ======== [CoSight-END] feature: pdf-word-image-vision ========

            # ======== [CoSight-START] feature: overview-md ========
            # moved/deleted 事件 cleanup 完也要刷新 overview.md（否则 CoSightBot
            # 看到的还是包含已删除文档的旧 overview.md）
            from .search import sync_chapters_table, clear_cache_for_route
            from .overview_builder import clear_overview_md
            sync_chapters_table(self.src_root, self.agent_id, session_key_hash=self.session_key_hash)
            try:
                out = write_overview_md(lan_dir, pre_dir)
                logger.info(
                    f"LlamaIndex Watchdog: [overview-md] delete/moved handler "
                    f"event={event_type} src={src_path} agent={self.agent_id} "
                    f"session={self.session_key_hash or '(none)'} lan_dir={lan_dir} "
                    f"result={out or 'skipped'}"
                )
                # write_overview_md 在 pre_dir 瞬时空时会保留旧 overview.md，
                # 以防 delete→rebuild 竞争把树永久清掉。但如果 pre_dir 在这次
                # delete 之后**真为空**（用户删了最后一个文档，且没打算立刻
                # recreate），旧 overview.md 是过期内容，要清掉。
                if not any(pre_dir.rglob("*.md")):
                    cleared = clear_overview_md(lan_dir)
                    if cleared:
                        logger.info(
                            f"LlamaIndex Watchdog: [overview-md] pre_dir empty after "
                            f"{event_type}, cleared stale overview lan_dir={lan_dir}"
                        )
            except Exception as oe:
                logger.warning(
                    f"LlamaIndex Watchdog: [overview-md] refresh failed on delete (non-fatal) "
                    f"agent={self.agent_id} session={self.session_key_hash or '(none)'} "
                    f"lan_dir={lan_dir} error={oe}"
                )
            rk = get_route_key(self.src_root, agent_id=self.agent_id, session_key_hash=self.session_key_hash)
            clear_cache_for_route(rk)
            # ======== [CoSight-END] feature: overview-md ========

            if event_type == "moved" and dest_path:
                logger.info(f"LlamaIndex Watchdog: Redirecting moved destination: {dest_path}")
                return self._update_for_event(dest_path, "created", None, is_directory)
            return "success"

        index = get_cached_index(self.src_root, self.agent_id, session_key_hash=self.session_key_hash)
        if index is None:
            llm_config = resolve_runtime_llm_config("watchdog_reload", session_key=self.session_key, agent_id=self.agent_id)
            if llm_config:
                try:
                    engine = get_query_engine(
                        self.src_root, self.agent_id, llm_client=llm_config,
                        session_key_hash=self.session_key_hash, allow_preprocessing=False,
                    )
                    index = getattr(engine, "_index", None)
                except Exception as e:
                    logger.warning(f"LlamaIndex Watchdog: get_query_engine failed in _update_for_event: {e}")

        if index is None:
            logger.warning("LlamaIndex Watchdog: Index unavailable, rebuilding.")
            # 该事件已在 _process_event 中计入 waiting；全量重建会自行 add_waiting(N)，
            # 这里先退掉本次单文件事件的计数，避免 waiting 重复叠加。
            global_progress.add_waiting(-1)
            self.run_common_build_sync(force=False)
            return "success"

        try:
            from .search import _get_ipc_lock
            from .embedding_model import embedding_configured
            # 向量入库条件化：embedding 未配置时跳过全部 insert_nodes（不发起连接），
            # 预处理/overview 生成不受影响（design prod-outside §4.3 方案 A）。
            embed_on = embedding_configured()
            if is_directory:
                # 保底全量扫描
                processed_files = process_directory(
                    self.src_root,
                    pre_dir,
                    on_ppt_fallback=self._notify_ppt_fallback,
                    session_key=self.session_key,
                    agent_id=self.agent_id,
                    progress_callback=_vision_cb
                )
                if processed_files:
                    from common.index_api import update_file_info
                    for f_path in processed_files:
                        try:
                            f_p = Path(f_path)
                            f_rel = f_p.relative_to(self.src_root).as_posix()
                            f_stat = f_p.stat()
                            update_file_info(lan_dir, f_rel, {"mtime": f_stat.st_mtime, "size": f_stat.st_size, "hash": _calculate_file_hash(f_p), "status": "success"})
                        except Exception: pass

                pre_target_dir = pre_dir / rel
                if pre_target_dir.exists():
                    for md_file in sorted(pre_target_dir.rglob("*.md")):
                        nodes = _parse_md_to_chapter_nodes(md_file) if embed_on else []
                        if nodes:
                            doc_id = md_file.resolve().as_posix()
                            with _get_ipc_lock(lan_dir):
                                for variant in [doc_id, doc_id.replace("/", "\\")]:
                                    try: index.delete_ref_doc(variant, delete_from_docstore=True)
                                    except Exception: pass
                                index.insert_nodes(nodes)
            else:
                if not is_supported_file(Path(src_path)):
                    return "success"

                # ======== 指纹预过滤 ========
                # watcher 的 on_modified 事件会在第一次 OCR 完成后**又触发一次**
                # 完整 OCR（10+ 分钟重复浪费）。
                # 详见：新概念英语第一册.pdf 拖入后被识别两次的根因分析。
                # process_directory（全量入口）已经有指纹预过滤，
                # 单文件入口（这里）之前漏了 — 补上。
                try:
                    from common.index_api import get_full_status_data
                    # 注意：从 _is_fingerprint_match 在 handler 模块本身上做 monkeypatch 时
                    # 不会生效（inline import 会重新导入），所以测试时直接 patch 源模块。
                    from file_watcher.preprocessor import _is_fingerprint_match
                    status_data = get_full_status_data(lan_dir) or {}
                    recorded = status_data.get("files") if isinstance(status_data, dict) else None
                    if recorded and _is_fingerprint_match(
                        Path(src_path), self.src_root, recorded, pre_dir,
                        session_key=self.session_key, agent_id=self.agent_id,
                    ):
                        # 指纹匹配 = 上次已成功处理 + .md 产物完整 =
                        # 节点已在 lance 里（line 666-677 流程已 insert_nodes）。
                        # 直接 return "skipped"，不动 lance，避免重复 insert。
                        logger.info(
                            f"LlamaIndex Watchdog: [skip] {std_rel} "
                            f"(fingerprint match, no reprocess)"
                        )
                        return "skipped"
                except Exception as fe:
                    logger.debug(f"LlamaIndex Watchdog: fingerprint precheck skipped for {std_rel}: {fe}")

                if process_single_file(
                    Path(src_path),
                    pre_dir,
                    self.src_root,
                    on_ppt_fallback=self._notify_ppt_fallback,
                    progress_callback=_vision_cb,
                    on_page_done=self._build_on_page_done(
                        pre_dir / rel.with_name(md_name), lan_dir, pre_dir
                    ),
                ):
                    pre_target_file = pre_dir / rel.with_name(md_name)
                    if pre_target_file.exists():
                        nodes = _parse_md_to_chapter_nodes(pre_target_file) if embed_on else []
                        if nodes:
                            doc_id = pre_target_file.resolve().as_posix()
                            with _get_ipc_lock(lan_dir):
                                for variant in [doc_id, doc_id.replace("/", "\\")]:
                                    try: index.delete_ref_doc(variant, delete_from_docstore=True)
                                    except Exception: pass
                                index.insert_nodes(nodes)
                            logger.info(f"LlamaIndex Watchdog: Updated {len(nodes)} nodes for {std_rel}")
                else:
                    pre_target_file = pre_dir / rel.with_name(md_name)
                    if pre_target_file.exists():
                        logger.info(f"LlamaIndex Watchdog: Skipping indexing for {std_rel} (already up to date)")
                        return "skipped"
                    else:
                        logger.error(f"LlamaIndex Watchdog: Preprocessing failed for {std_rel}")
                        return "failed"

                # 清理 sub-progress（防止面板残留）
                try:
                    global_progress.finish_file_subprogress(target_filename)
                except Exception:
                    pass

            from .search import sync_chapters_table, optimize_table, clear_cache_for_route
            sync_chapters_table(self.src_root, self.agent_id, session_key_hash=self.session_key_hash)
            optimize_table(lan_dir, "nodes")
            rk = get_route_key(self.src_root, agent_id=self.agent_id, session_key_hash=self.session_key_hash)
            clear_cache_for_route(rk)
            # ======== [CoSight-START] feature: overview-md ========
            # 增量更新路径无 _update_status 调用，但需同步刷新 overview.md
            try:
                out = write_overview_md(lan_dir, pre_dir)
                logger.info(
                    f"LlamaIndex Watchdog: [overview-md] _update_for_event "
                    f"event={event_type} src={src_path} agent={self.agent_id} "
                    f"session={self.session_key_hash or '(none)'} lan_dir={lan_dir} "
                    f"result={out or 'skipped'}"
                )
            except Exception as oe:
                logger.warning(
                    f"LlamaIndex Watchdog: [overview-md] refresh failed (non-fatal) "
                    f"event={event_type} src={src_path} agent={self.agent_id} "
                    f"session={self.session_key_hash or '(none)'} lan_dir={lan_dir} error={oe}"
                )
            # ======== [CoSight-END] feature: overview-md ========
            return "success"

        except Exception as e:
            logger.error(f"LlamaIndex Watchdog: Failed to process {event_type} for {src_path}: {e}", exc_info=True)
            return "failed"

    def _debounce(self, src_path: str, event_type: str, dest_path: str = None):
        """防抖处理。按文件路径聚合事件，避免同一文件的 created/modified 多次触发
        导致进度条 waiting 虚高。"""
        with self._event_lock:
            std_path = str(src_path).replace("\\", "/")
            key = f"file:{std_path}"
            if key in self._timers:
                self._timers[key].cancel()

            timer = threading.Timer(self.debounce_seconds, self._dispatch_process_event, [src_path, event_type, dest_path, key])
            self._timers[key] = timer
            timer.start()

    def _dispatch_process_event(self, src_path: str, event_type: str, dest_path: str, key: str):
        with self._event_lock:
            self._timers.pop(key, None)
        self._process_event(src_path, event_type, dest_path, is_directory=False)

    def on_created(self, event):
        if not event.is_directory and not self._is_office_temp(event.src_path) and not self._is_excluded_event_path(event.src_path):
            logger.info(f"LlamaIndex Watchdog: [on_created] {event.src_path}")
            with self._event_lock:
                try: self._last_mtimes[event.src_path] = os.path.getmtime(event.src_path)
                except OSError: pass
            self._debounce(event.src_path, "created")

    def on_modified(self, event):
        if not event.is_directory and not self._is_office_temp(event.src_path) and not self._is_excluded_event_path(event.src_path):
            logger.info(f"LlamaIndex Watchdog: [on_modified] {event.src_path}")
            try:
                current_mtime = os.path.getmtime(event.src_path)
                with self._event_lock:
                    last_mtime = self._last_mtimes.get(event.src_path)
                    if last_mtime is None:
                        self._last_mtimes[event.src_path] = current_mtime
                        if abs(time.time() - current_mtime) > 5.0:
                            logger.info(f"LlamaIndex Watchdog: [DROP] Fake modified (old file): {event.src_path}")
                            return
                    else:
                        if current_mtime == last_mtime:
                            logger.info(f"LlamaIndex Watchdog: [DROP] Duplicate modified (mtime unchanged): {event.src_path}")
                            return
                        self._last_mtimes[event.src_path] = current_mtime
                    logger.info(f"LlamaIndex Watchdog: [ACCEPT] Real modified event for {Path(event.src_path).name}")
            except OSError: pass

            if self._is_office_file(event.src_path) and self._has_office_lock(event.src_path):
                return
            self._debounce(event.src_path, "modified")

    def on_deleted(self, event):
        if event.is_directory:
            return
        if self._is_office_temp(event.src_path):
            original_file = self._get_original_file_from_lock(event.src_path)
            if original_file:
                self._debounce(original_file, "modified")
            return
        # ======== [CoSight-START] feature: exclude-cosightpro-from-preprocessing ========
        # 旧版状态目录（.cosightpro）子树里的文件删除事件直接丢掉——它们是
        # 运行时状态，不该触发索引清理、写入 fingerprint 表等动作。
        # 注意按 src_root 相对路径判断：session 上传目录本身在 .cosightpro 下。
        if self._is_excluded_event_path(event.src_path):
            return
        # ======== [CoSight-END] feature: exclude-cosightpro-from-preprocessing ========

        with self._event_lock:
            self._last_mtimes.pop(event.src_path, None)
        self._process_event(event.src_path, "deleted", is_directory=False)

    def on_moved(self, event):
        if event.is_directory:
            return
        if not self._is_office_temp(event.src_path) and not self._is_office_temp(event.dest_path) \
                and not self._is_excluded_event_path(event.src_path) and not (event.dest_path and self._is_excluded_event_path(event.dest_path)):
            with self._event_lock:
                self._last_mtimes.pop(event.src_path, None)
                try:
                    if event.dest_path:
                        self._last_mtimes[event.dest_path] = os.path.getmtime(event.dest_path)
                except OSError: pass
            self._process_event(event.src_path, "moved", event.dest_path, is_directory=False)
