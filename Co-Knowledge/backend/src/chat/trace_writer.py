"""trace 的 best-effort 写入：有界队列 + 单写线程 + 熔断。

为什么不让 `BackgroundTask` 直接写库：Starlette 的 sync background 与 FastAPI 的 sync
handler 共用 anyio 线程池。DB 不可达时，psycopg2 建立连接可能阻塞到 TCP 超时，几个
trace 写入就能把线程池占满，反过来拖慢 `/query`。这里 background 只做 `put_nowait`，
真正 DB I/O 只占一个后台线程；队列满/熔断时直接丢 trace，永不阻塞问答。

进程退出时队列尾部会丢：这是 best-effort 观测数据的已知取舍。
"""
from __future__ import annotations

import os
import queue
import threading
import time
from typing import Any, Dict, Optional

from chat import repository_pg
from chat.trace_state import TraceState
from engine.logutil import logger

QUEUE_MAX = 1000
FAILURE_THRESHOLD = 3
COOLDOWN_SECONDS = 30.0
FULL_LOG_INTERVAL_SECONDS = 60.0

_QUEUE: queue.Queue = queue.Queue(maxsize=QUEUE_MAX)
_WORKER_LOCK = threading.Lock()
_WORKER: Optional[threading.Thread] = None
_STATE_LOCK = threading.Lock()
_CONSECUTIVE_FAILURES = 0
_SKIP_UNTIL = 0.0
_LAST_FULL_LOG = 0.0


def trace_enabled() -> bool:
    """请求时读取开关，便于测试与线上热切换（重启生效）。"""
    value = os.environ.get('RKB_QUERY_TRACE_ENABLED', 'true').strip().lower()
    return value not in ('0', 'false', 'no', 'off')


def enqueue_trace(state: Optional[TraceState]) -> bool:
    """终态收敛后入队；队列满/关闭时不阻塞、返回 False。"""
    if state is None or not trace_enabled():
        return False
    payload = state.snapshot(time.perf_counter())
    _ensure_worker()
    try:
        _QUEUE.put_nowait(payload)
        return True
    except queue.Full:
        _log_full_once()
        return False


def _ensure_worker() -> None:
    global _WORKER
    with _WORKER_LOCK:
        if _WORKER is not None and _WORKER.is_alive():
            return
        _WORKER = threading.Thread(
            target=_worker_loop, name='query-trace-writer', daemon=True)
        _WORKER.start()


def _worker_loop() -> None:
    while True:
        payload = _QUEUE.get()
        try:
            _process_one(payload)
        except Exception:                                           # noqa: BLE001
            logger.exception('[query-trace] writer loop unexpected error')
        finally:
            _QUEUE.task_done()


def _process_one(payload: Dict[str, Any]) -> bool:
    """写一行；连续失败触发短暂熔断，避免 DB 故障时反复重试。"""
    if _is_skipping():
        return False
    ok = False
    try:
        ok = repository_pg.persist_query_trace(payload)
    finally:
        _record_result(ok)
    return ok


def _is_skipping() -> bool:
    with _STATE_LOCK:
        return time.monotonic() < _SKIP_UNTIL


def _record_result(ok: bool) -> None:
    global _CONSECUTIVE_FAILURES, _SKIP_UNTIL
    with _STATE_LOCK:
        if ok:
            _CONSECUTIVE_FAILURES = 0
            _SKIP_UNTIL = 0.0
            return
        _CONSECUTIVE_FAILURES += 1
        if _CONSECUTIVE_FAILURES >= FAILURE_THRESHOLD:
            _SKIP_UNTIL = max(_SKIP_UNTIL, time.monotonic() + COOLDOWN_SECONDS)
            logger.warning('[query-trace] %s consecutive failures, '
                           'pausing writes for %.0fs',
                           _CONSECUTIVE_FAILURES, COOLDOWN_SECONDS)


def _log_full_once() -> None:
    global _LAST_FULL_LOG
    now = time.monotonic()
    with _STATE_LOCK:
        if now - _LAST_FULL_LOG < FULL_LOG_INTERVAL_SECONDS:
            return
        _LAST_FULL_LOG = now
    logger.warning('[query-trace] queue full (%s), dropping trace', QUEUE_MAX)


def _reset_for_tests() -> None:
    """仅测试用：清空计数器/熔断状态（不杀已启动的 daemon 线程）。"""
    global _CONSECUTIVE_FAILURES, _SKIP_UNTIL, _LAST_FULL_LOG
    with _STATE_LOCK:
        _CONSECUTIVE_FAILURES = 0
        _SKIP_UNTIL = 0.0
        _LAST_FULL_LOG = 0.0
