"""
历史应答标书处理器。

确定性 pandas/openpyxl 解析（列约定见 docs/soc-kb-format.md，零兜底——
表头不匹配即报错，不猜不编）。
"""
import os
import json
import uuid
import re
import shutil
import threading
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
import sys
from filelock import FileLock


from common.soc_vector_paths import HISTORICAL_RESPONSES_DIR, cosight_state_root
from watch_dog.file_watcher.embedding_model import EmbeddingServiceError
from watch_dog.file_watcher.search import optimize_table

logger = logging.getLogger("soc_rag.historical_processor")

# 历史应答状态文件名（与公共 index_api 统一使用 .llamaindex_status，各 lancedb_dir 互不干扰）
HISTORICAL_STATUS_FILE = ".llamaindex_status"


def _get_ipc_lock(lancedb_dir: Path) -> FileLock:
    """获取跨进程文件锁，保护历史应答数据库的并发写入"""
    lancedb_dir.mkdir(parents=True, exist_ok=True)
    return FileLock(str(lancedb_dir / ".historical_db_write.lock"))


# ---------------------------------------------------------------------------
# 状态管理
# ---------------------------------------------------------------------------

def _update_historical_status(lancedb_dir: Path, status: str, source_dir: Path = None, error: str = None):
    try:
        lancedb_dir.mkdir(parents=True, exist_ok=True)
        status_file = lancedb_dir / HISTORICAL_STATUS_FILE

        # 尝试读取现有数据，避免抹除 files 字典
        data = {}
        if status_file.exists():
            try:
                with open(status_file, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
            except Exception:
                pass

        data.update({
            "status": status,
            "error": error,
            "timestamp": time.time(),
            "v": 1
        })

        if source_dir:
            data["source_dir"] = str(source_dir.expanduser().resolve())

        with open(status_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"Historical: Updated status to '{status}' in {lancedb_dir.name}")
    except Exception as e:
        logger.error(f"Historical: Failed to update status: {e}")


def get_historical_status(lancedb_dir: Path) -> str:
    status_file = lancedb_dir / HISTORICAL_STATUS_FILE
    if not status_file.exists():
        return "none"
    try:
        with open(status_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("status", "none")
    except Exception as e:
        logger.warning(f"Historical: Failed to read status file: {e}")
        return "failed"


# ---------------------------------------------------------------------------
# Excel 解析
# ---------------------------------------------------------------------------

def _clean_cell(value: object) -> str:
    """单元格清洗：None / pandas NaN → ""；其余转字符串去空白。"""
    if value is None:
        return ""
    if isinstance(value, float) and value != value:  # NaN（pandas 空单元格）
        return ""
    return str(value).strip()


def _normalize_compliance(raw: object) -> "str | None":
    """合规值归一到 FC/PC/NC/None。

    规则（与 docs/soc-kb-format.md 约定一致）：
      - 已是 FC/PC/NC（大小写不敏感）→ 原样大写返回
      - "Complied" / "Y" / "Yes" / "满足" / "完全满足" → FC
      - "Partial Complied" / "Partial" / "P" / "部分满足" → PC
      - "Not Complied" / "N" / "No" / "不满足" → NC
      - 空值或无法识别 → None
    """
    text = _clean_cell(raw)
    if not text:
        return None
    upper = text.upper()
    if upper in ("FC", "PC", "NC"):
        return upper
    if upper in ("COMPLIED", "Y", "YES", "FULLY COMPLIANT") or text in ("满足", "完全满足"):
        return "FC"
    if upper in ("PARTIAL COMPLIED", "PARTIAL", "PARTIALLY COMPLIED", "P") or text == "部分满足":
        return "PC"
    if upper in ("NOT COMPLIED", "N", "NO", "NON-COMPLIANT") or text == "不满足":
        return "NC"
    return None


# 列名别名表（小写归一后匹配）：历史应答文件的表头约定
_COLUMN_ALIASES = {
    "requirement": {
        "需求", "需求描述", "要求", "需求/要求", "requirement", "requirements",
        "demand", "requirement description", "description",
    },
    "no": {"编号", "序号", "no", "no.", "number", "item", "item no", "id"},
    "compliance": {"合规", "合规性", "应答", "compliance", "comply", "应答情况"},
    "remarks": {"备注", "说明", "备注/说明", "remarks", "remark", "note", "notes", "comment"},
    "reference_document": {
        "参考文档", "参考文件", "参考资料", "reference", "reference_document",
        "reference document", "reference doc", "ref",
    },
}


def _match_header_row(values: list[list], max_scan_rows: int = 10) -> "tuple[int, dict[str, int]] | None":
    """在前 N 行里找表头行：命中 requirement 别名的行。

    返回 (表头行索引, {字段: 列索引})；未命中返回 None。
    """
    for row_idx, row in enumerate(values[:max_scan_rows]):
        mapping: dict[str, int] = {}
        for col_idx, cell in enumerate(row):
            name = str(cell or "").strip().lower()
            if not name:
                continue
            for field, aliases in _COLUMN_ALIASES.items():
                if field not in mapping and name in aliases:
                    mapping[field] = col_idx
        if "requirement" in mapping:
            return row_idx, mapping
    return None


def _read_sheet_values(file_path: Path) -> "list[tuple[str, list[list]]]":
    """读出所有 sheet 的单元格矩阵：[(sheet_name, rows)]。xlsx/xlsm/xls/csv。"""
    ext = file_path.suffix.lower()
    if ext == ".csv":
        import csv
        for enc in ("utf-8-sig", "gbk", "latin-1"):
            try:
                with open(file_path, newline="", encoding=enc) as f:
                    rows = [list(r) for r in csv.reader(f)]
                return [("Sheet1", rows)]
            except UnicodeDecodeError:
                continue
        raise ValueError(f"CSV 编码无法识别: {file_path.name}")
    if ext in (".xlsx", ".xlsm", ".xls"):
        import pandas as pd
        sheets = pd.read_excel(
            file_path, sheet_name=None, header=None, dtype=object,
        )
        return [(name, df.values.tolist()) for name, df in sheets.items()]
    raise ValueError(f"不支持的历史应答文件类型: {file_path.name}（仅 xlsx/xlsm/xls/csv）")


def parse_historical_file(file_path: Path, workspace_root: Path = None) -> List[Dict[str, Any]]:
    """解析历史应答 Excel/CSV，提取应答条目列表（确定性解析，零兜底）。

    列约定（表头别名见 _COLUMN_ALIASES，docs/soc-kb-format.md 有完整说明）：
      - 必需：需求列（requirement）
      - 可选：编号 / 合规（FC/PC/NC 归一）/ 备注 / 参考文档
    每个 sheet 独立探测表头（前 10 行内含"需求"列即视为应答 sheet），
    无表头的 sheet 跳过；全部 sheet 均无表头 → ValueError（不猜不编）。

    Args:
        file_path: 历史应答文件（xlsx/xlsm/xls/csv）
        workspace_root: 保留参数（调用方约束），本实现忽略。

    Returns:
        条目列表，每项含 sheet/row/no/requirement/compliance/remarks/
        reference_document + source_file/source_path。
    """
    sheets = _read_sheet_values(file_path)
    items: List[Dict[str, Any]] = []
    for sheet_name, values in sheets:
        found = _match_header_row(values)
        if not found:
            continue
        header_idx, mapping = found
        req_col = mapping["requirement"]
        for row_idx in range(header_idx + 1, len(values)):
            row = values[row_idx]
            if req_col >= len(row):
                continue
            requirement = _clean_cell(row[req_col])
            if not requirement:
                continue

            def _cell(field: str) -> str:
                col = mapping.get(field)
                if col is None or col >= len(row):
                    return ""
                return _clean_cell(row[col])

            items.append({
                "sheet": sheet_name,
                "row": row_idx + 1,  # 1-based，对齐 Excel 行号
                "no": _cell("no"),
                "requirement": requirement,
                "compliance": _normalize_compliance(_cell("compliance")),
                "remarks": _cell("remarks"),
                "reference_document": _cell("reference_document"),
            })

    if not items:
        raise ValueError(
            f"未在 {file_path.name} 的任何 sheet 中找到应答表头"
            f"（需要包含「需求」列；列约定见 docs/soc-kb-format.md）"
        )

    for item in items:
        item["source_file"] = file_path.name
        item["source_path"] = str(file_path)
    return items



# ---------------------------------------------------------------------------
# LanceDB 操作
# ---------------------------------------------------------------------------

try:
    import lancedb
except ImportError:
    lancedb = None

def _check_table_exists(db, table_name: str) -> bool:
    """动态检查表是否存在，兼容不同版本的 LanceDB API"""
    try:
        tables = db.list_tables()
        if hasattr(tables, "tables"):
            return table_name in tables.tables
        return table_name in tables
    except Exception:
        try:
            return table_name in db.table_names()
        except Exception:
            return False

def _safe_delete_by_source_path(table, source_path: str) -> bool:
    """安全删除指定 source_path 的记录。"""
    try:
        safe_path = source_path.replace("'", "''")
        table.delete(f"source_path = '{safe_path}'")
        return True
    except Exception as e:
        logger.error(f"Failed to delete records for {source_path}: {e}")
        return False


def _safe_delete_by_source_prefix(table, source_path: str) -> bool:
    """删除指定 source_path 的精确匹配记录及其所有子路径记录（用于文件夹删除场景）。"""
    try:
        safe_path = source_path.replace("'", "''")
        expr = f"source_path = '{safe_path}' OR source_path LIKE '{safe_path}/%'"
        table.delete(expr)
        return True
    except Exception as e:
        logger.error(f"Failed to delete records by prefix for {source_path}: {e}")
        return False


# ---------------------------------------------------------------------------
# 事件处理（核心入口）
# ---------------------------------------------------------------------------

def handle_historical_file_event(
    src_path: str,
    event_type: str,
    dest_path: str,
    lancedb_dir: Path,
    workspace_root: Path = None,
) -> bool:
    """处理单个历史应答文件事件（created/modified/deleted/moved）。

    Returns True if the file was processed successfully (or skipped because
    fingerprint-matched / not applicable), False if processing failed.
    """
    from watch_dog.file_watcher.progress_ui import global_progress

    src_p = Path(src_path)
    dest_p = Path(dest_path) if dest_path else None

    # 确定用于判断属性的有效路径（如果是移动，则看目标路径）
    active_p = dest_p if (event_type == "moved" and dest_p) else src_p
    filename = active_p.name

    # 基础过滤（在 start_processing 之前执行，避免被过滤的事件污染进度计数器）
    is_excel = active_p.suffix.lower() in ('.xlsx', '.csv')
    is_temp = filename.startswith("~$")

    # deleted 事件始终放行（需要清理数据库记录，不论文件后缀）
    if event_type == "deleted":
        if is_temp:
            return True
    elif not is_excel or is_temp:
        return True

    if not lancedb:
        logger.warning("lancedb not installed, skipping historical paradigm learning.")
        return True

    global_progress.start_processing(filename)

    task_failed = False
    error_msg = ""

    try:

        # 2. workspace_root 即 hist_dir (= source_dir / 02_Historical_Responses)，
        # rel = file.relative_to(workspace_root) 即去掉 hist_dir 前缀的 POSIX 路径。
        # 任何 file 不在 workspace_root 下时返回 None，caller 直接跳过。
        def _get_rel_path(p: Path) -> Optional[str]:
            if not workspace_root:
                return None
            try:
                # 强制转为绝对路径再求相对，避免 Windows 盘符大小写或长短路径干扰
                abs_p = p.expanduser().resolve()
                abs_root = workspace_root.expanduser().resolve()
                return abs_p.relative_to(abs_root).as_posix()
            except ValueError:
                return None

        rel_path = _get_rel_path(active_p)
        if rel_path is None:
            logger.debug(f"Historical: Skipping path not under workspace_root: {active_p}")
            return

        logger.info(f"Historical Response Event: {event_type} on {filename} (rel={rel_path})")
        table_name = "response_paradigm"

        try:
            db = lancedb.connect(str(lancedb_dir))
        except Exception as e:
            logger.error(f"Failed to connect to LanceDB at {lancedb_dir}: {e}")
            return

        # ========== deleted ==========
        if event_type == "deleted":
            with _get_ipc_lock(lancedb_dir):
                if _check_table_exists(db, table_name):
                    table = db.open_table(table_name)
                    posix_path = src_p.expanduser().resolve().as_posix()
                    if _safe_delete_by_source_prefix(table, posix_path):
                        logger.info(f"Deleted historical paradigms for {posix_path} (including children)")
                        optimize_table(lancedb_dir, table_name)

            # 清理 JSON 指纹（同时清理单文件和目录下所有子文件的指纹）
            # 直接调 index_api：本文件仅在 build_soc_vector.py 独立脚本上下文里运行，
            # 无进程间 IPC 通道。
            try:
                from common.index_api import remove_file_info, remove_directory_info
                rel_path = _get_rel_path(src_p)
                if rel_path is not None:
                    remove_file_info(lancedb_dir, rel_path)
                    remove_directory_info(lancedb_dir, rel_path)
            except Exception as e:
                logger.warning(f"Failed to remove historical fingerprint: {e}")
            return

        # ========== moved ==========
        if event_type == "moved" and dest_p:
            with _get_ipc_lock(lancedb_dir):
                if _check_table_exists(db, table_name):
                    table = db.open_table(table_name)
                    posix_old = src_p.expanduser().resolve().as_posix()
                    if _safe_delete_by_source_prefix(table, posix_old):
                        logger.info(f"Deleted old records for moved file {posix_old} (including children)")
                        optimize_table(lancedb_dir, table_name)

            # 清理旧 JSON 指纹（同时清理单文件和目录下所有子文件的指纹）
            try:
                from common.index_api import remove_file_info, remove_directory_info
                rel_old = _get_rel_path(src_p)
                if rel_old is not None:
                    remove_file_info(lancedb_dir, rel_old)
                    remove_directory_info(lancedb_dir, rel_old)
            except Exception as e:
                logger.warning(f"Failed to remove old historical fingerprint: {e}")

            if _get_rel_path(dest_p) is None or dest_p.suffix.lower() not in ('.xlsx', '.csv'):
                logger.info(f"File moved out of monitored directory: {dest_p}")
                return
            src_p = dest_p
            logger.info(f"File moved within directory, will re-parse: {src_p}")

        # ========== created / modified / moved(目录内) ==========
        if event_type in ("created", "modified", "moved"):
            if not src_p.exists():
                return

            # --- 指纹校验：如果内容未变，跳过昂贵的 AI 解析 ---
            rel_path = _get_rel_path(src_p)
            if rel_path is None:
                logger.warning(f"Historical: file not under workspace_root, will re-parse: {src_p}")
            try:
                from common.index_api import get_all_file_info
                all_info = get_all_file_info(lancedb_dir)
                old_info = all_info.get(rel_path)
                if old_info and old_info.get("status") == "success":
                    stat = src_p.stat()
                    current_hash = _calculate_file_hash(src_p)

                    # 匹配逻辑：(mtime一致 且 size一致) OR (hash一致 且 size一致)
                    mtime_match = abs(old_info.get("mtime", 0) - stat.st_mtime) < 0.1
                    size_match = old_info.get("size") == stat.st_size
                    hash_match = current_hash and old_info.get("hash") == current_hash

                    if (mtime_match and size_match) or (hash_match and size_match):
                        logger.info(f"Historical Watchdog: [SKIP] Content/Fingerprint match for {rel_path}")
                        global_progress.finish_processing(filename)
                        return
            except Exception as e:
                logger.warning(f"Historical: Failed to check fingerprint: {e}")

            # 1. 推断 agent_id（从 lancedb_dir 路径中提取）
            agent_id = _extract_agent_id_from_lancedb_dir(lancedb_dir)

            # 2. 解析文件（先解析，成功后再删旧记录，避免解析失败导致数据丢失）
            t0 = time.perf_counter()
            items = parse_historical_file(src_p)
            parse_time = time.perf_counter() - t0
            logger.info(f"Extracted {len(items)} items from {src_p.name} in {parse_time:.2f}s")

            if not items:
                task_failed = True
                error_msg = f"未能提取到历史应答内容 (耗时 {parse_time:.2f}s)"
                return

            # 5. 解析成功，删除该文件的旧记录（延迟到写入锁中执行）

            # 6. 生成向量 (分片请求，防止大文件导致 API 超时)
            from watch_dog.file_watcher.embedding_model import OnlineBGEEmbedding
            texts = [i["requirement"] for i in items]
            embed_model = OnlineBGEEmbedding()
            vectors = []
            chunk_size = 100  # 每 100 条请求一次，平衡速度与稳定性

            logger.info(f"Generating embeddings for {len(texts)} items in chunks of {chunk_size}...")
            try:
                for i in range(0, len(texts), chunk_size):
                    chunk = texts[i:i + chunk_size]
                    chunk_vectors = embed_model._get_text_embeddings(chunk)
                    vectors.extend(chunk_vectors)
                    logger.debug(f"Progress: {len(vectors)}/{len(texts)} embeddings generated")
            except EmbeddingServiceError as e:
                task_failed = True
                error_msg = f"生成向量失败: {str(e)}"
                logger.error(f"Failed to get embeddings: {e}")
                raise
            except Exception as e:
                task_failed = True
                error_msg = f"生成向量失败: {str(e)}"
                logger.error(f"Failed to get embeddings: {e}")
                return

            # 7. 构建记录
            to_insert = []
            # 统一使用绝对 POSIX 路径，与普通索引保持一致
            source_path = src_p.expanduser().resolve().as_posix()
            for i, item in enumerate(items):
                to_insert.append({
                    "id": str(uuid.uuid4()),
                    "description": item["requirement"],
                    "compliance": item["compliance"],
                    "remarks": item["remarks"],
                    "reference_document": item["reference_document"],
                    "semantic_vector": vectors[i],
                    "reviewed": True,
                    "created_at": datetime.now().isoformat(),
                    "source_file": src_p.name,
                    "source_path": source_path,
                })

            # 8. 入库（带跨进程锁执行）
            if to_insert:
                with _get_ipc_lock(lancedb_dir):
                    table_exists_now = _check_table_exists(db, table_name)

                    if table_exists_now:
                        table = db.open_table(table_name)
                        # 先清理旧记录 (使用 POSIX 路径)
                        if _safe_delete_by_source_path(table, source_path):
                            logger.info(f"Cleared old records for {source_path}")

                        table.add(to_insert)
                    else:
                        db.create_table(table_name, data=to_insert)

                    optimize_table(lancedb_dir, table_name)
                    logger.info(
                        f"Inserted {len(to_insert)} records for {src_p} "
                        f"(total time: {time.perf_counter() - t0:.2f}s)"
                    )

                # 成功后写入指纹（直接调 index_api，独立脚本下也生效）
                try:
                    from common.index_api import update_file_info
                    rel_path = _get_rel_path(src_p)
                    if rel_path is None:
                        logger.warning(f"Historical: skipping fingerprint, file not under workspace_root: {src_p}")
                    else:
                        stat = src_p.stat()
                        update_file_info(lancedb_dir, rel_path, {
                            "mtime": stat.st_mtime,
                            "size": stat.st_size,
                            "hash": _calculate_file_hash(src_p),
                            "status": "success",
                            "error": ""
                        })
                except Exception as e:
                    logger.warning(f"Failed to report historical fingerprint: {e}")

    except EmbeddingServiceError as e:
        task_failed = True
        error_msg = f"向量模型调用失败: {str(e)}"
        logger.error(f"Historical embedding failed for {filename}: {e}", exc_info=True)
        raise
    except Exception as e:
        task_failed = True
        error_msg = f"历史应答解析异常: {str(e)}"
        logger.error(f"Historical processing failed for {filename}: {e}", exc_info=True)
        # 失败上报
        try:
            from common.index_api import update_file_info
            rel_path = _get_rel_path(src_p)
            if rel_path is not None:
                update_file_info(lancedb_dir, rel_path, {
                    "mtime": 0,
                    "size": 0,
                    "status": "failed",
                    "error": str(e)
                })
        except Exception:
            pass
    finally:
        if task_failed:
            global_progress.fail_processing(filename, src_path, error_msg)
        else:
            global_progress.finish_processing(filename)

    return not task_failed

    
import hashlib

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


def _is_historical_fingerprint_match(file_path: Path, workspace_root: Path, recorded_files: dict) -> bool:
    """判断历史应答文件 (xlsx/csv) 是否与上次成功解析的记录指纹一致。

    workspace_root 即 hist_dir（= source_dir / 02_Historical_Responses），rel = file.relative_to(workspace_root) 即去掉 hist_dir 前缀的 POSIX 路径（不再带 02_Historical_Responses/ 前缀，与 common handler 的 specs_pd_dir 用法对称）。

    匹配条件：
      - recorded_files 中存在该文件的 POSIX 相对路径条目，且 status == "success"
      - size 相等，且 (mtime 接近 或 md5 hash 相等)

    用于在批量派发 AI 解析前快速跳过未变更文件，避免对稳定文件重复调用解析流程。
    """
    if not recorded_files:
        return False
    try:
        if workspace_root:
            abs_file = file_path.expanduser().resolve()
            abs_root = workspace_root.expanduser().resolve()
            rel_path = abs_file.relative_to(abs_root).as_posix()
        else:
            rel_path = file_path.name
    except (ValueError, OSError):
        return False
    info = recorded_files.get(rel_path)
    if not info or info.get("status") != "success":
        return False
    try:
        stat = file_path.stat()
    except OSError:
        return False
    # 匹配逻辑：(mtime一致 且 size一致) OR (hash一致 且 size一致)
    mtime_match = abs(info.get("mtime", 0) - stat.st_mtime) < 0.1
    size_match = info.get("size") == stat.st_size
    current_hash = _calculate_file_hash(file_path) if not mtime_match else ""
    hash_match = bool(current_hash) and info.get("hash") == current_hash
    return (mtime_match and size_match) or (hash_match and size_match)

def _extract_agent_id_from_lancedb_dir(lancedb_dir: Path) -> str:
    """从 lancedb_dir 路径中提取 agent_id。

    预期路径格式: <state_root>/workspace-{agent_id}/llamaindex_data/lancedb/historical_paradigms
    （state_root = 工作目录下 data/，COSIGHTBOT_HOME 可覆盖）
    """
    for part in lancedb_dir.parts:
        if part.startswith("workspace-"):
            return part[len("workspace-"):]
    return ""


# ---------------------------------------------------------------------------
# 批量任务
# ---------------------------------------------------------------------------

_historical_task_running = False
_historical_task_lock = threading.Lock()


def run_historical_batch(material_source_dir: Path, agent_id: str):
    """扫描 02_Historical_Responses/ 下所有 xlsx/csv，逐文件处理。

    优化：派发前按 size + (mtime 或 md5) 指纹快速跳过未变更文件，
    避免对稳定文件重复调用昂贵的 AI 解析流程。
    """
    global _historical_task_running

    with _historical_task_lock:
        if _historical_task_running:
            logger.info("Historical: Another batch task is already running, skipping.")
            return
        _historical_task_running = True

    try:
        hist_dir = material_source_dir / HISTORICAL_RESPONSES_DIR
        if not hist_dir.exists() or not hist_dir.is_dir():
            with _historical_task_lock:
                _historical_task_running = False
            return

        logger.info(f"Historical: Starting batch processing in {hist_dir}")

        from common.soc_vector_paths import soc_historical_lancedb_dir
        lancedb_root = soc_historical_lancedb_dir(agent_id)
        lancedb_root.mkdir(parents=True, exist_ok=True)

        # 在覆盖为 "initializing" 之前读取旧状态，用于指纹预过滤
        prior_status_data = {}
        try:
            from common.index_api import get_full_status_data as _get_full_status_data
            prior_status_data = _get_full_status_data(lancedb_root)
        except Exception as e:
            logger.warning(f"Historical: Failed to load prior status data: {e}")

        recorded_files = None
        if (prior_status_data
                and prior_status_data.get("status") == "ready"
                and isinstance(prior_status_data.get("files"), dict)):
            recorded_files = prior_status_data["files"]

        _update_historical_status(lancedb_root, "initializing", source_dir=material_source_dir)

        files = [
            f for f in hist_dir.iterdir()
            if f.is_file() and f.suffix.lower() in ['.xlsx', '.csv'] and not f.name.startswith("~$")
        ]
        if not files:
            _update_historical_status(lancedb_root, "ready", source_dir=material_source_dir)
            with _historical_task_lock:
                _historical_task_running = False
            return

        # 指纹预过滤：仅保留变更或新增的文件
        # workspace_root = hist_dir（不再是 material_source_dir），key 不再带
        # 02_Historical_Responses/ 前缀，与 common handler 的 specs_pd_dir 用法对称。
        if recorded_files:
            to_process = []
            skipped = 0
            for f in files:
                if _is_historical_fingerprint_match(f, hist_dir, recorded_files):
                    skipped += 1
                else:
                    to_process.append(f)
            logger.info(
                f"Historical: fingerprint pre-filter: {len(to_process)}/{len(files)} to process, "
                f"{skipped} skipped (unchanged)."
            )
            files = to_process

        if not files:
            # 所有文件指纹匹配，无需调用 AI
            _update_historical_status(lancedb_root, "ready", source_dir=material_source_dir)
            logger.info("Historical: All files fingerprint-matched, nothing to do.")
            with _historical_task_lock:
                _historical_task_running = False
            return

        from watch_dog.file_watcher.progress_ui import global_progress
        global_progress.add_waiting(len(files))

        logger.info(f"Historical: Processing {len(files)} files...")

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="hist-batch") as executor:
            for f in files:
                executor.submit(
                    handle_historical_file_event,
                    str(f), "created", None, lancedb_root, workspace_root=hist_dir
                )

        # 批量构建结束后，强制对该库进行一次最终的优化清理
        try:
            from watch_dog.file_watcher.search import optimize_table
            optimize_table(lancedb_root, "response_paradigm")
        except Exception as oe:
            logger.warning(f"Historical: Failed to optimize table after batch run: {oe}")

        _update_historical_status(lancedb_root, "ready", source_dir=material_source_dir)
        logger.info(f"Historical: All files processed")
    except Exception as e:
        logger.error(f"Historical: Batch processing failed: {e}", exc_info=True)
        try:
            from common.soc_vector_paths import soc_historical_lancedb_dir
            lancedb_root = soc_historical_lancedb_dir(agent_id)
            _update_historical_status(lancedb_root, "failed", source_dir=material_source_dir, error=str(e))
        except Exception:
            pass
    finally:
        with _historical_task_lock:
            _historical_task_running = False


if __name__ == "__main__":
    # 手工自测：python -m common.soc_kb_builder.vector_build.historical_processor <历史应答.xlsx>
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    if len(sys.argv) < 2:
        print("用法: python -m common.soc_kb_builder.vector_build.historical_processor <历史应答.xlsx|csv>")
        sys.exit(2)
    test_file = Path(sys.argv[1])
    results = parse_historical_file(test_file)
    print(f"提取条目数: {len(results)}")
    for item in results[:2]:
        print(json.dumps(item, ensure_ascii=False, indent=2))
