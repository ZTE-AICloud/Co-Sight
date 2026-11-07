"""任务对象与状态机。

状态取值（入库与接口都用 ``.name()``）：
``PENDING`` / ``RUNNING`` / ``RETRY`` / ``COMPLETED`` / ``FAILED``。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

STATUS_PENDING = 'PENDING'
STATUS_RUNNING = 'RUNNING'
STATUS_RETRY = 'RETRY'
STATUS_COMPLETED = 'COMPLETED'
STATUS_FAILED = 'FAILED'

TERMINAL_STATUSES = (STATUS_COMPLETED, STATUS_FAILED)
# ``taskId2task`` 只保留未完成的任务；COMPLETED 时移除（FAILED 仍留着供查询）
ACTIVE_STATUSES = (STATUS_PENDING, STATUS_RUNNING, STATUS_RETRY, STATUS_FAILED)

TASK_TYPE_FILE_IMPORT = 'FILE_IMPORT'
# ``kb_import_task.related_identifier_id`` 是 ``bpchar(32)``，超长要截断
RELATED_ID_LENGTH = 32


class TaskStatus:
    """状态常量集合（保留大写常量名）。"""

    PENDING = STATUS_PENDING
    RUNNING = STATUS_RUNNING
    RETRY = STATUS_RETRY
    COMPLETED = STATUS_COMPLETED
    FAILED = STATUS_FAILED


@dataclass
class FileTask:
    """一个导入任务。

    :param file_handle: 文件句柄（dict）。从库里恢复的任务**没有**它 ——
        恢复时只取 fileId，所以恢复出来的任务查得到但跑不了。
    """

    task_id: str
    file_handle: Optional[dict] = None
    status: str = STATUS_PENDING
    retry_count: int = 0
    max_retry_count: int = 3
    create_time: datetime = field(default_factory=datetime.now)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    error_message: Optional[str] = None

    @staticmethod
    def new_task_id() -> str:
        """``UUID.randomUUID().toString().replace("-", "")`` —— 32 位十六进制。"""
        return uuid.uuid4().hex

    @property
    def related_identifier_id(self) -> Optional[str]:
        file_handle = self.file_handle or {}
        file_id = file_handle.get('fileId')
        return str(file_id)[:RELATED_ID_LENGTH] if file_id else None

    def can_retry(self) -> bool:
        return self.retry_count < self.max_retry_count

    def mark_as_running(self) -> None:
        self.status = STATUS_RUNNING
        self.start_time = datetime.now()

    def mark_as_retry(self) -> None:
        """注意：**先自增再重投**（``retry_count`` 先自增）。"""
        self.status = STATUS_RETRY
        self.retry_count += 1

    def mark_as_completed(self) -> None:
        self.status = STATUS_COMPLETED
        self.end_time = datetime.now()

    def mark_as_failed(self, reason: str) -> None:
        self.status = STATUS_FAILED
        self.end_time = datetime.now()
        self.error_message = reason

    def failure_message(self, exception) -> str:
        """``handleTaskFailure`` 的文案（含重试次数，便于排障）。

        ⚠️ 异常**没有消息**时格式化出来是字符串 ``null``
        —— 线上 ``/file-tasks/failed`` 里那句 ``Error: null`` 就是这么来的。
        Python 的 ``str(Exception())`` 给的是空串，得补回 ``null`` 才对得上。
        """
        text = str(exception)
        return 'Task failed after %d retries. Error: %s' % (
            self.retry_count, text if text else 'null')


def parse_status(raw: Any) -> str:
    """把库里的 ``status`` 字符串解析回枚举名；解析不了回落 ``PENDING``。"""
    text = str(raw or '').strip()
    return text if text in (STATUS_PENDING, STATUS_RUNNING, STATUS_RETRY,
                            STATUS_COMPLETED, STATUS_FAILED) else STATUS_PENDING
