#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公共索引 API。

保留的公共面：索引状态/文件信息读写（ensure_ready、get_full_status_data、
update_file_info、remove_file_info、remove_directory_info、get_all_file_info、
get_status）与缓存/磁盘清理（forget_project、wipe_project）。

无中央调度与常驻监听：构建/增量由技能层显式调用
watch_dog/llamaindex_task_runner.py 子进程（common_build/common_update）。
"""
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional


logger = logging.getLogger("index_api")

# ---------------------------------------------------------------------------
# 全局状态
# ---------------------------------------------------------------------------

STATUS_FILE = ".llamaindex_status"


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

def _get_dirs(material_source_dir: Path, agent_id: str):
    from file_watcher.config import get_llamaindex_storage_dirs
    return get_llamaindex_storage_dirs(material_source_dir, agent_id)


def _update_status(lancedb_dir: Path, status: str, source_dir: Path = None,
                   error: str = None):
    try:
        lancedb_dir.mkdir(parents=True, exist_ok=True)
        status_file = _get_status_file(lancedb_dir)

        # 保留现有的 files 记录（如果存在）
        existing_files = {}
        if status_file.exists():
            try:
                with open(status_file, "r", encoding="utf-8-sig") as f:
                    old_data = json.load(f)
                    existing_files = old_data.get("files", {})
            except Exception:
                pass

        data = {"status": status, "error": error, "timestamp": time.time(), "v": 1, "files": existing_files}
        if source_dir:
            data["source_dir"] = Path(source_dir).expanduser().resolve().as_posix()
        _atomic_write_json(status_file, data)
        logger.info(f"Index API: Updated status to '{status}' in {lancedb_dir.name}")
    except Exception as e:
        logger.error(f"Index API: Failed to update status: {e}")



def _atomic_write_json(path: Path, data: dict) -> None:
    """P1-4 原子写：.tmp + os.replace，防硬杀 worker 留半写状态。"""
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        logger.warning(f"Index API: atomic write {path.name} failed: {e}")
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass





def _embedding_configured() -> bool:
    """向量入库是否已配置（COSIGHTBOT_EMBEDDING_API_URL 存在）。

    实时读环境变量，不 import embedding_model（避免把 llama_index 等重依赖
    拖进轻量调用方进程）。与 file_watcher.embedding_model.embedding_configured
    保持同一判定口径。
    """
    return bool(os.environ.get("COSIGHTBOT_EMBEDDING_API_URL"))


def ensure_ready(lancedb_dir: Path, source_dir: Path = None):
    """P0：若 status 非 ready 但已有可问答内容则置 ready。

    ready 语义从"全部完成"改为"有可问答内容"：逐文件流水线每文件入库成功后调用，
    让首个成功文件即使其余仍在处理/失败也能被 overview_resolver 暴露、可问答。
    已是 ready 则 no-op。

    产物要求按向量入库是否配置分两种口径（design prod-outside §4.3 方案 A）：
    - 已配置 COSIGHTBOT_EMBEDDING_API_URL：要求 overview.md + nodes.lance 同时存在（原语义）；
    - 未配置（向量入库整体跳过，nodes.lance 永远不会创建）：只要求 overview.md 存在，
      否则从零构建会永远卡在 initializing，三步法就绪门禁被卡死。
    """
    try:
        status_file = _get_status_file(lancedb_dir)
        if not status_file.exists():
            return
        with open(status_file, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if data.get("status") == "ready":
            return
        artifacts_ready = (lancedb_dir / "overview.md").exists() and (
            not _embedding_configured() or (lancedb_dir / "nodes.lance").exists()
        )
        if artifacts_ready:
            _update_status(lancedb_dir, "ready", source_dir=source_dir)
    except Exception as e:
        logger.warning(f"Index API: ensure_ready failed in {lancedb_dir.name}: {e}")


def _get_status_file(lancedb_dir: Path) -> Path:
    return lancedb_dir / STATUS_FILE


def _save_status_data(lancedb_dir: Path, data: dict):
    """私有辅助函数：原子写完整状态数据（P1-4）。"""
    status_file = _get_status_file(lancedb_dir)
    _atomic_write_json(status_file, data)


def update_file_info(lancedb_dir: Path, rel_path: str, file_info: dict):
    """更新单个文件的指纹和处理状态。

    file_info 结构: {"mtime": float, "size": int, "status": "success"|"failed", "error": ""}
    """
    try:
        lancedb_dir.mkdir(parents=True, exist_ok=True)
        data = get_full_status_data(lancedb_dir)

        files = data.setdefault("files", {})
        # 统一路径格式为 /
        std_rel = rel_path.replace("\\", "/")
        files[std_rel] = file_info

        _save_status_data(lancedb_dir, data)

        # 增量/会话级路径不会调 _update_status（handler.py 注明"增量更新路径无
        # _update_status 调用"），状态文件只有 files、顶层 status 缺失，会被
        # 启动清理逻辑误判为"被终止的构建"而删除整个
        # lancedb + pre-processed 目录，导致每次重启都把已处理文档全量重预处理。
        # 成功指纹落盘时若可查询产物（overview.md + nodes.lance）已齐备，
        # 顺势把顶层 status 自愈为 ready。ensure_ready 内部对产物不齐备 /
        # 已是 ready 的情况均为 no-op，重复调用无副作用。
        if isinstance(file_info, dict) and file_info.get("status") == "success":
            ensure_ready(lancedb_dir)
    except Exception as e:
        logger.error(f"Index API: Failed to update file info for {rel_path}: {e}")


def remove_file_info(lancedb_dir: Path, rel_path: str):
    """从状态表中彻底移除单个文件的记录。"""
    try:
        data = get_full_status_data(lancedb_dir)
        files = data.get("files", {})
        std_rel = rel_path.replace("\\", "/")
        if std_rel in files:
            del files[std_rel]
            _save_status_data(lancedb_dir, data)
            logger.info(f"Index API: Removed file info for {std_rel}")
            return True
    except Exception as e:
        logger.error(f"Index API: Failed to remove file info for {rel_path}: {e}")
    return False


def remove_directory_info(lancedb_dir: Path, dir_rel_path: str):
    """批量移除指定目录下所有文件的指纹记录。"""
    try:
        data = get_full_status_data(lancedb_dir)
        files = data.get("files", {})
        if not files:
            return 0

        std_dir = dir_rel_path.replace("\\", "/").rstrip("/") + "/"
        keys_to_del = [k for k in files if k.startswith(std_dir)]

        if keys_to_del:
            for k in keys_to_del:
                del files[k]
            _save_status_data(lancedb_dir, data)
            logger.info(f"Index API: Removed {len(keys_to_del)} file records for directory {dir_rel_path}")
            return len(keys_to_del)
    except Exception as e:
        logger.error(f"Index API: Failed to remove directory info for {dir_rel_path}: {e}")
    return 0


def get_all_file_info(lancedb_dir: Path) -> dict:
    """获取指定数据库目录下所有已记录的文件信息。"""
    status_file = _get_status_file(lancedb_dir)
    if not status_file.exists():
        return {}
    try:
        with open(status_file, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
            return data.get("files", {})
    except Exception:
        return {}


def get_full_status_data(lancedb_dir: Path) -> dict:
    """获取完整的状态数据字典。"""
    status_file = _get_status_file(lancedb_dir)
    if not status_file.exists():
        return {}
    try:
        with open(status_file, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def get_status(material_source_dir: Path, agent_id: str) -> str:
    _, lancedb_dir = _get_dirs(material_source_dir, agent_id)
    if not lancedb_dir:
        return "none"
    status_file = lancedb_dir / STATUS_FILE
    if not status_file.exists():
        return "none"
    try:
        with open(status_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("status", "none")
    except Exception as e:
        logger.warning(f"Index API: Failed to read status file: {e}")
        return "failed"


def forget_project(agent_id: str):
    """
    清除与该 agent 关联的 LlamaIndex 内存缓存。
    """
    logger.info(f"Index API: forget_project agent={agent_id}")
    try:
        from file_watcher.search import clear_cache
        clear_cache(agent_id)
    except Exception as e:
        logger.warning(f"Index API: Error clearing cache for {agent_id}: {e}")


def wipe_project(agent_id: str, material_source_dir: Path | None = None):
    """
    彻底清空 agent 关联的 lancedb 索引目录（所有表 + pre-processed 缓存 + 状态文件）。

    与 forget_project 的区别：forget_project 只清内存缓存；wipe_project 真删磁盘数据。

    Args:
        agent_id: 智能体 ID。
        material_source_dir: 绑定的源目录。可选：传了就顺手按 lancedb_dir 定位；
            不传则只清内存 cache + 状态文件（不删 lancedb 磁盘文件）。
    """
    logger.info(f"Index API: wipe_project agent={agent_id} dir={material_source_dir}")

    # 1. 清内存缓存（query engine + route_key 锁等）
    try:
        from file_watcher.search import clear_cache
        clear_cache(agent_id)
    except Exception as e:
        logger.warning(f"Index API: wipe_project clear_cache error: {e}")

    if material_source_dir is None:
        return

    # 2. 解析 lancedb 与 pre-processed 目录
    try:
        from file_watcher.config import get_llamaindex_storage_dirs
        pre_dir, lan_dir = get_llamaindex_storage_dirs(material_source_dir, agent_id)
    except Exception as e:
        logger.warning(f"Index API: wipe_project resolve storage dirs error: {e}")
        return

    if not lan_dir:
        return

    # 3. 真正清 lancedb 表（drop_table chapters/nodes + 清目录）
    try:
        import lancedb
        if lan_dir.exists():
            db = lancedb.connect(str(lan_dir))
            table_names = []
            try:
                tables = db.list_tables()
                table_names = list(tables.tables if hasattr(tables, "tables") else tables)
            except Exception:
                pass
            for tbl_name in table_names:
                try:
                    db.drop_table(tbl_name)
                    logger.info(f"Index API: wipe_project dropped table {tbl_name} in {lan_dir.name}")
                except Exception as e:
                    logger.warning(f"Index API: wipe_project drop_table({tbl_name}) error: {e}")
    except Exception as e:
        logger.warning(f"Index API: wipe_project lancedb cleanup error: {e}")

    # 4. 清 pre-processed 目录（lancedb 已经 drop_table，pre_dir 的 .md 也该清掉，避免 fingerprint 误判）
    if pre_dir and pre_dir.exists():
        try:
            import shutil
            shutil.rmtree(pre_dir, ignore_errors=True)
            logger.info(f"Index API: wipe_project removed pre_dir {pre_dir}")
        except Exception as e:
            logger.warning(f"Index API: wipe_project rmtree pre_dir error: {e}")

    # 5. 重写 .llamaindex_status 为 {status: ready, files: {}}，让后续 scan 看到一致状态
    try:
        lan_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "status": "ready",
            "error": None,
            "timestamp": time.time(),
            "v": 1,
            "files": {},
        }
        if material_source_dir:
            data["source_dir"] = Path(material_source_dir).expanduser().resolve().as_posix()
        status_file = _get_status_file(lan_dir)
        with open(status_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Index API: wipe_project rewrote status file {status_file}")
    except Exception as e:
        logger.warning(f"Index API: wipe_project status rewrite error: {e}")
