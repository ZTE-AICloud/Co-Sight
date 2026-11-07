import os

from infrastructure.config.settings import Config


def get_work_dir():
    return Config.get('work_dir')


def get_log_dir():
    """日志目录：``LOG_DIR`` 优先（与编排侧同一规则），否则 ``<work_dir>/logs``。

    compose 把 ``/data/rkb/logs`` 挂成持久卷；不认 ``LOG_DIR`` 时 RKB 的日志会写进
    容器层 ``/app/logs``，重建即丢 —— 这正是两套 logger 各写一处、
    且 RKB 那份不持久的原因。
    """
    return os.environ.get('LOG_DIR', '').strip() or os.path.join(get_work_dir(), 'logs')
