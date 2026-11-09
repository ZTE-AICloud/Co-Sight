#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
独立子进程任务运行器 (Subprocess Task Runner)

此脚本用于在独立的子进程中执行 LlamaIndex 的重型操作（全量构建、增量更新）。
每一次构建/索引任务都在独立进程中执行，调用方（技能 CLI）采集其输出。

进度机制：stdout [progress] 行（file_watcher.progress_ui 的 stdout 后端），
由调用方流式透传；文件信息经 _LocalProgressReporter 直接落盘 common.index_api。
"""

import argparse
import sys
import os
import hashlib
import logging
from pathlib import Path

# 强制 UTF-8 读写（双平台防御：Windows GBK / Linux 非 UTF-8 locale 同理会乱码）。
# 只对支持的流逐个 reconfigure、不重建 TextIOWrapper：重建会在 pytest capture
# 等流替换场景下顶掉原流并触发底层临时文件关闭；无 reconfigure 能力的流
# （测试替身等）安全跳过。内嵌运行时 python≥3.7，reconfigure 必然可用。
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_stream, 'reconfigure'):
        try:
            _stream.reconfigure(encoding='utf-8')
        except (AttributeError, OSError, ValueError):
            pass

logger = logging.getLogger("llamaindex_task_runner")


def _calculate_file_hash(path: Path) -> str:
    """计算文件的 MD5 哈希值。"""
    try:
        hasher = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return ""


_current_dir = os.path.dirname(os.path.abspath(__file__))
_runtime_root = str(Path(_current_dir).parent)
for _p in (_current_dir, _runtime_root):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common.logging_setup import log_event, setup_logging  # noqa: E402

setup_logging()
log_event(logger, "subprocess:init", python=sys.version.split()[0], pid=os.getpid())

# 注意:本脚本由技能 CLI 作为 __main__ 直接 spawn 跑,__package__ 为空,
# 相对导入 `from .X import Y` 在这种模式下会 ImportError;
# 改成绝对导入(由上方 _runtime_root = ... sys.path.insert 已注入)。


class _LocalProgressReporter:
    """本地进度上报对象（stdout 直出）。

    - 一级/二级进度委托给 stdout [progress] 后端（file_watcher.progress_ui），
      由调用方（技能 CLI）流式采集；
    - 文件信息维护（update/remove_file_info）直接落盘到 common.index_api ——
      必须真实落盘，否则增量更新后的文件状态永不持久化；
    - join() 无操作（无 IPC 队列，仅为兼容调用方保留）。
    """

    def __init__(self) -> None:
        from file_watcher.progress_ui import global_progress
        from common import index_api

        self._ui = global_progress
        self._index = index_api

    def __getattr__(self, name):  # 其余进度方法直通 stdout 后端
        return getattr(self._ui, name)

    def update_file_info(self, lancedb_dir, rel_path, file_info) -> None:
        self._index.update_file_info(Path(lancedb_dir), rel_path, file_info)

    def remove_file_info(self, lancedb_dir, rel_path) -> None:
        self._index.remove_file_info(Path(lancedb_dir), rel_path)

    def remove_directory_info(self, lancedb_dir, dir_rel_path) -> None:
        self._index.remove_directory_info(Path(lancedb_dir), dir_rel_path)

    def join(self) -> None:
        pass


ipc_progress = _LocalProgressReporter()

def run_common_build(agent_id: str, path: str, force: bool, session_key_hash: str = "", session_key: str = ""):
    from file_watcher.handler import LlamaIndexIncrementalHandler
    ipc_progress.set_system_status("正在构建知识库索引 (请耐心等待)...")
    try:
        material_path = Path(path)
        log_event(
            logger, "build:subprocess:start",
            agent=agent_id, path=material_path, force=force,
            session=session_key_hash or "(none)",
        )
        handler = LlamaIndexIncrementalHandler(
            src_root=material_path,
            agent_id=agent_id,
            session_key_hash=session_key_hash,
            session_key=session_key,
        )
        handler.run_common_build_sync(force=force)
        log_event(logger, "build:subprocess:done", agent=agent_id, path=material_path)
    except Exception as e:
        logger.error(f"Common build failed for {agent_id}: {e}", exc_info=True)
        log_event(logger, "build:subprocess:error", agent=agent_id, error=f"{type(e).__name__}: {e}")
        raise
    finally:
        ipc_progress.set_system_status("")

def run_common_update(agent_id: str, path: str, src_path: str, event_type: str, dest_path: str | None, is_directory: bool, session_key_hash: str = "", session_key: str = ""):
    """执行单个文件的增量转换和入库。此时不再处理目录级别的批量更新。"""
    from file_watcher.handler import LlamaIndexIncrementalHandler
    from file_watcher.config import get_llamaindex_storage_dirs, get_session_storage_dirs

    ipc_progress.set_system_status("正在更新知识库索引 (请耐心等待)...")
    try:
        material_path = Path(path)
        active_path = Path(dest_path) if (event_type == "moved" and dest_path) else Path(src_path)
        filename = active_path.name
        log_event(
            logger, "update:subprocess:start",
            agent=agent_id, event_type=event_type, src=src_path, dest=dest_path,
            is_dir=is_directory, session=session_key_hash or "(none)",
        )

        handler = LlamaIndexIncrementalHandler(
            src_root=material_path,
            agent_id=agent_id,
            session_key_hash=session_key_hash,
            session_key=session_key,
        )
        if session_key_hash:
            _, _, lan_dir = get_session_storage_dirs(agent_id, session_key_hash)
        else:
            _, lan_dir = get_llamaindex_storage_dirs(material_path, agent_id)

        ipc_progress.start_processing(filename, is_delete=(event_type == "deleted"))

        try:
            result = handler._update_for_event(src_path, event_type, dest_path, is_directory)

            if not is_directory:
                rel_path = Path(src_path).relative_to(material_path).as_posix()
                if event_type == "deleted":
                    ipc_progress.remove_file_info(lan_dir, rel_path)
                elif result == "failed":
                    fail_rel = rel_path
                    if event_type == "moved" and dest_path:
                        ipc_progress.remove_file_info(lan_dir, rel_path)
                        fail_rel = Path(dest_path).relative_to(material_path).as_posix()
                    ipc_progress.update_file_info(lan_dir, fail_rel, {"mtime": 0, "size": 0, "status": "failed", "error": "文件预处理失败，转换所有方法均报错"})
                    ipc_progress.fail_processing(filename, src_path, f"增量更新失败: 文件预处理失败: {filename}")
                    return
                elif result == "skipped":
                    pass
                elif event_type == "moved" and dest_path:
                    new_rel = Path(dest_path).relative_to(material_path).as_posix()
                    ipc_progress.remove_file_info(lan_dir, rel_path)
                    if active_path.exists():
                        stat = active_path.stat()
                        ipc_progress.update_file_info(lan_dir, new_rel, {"mtime": stat.st_mtime, "size": stat.st_size, "hash": _calculate_file_hash(active_path), "status": "success", "error": ""})
                elif active_path.exists():
                    rel_curr = Path(active_path).relative_to(material_path).as_posix()
                    stat = active_path.stat()
                    ipc_progress.update_file_info(lan_dir, rel_curr, {"mtime": stat.st_mtime, "size": stat.st_size, "hash": _calculate_file_hash(active_path), "status": "success", "error": ""})

            ipc_progress.finish_processing(filename)
        except FileNotFoundError as e:
            if event_type == "deleted":
                rel_path = Path(src_path).relative_to(material_path).as_posix()
                ipc_progress.remove_file_info(lan_dir, rel_path)
                ipc_progress.finish_processing(filename)
            else:
                rel_path = Path(src_path).relative_to(material_path).as_posix()
                ipc_progress.update_file_info(lan_dir, rel_path, {"mtime": 0, "size": 0, "status": "failed", "error": f"文件在处理前已失踪: {str(e)}"})
                ipc_progress.fail_processing(filename, src_path, f"增量更新失败: 文件转换失败: {filename}")
        except Exception as e:
            if not is_directory and event_type != "deleted":
                rel_path = Path(src_path).relative_to(material_path).as_posix()
                ipc_progress.update_file_info(lan_dir, rel_path, {"mtime": 0, "size": 0, "status": "failed", "error": str(e)})
                ipc_progress.fail_processing(filename, src_path, f"增量更新失败: {str(e)}")
            else:
                ipc_progress.finish_processing(filename)
        log_event(logger, "update:subprocess:done", agent=agent_id, event_type=event_type, src=src_path)
    finally:
        ipc_progress.set_system_status("")

def main():
    parser = argparse.ArgumentParser(description="Subprocess Task Runner for LlamaIndex")
    parser.add_argument("action", choices=["common_build", "common_update", "full_build"])
    parser.add_argument("--agent_id", required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--src_path", type=str)
    parser.add_argument("--dest_path", type=str)
    parser.add_argument("--event_type", type=str)
    parser.add_argument("--is_directory", action="store_true")
    parser.add_argument("--session_key_hash", type=str, default="")
    parser.add_argument("--session_key", type=str, default="")
    args = parser.parse_args()
    try:
        if args.action == "common_build": run_common_build(args.agent_id, args.path, args.force, args.session_key_hash, args.session_key)
        elif args.action == "common_update": run_common_update(args.agent_id, args.path, args.src_path, args.event_type, args.dest_path, args.is_directory, args.session_key_hash, args.session_key)
        elif args.action == "full_build":
            run_common_build(args.agent_id, args.path, args.force, args.session_key_hash, args.session_key)
    finally:
        ipc_progress.set_system_status("")
    ipc_progress.join()

if __name__ == "__main__":
    main()
