"""版本构建队列：提交进 ``task_center.task``，由本模块的 worker 认领执行。

为什么不用 ``infrastructure.tasks.TaskEngine``：那个引擎在**注册车道时**就会起
进程内 worker，导入即产生线程——单测会挂住，脚本也停不下来。这里只用它的持久化
原语（``pg_queue`` 的 claim/complete/fail），worker 生命周期由 :func:`start`
显式控制，导入本模块没有任何副作用。

语义与文件导入、图谱抽取一致：``FOR UPDATE SKIP LOCKED`` 认领、租约 + 心跳、
失败按 ``max_attempts`` 重排。构建本身幂等（已 INDEXED 的知识会被跳过），
所以 at-least-once 重跑是安全的。
"""

from __future__ import annotations

import json
import os
import socket
import threading
from typing import Any, Optional
from uuid import uuid4

from infrastructure.db.kb import connection
from infrastructure.logging.logutil import log
from infrastructure.tasks import pg_queue

LANE = 'text2sql_index'
TASK_TYPE = 'T2S_INDEX'
MAX_ATTEMPTS = 2
LEASE_SECONDS = 300
POLL_SECONDS = float(os.environ.get('RKB_TEXT2SQL_QUEUE_POLL_SECONDS') or 2.0)

_stop = threading.Event()
_thread: Optional[threading.Thread] = None


def enabled() -> bool:
    return os.environ.get('RKB_TASK_QUEUE_DB', '1').strip().lower() not in (
        '0', 'false', 'no', 'off')


def enqueue(datasource_id: str, version_id: str) -> str:
    """写一条 PENDING 任务并唤醒同车道的 worker，返回任务 id。"""
    task_id = f't2s-{uuid4().hex}'
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO task_center.task
                    (id, task_type, lane, status, max_attempts, kbase_id, payload)
                VALUES (%s, %s, %s, 'PENDING', %s, %s, %s::jsonb)
                """,
                (task_id, TASK_TYPE, LANE, MAX_ATTEMPTS, datasource_id,
                 json.dumps({'datasourceId': datasource_id,
                             'versionId': version_id}, ensure_ascii=False)))
    pg_queue.notify(LANE)
    return task_id


def worker_id() -> str:
    return f'text2sql-{socket.gethostname()}-{os.getpid()}'


def run_once(worker: Optional[str] = None) -> bool:
    """认领并执行一条任务；没有可执行任务返回 ``False``。"""
    claimed = pg_queue.claim(LANE, [TASK_TYPE], worker or worker_id(),
                             lease_seconds=LEASE_SECONDS)
    if not claimed:
        return False
    _execute(claimed, worker or worker_id())
    return True


def _execute(task: dict[str, Any], worker: str) -> None:
    from text_to_sql.service import get_service

    task_id = str(task.get('id'))
    payload = task.get('payload') or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            payload = {}
    datasource_id = payload.get('datasourceId')
    version_id = payload.get('versionId')
    stopping = threading.Event()

    def heartbeat() -> None:
        while not stopping.wait(LEASE_SECONDS / 3):
            try:
                pg_queue.heartbeat(task_id, worker,
                                   progress=int(task.get('progress') or 0),
                                   lease_seconds=LEASE_SECONDS)
            except Exception:                              # noqa: BLE001
                log.warning('text2sql queue heartbeat failed %s', task_id)

    beat = threading.Thread(target=heartbeat, name=f'{task_id}-heartbeat',
                            daemon=True)
    beat.start()
    try:
        if not datasource_id or not version_id:
            raise ValueError('任务缺少 datasourceId/versionId')
        result = get_service().build_version(datasource_id, version_id)
        pg_queue.complete(task_id, worker, progress=100)
        log.info('text2sql build %s done: %s', task_id, result.get('status'))
    except Exception as error:                             # noqa: BLE001
        log.warning('text2sql build %s failed', task_id, exc_info=True)
        pg_queue.fail(task_id, worker, str(error)[:1000])
    finally:
        stopping.set()


def _loop() -> None:
    while not _stop.wait(POLL_SECONDS):
        try:
            pg_queue.reclaim_expired()
        except Exception:                                  # noqa: BLE001
            log.warning('text2sql queue reclaim failed', exc_info=True)
        try:
            while not _stop.is_set() and run_once():
                continue
        except Exception:                                  # noqa: BLE001
            log.warning('text2sql queue worker loop failed', exc_info=True)
            _stop.wait(POLL_SECONDS)


def start() -> None:
    """启动后台 worker；队列关闭（``RKB_TASK_QUEUE_DB=0``）时为空操作。"""
    global _thread
    if not enabled() or (_thread and _thread.is_alive()):
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name='text2sql-build-queue',
                               daemon=True)
    _thread.start()
    log.info('text2sql build queue worker started: lane=%s', LANE)


def stop() -> None:
    _stop.set()


def status(task_id: str) -> Optional[dict[str, Any]]:
    return pg_queue.get(task_id)


def snapshot() -> dict[str, int]:
    try:
        return pg_queue.count_by_lane(LANE)
    except Exception:                                      # noqa: BLE001
        return {}
