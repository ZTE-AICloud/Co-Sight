"""查询结果的保留期清理。

``t2s_query_run`` 保存的是「历史解释」：问题、版本、SQL、校验、耗时都不可变。
但 ``result_snapshot``（结果预览）只是给人看一眼的，长期留着既占空间也放大了
数据暴露面。这里按 ``RKB_TEXT2SQL_RESULT_RETENTION_DAYS``（默认 30，0 表示不清理）
定期把过期预览清空，运行记录本身保留。
"""

from __future__ import annotations

import os
import threading
from typing import Optional

from infrastructure.logging.logutil import log

DEFAULT_RETENTION_DAYS = 30
DEFAULT_INTERVAL_SECONDS = 3600

_stop = threading.Event()
_thread: Optional[threading.Thread] = None


def retention_days() -> int:
    raw = os.environ.get('RKB_TEXT2SQL_RESULT_RETENTION_DAYS', '').strip()
    if not raw:
        return DEFAULT_RETENTION_DAYS
    try:
        return max(int(raw), 0)
    except ValueError:
        log.warning('RKB_TEXT2SQL_RESULT_RETENTION_DAYS=%r 不是整数，用默认值', raw)
        return DEFAULT_RETENTION_DAYS


def purge_once() -> int:
    """执行一次清理；失败只记日志，不影响服务。"""
    if retention_days() <= 0:
        return 0
    from text_to_sql import query_repository

    try:
        removed = query_repository.purge_expired_results()
    except Exception:                                      # noqa: BLE001
        log.warning('text2sql 结果保留期清理失败', exc_info=True)
        return 0
    if removed:
        log.info('text2sql 清理过期结果预览 %s 条', removed)
    return removed


def _loop(interval: int) -> None:
    while not _stop.wait(interval):
        purge_once()


def start() -> None:
    global _thread
    if retention_days() <= 0 or (_thread and _thread.is_alive()):
        return
    interval = int(os.environ.get('RKB_TEXT2SQL_RETENTION_INTERVAL_SECONDS')
                   or DEFAULT_INTERVAL_SECONDS)
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(max(interval, 60),),
                               name='text2sql-retention', daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
