"""统一任务表的物理位置。

任务管理独立在 ``task_center`` schema，业务表仍留在 ``public``。
"""

TASK_SCHEMA = 'task_center'
TASK_NAME = 'task'
TASK_TABLE = f'{TASK_SCHEMA}.{TASK_NAME}'
