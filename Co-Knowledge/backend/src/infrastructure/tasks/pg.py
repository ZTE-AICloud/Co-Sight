"""统一任务表的物理位置。

任务管理独立在 ``task_center`` schema，业务表仍留在 ``public``；旧的三张表是
``public`` 下的只读兼容视图（见 ``deploy/init/pg/10-unify-task-tables.sql``）。
"""

TASK_SCHEMA = 'task_center'
TASK_NAME = 'task'
TASK_TABLE = f'{TASK_SCHEMA}.{TASK_NAME}'
