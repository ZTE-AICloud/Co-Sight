"""DB 队列车道（DurableTaskLane）的取任务/执行行为。

不连数据库：claim/execute 都是注入的桩；真正的 claim SQL 由
``tools``/真实库冒烟覆盖。
"""

from __future__ import annotations

import threading

from infrastructure.tasks.durable_lane import DurableTaskLane
from infrastructure.tasks.types import TaskRecord


def test_durable_lane_claims_once_and_executes():
    lane = DurableTaskLane('test', workers=3, poll_seconds=0.02)
    record = TaskRecord(task_id='t1', kind='k')
    remaining = [record]
    lock = threading.Lock()
    executed = threading.Event()
    seen = []

    def claim(worker_id):
        with lock:
            return remaining.pop() if remaining else None

    def execute(item):
        seen.append(item.task_id)
        executed.set()

    lane.start(claim, execute)
    try:
        assert executed.wait(2.0)
    finally:
        lane.shutdown()

    assert seen == ['t1']


def test_durable_lane_shutdown_stops_workers():
    lane = DurableTaskLane('test', workers=2, poll_seconds=0.02)
    lane.start(lambda worker_id: None, lambda record: None)
    lane.shutdown()
    assert lane.is_shutdown
