"""文件任务监控（``/file-tasks/*``）。

**这一族用的是另一套信封**，不是 ``{code:{...},bo,other}``：

* 成功：``{"success": true, "data": ..., "timestamp": <epoch 毫秒>}``
* 未找到：**HTTP 200** + ``{"success": false, "error": "Task not found", "timestamp": ...}``
* 真出错：**HTTP 500** + ``{"success": false, "error": ...}`` —— **不带 timestamp**

契约文件在这三条上都不准：它写了 404、写了
``task.json`` 那套 ``taskType/progress/attempt`` 字段、也没记 ``/failed``。
**以实现为准**（契约里那份 task.json 的状态枚举是 SUCCEEDED/CANCELLED，
而实际状态是 COMPLETED/RETRY，字段集也完全不同）。

数据来源要分清，否则会写出「重启后统计看起来正常」的假象：

* ``pendingCount`` / ``runningCount`` / ``failedCount`` / ``retryCount`` / ``queueSize``
  → **只看内存表**。重启后全是 0（队列不重投，符合既定语义）。
* ``completedCount`` → **查库**（``kb_import_task`` 里 COMPLETED 的 FILE_IMPORT 任务）。
  已完成的任务一完成就被移出内存表，所以内存里永远数不到。
* ``getTask`` → 内存优先，**查不到回落 ``kb_import_task``**。所以任务详情在重启后仍然查得到，
  但恢复出来的对象只有 fileId：``fileName`` 是 null、``maxRetryCount`` 是 0、
  ``startTime`` / ``errorMessage`` 也是 null。
* ``getFailedTasks`` → **只看内存**，重启后返回空数组。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from knowledge_base.task import runtime
from knowledge_base.task.wrapper import STATUS_COMPLETED, STATUS_FAILED

# ``TaskStatus.getDescription()``：注意**入库的是枚举名**，这里只用于展示
STATUS_DESCRIPTIONS = {
    'PENDING': '待处理',
    'RUNNING': '执行中',
    'RETRY': '重试中',
    'COMPLETED': '已完成',
    'FAILED': '失败',
}

# ``FileTaskQueueManager.getTask`` 查不到时的固定文案
TASK_NOT_FOUND = 'Task not found'


def iso_local_datetime(value: Optional[datetime]) -> Optional[str]:
    """时间格式：``ISO_LOCAL_DATE_TIME``。

    小数位是**按需最少位数、不留尾随零**（``appendFraction(NANO_OF_SECOND, 0, 9, true)``）：
    整数秒就完全没有小数点后面的部分，毫秒 324 是 ``.324``，纳秒满 9 位就是 9 位。
    线上格式形如：``YYYY-MM-DDTHH:MM:SS.ffffff``。

    Python 的 ``datetime`` 只到微秒，所以最多给到 6 位 —— 形状规则一致，位数少 3 位。
    （值本身也不可能一样：两边是各自的时钟。）
    """
    if value is None:
        return None
    base = value.strftime('%Y-%m-%dT%H:%M:%S')
    nanos = value.microsecond * 1000
    if nanos == 0:
        return base
    return f'{base}.{nanos:09d}'.rstrip('0')


def build_task_info(task) -> dict:
    """``buildTaskInfo``：字段全给（值为 null 时也写 null，不省键）。

    ``durationMillis`` / ``durationSeconds`` 只在 start 与 end **都有值**时才出现
    —— 不是「有就写 null」，是**键根本不出现**。
    """
    file_handle = task.file_handle or {}
    info = {
        'taskId': task.task_id,
        'fileId': file_handle.get('fileId'),
        'fileName': file_handle.get('fileName'),
        'status': task.status,
        'statusDescription': STATUS_DESCRIPTIONS.get(task.status),
        'retryCount': task.retry_count,
        'maxRetryCount': task.max_retry_count,
        'createTime': iso_local_datetime(task.create_time),
        'startTime': iso_local_datetime(task.start_time),
        'endTime': iso_local_datetime(task.end_time),
        'errorMessage': task.error_message,
    }
    if task.start_time is not None and task.end_time is not None:
        duration_millis = int((task.end_time - task.start_time).total_seconds() * 1000)
        info['durationMillis'] = duration_millis
        info['durationSeconds'] = duration_millis / 1000.0
    return info


def statistics() -> dict:
    """``getQueueStatistics``。键序与 ``QueueStatistics`` 的字段声明一致。"""
    return runtime.get_queue().statistics()


def task_detail(task_id: str) -> Optional[dict]:
    """``getTaskDetails``：查不到返回 None（由路由层装成 200 + ``success:false``）。"""
    task = runtime.get_queue().get_task(task_id)
    return None if task is None else build_task_info(task)


def failed_tasks() -> list[dict]:
    """``getFailedTasks``：**只数内存里的**，重启后是空数组。"""
    return [build_task_info(task) for task in runtime.get_queue().failed_tasks()]


def error_text(error: BaseException) -> Optional[str]:
    """取异常消息：异常可以没有消息，那时是 **null** 而不是空串。

    Python 的 ``str(Exception())`` 给的是 ``''``，直接透传会让前端拿到 ``""``
    而不是 ``null``（``/file-tasks/failed`` 里那句 ``Error: null`` 就是这么来的）。
    """
    text = str(error)
    return text or None


def is_terminal(task) -> bool:
    """终态判定（供测试与排障用）。"""
    return task.status in (STATUS_COMPLETED, STATUS_FAILED)


__all__ = [
    'STATUS_DESCRIPTIONS',
    'TASK_NOT_FOUND',
    'build_task_info',
    'error_text',
    'failed_tasks',
    'is_terminal',
    'iso_local_datetime',
    'statistics',
    'task_detail',
]
