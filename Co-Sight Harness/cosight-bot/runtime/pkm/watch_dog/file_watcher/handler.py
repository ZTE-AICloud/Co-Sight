#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件监听增量处理器

基于 watchdog 监听文件变更，增量执行文档预处理（格式转换 → markdown
+ 章节切分 + 多模态图片）并维护 overview 产物（overview.md /
node_index.json / .llamaindex_status 指纹）。

检索（overview 三步法）只读 pre_dir 磁盘产物，不建/不查向量库；
历史 LlamaIndex 向量入库路径已移除（design/del-main-rag.md）。

只经技能 CLI 显式触发（全量构建 / 单文件增量），不启动监听进程。
"""

import json
import os
import shutil
import threading
import time
import logging
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

from filelock import FileLock, Timeout
from watchdog.events import FileSystemEventHandler

from .config import (
    get_route_key,
    get_llamaindex_storage_dirs,
    get_session_storage_dirs,
    is_under_pre_processed_dir,
)
from common.cosight_runtime import resolve_runtime_llm_config
from common.logging_setup import log_event, log_stage
from .preprocessor import is_supported_file, process_single_file, process_directory, _calculate_file_hash, is_office_temp, is_under_excluded_dir
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

# section index 写锁：全量构建与增量更新互斥。增量更新拿不到锁时直接跳过，
# 因为全量构建结束时会把构建期间的全部文件重新写入。
SECTION_INDEX_LOCK_NAME = ".section_index.lock"

# 批量构建的 overview 重生成节流：write_overview_md 单次成本随语料线性增长
# （实测 1047 md ≈ 6s，主要是静默的全量 headers 提取），而逐文件流水线每文件
# 调一次 → O(N²)：437 文件实测 35min 几乎全耗在这，预处理本身只要 6s。
# 构建期按「距上次刷新 ≥ OVERVIEW_REFRESH_MIN_INTERVAL_S 且步长内累计文件数
# 达标」双重节流；首个文件与构建收尾无条件写（前者保证尽早 ready 可问答，
# 后者保证最终产物完整）。步长随语料规模放大（max(50, N/10)），把全构建期
# 重建总次数压到 ~10 次 + 首末。
OVERVIEW_REFRESH_MIN_INTERVAL_S = float(os.environ.get("COSIGHTBOT_OVERVIEW_REFRESH_MIN_INTERVAL", "60"))
_overview_refresh_state: dict = {}  # lan_dir(str) -> {"ts": float, "files": int, "total": int}

# 指纹攒批落盘阈值：状态文件大小随文件数线性（50 万文件 ~136MB），逐文件
# 全量重写是 O(N²)。攒批后 50 万文件仅 ~500 次全量写。env 可覆盖（测试缩短）。
STATUS_FLUSH_EVERY = int(os.environ.get("COSIGHTBOT_STATUS_FLUSH_EVERY", "1000"))


def _strip_reader_metadata(doc):
    """去掉 SimpleDirectoryReader 注入的 reader 字段。

    历史上为向量入库 schema 兼容而设；向量路径已移除，函数保留
    （soc 构建侧模块级复用本实现，勿删勿移）。
    """
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

    def _reset_overview_throttle(self, lan_dir: Path, total_files: int) -> None:
        """构建开始时重置 overview 节流状态（ts=0 使首个成功文件立即刷新一次）。"""
        max_intermediate_files = int(os.environ.get(
            "COSIGHTBOT_OVERVIEW_INTERMEDIATE_MAX_FILES", "50000"
        ))
        # 51W 规模下每次全量 overview 重写（即使不读章节标题）也要数分钟，
        # 会阻塞预处理主线程。超过阈值默认只保留首次 + 收尾两次刷新；
        # 小库仍可中间刷新，保持“边建边查”。
        intermediate_allowed = (
            os.environ.get("COSIGHTBOT_OVERVIEW_REFRESH_INTERMEDIATE", "1") != "0"
            and total_files <= max_intermediate_files
        )
        _overview_refresh_state[str(lan_dir)] = {
            "ts": 0.0, "files": 0, "total": max(1, total_files),
            "first_done": False,
            "intermediate": intermediate_allowed,
            "show_sections_intermediate": os.environ.get(
                "COSIGHTBOT_OVERVIEW_REFRESH_SHOW_SECTIONS", "0"
            ) == "1",
        }

    def _flush_status_buffer(self, lan_dir: Path, status_buffer: dict, last_flush: list) -> None:
        """把攒批的指纹一次性落盘（update_file_info_batch：一次读-合并-写）。"""
        from common.index_api import update_file_info_batch, ensure_ready
        if not status_buffer:
            return
        count = len(status_buffer)
        try:
            update_file_info_batch(lan_dir, status_buffer)
            log_event(logger, "build:status:flush", level=logging.DEBUG, count=count)
        finally:
            status_buffer.clear()
        try:
            ensure_ready(lan_dir, self.src_root)
        except Exception:
            pass
        last_flush[0] = time.monotonic()

    def _maybe_refresh_overview(self, lan_dir: Path, pre_dir: Path, force: bool = False) -> None:
        """按节流策略刷新 overview 产物（构建期逐文件/逐页高频调用的唯一入口）。

        首次调用立即写（ts==0 哨兵），保证首个成功文件完成即 ready 可问答；
        之后仅当「距上次刷新 ≥ OVERVIEW_REFRESH_MIN_INTERVAL_S 且步长内累计
        文件数达标」才重生成，消除逐文件重建的 O(N²) 开销。
        """
        key = str(lan_dir)
        st = _overview_refresh_state.setdefault(key, {
            "ts": 0.0, "files": 0, "total": 1, "first_done": False,
            "intermediate": True, "show_sections_intermediate": False,
        })
        st["files"] += 1
        step = max(50, st["total"] // 10)
        first = not st.get("first_done") and st["ts"] == 0.0
        # 中间刷新关闭时，仅保留首次（尽早 ready）和构建收尾（run_common_build_sync
        # 直接调用 write_overview_md）两次。
        if not first and not st.get("intermediate", True) and not force:
            return
        due = (
            force
            or first
            or (time.time() - st["ts"] >= OVERVIEW_REFRESH_MIN_INTERVAL_S and st["files"] >= step)
        )
        if not due:
            return
        # 首次/中间刷新不展开章节标题：不逐篇读 51W 个 md，避免每次 10+ 分钟；
        # 收尾刷新由调用方使用默认 show_sections=True 生成完整树。
        show_sections = False if first else bool(
            st.get("show_sections_intermediate", False)
        )
        try:
            write_overview_md(lan_dir, pre_dir, show_sections=show_sections)
            st["first_done"] = True
            st["ts"] = time.time()
            st["files"] = 0
        except Exception as oe:
            logger.warning(f"overview refresh failed (non-fatal): {oe}")

    def _pipeline_handle_success(self, file_path: Path, md_path: Path, lan_dir: Path,
                                 status_buffer: dict | None = None) -> bool:
        """P1-5 辅助：单文件预处理成功路径。返回 True/False 便于测试。

        去向量后仅做指纹簿记 + overview 刷新 + 就绪翻 ready；md_path
        保留在签名里（调用方与测试沿用），read-doc 直接读 pre_dir 磁盘。
        status_buffer 传入时指纹写入攒批（由调用方经 update_file_info_batch
        统一落盘），消除大库构建时逐文件全量重写状态文件的 O(N²) 开销。
        """
        from common.index_api import update_file_info
        rel = file_path.relative_to(self.src_root).as_posix()
        try:
            f_stat = file_path.stat()
            info = {
                "mtime": f_stat.st_mtime, "size": f_stat.st_size,
                "hash": _calculate_file_hash(file_path), "status": "success",
            }
            if status_buffer is not None:
                status_buffer[rel] = info
            else:
                update_file_info(lan_dir, rel, info)
            log_event(
                logger, "build:file:indexed", level=logging.DEBUG,
                rel=rel, size=info["size"], hash=info["hash"][:12], status="success",
            )
        except Exception as e:
            logger.error(f"LlamaIndex Watchdog: ingest failed for {rel}: {e}", exc_info=True)
            log_event(
                logger, "build:file:index-failed", level=logging.ERROR,
                rel=rel, error=f"{type(e).__name__}: {e}", exc_info=True,
            )
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
            self._maybe_refresh_overview(lan_dir, self.pre_dir)
        except Exception as oe:
            logger.warning(f"LlamaIndex Watchdog: overview refresh failed (non-fatal): {oe}")
        if status_buffer is None:
            # 攒批模式下 ensure_ready 由 _flush_status_buffer 统一触发
            # （ensure_ready 需读全量状态文件，逐文件调用同样是大库 O(N²) 开销）
            try:
                ensure_ready(lan_dir, self.src_root)
            except Exception:
                pass
        return True

    def _pipeline_mark_failed(self, file_path: Path, rel: str, lan_dir: Path, err: str) -> None:
        """P1-5 辅助：标记失败 + 进度框通知。"""
        from common.index_api import update_file_info
        log_event(
            logger, "build:file:failed", level=logging.WARNING,
            rel=rel, error=err,
        )
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
        """P3：构建按页增量回调——首页 + 每 PAGE_INGEST_INTERVAL 页刷新 overview
        + ensure_ready，让大文件"边处理边可查"（read-doc 直接读 pre_dir 磁盘产物）。
        供 _preprocess_one（批量 run_common_build_sync）与 _update_for_event（增量单文件）共用。"""
        def _on_page_done(page_index, total):
            try:
                if page_index == 1 or page_index % PAGE_INGEST_INTERVAL == 0:
                    from common.index_api import ensure_ready
                    if md_path.exists():
                        self._maybe_refresh_overview(lan_dir, pre_dir)
                        ensure_ready(lan_dir, self.src_root)
            except Exception as _e:
                logger.warning(f"on_page_done overview refresh failed page {page_index}: {_e}")
        return _on_page_done

    def _write_section_index_status(self, lan_dir: Path, status: str, **fields) -> None:
        try:
            payload = {"status": status, "updated_at": time.time(), **fields}
            (lan_dir / ".section_index_status.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as exc:
            log_event(logger, "build:section-index:status:error", level=logging.WARNING,
                      error=f"{type(exc).__name__}: {exc}")

    def _section_index_needs_upgrade(self, lan_dir: Path) -> bool:
        """稳定 ID 上线后，旧 schema/旧 doc_key 索引需要全量重建。"""
        try:
            import lancedb
            from .section_index import SCHEMA_VERSION

            db = lancedb.connect(str(lan_dir))
            tables = db.list_tables()
            names = set(getattr(tables, "tables", tables))
            if "build_meta" not in names or "doc_skeleton" not in names:
                return False
            meta = {
                row["key"]: row["value"]
                for row in db.open_table("build_meta").to_arrow().to_pylist()
            }
            version = meta.get("schema_version")
            if version and version != str(SCHEMA_VERSION):
                return True
            doc = db.open_table("doc_skeleton")
            if doc.count_rows() == 0:
                return False
            try:
                legacy = doc.to_lance().to_table(
                    filter="doc_key = rel_path", limit=1
                ).num_rows
            except Exception:
                legacy = 0
            return bool(legacy)
        except Exception:
            return False

    def _build_section_index(self, lan_dir: Path, pre_dir: Path,
                             rel_paths: set[str], force: bool = False) -> None:
        """构建/更新 section 级索引（LanceDB 骨架/指针 + f16 向量 + tantivy FTS）。

        失败不阻塞 overview 构建，但会写 `.section_index_status.json` 并打 ERROR 日志。
        """
        if os.environ.get("COSIGHTBOT_SECTION_INDEX", "1") == "0":
            log_event(logger, "build:section-index:skip", reason="disabled_by_env",
                      agent=self.agent_id, lan_dir=str(lan_dir))
            self._write_section_index_status(lan_dir, "skipped", reason="disabled_by_env")
            return
        if not force and not rel_paths:
            # 升级路径：旧 schema（doc_key=rel_path）即使没有文件变更也要重建。
            if self._section_index_needs_upgrade(lan_dir):
                log_event(logger, "build:section-index:upgrade",
                          reason="legacy_schema", agent=self.agent_id)
                force = True
            else:
                log_event(logger, "build:section-index:skip", reason="no_changed_files",
                          agent=self.agent_id, lan_dir=str(lan_dir))
                self._write_section_index_status(lan_dir, "skipped", reason="no_changed_files")
                return
        lock = FileLock(str(lan_dir / SECTION_INDEX_LOCK_NAME))
        try:
            lock.acquire(timeout=10)
        except Timeout:
            log_event(logger, "build:section-index:skip", reason="locked",
                      agent=self.agent_id, lan_dir=str(lan_dir))
            self._write_section_index_status(lan_dir, "skipped", reason="locked")
            return
        try:
            from .section_index import SectionIndex

            t0 = time.perf_counter()
            self._write_section_index_status(lan_dir, "building")
            si = SectionIndex(lan_dir)
            # 首次升级：索引表为空时全量构建，不能只建增量文件
            build_rels = None if (force or si.doc_table.count_rows() == 0) else rel_paths
            # 旧索引的 doc_key 是 rel_path；稳定 ID 上线后必须全量重建，
            # 否则新旧 key 混用，增量删除/检索都会漏。
            if build_rels is not None:
                try:
                    legacy = si.doc_table.to_lance().to_table(
                        filter="doc_key = rel_path", limit=1
                    ).num_rows
                except Exception:
                    legacy = 0
                if legacy:
                    log_event(
                        logger, "build:section-index:upgrade",
                        reason="legacy_doc_key", agent=self.agent_id,
                    )
                    build_rels = None
            log_event(
                logger, "build:section-index:start",
                agent=self.agent_id, lan_dir=str(lan_dir),
                mode="full" if build_rels is None else "incremental",
                changed=len(rel_paths), force=force,
            )
            summary = si.build_from_pre_dir(
                pre_dir, rel_paths=build_rels, full_build=(build_rels is None)
            )
            final = si.finalize()
            status = "ready" if summary.get("failed", 0) == 0 else "partial"
            self._write_section_index_status(
                lan_dir, status,
                docs=final.get("docs"), sections=final.get("sections"),
                pointers=final.get("pointers"), failed=summary.get("failed", 0),
                ann_enabled=final.get("ann_enabled"),
                duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
            log_event(
                logger, "build:section-index:done",
                agent=self.agent_id, status=status, **{**summary, **final},
            )
        except Exception as exc:
            log_event(
                logger, "build:section-index:error", level=logging.ERROR,
                agent=self.agent_id, lan_dir=str(lan_dir),
                error=f"{type(exc).__name__}: {exc}", exc_info=True,
            )
            self._write_section_index_status(
                lan_dir, "failed", error=f"{type(exc).__name__}: {exc}"
            )
        finally:
            lock.release()

    def _update_section_index_for_event(self, lan_dir: Path, pre_dir: Path,
                                        rel_path: str, md_name: str | None = None,
                                        event: str = "created") -> None:
        """增量更新/删除单文档的 section 索引；失败只记录，不阻塞 overview。"""
        if os.environ.get("COSIGHTBOT_SECTION_INDEX", "1") == "0":
            return
        lock = FileLock(str(lan_dir / SECTION_INDEX_LOCK_NAME))
        try:
            lock.acquire(timeout=0)
        except Timeout:
            # 全量构建进行中：构建收尾会覆盖本次变更，跳过即可。
            log_event(logger, "section_index:incremental:skip", level=logging.DEBUG,
                      rel=rel_path, event=event, reason="locked")
            return
        try:
            from .section_index import SectionIndex

            si = SectionIndex(lan_dir)
            if event == "deleted":
                si.delete_document(rel_path)
                si.commit()
                log_event(logger, "section_index:incremental:deleted",
                          rel=rel_path, agent=self.agent_id)
            else:
                md_path = pre_dir / Path(rel_path).with_name(md_name) if md_name else pre_dir / rel_path
                if md_path.exists():
                    summary = si.upsert_document(md_path, rel_path)
                    si.commit()
                    log_event(logger, "section_index:incremental:upserted",
                              rel=rel_path, agent=self.agent_id, **summary)
                else:
                    log_event(logger, "section_index:incremental:skip", level=logging.WARNING,
                              rel=rel_path, reason="md_missing")
        except Exception as exc:
            log_event(logger, "section_index:incremental:error", level=logging.ERROR,
                      rel=rel_path, event=event,
                      error=f"{type(exc).__name__}: {exc}", exc_info=True)
            self._write_section_index_status(
                lan_dir, "failed", error=f"{type(exc).__name__}: {exc}", rel=rel_path
            )
        finally:
            lock.release()

    def run_common_build_sync(self, force: bool = False):
        """逐文件流水线构建：每文件预处理完即写 overview 产物即就绪，单文件失败不阻塞其余。

        替代原"全量预处理 -> 一次性建索引"的批处理：用 as_completed 逐文件消费，
        每完成一个就刷新 overview + ensure_ready，使其立即可问答（read-doc 读磁盘）。
        超时/异常的文件标记 failed 并继续。
        单文件 OCR hang 由 VISION_TOTAL_TIMEOUT 兜住；未覆盖的 hang 由
        VISION_TOTAL_TIMEOUT 兜底。
        """
        logger.info(f"LlamaIndex Watchdog: run_common_build_sync material={self.src_root.name}, agent={self.agent_id}, force={force}")
        build_t0 = time.perf_counter()
        log_event(
            logger, "build:start",
            agent=self.agent_id, source=str(self.src_root), force=force,
            session=self.session_key_hash or "(none)",
        )

        from common.index_api import _update_status, update_file_info, get_full_status_data, ensure_ready
        from .preprocessor import _is_fingerprint_match, EXT_PDF, EXT_MARKITDOWN, EXT_MHTML, EXT_TEXT, EXT_IMAGES
        from concurrent.futures import as_completed

        pre_dir, lan_dir = self._get_storage_dirs()
        if not pre_dir or not lan_dir:
            return
        # _pipeline_handle_success / _on_page_done 等嵌套函数需访问 pre_dir/lan_dir
        self.pre_dir = pre_dir
        self.lan_dir = lan_dir

        # 保留解析 + 门控：预处理 OCR/vision 依赖 LLM 配置就绪；无配置不启动构建。
        # （去向量后本函数不再把 llm_client 传给索引构建；技能 CLI 无 daemon 兜底，
        # 静默空跑会误导用户，故保持硬失败语义。）
        llm_config = resolve_runtime_llm_config("full_build", session_key=self.session_key, agent_id=self.agent_id)
        if not llm_config:
            _update_status(lan_dir, "failed", source_dir=self.src_root, error="LLM 未配置")
            raise RuntimeError(
                "LLM 未配置（ANTHROPIC_* 或 OPENAI_*，见 data/.env），无法构建索引"
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
            total_supported = len(supported_files)
            if recorded_files:
                supported_files = [
                    f for f in supported_files
                    if not _is_fingerprint_match(f, self.src_root, recorded_files, pre_dir,
                                                 session_key=self.session_key, agent_id=self.agent_id)
                ]
            skipped_fingerprint = total_supported - len(supported_files)
            logger.info(f"LlamaIndex Watchdog: pipeline {len(supported_files)} file(s) to process (force={force}).")
            log_event(
                logger, "build:scan",
                agent=self.agent_id, source=str(self.src_root),
                total_files=len(all_files), supported=total_supported,
                to_process=len(supported_files), skipped_fingerprint=skipped_fingerprint,
                force=force, pre_dir=str(pre_dir), lan_dir=str(lan_dir),
            )
            global_progress.add_waiting(len(supported_files))
            # overview 逐文件重建是 O(N²)，构建期换节流刷新（首个文件立即写、收尾兜底写）
            self._reset_overview_throttle(lan_dir, total_files=len(supported_files))

            # 指纹攒批缓冲：闭包内经 _flush_status_buffer 统一落盘
            status_buffer: dict = {}
            processed_rels: set[str] = set()
            last_flush = [time.monotonic()]

            def _preprocess_one(file_path: Path):
                """预处理单个文件，返回 md_path 或 None。处理进度上报。"""
                filename = file_path.name
                rel = file_path.relative_to(self.src_root).as_posix()
                t_file = time.perf_counter()
                try:
                    file_size = file_path.stat().st_size
                except OSError:
                    file_size = -1
                log_event(logger, "build:file:start", level=logging.DEBUG,
                          rel=rel, size=file_size)
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
                        result_path = md_path if md_path.exists() else None
                        log_event(
                            logger, "build:file:done", level=logging.DEBUG,
                            rel=rel, md=str(result_path) if result_path else None,
                            duration_ms=round((time.perf_counter() - t_file) * 1000, 1),
                        )
                        return result_path
                    global_progress.fail_processing(filename, str(file_path), "文件格式解析失败或已被跳过")
                    log_event(
                        logger, "build:file:failed", level=logging.WARNING,
                        rel=rel, reason="format_or_skipped",
                        duration_ms=round((time.perf_counter() - t_file) * 1000, 1),
                    )
                    return None
                except Exception as e:
                    global_progress.fail_processing(filename, str(file_path), f"异常: {e}")
                    log_event(
                        logger, "build:file:error", level=logging.ERROR,
                        rel=rel, error=f"{type(e).__name__}: {e}",
                        duration_ms=round((time.perf_counter() - t_file) * 1000, 1),
                        exc_info=True,
                    )
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
                    if self._pipeline_handle_success(file_path, md_path, lan_dir,
                                                     status_buffer=status_buffer):
                        processed_rels.add(rel)
                        if len(processed_rels) % 100 == 0:
                            log_event(
                                logger, "build:progress",
                                agent=self.agent_id,
                                processed=len(processed_rels),
                                total=len(supported_files),
                                pending_failures=len(failed_to_retry),
                                duration_ms=round((time.perf_counter() - build_t0) * 1000, 1),
                            )

                    # 指纹攒批落盘：达到批次阈值或距上次落盘 ≥30s 就刷一次，
                    # 避免大库构建时逐文件全量重写状态文件（O(N²) 磁盘/CPU 开销）
                    if status_buffer and (
                        len(status_buffer) >= STATUS_FLUSH_EVERY
                        or time.monotonic() - last_flush[0] >= 30
                    ):
                        self._flush_status_buffer(lan_dir, status_buffer, last_flush)

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
                            if self._pipeline_handle_success(fp, md, lan_dir,
                                                             status_buffer=status_buffer):
                                processed_rels.add(rel)
                        else:
                            err = failed_to_retry[fp]
                            logger.warning(f"LlamaIndex Watchdog: retry still failed for {rel}: {err}")
                            self._pipeline_mark_failed(fp, rel, lan_dir, f"预处理失败/超时 (重试 1 次仍失败): {err}")
                    # 重试循环结束后先把攒批指纹落盘，再做 overview 收尾 + ready
                    self._flush_status_buffer(lan_dir, status_buffer, last_flush)
                    try:
                        write_overview_md(lan_dir, pre_dir)
                    except Exception as oe:
                        logger.warning(f"LlamaIndex Watchdog: overview refresh failed (non-fatal): {oe}")
                    try:
                        ensure_ready(lan_dir, self.src_root)
                    except Exception:
                        pass

            # 批末收尾：攒批指纹落盘 + overview + ready
            self._flush_status_buffer(lan_dir, status_buffer, last_flush)
            try:
                write_overview_md(lan_dir, pre_dir)
            except Exception as oe:
                logger.warning(f"LlamaIndex Watchdog: overview finalize failed (non-fatal): {oe}")
            try:
                ensure_ready(lan_dir, self.src_root)
            except Exception:
                pass
            self._build_section_index(lan_dir, pre_dir, processed_rels, force=force)
            log_event(
                logger, "build:done",
                agent=self.agent_id, source=str(self.src_root),
                supported=total_supported, to_process=len(supported_files),
                skipped_fingerprint=skipped_fingerprint,
                duration_ms=round((time.perf_counter() - build_t0) * 1000, 1),
            )
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
        log_event(
            logger, "update:event", event_type=event_type, rel=std_rel,
            src=src_path, dest=dest_path, is_dir=is_directory,
        )
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

            if is_directory:
                pre_target_dir = pre_dir / rel
                if is_under_pre_processed_dir(pre_target_dir):
                    shutil.rmtree(pre_target_dir, ignore_errors=True)
            else:
                pre_target_file = pre_dir / rel.with_name(md_name)
                pre_target_file.unlink(missing_ok=True)

                # ======== [CoSight-START] feature: chapter-cleanup ========
                # 同步删除 chapter_splitter 生成的 _chapters 子目录。
                # 否则后续 pre_dir.glob("**/*.md") 递归扫描（overview 树生成等）
                # 会把章节子文件当根级 .md，导致 overview.md / node_index.json
                # 全部错位。
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
            from .search import clear_cache_for_route
            from .overview_builder import clear_overview_md
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

            if not is_directory:
                self._update_section_index_for_event(
                    lan_dir, pre_dir, std_rel, event="deleted"
                )
            else:
                log_event(
                    logger, "section_index:incremental:skip", level=logging.WARNING,
                    reason="directory_event", rel=std_rel, event_type=event_type,
                )

            if event_type == "moved" and dest_path:
                logger.info(f"LlamaIndex Watchdog: Redirecting moved destination: {dest_path}")
                return self._update_for_event(dest_path, "created", None, is_directory)
            return "success"

        try:
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
                        # 指纹匹配 = 上次已成功处理 + .md 产物完整，
                        # 直接 return "skipped"，避免重复预处理。
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
                    # 预处理完成：指纹簿记与 overview 刷新在函数收尾统一处理。
                    # section 索引必须等 overview 写完 node_index.json 后再更新，
                    # 才能拿到稳定节点 ID（见下方收尾逻辑）。
                    pass
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

            # 去向量后 engine 缓存已无写入方，此调用保留为无害的缓存清扫
            from .search import clear_cache_for_route
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
            # overview/node_index 已刷新，再增量更新 section 索引：此时才能从
            # node_index.json 解析到稳定节点 ID。失败只记录，不阻塞 overview。
            if not is_directory:
                self._update_section_index_for_event(
                    lan_dir, pre_dir, rel.as_posix(),
                    md_name=md_name, event=event_type,
                )
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
