"""抽图任务状态查询（``GET /graph/task/{taskId}`` 与 ``GET /graph/task/{taskId}``）。

**两个端点输出字节级相同** —— v1 的 ``GraphExtractController`` 与 v2 的
``GraphExtractControllerV2`` 在这条路径上是同一份实现（同样的校验、同样的 DTO、
同样的 i18n 键），只差 v2 用 ``TxLog`` 打日志。所以这里一个函数服务两条路由。

## 三处要注意

1. 找不到任务回的是 **0004**（``IllegalArgumentException``），**不是** 0005 ——
   这是本接口层里少见的「业务失败走校验码」。
2. ``taskId`` 超 50 字符也回 0004，且文案里带**当前长度**。
3. 五个时间字段按 ``yyyy-MM-dd HH:mm:ss`` 序列化（``spring.jackson.date-format``，
   时区 GMT+8）。PG 那边是 ``timestamp without time zone``，本来就是本地时间，
   直接格式化即可 —— 别再套一次时区转换。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from shared.errors.api import KbValidationError
from graph.repository import graph_extract_store
from infrastructure.logging.logutil import log

# ``GraphExtractTaskQueryResponseDTO`` 的字段（声明序 = JSON 键序）
_DATE_FIELDS = ('createdDate', 'updatedDate', 'startTime', 'finishTime')

# ``validateTaskId`` 的长度上限
TASK_ID_MAX = 50

# ``SysGlobalConst``：v2 建任务时 ``created_by`` 写的是当前用户；v1 写死 "system"
# （见各建任务路径，这里只是常量供调用方用）
DEFAULT_TASK_CREATOR = 'system'


def query_task_status(task_id: Optional[str]) -> dict:
    """``queryTaskStatus``（v1/v2 共用）。"""
    _validate_task_id(task_id)

    task = graph_extract_store.select_task(task_id)
    if task is None:
        # ⚠️ **0004**，不是 0005。文案带任务 ID，且跟随请求语言。
        log.error('graph extract task not found: %s', task_id)
        raise KbValidationError('graph.extract.task.not.exist', task_id)

    return {
        'taskId': task.get('id'),
        'kbId': task.get('kb_id'),
        'schemaId': task.get('schema_id'),
        'operatorId': task.get('operator_id'),
        'fileCount': task.get('file_count'),
        'status': task.get('status'),
        'progress': task.get('progress'),
        'errorMessage': task.get('error_message'),
        'resultFilePath': task.get('result_file_path'),
        'createdBy': task.get('created_by'),
        'createdDate': _format_date(task.get('created_at')),
        'updatedDate': _format_date(task.get('updated_at')),
        'startTime': _format_date(task.get('start_time')),
        'finishTime': _format_date(task.get('finish_time')),
    }


def _validate_task_id(task_id: Optional[str]) -> None:
    """``validateTaskId``：空/全空白 → ``taskid.empty``；超 50 → ``taskid.length.exceed``。"""
    if task_id is None or not str(task_id).strip():
        raise KbValidationError('graph.extract.taskid.empty')
    if len(str(task_id)) > TASK_ID_MAX:
        raise KbValidationError('graph.extract.taskid.length.exceed', len(str(task_id)))


def _format_date(value: Any) -> Optional[str]:
    """``spring.jackson.date-format: yyyy-MM-dd HH:mm:ss``（GMT+8）。

    PG 的 ``timestamp without time zone`` 取出来就是 naive datetime，容器 TZ 为
    Asia/Shanghai —— 按 GMT+8 口径，所以**直接格式化**。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    return str(value)
