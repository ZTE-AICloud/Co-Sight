"""统一任务引擎：类型注册 + 分车道执行 + 重试/延迟重投 + 关停。

刻意**不**做持久化恢复：现有文件队列与图谱线程池都是「重启不重投」，引擎把这条
语义固化为默认行为。需要恢复能力的任务类型应在领域层单独实现，而不是偷偷改引擎。

延迟重投由独立的调度线程负责 —— worker 失败后只把记录放进调度堆，绝不 ``sleep``，
否则一条 5 秒的重试就会占住一个 worker，批量导入时会把整条车道拖住。
"""

from __future__ import annotations

import heapq
import select
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from infrastructure.logging.logutil import log
from infrastructure.tasks import cancellation, pg_queue, registry
from infrastructure.tasks.durable_lane import DEFAULT_POLL_SECONDS, DurableTaskLane
from infrastructure.tasks.lane import DEFAULT_POLL_TIMEOUT_SECONDS, TaskLane
from infrastructure.tasks.types import (
    REQUEUE_FAILED_MESSAGE,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RETRY,
    STATUS_RUNNING,
    TaskContext,
    TaskKind,
    TaskLaneStats,
    TaskRecord,
    TaskRejectedError,
    TaskRunner,
    TaskStore,
)


@dataclass(frozen=True)
class _Registration:
    kind: TaskKind
    runner: TaskRunner
    store: Optional[TaskStore]


class _Scheduler:
    """延迟重投堆。一个引擎一个线程，堆里只放待重投的记录。"""

    def __init__(self, on_due: Callable[[str, TaskRecord], None],
                 on_shutdown: Callable[[TaskRecord], None]):
        self._on_due = on_due
        self._on_shutdown = on_shutdown
        self._heap: list[tuple[float, int, str, TaskRecord]] = []
        self._seq = 0
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._stop = False
        self._thread = threading.Thread(
            target=self._loop, name='task-engine-scheduler', daemon=True)
        self._thread.start()

    def schedule(self, lane: str, record: TaskRecord, delay: float) -> None:
        with self._cond:
            self._seq += 1
            heapq.heappush(
                self._heap, (time.monotonic() + max(0.0, delay), self._seq, lane, record))
            self._cond.notify()

    def pending_for(self, lane: str) -> int:
        with self._lock:
            return sum(1 for _due, _seq, name, _record in self._heap if name == lane)

    def stop(self) -> None:
        with self._cond:
            self._stop = True
            leftover = [entry[3] for entry in self._heap]
            self._heap.clear()
            self._cond.notify_all()
        for record in leftover:
            self._on_shutdown(record)

    def _loop(self) -> None:
        while True:
            with self._cond:
                if self._stop:
                    return
                if not self._heap:
                    self._cond.wait(timeout=1.0)
                    continue
                due, seq, lane, record = self._heap[0]
                now = time.monotonic()
                if due > now:
                    self._cond.wait(timeout=due - now)
                    continue
                heapq.heappop(self._heap)
            self._on_due(lane, record)


class TaskEngine:
    """进程内任务引擎；每个实例可以注册多条车道与多类任务。"""

    def __init__(self):
        self._lanes: dict[str, TaskLane | DurableTaskLane] = {}
        self._lane_modes: dict[str, str] = {}
        self._lane_kinds: dict[str, list[str]] = {}
        self._lane_lease: dict[str, int] = {}
        self._lane_capacity: dict[str, int] = {}
        self._kinds: dict[str, _Registration] = {}
        self._kind_by_task_type: dict[str, str] = {}
        self._records: dict[str, TaskRecord] = {}
        # 完成/失败计数独立于记录保留策略：即使 COMPLETED 记录被移出内存，
        # 观测面仍然能看到累计值。
        self._counters: dict[str, dict[str, int]] = {}
        self._lock = threading.Lock()
        self._shutdown = False
        self._started = False
        self._in_flight: dict[str, tuple[str, int]] = {}
        #: taskId → 本实例执行线程的取消事件（协作式中止）。
        self._cancel_events: dict[str, threading.Event] = {}
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._reclaim_thread: Optional[threading.Thread] = None
        self._listener_stop = threading.Event()
        self._listener_thread: Optional[threading.Thread] = None
        self._instance_id = uuid.uuid4().hex[:8]
        self._scheduler = _Scheduler(self._requeue_delayed, self._fail_on_shutdown)

    # ------------------------------------------------------------------
    # 注册 / 启动
    # ------------------------------------------------------------------

    def register_lane(self, name: str, *, workers: int = 1, capacity: int = 0,
                      poll_timeout: float = DEFAULT_POLL_TIMEOUT_SECONDS,
                      mode: str = 'memory',
                      poll_seconds: float = DEFAULT_POLL_SECONDS
                      ) -> TaskLane | DurableTaskLane:
        if mode not in ('memory', 'db'):
            raise ValueError(f'unknown task lane mode: {mode}')
        with self._lock:
            if name in self._lanes:
                raise ValueError(f'task lane already registered: {name}')
            if mode == 'db':
                lane: TaskLane | DurableTaskLane = DurableTaskLane(
                    name, workers=workers, poll_seconds=poll_seconds)
            else:
                lane = TaskLane(name, workers=workers, capacity=capacity,
                                poll_timeout=poll_timeout)
            self._lanes[name] = lane
            self._lane_modes[name] = mode
            self._lane_kinds[name] = []
            self._lane_lease[name] = 60
            # DB 车道的 capacity 由提交/管理面查库判断（内存车道由 queue.Queue 兜住）。
            self._lane_capacity[name] = capacity
            self._counters[name] = {'completed': 0, 'failed': 0}
        # 车道懒启动：注册时不起线程，第一次提交/引擎启动时才创建 worker。
        return lane

    def register_kind(self, kind: TaskKind, runner: TaskRunner,
                      store: Optional[TaskStore] = None) -> None:
        with self._lock:
            if kind.name in self._kinds:
                raise ValueError(f'task kind already registered: {kind.name}')
            if kind.lane not in self._lanes:
                raise ValueError(f'task lane is not registered: {kind.lane}')
            if self._lane_modes[kind.lane] != kind.queue_mode:
                raise ValueError(
                    f'task kind {kind.name} queue_mode={kind.queue_mode} '
                    f'does not match lane {kind.lane} mode={self._lane_modes[kind.lane]}')
            self._kinds[kind.name] = _Registration(kind=kind, runner=runner, store=store)
            persist_type = kind.persist_type or kind.name
            self._kind_by_task_type[persist_type] = kind.name
            self._lane_kinds[kind.lane].append(persist_type)
            self._lane_lease[kind.lane] = max(
                self._lane_lease[kind.lane], kind.lease_seconds)
        registry.register_cancel_hook(persist_type, kind.cancel_hook)
        registry.register_retry_hook(persist_type, kind.retry_hook)

    def ensure_capacity(self, lane_name: str) -> None:
        """DB 车道准入：PENDING/RETRY 达到 capacity 时拒绝新任务。

        内存车道的容量由 ``queue.Queue`` 自己兜；这里只查库。图谱链路的任务行
        由领域 store 先建、再 ``submit(create_row=False)``，所以调用方必须在
        建行**之前**调本方法，避免被拒后留下孤儿行。
        """
        with self._lock:
            capacity = self._lane_capacity.get(lane_name, 0)
            mode = self._lane_modes.get(lane_name)
        if mode != 'db' or capacity <= 0:
            return
        pending = pg_queue.pending_count(lane_name)
        if pending >= capacity:
            raise TaskRejectedError(
                f'task lane {lane_name} is full: {pending} pending >= {capacity}')

    def start(self) -> None:
        """启动 DB 车道 + 心跳/回收线程；幂等。"""
        with self._lock:
            if self._started:
                return
            self._started = True
            durable = [(name, lane) for name, lane in self._lanes.items()
                       if self._lane_modes[name] == 'db']
            lease = max((self._lane_lease[name] for name, _ in durable), default=60)
        for name, lane in durable:
            lane.start(self._make_claim(name), self._execute_durable)  # type: ignore[arg-type]
        if durable:
            try:
                reclaimed = pg_queue.reclaim_expired()
                if reclaimed:
                    log.warning('reclaimed %d expired task(s) at startup', len(reclaimed))
            except Exception:                              # noqa: BLE001
                log.warning('startup task reclaim failed', exc_info=True)
            interval = max(1.0, lease / 3.0)
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop, args=(interval,),
                name='task-engine-heartbeat', daemon=True)
            self._heartbeat_thread.start()
            self._reclaim_thread = threading.Thread(
                target=self._reclaim_loop, args=(interval,),
                name='task-engine-reclaim', daemon=True)
            self._reclaim_thread.start()
            self._listener_thread = threading.Thread(
                target=self._listen_loop, name='task-engine-listen', daemon=True)
            self._listener_thread.start()

    # ------------------------------------------------------------------
    # 提交 / 查询
    # ------------------------------------------------------------------

    def submit(self, kind_name: str, payload: Optional[dict] = None, *,
               task_id: Optional[str] = None, create_row: bool = True) -> str:
        """提交一条任务；返回 taskId。拒绝时按 kind 的策略抛错或同步执行。

        :param create_row: DB 模式下是否由 ``store.on_submit`` 新建任务行。
            图谱链路在提交前已经由领域 store 建好行，传 False。
        """
        with self._lock:
            registration = self._kinds.get(kind_name)
        if registration is None:
            raise TaskRejectedError(f'task kind is not registered: {kind_name}')

        kind = registration.kind
        lane = self._lanes[kind.lane]
        if kind.queue_mode == 'db' and create_row:
            self.ensure_capacity(kind.lane)
        record = TaskRecord(task_id=task_id or uuid.uuid4().hex,
                            kind=kind.name, payload=dict(payload or {}))

        if kind.queue_mode == 'db':
            self._remember(record)
            if create_row:
                self._notify(registration.store, 'on_submit', record)
            if self._shutdown:
                self._forget(record)
                if create_row:
                    self._notify(registration.store, 'on_reject', record)
                raise TaskRejectedError(
                    f'task lane {kind.lane} is shutdown; cannot accept {record.task_id}')
            try:
                pg_queue.notify(kind.lane)
            except Exception:                            # noqa: BLE001
                log.warning('task notify failed for lane %s', kind.lane, exc_info=True)
            self.start()
            lane.wake()                                  # type: ignore[union-attr]
            return record.task_id

        # 先记内存、通知存储，再入队：worker 可能瞬间取走并标记 RUNNING，
        # 晚通知会让存储看到 RUNNING 先于 PENDING。
        self._remember(record)
        self._notify(registration.store, 'on_submit', record)

        if not self._shutdown and not lane.is_shutdown:
            lane.start(self._run_record)                 # type: ignore[union-attr]
        # 与 shutdown 的置位在同一把锁里，避免「检查时未关停、入队时已关停」
        # 的任务留在队列里没人消费。
        with self._lock:
            accepted = (not self._shutdown and not lane.is_shutdown
                        and lane.submit(record))         # type: ignore[union-attr]
        if accepted:
            return record.task_id

        if kind.reject == 'inline':
            log.warning('task lane %s rejected %s; running inline',
                        kind.lane, record.task_id)
            self._execute(registration, record)
            return record.task_id

        self._forget(record)
        self._notify(registration.store, 'on_reject', record)
        raise TaskRejectedError(
            f'task lane {kind.lane} rejected {record.task_id}: queue is full or shutdown')

    def get(self, task_id: str) -> Optional[TaskRecord]:
        with self._lock:
            return self._records.get(task_id)

    def stats(self) -> dict[str, TaskLaneStats]:
        with self._lock:
            lanes = dict(self._lanes)
            records = list(self._records.values())
            kinds = dict(self._kinds)
            counters = {name: dict(values) for name, values in self._counters.items()}
        counts: dict[str, dict[str, int]] = {name: {'retry': 0} for name in lanes}
        for record in records:
            registration = kinds.get(record.kind)
            if registration is None:
                continue
            if record.status == STATUS_RETRY:
                counts[registration.kind.lane]['retry'] += 1
        result = {}
        for name, lane in lanes.items():
            if self._lane_modes.get(name) == 'db':
                try:
                    db_counts = pg_queue.count_by_lane(name)
                except Exception:                        # noqa: BLE001
                    log.warning('count db lane %s failed', name, exc_info=True)
                    db_counts = {}
                queued = db_counts.get('PENDING', 0) + db_counts.get('RETRY', 0)
                result[name] = TaskLaneStats(
                    name=name,
                    workers=lane.workers,
                    capacity=self._lane_capacity.get(name, 0),
                    queued=queued,
                    running=db_counts.get('RUNNING', 0),
                    delayed=0,
                    pending=queued,
                    retry=db_counts.get('RETRY', 0),
                    completed=db_counts.get('COMPLETED', 0),
                    failed=db_counts.get('FAILED', 0),
                    shutdown=lane.is_shutdown,
                )
                continue
            delayed = self._scheduler.pending_for(name)
            result[name] = TaskLaneStats(
                name=name,
                workers=lane.workers,
                capacity=lane.capacity,                 # type: ignore[union-attr]
                queued=lane.queued,                     # type: ignore[union-attr]
                running=lane.running,
                delayed=delayed,
                pending=lane.queued + delayed,          # type: ignore[union-attr]
                retry=counts[name]['retry'],
                completed=counters.get(name, {}).get('completed', 0),
                failed=counters.get(name, {}).get('failed', 0),
                shutdown=lane.is_shutdown,
            )
        return result

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------

    def _run_record(self, record: TaskRecord) -> None:
        with self._lock:
            registration = self._kinds.get(record.kind)
        if registration is None:
            log.error('task %s has no registered kind %s', record.task_id, record.kind)
            return
        self._execute(registration, record)

    # ------------------------------------------------------------------
    # DB 队列：认领 / 执行 / 心跳 / 回收
    # ------------------------------------------------------------------

    def _make_claim(self, lane_name: str) -> Callable[[str], Optional[TaskRecord]]:
        prefix = f'{self._instance_id}:{lane_name}'

        def claim(worker_id: str) -> Optional[TaskRecord]:
            with self._lock:
                task_types = list(self._lane_kinds.get(lane_name, []))
                lease = self._lane_lease.get(lane_name, 60)
            row = pg_queue.claim(lane_name, task_types,
                                 f'{prefix}:{worker_id}', lease)
            return self._record_from_row(row) if row else None

        return claim

    def _record_from_row(self, row: dict) -> TaskRecord:
        task_type = row.get('task_type')
        kind_name = self._kind_by_task_type.get(task_type, task_type)
        return TaskRecord(
            task_id=row['id'],
            kind=kind_name,
            payload=row.get('payload') or {},
            extra=row.get('extra') or {},
            status=row.get('status') or STATUS_RUNNING,
            attempt=int(row.get('attempt') or 1),
            created_at=row.get('created_at') or datetime.now(),
            start_time=row.get('start_time'),
            end_time=row.get('finish_time'),
            error_message=row.get('error_message'),
            available_at=row.get('available_at'),
            locked_by=row.get('locked_by'),
            locked_until=row.get('locked_until'),
            heartbeat_at=row.get('heartbeat_at'),
        )

    def _execute_durable(self, record: TaskRecord) -> None:
        with self._lock:
            registration = self._kinds.get(record.kind)
        if registration is None:
            log.error('durable task %s has no registered kind %s',
                      record.task_id, record.kind)
            return
        kind = registration.kind
        worker_id = record.locked_by
        if not worker_id:
            log.error('durable task %s claimed without locked_by', record.task_id)
            return
        cancel_event = threading.Event()
        with self._lock:
            self._in_flight[record.task_id] = (worker_id, kind.lease_seconds)
            self._cancel_events[record.task_id] = cancel_event
        record.status = STATUS_RUNNING
        ctx = TaskContext(record=record, lane=kind.lane,
                          store=registration.store, cancel_event=cancel_event)
        cancellation.set_cancel_event(cancel_event)
        try:
            registration.runner(record, ctx)
        except cancellation.TaskCancelled as error:
            self._handle_cancelled(registration, record, worker_id, error)
        except Exception as error:                        # noqa: BLE001
            self._handle_durable_failure(registration, record, worker_id, error)
        else:
            if kind.status_owner == 'engine':
                if pg_queue.complete(record.task_id, worker_id):
                    record.status = STATUS_COMPLETED
                    record.end_time = datetime.now()
                    record.error_message = None
                    self._notify(registration.store, 'on_change', record)
                    self._bump(kind.lane, 'completed')
                else:
                    log.warning('durable task %s lost its lease before completion',
                                record.task_id)
            else:
                # 领域 runner 自己写终态；这里只释放租约，不覆盖状态。
                pg_queue.release(record.task_id, worker_id)
                self._notify(registration.store, 'on_change', record)
        finally:
            cancellation.clear_cancel_event()
            with self._lock:
                self._in_flight.pop(record.task_id, None)
                self._cancel_events.pop(record.task_id, None)

    def _handle_cancelled(self, registration: _Registration, record: TaskRecord,
                          worker_id: str, error: BaseException) -> None:
        """runner 在安全点中止：落 CANCELLED，不重试。"""
        text = str(error).strip()
        message = text or 'Cancelled by user'
        if pg_queue.cancel_running(record.task_id, worker_id, message):
            record.status = STATUS_CANCELLED
            record.end_time = datetime.now()
            record.error_message = message
            self._notify(registration.store, 'on_change', record)
            self._run_cancel_hook(registration.kind, record)
            log.info('durable task %s cancelled by request', record.task_id)
        else:
            log.warning('durable task %s lost its lease before cancellation',
                        record.task_id)

    @staticmethod
    def _run_cancel_hook(kind: TaskKind, record: TaskRecord) -> None:
        """RUNNING 取消也要同步领域状态（文件行/图谱库），与排队取消一致。"""
        task_type = kind.persist_type or kind.name
        hook = registry.cancel_hook_for(task_type)
        if hook is None:
            return
        payload = record.payload or {}
        kbase_id = (payload.get('kbase_id')
                    or (payload.get('dto') or {}).get('kbId')
                    or payload.get('kbIndexName'))
        if isinstance(kbase_id, str) and kbase_id.startswith('graph_'):
            kbase_id = kbase_id[len('graph_'):]
        try:
            hook({'id': record.task_id, 'task_type': task_type,
                  'kbase_id': kbase_id, 'payload': payload})
        except Exception:                                # noqa: BLE001
            log.warning('task cancel hook failed: task=%s type=%s',
                        record.task_id, task_type, exc_info=True)

    def _handle_durable_failure(self, registration: _Registration,
                                record: TaskRecord, worker_id: str,
                                error: BaseException) -> None:
        kind = registration.kind
        if kind.status_owner == 'runner':
            # 领域 _run 内部已经落 FAILED/保留 RUNNING；这里不覆盖它的语义。
            pg_queue.release(record.task_id, worker_id)
            self._notify(registration.store, 'on_change', record)
            log.warning('durable task %s runner raised; status left to domain',
                        record.task_id, exc_info=True)
            return
        message = _error_text(error)
        if record.attempt < kind.max_attempts:
            next_attempt = record.attempt + 1
            try:
                delay = float(kind.retry_delay(error) or 0.0)
            except Exception:                             # noqa: BLE001
                delay = 0.0
            if pg_queue.reschedule(record.task_id, worker_id, next_attempt,
                                   delay, message):
                record.status = STATUS_RETRY
                record.attempt = next_attempt
                record.error_message = message
                self._notify(registration.store, 'on_change', record)
            else:
                log.warning('durable task %s lost its lease before retry',
                            record.task_id)
            return
        if pg_queue.fail(record.task_id, worker_id, message):
            record.status = STATUS_FAILED
            record.end_time = datetime.now()
            record.error_message = message
            self._notify(registration.store, 'on_change', record)
            self._bump(kind.lane, 'failed')
        else:
            log.warning('durable task %s lost its lease before failure',
                        record.task_id)

    def _heartbeat_loop(self, interval: float) -> None:
        while not self._heartbeat_stop.wait(interval):
            with self._lock:
                items = list(self._in_flight.items())
            for task_id, (worker_id, lease) in items:
                try:
                    if not pg_queue.heartbeat(task_id, worker_id, lease):
                        log.warning('durable task %s heartbeat lost its lease', task_id)
                except Exception:                     # noqa: BLE001
                    log.warning('durable task %s heartbeat failed',
                                task_id, exc_info=True)
            self._poll_cancel_requests()

    def _poll_cancel_requests(self) -> None:
        """NOTIFY 丢失时的兜底：心跳时顺带查一次取消标记。"""
        with self._lock:
            task_ids = list(self._in_flight.keys())
        if not task_ids:
            return
        try:
            for task_id in pg_queue.cancel_requested_ids(task_ids):
                self._request_cancel(task_id)
        except Exception:                             # noqa: BLE001
            log.warning('poll task cancel requests failed', exc_info=True)

    def _request_cancel(self, task_id: str) -> None:
        with self._lock:
            event = self._cancel_events.get(task_id)
        if event is not None:
            event.set()

    def _reclaim_loop(self, interval: float) -> None:
        while not self._heartbeat_stop.wait(interval):
            try:
                reclaimed = pg_queue.reclaim_expired()
            except Exception:                         # noqa: BLE001
                log.warning('task reclaim failed', exc_info=True)
                continue
            if reclaimed:
                log.warning('reclaimed %d expired task(s): %s',
                            len(reclaimed),
                            [row.get('id') for row in reclaimed])

    def _listen_loop(self) -> None:
        """LISTEN/NOTIFY 唤醒；连接断开时退避重连。"""
        while not self._listener_stop.is_set():
            conn = None
            try:
                conn = pg_queue.listen_connection()
                while not self._listener_stop.is_set():
                    if not select.select([conn], [], [], 1.0)[0]:
                        continue
                    conn.poll()
                    while conn.notifies:
                        note = conn.notifies.pop(0)
                        if note.channel == pg_queue.CANCEL_NOTIFY_CHANNEL:
                            self._request_cancel(note.payload)
                        else:
                            self._wake_lane(note.payload)
            except Exception:                         # noqa: BLE001
                if not self._listener_stop.is_set():
                    log.warning('task listener failed; retrying in 2s', exc_info=True)
                    self._listener_stop.wait(2.0)
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:                 # noqa: BLE001
                        pass

    def _wake_lane(self, lane_name: Optional[str]) -> None:
        with self._lock:
            lanes = [(name, lane) for name, lane in self._lanes.items()
                     if self._lane_modes.get(name) == 'db']
        if lane_name:
            for name, lane in lanes:
                if name == lane_name:
                    lane.wake()                       # type: ignore[union-attr]
                    return
            return
        for _name, lane in lanes:
            lane.wake()                               # type: ignore[union-attr]

    def _execute(self, registration: _Registration, record: TaskRecord) -> None:
        kind = registration.kind
        record.status = STATUS_RUNNING
        record.start_time = datetime.now()
        self._notify(registration.store, 'on_change', record)
        ctx = TaskContext(record=record, lane=kind.lane, store=registration.store)
        try:
            registration.runner(record, ctx)
        except Exception as error:                        # noqa: BLE001
            self._handle_failure(registration, record, error)
        else:
            record.status = STATUS_COMPLETED
            record.end_time = datetime.now()
            record.error_message = None
            self._notify(registration.store, 'on_change', record)
            self._bump(kind.lane, 'completed')
            if not kind.retain_completed:
                self._forget(record)

    def _handle_failure(self, registration: _Registration, record: TaskRecord,
                        error: BaseException) -> None:
        kind = registration.kind
        if record.attempt < kind.max_attempts:
            record.attempt += 1
            record.status = STATUS_RETRY
            record.error_message = _error_text(error)
            self._notify(registration.store, 'on_change', record)
            try:
                delay = float(kind.retry_delay(error) or 0.0)
            except Exception:                             # noqa: BLE001
                log.warning('task kind %s retry_delay failed; retrying immediately',
                            kind.name, exc_info=True)
                delay = 0.0
            if delay > 0:
                self._scheduler.schedule(kind.lane, record, delay)
                return
            lane = self._lanes[kind.lane]
            if lane.submit(record):
                return
            record.status = STATUS_FAILED
            record.end_time = datetime.now()
            record.error_message = REQUEUE_FAILED_MESSAGE
            self._notify(registration.store, 'on_change', record)
            self._bump(kind.lane, 'failed')
            return

        record.status = STATUS_FAILED
        record.end_time = datetime.now()
        record.error_message = _error_text(error)
        self._notify(registration.store, 'on_change', record)
        self._bump(kind.lane, 'failed')

    def _requeue_delayed(self, lane_name: str, record: TaskRecord) -> None:
        lane = self._lanes.get(lane_name)
        if lane is None or self._shutdown or lane.is_shutdown:
            self._fail_on_shutdown(record, 'Task engine is shutdown')
            return
        if lane.submit(record):
            return
        # 队满：稍后再试，不能把记录丢掉。
        self._scheduler.schedule(lane_name, record, 0.05)

    def _fail_on_shutdown(self, record: TaskRecord,
                          message: str = 'Task engine is shutdown') -> None:
        with self._lock:
            registration = self._kinds.get(record.kind)
        record.status = STATUS_FAILED
        record.end_time = datetime.now()
        record.error_message = message
        if registration is not None:
            self._notify(registration.store, 'on_change', record)
            self._bump(registration.kind.lane, 'failed')

    # ------------------------------------------------------------------
    # 内存表 / 存储回调
    # ------------------------------------------------------------------

    def _remember(self, record: TaskRecord) -> None:
        with self._lock:
            self._records[record.task_id] = record

    def _forget(self, record: TaskRecord) -> None:
        with self._lock:
            self._records.pop(record.task_id, None)

    def _bump(self, lane: str, key: str) -> None:
        with self._lock:
            bucket = self._counters.get(lane)
            if bucket is not None:
                bucket[key] += 1

    @staticmethod
    def _notify(store: Optional[TaskStore], method: str, record: TaskRecord) -> None:
        if store is None:
            return
        callback = getattr(store, method, None)
        if callback is None:
            return
        try:
            callback(record)
        except Exception:                                 # noqa: BLE001
            log.warning('task store %s failed for %s', method, record.task_id,
                        exc_info=True)

    # ------------------------------------------------------------------
    # 关停
    # ------------------------------------------------------------------

    def shutdown(self, drain_seconds: float = 0.0) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            lanes = list(self._lanes.values())
        self._heartbeat_stop.set()
        self._listener_stop.set()
        for thread in (self._heartbeat_thread, self._reclaim_thread,
                       self._listener_thread):
            if thread is not None:
                thread.join(timeout=2.0)
        self._scheduler.stop()
        for lane in lanes:
            lane.shutdown(drain_seconds)

    @property
    def is_shutdown(self) -> bool:
        return self._shutdown


def _error_text(error: BaseException) -> str:
    text = str(error)
    return text if text else 'null'
