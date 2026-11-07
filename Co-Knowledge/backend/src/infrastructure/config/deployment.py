from infrastructure.config.settings import Config
import os


def is_dev_mode():
    return Config.get('dev_mode') == 'true'


def get_maintenance_work_mem():
    """
    获取索引创建的maintenance_work_mem配置
    默认值: 256MB
    """
    return os.environ.get('MAINTENANCE_WORK_MEM', '256MB')


def get_max_parallel_maintenance_workers():
    """
    获取索引创建的max_parallel_maintenance_workers配置
    默认值: 0 (取值为0时，不设置该参数)
    取值范围: 0-5
    """
    value = os.environ.get('MAX_PARALLEL_MAINTENANCE_WORKERS', '0')
    try:
        int_value = int(value)
        # 限制范围在0-5之间
        return max(0, min(5, int_value))
    except ValueError:
        return 0

