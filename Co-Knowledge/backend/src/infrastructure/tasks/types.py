"""统一任务引擎的公共类型。

设计边界（见 ``docs`` 里的任务引擎说明）：

* 引擎只管**执行**：提交、车道、worker、重试、延迟重投、拒绝、关停。
* 任务语义仍归领域：状态写哪张表、进度怎么算、失败是否回滚，都由 ``TaskRunner``
  与 ``TaskStore`` 决定。引擎的 ``TaskRecord.status`` 只是进程内记忆态。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Literal, Optional, Protocol

STATUS_PENDING = 'PENDING'
STATUS_RUNNING = 'RUNNING'
STATUS_RETRY = 'RETRY'
STATUS_COMPLETED = 'COMPLETED'
STATUS_COMPLETED_WITH_ERRORS = 'COMPLETED_WITH_ERRORS'
STATUS_FAILED = 'FAILED'
STATUS_CANCELLED = 'CANCELLED'

TERMINAL_STATUSES = (STATUS_COMPLETED, STATUS_COMPLETED_WITH_ERRORS,
                     STATUS_FAILED, STATUS_CANCELLED)

#: 任务落停后可人工重试的状态（``COMPLETED_WITH_ERRORS`` 不在此列：
#: 重跑会重复写入已成功的那部分数据）。
RETRYABLE_STATUSES = (STATUS_FAILED, STATUS_CANCELLED)

#: 重试时车道已满/关停，任务无法重投的终态文案。
#: 领域适配器需要按原样透出（不能再套一层 ``Task failed after N retries``）。
REQUEUE_FAILED_MESSAGE = 'Failed to resubmit task: queue is full'

RejectPolicy = Literal['raise', 'inline']
QueueMode = Literal['memory', 'db']
StatusOwner = Literal['engine', 'runner']

#: 管理动作成功后的领域副作用（入参是任务行）。
TaskHook = Callable[[dict[str, Any]], None]
#: 取消成功后的领域副作用（把文件/知识库状态也落成失败/取消）。
CancelHook = TaskHook


def no_retry_delay(_error: BaseException) -> float:
    """默认不延迟；需要延迟重投的任务类型注入自己的函数。"""
    return 0.0


@dataclass(frozen=True)
class TaskKind:
    """一类任务的执行策略。

    :param name: 任务类型名（``submit`` 的键）
    :param lane: 所属车道；车道决定 worker 数与队列容量
    :param max_attempts: **总执行次数**（1 表示不重试；文件链是 1+3=4）
    :param retry_delay: 失败后延迟多少秒再重投；0 表示立即重投
    :param reject: 车道满/关停时的策略：``raise`` 抛错、``inline`` 在调用线程同步跑
    :param retain_completed: 完成后是否保留进程内记录。默认 False（与文件队列一致：
        完成即移出内存，避免长跑进程无限累积）；领域仍需查详情时应走自己的持久化表。
    :param queue_mode: ``memory`` = 进程内队列；``db`` = 从 task_center.task 认领。
    :param lease_seconds: DB 模式的租约时长；长任务需要 runner 侧定期心跳。
    :param status_owner: DB 模式下由谁写终态：``engine`` 或领域 runner。
    :param persist_type: 落库时 ``task_center.task.task_type`` 的取值；默认同 ``name``。
    :param cancel_hook: 队列层把任务置为 CANCELLED 后调用，用于同步领域状态
        （文件行、图谱库状态）；异常只记日志，不回滚取消结果。
    :param retry_hook: 队列层把任务重置为 PENDING 后调用，用于把领域状态退回
        「处理中」（例如文件行 2 → 0）；异常只记日志，不回滚重试结果。
    """

    name: str
    lane: str
    max_attempts: int = 1
    retry_delay: Callable[[BaseException], float] = no_retry_delay
    reject: RejectPolicy = 'raise'
    retain_completed: bool = False
    queue_mode: QueueMode = 'memory'
    lease_seconds: int = 60
    status_owner: StatusOwner = 'engine'
    persist_type: Optional[str] = None
    cancel_hook: Optional[CancelHook] = None
    retry_hook: Optional[TaskHook] = None


@dataclass
class TaskRecord:
    """引擎持有的一条任务记录；领域存储通过 ``TaskStore`` 从它投影。"""

    task_id: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    status: str = STATUS_PENDING
    attempt: int = 1
    created_at: datetime = field(default_factory=datetime.now)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    error_message: Optional[str] = None
    available_at: Optional[datetime] = None
    locked_by: Optional[str] = None
    locked_until: Optional[datetime] = None
    heartbeat_at: Optional[datetime] = None


@dataclass(frozen=True)
class TaskLaneStats:
    name: str
    workers: int
    capacity: int
    queued: int
    running: int
    delayed: int
    pending: int
    retry: int
    completed: int
    failed: int
    shutdown: bool


class TaskStore(Protocol):
    """领域持久化适配器。引擎只调用，不关心 SQL。

    ``on_submit`` / ``on_change`` 里的异常由引擎记录日志后吞掉 —— 持久化是观测面，
    不能因为它抖动把任务执行本身判死。需要严格落库的调用方应在 ``submit`` 之前自己做。
    """

    def on_submit(self, record: TaskRecord) -> None:
        ...

    def on_change(self, record: TaskRecord) -> None:
        ...

    def load(self, task_id: str) -> Optional[TaskRecord]:
        ...


class TaskRunner(Protocol):
    def __call__(self, record: TaskRecord, ctx: 'TaskContext') -> None:
        ...


@dataclass(frozen=True)
class TaskContext:
    """runner 可用的上下文；进度回写是可选的领域能力。"""

    record: TaskRecord
    lane: str
    store: Optional[TaskStore] = None
    cancel_event: Optional[threading.Event] = None

    def set_progress(self, percent: int) -> None:
        callback = getattr(self.store, 'on_progress', None)
        if callback is not None:
            callback(self.record, int(percent))

    def is_cancelled(self) -> bool:
        return bool(self.cancel_event is not None and self.cancel_event.is_set())

    def raise_if_cancelled(self) -> None:
        from infrastructure.tasks.cancellation import raise_if_cancelled

        raise_if_cancelled()


class TaskRejectedError(RuntimeError):
    """任务被拒绝：车道已满、引擎已关停或任务类型未注册。"""
