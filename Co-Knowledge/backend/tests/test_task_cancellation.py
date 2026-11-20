"""协作式取消：线程信号、文件链回滚与引擎确认落库。"""

import threading

import pytest

from infrastructure.tasks import TaskEngine, TaskKind, TaskRecord, cancellation, registry
from infrastructure.tasks.cancellation import TaskCancelled
from knowledge_base.task.chain import FileHandlerChain


class _Handler:
    def __init__(self, name, calls):
        self.name = name
        self.calls = calls

    def handle(self, file_handle):
        self.calls.append(('handle', self.name))

    def rollback(self, file_handle):
        self.calls.append(('rollback', self.name))


def test_raise_if_cancelled_uses_thread_local_event():
    event = threading.Event()
    cancellation.set_cancel_event(event)
    try:
        cancellation.raise_if_cancelled()
    finally:
        cancellation.clear_cancel_event()

    event.set()
    cancellation.set_cancel_event(event)
    try:
        with pytest.raises(TaskCancelled):
            cancellation.raise_if_cancelled()
    finally:
        cancellation.clear_cancel_event()


def test_file_chain_cancels_before_next_handler_and_rolls_back():
    calls = []
    chain = (FileHandlerChain()
             .add_handler(_Handler('parse', calls))
             .add_handler(_Handler('split', calls)))
    event = threading.Event()
    event.set()
    cancellation.set_cancel_event(event)
    try:
        with pytest.raises(TaskCancelled):
            chain.execute({})
    finally:
        cancellation.clear_cancel_event()

    assert calls == [('rollback', 'parse')]


def _engine():
    engine = TaskEngine()
    engine.register_lane('lane', mode='db')
    engine.register_kind(
        TaskKind(name='kind', lane='lane', queue_mode='db'),
        lambda record, ctx: None)
    return engine


def test_poll_cancel_requests_sets_in_flight_event(monkeypatch):
    engine = _engine()
    event = threading.Event()
    engine._in_flight['t1'] = ('w1', 60)
    engine._cancel_events['t1'] = event
    monkeypatch.setattr(
        'infrastructure.tasks.engine.pg_queue.cancel_requested_ids',
        lambda ids: ['t1'])

    engine._poll_cancel_requests()

    assert event.is_set()


def test_handle_cancelled_marks_task_cancelled(monkeypatch):
    engine = _engine()
    record = TaskRecord(task_id='t1', kind='kind')
    monkeypatch.setattr(
        'infrastructure.tasks.engine.pg_queue.cancel_running',
        lambda task_id, worker_id, reason: True)

    engine._handle_cancelled(engine._kinds['kind'], record, 'w1', TaskCancelled())

    assert record.status == 'CANCELLED'
    assert record.error_message == 'Cancelled by user'


def test_handle_cancelled_runs_domain_hook(monkeypatch):
    engine = _engine()
    record = TaskRecord(task_id='t1', kind='kind', payload={'fileId': 'f1'})
    seen = []
    registry.register_cancel_hook('kind', seen.append)
    monkeypatch.setattr(
        'infrastructure.tasks.engine.pg_queue.cancel_running',
        lambda task_id, worker_id, reason: True)
    try:
        engine._handle_cancelled(engine._kinds['kind'], record, 'w1', TaskCancelled())
    finally:
        registry.unregister_cancel_hook('kind')

    assert seen and seen[0]['id'] == 't1'
    assert seen[0]['payload'] == {'fileId': 'f1'}
