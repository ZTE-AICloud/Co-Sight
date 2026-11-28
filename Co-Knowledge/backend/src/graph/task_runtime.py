"""图谱域的任务车道：抽图与图谱导入。

两条车道刻意分开，且与文件入库队列互不共享 worker：

* 抽图任务是长任务（算子超时 1800s），不能饿死文件入库；
* 图谱导入内部还有 16 路向量化并发，与抽图合并会把总并发砍半。

队列模式由 ``RKB_TASK_QUEUE_DB`` 决定：生产环境用 **DB 队列**
（``FOR UPDATE SKIP LOCKED`` + 租约 + 心跳 + 回收），单测用内存队列。
任务行统一在 ``task_center.task``；状态由领域 ``_run`` 写入
（``status_owner='runner'``），引擎只负责认领/续租/释放。

payload 必须可重建：

* 抽图：``tmpDir`` / ``dto`` / ``schemaObj`` / ``isUpdate`` / ``cacheSchemaId``
* 导入：``kbIndexName`` / ``schemaId`` / ``schemaObj`` / ``zipPath``
"""

from __future__ import annotations

import atexit
import os

from infrastructure.tasks import TaskContext, TaskEngine, TaskKind, TaskRecord

_EXTRACT_LANE = 'graph_extract'
_IMPORT_LANE = 'graph_import'

_QUEUE_DB = os.environ.get('RKB_TASK_QUEUE_DB', '1').strip().lower() not in (
    '0', 'false', 'no', 'off')
_QUEUE_MODE = 'db' if _QUEUE_DB else 'memory'
_LEASE_SECONDS = 120


def _capacity(env_name: str, default: int = 2000) -> int:
    try:
        return max(0, int(os.environ.get(env_name, '') or default))
    except ValueError:
        return default


#: DB 车道的积压上限（PENDING+RETRY）；0 = 不限制。
_EXTRACT_CAPACITY = _capacity('RKB_GRAPH_EXTRACT_CAPACITY')
_IMPORT_CAPACITY = _capacity('RKB_GRAPH_IMPORT_CAPACITY')

_ENGINE = TaskEngine()
_ENGINE.register_lane(_EXTRACT_LANE, workers=5, mode=_QUEUE_MODE,
                      capacity=_EXTRACT_CAPACITY)
_ENGINE.register_lane(_IMPORT_LANE, workers=5, mode=_QUEUE_MODE,
                      capacity=_IMPORT_CAPACITY)


def _cancel_extract(row: dict) -> None:
    """取消排队中的抽图任务：图谱库落「解析失败」，不留永久构建中。"""
    kb_id = row.get('kbase_id')
    if not kb_id:
        return
    from knowledge_base.service import kbase_service as kbase_store

    kbase_store.update_process(kb_id, 101, 100)          # STATUS_PARSING_FAIL
    kbase_store.update_fail_reason(kb_id, '任务已取消', 'Task cancelled')


def _cancel_import(row: dict) -> None:
    """取消排队中的导入任务：图谱库落「入库失败」。"""
    kb_id = row.get('kbase_id')
    if not kb_id:
        return
    from knowledge_base.service import kbase_service as kbase_store

    kbase_store.update_process_with_time(kb_id, '104', 100)  # STATUS_STORING_FAIL
    kbase_store.update_fail_reason(kb_id, '任务已取消', 'Task cancelled')


def ensure_extract_capacity() -> None:
    """建任务行之前调用；队列满时抛 ``TaskRejectedError``。"""
    _ENGINE.ensure_capacity(_EXTRACT_LANE)


def ensure_import_capacity() -> None:
    _ENGINE.ensure_capacity(_IMPORT_LANE)


def _run_extract(record: TaskRecord, ctx: TaskContext) -> None:
    """从持久化 payload 重建抽图执行。"""
    payload = record.payload
    from graph.service import graph_extract_v2_service

    graph_extract_v2_service._run(
        record.task_id,
        payload.get('tmpDir'),
        payload.get('dto') or {},
        payload.get('schemaObj'),
        bool(payload.get('isUpdate')),
        payload.get('cacheSchemaId'),
        payload.get('fileCount'),
    )


def _run_import(record: TaskRecord, ctx: TaskContext) -> None:
    """从持久化 payload 重建图谱导入；zip 放共享卷，崩溃后可重试。"""
    payload = record.payload
    zip_path = payload.get('zipPath')
    try:
        from graph.service import graph_import_engine

        graph_import_engine.import_from_zip(
            payload.get('kbIndexName'),
            payload.get('schemaId'),
            zip_path,
            kbase_schema_obj=payload.get('schemaObj'),
            task_id=record.task_id,
        )
    finally:
        if zip_path:
            # 只删 zip 和它的专用空目录；不要 rmtree 任意父目录（防旧 payload）。
            try:
                os.unlink(zip_path)
            except OSError:
                pass
            try:
                os.rmdir(os.path.dirname(zip_path))
            except OSError:
                pass


_ENGINE.register_kind(
    TaskKind(name=_EXTRACT_LANE, lane=_EXTRACT_LANE, max_attempts=1,
             queue_mode=_QUEUE_MODE, persist_type='GRAPH_EXTRACT',
             status_owner='runner', lease_seconds=_LEASE_SECONDS,
             cancel_hook=_cancel_extract),
    _run_extract)
_ENGINE.register_kind(
    TaskKind(name=_IMPORT_LANE, lane=_IMPORT_LANE, max_attempts=1,
             queue_mode=_QUEUE_MODE, persist_type='GRAPH_IMPORT',
             status_owner='runner', lease_seconds=_LEASE_SECONDS,
             cancel_hook=_cancel_import),
    _run_import)


def start() -> None:
    """启动 DB 车道 + 心跳/回收（内存模式为空操作）。"""
    _ENGINE.start()


def submit_extract(payload: dict, task_id: str) -> str:
    """提交一次抽图执行；任务行已由 ``graph_extract_store.insert_task`` 建好。"""
    return _ENGINE.submit(_EXTRACT_LANE, payload, task_id=task_id,
                          create_row=False)


def submit_update(payload: dict, task_id: str) -> str:
    return _ENGINE.submit(_EXTRACT_LANE, payload, task_id=task_id,
                          create_row=False)


def submit_import(payload: dict, task_id: str) -> str:
    """提交一次图谱包导入；任务行已由 ``graph_import_store.create_task`` 建好。"""
    return _ENGINE.submit(_IMPORT_LANE, payload, task_id=task_id,
                          create_row=False)


def stats() -> dict:
    """两条车道的观测快照。"""
    return _ENGINE.stats()


def shutdown(drain_seconds: float = 0.0) -> None:
    _ENGINE.shutdown(drain_seconds)


atexit.register(shutdown)
