"""统一任务引擎的行为锁定测试。

引擎只负责「跑」：提交、车道隔离、重试、延迟重投、拒绝策略、关停。
任务语义（状态写哪张表、进度怎么算、失败要不要回滚）由各领域的 runner 负责。

跑法::

    cd backend && python -m pytest tests/test_task_engine.py -q
"""

from __future__ import annotations

import threading
import time

import pytest

from infrastructure.tasks import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RUNNING,
    TaskEngine,
    TaskKind,
    TaskRejectedError,
)


def wait_until(predicate, timeout=3.0, interval=0.005):
    """轮询等待；超时抛 AssertionError（避免把等待写成固定 sleep）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError('condition not met within %.1fs' % timeout)


class RecordingStore:
    """记录引擎回调；用于断言状态迁移顺序。"""

    def __init__(self):
        self.events = []
        self._lock = threading.Lock()

    def on_submit(self, record):
        self._append(('submit', record.status, record.attempt))

    def on_change(self, record):
        self._append(('change', record.status, record.attempt))

    def load(self, task_id):
        return None

    def _append(self, event):
        with self._lock:
            self.events.append(event)

    def statuses(self):
        with self._lock:
            return [event[1] for event in self.events]


def make_engine():
    return TaskEngine()


def test_runs_task_and_notifies_store_in_order():
    engine = make_engine()
    store = RecordingStore()
    done = threading.Event()
    engine.register_lane('test', workers=1)
    engine.register_kind(TaskKind(name='echo', lane='test', retain_completed=True),
                         lambda record, ctx: done.set(), store)

    task_id = engine.submit('echo')
    assert done.wait(3.0)
    wait_until(lambda: engine.get(task_id).status == STATUS_COMPLETED)

    assert store.statuses() == ['PENDING', STATUS_RUNNING, STATUS_COMPLETED]
    engine.shutdown()


def test_retries_until_max_attempts_then_fails():
    engine = make_engine()
    store = RecordingStore()
    calls = []

    def boom(record, ctx):
        calls.append(record.attempt)
        raise RuntimeError('boom')

    engine.register_lane('test', workers=1)
    engine.register_kind(TaskKind(name='boom', lane='test', max_attempts=3),
                         boom, store)

    task_id = engine.submit('boom')
    wait_until(lambda: engine.get(task_id).status == STATUS_FAILED)

    assert calls == [1, 2, 3]
    assert store.statuses()[-1] == STATUS_FAILED
    assert engine.get(task_id).attempt == 3
    assert 'boom' in engine.get(task_id).error_message
    engine.shutdown()


def test_retry_then_success_marks_completed():
    engine = make_engine()
    calls = []

    def flaky(record, ctx):
        calls.append(record.attempt)
        if record.attempt == 1:
            raise RuntimeError('first')

    engine.register_lane('test', workers=1)
    engine.register_kind(
        TaskKind(name='flaky', lane='test', max_attempts=3, retain_completed=True), flaky)

    task_id = engine.submit('flaky')
    wait_until(lambda: engine.get(task_id).status == STATUS_COMPLETED)

    assert calls == [1, 2]
    assert engine.get(task_id).attempt == 2
    engine.shutdown()


def test_max_attempts_one_never_retries():
    engine = make_engine()
    calls = []

    def boom(record, ctx):
        calls.append(record.attempt)
        raise RuntimeError('single shot')

    engine.register_lane('test', workers=1)
    engine.register_kind(TaskKind(name='single', lane='test', max_attempts=1), boom)

    task_id = engine.submit('single')
    wait_until(lambda: engine.get(task_id).status == STATUS_FAILED)

    assert calls == [1]
    engine.shutdown()


def test_delayed_retry_does_not_block_the_worker():
    """重试延迟期间，同一车道的其它任务必须能继续跑 —— 不能在 worker 里 sleep。"""
    engine = make_engine()
    first_done = threading.Event()
    retried_done = threading.Event()
    quick_done = threading.Event()

    def flaky(record, ctx):
        if record.attempt == 1:
            first_done.set()
            raise RuntimeError('retry me')
        retried_done.set()

    def quick(record, ctx):
        quick_done.set()

    engine.register_lane('test', workers=1)
    engine.register_kind(
        TaskKind(name='flaky', lane='test', max_attempts=2,
                 retry_delay=lambda _error: 1.0),
        flaky)
    engine.register_kind(TaskKind(name='quick', lane='test'), quick)

    engine.submit('flaky')
    assert first_done.wait(3.0)

    engine.submit('quick')
    assert quick_done.wait(0.8), 'quick task should run during the retry delay'
    assert not retried_done.is_set()

    assert retried_done.wait(3.0)
    engine.shutdown()


def test_lanes_are_isolated_so_long_tasks_do_not_starve_short_tasks():
    engine = make_engine()
    release = threading.Event()
    slow_running = []
    slow_lock = threading.Lock()
    all_slow_running = threading.Event()
    fast_done = threading.Event()

    def slow(record, ctx):
        with slow_lock:
            slow_running.append(record.task_id)
            if len(slow_running) == 5:
                all_slow_running.set()
        release.wait(3.0)

    def fast(record, ctx):
        fast_done.set()

    engine.register_lane('slow', workers=5)
    engine.register_lane('fast', workers=1)
    engine.register_kind(TaskKind(name='slow', lane='slow'), slow)
    engine.register_kind(TaskKind(name='fast', lane='fast'), fast)

    for _ in range(5):
        engine.submit('slow')
    assert all_slow_running.wait(3.0), 'all slow workers should be occupied'

    engine.submit('fast')
    assert fast_done.wait(1.0), 'fast lane must not be blocked by slow lane'
    assert not release.is_set()

    release.set()
    engine.shutdown()


def test_full_lane_rejects_when_policy_is_raise():
    engine = make_engine()
    release = threading.Event()
    running = threading.Event()

    def block(record, ctx):
        running.set()
        release.wait(3.0)

    engine.register_lane('test', workers=1, capacity=1)
    engine.register_kind(TaskKind(name='block', lane='test'), block)

    engine.submit('block')
    assert running.wait(3.0)
    engine.submit('block')            # 占满唯一一个排队位

    with pytest.raises(TaskRejectedError):
        engine.submit('block')

    release.set()
    engine.shutdown()


def test_full_lane_runs_inline_when_policy_is_inline():
    engine = make_engine()
    release = threading.Event()
    running = threading.Event()
    inline_done = threading.Event()
    caller = threading.get_ident()
    runner_thread = []

    def block(record, ctx):
        running.set()
        release.wait(3.0)

    def inline(record, ctx):
        runner_thread.append(threading.get_ident())
        inline_done.set()

    engine.register_lane('test', workers=1, capacity=1)
    engine.register_kind(TaskKind(name='block', lane='test'), block)
    engine.register_kind(TaskKind(name='inline', lane='test', reject='inline'), inline)

    engine.submit('block')
    assert running.wait(3.0)
    engine.submit('block')            # 占满排队位

    engine.submit('inline')
    assert inline_done.is_set(), 'inline rejection must run before submit returns'
    assert runner_thread == [caller]

    release.set()
    engine.shutdown()


def test_shutdown_rejects_new_tasks():
    engine = make_engine()
    engine.register_lane('test', workers=1)
    engine.register_kind(TaskKind(name='noop', lane='test'), lambda record, ctx: None)
    engine.shutdown()

    with pytest.raises(TaskRejectedError):
        engine.submit('noop')


def test_unknown_kind_is_rejected():
    engine = make_engine()
    with pytest.raises(TaskRejectedError):
        engine.submit('missing')
    engine.shutdown()


def test_completed_records_are_released_but_counters_remain():
    """完成记录默认移出内存，避免长跑进程累积；统计走独立计数器。"""
    engine = make_engine()
    done = threading.Event()
    engine.register_lane('test', workers=1)
    engine.register_kind(TaskKind(name='echo', lane='test'),
                         lambda record, ctx: done.set())

    task_id = engine.submit('echo')
    assert done.wait(3.0)
    wait_until(lambda: engine.stats()['test'].completed == 1)
    assert engine.get(task_id) is None
    engine.shutdown()
