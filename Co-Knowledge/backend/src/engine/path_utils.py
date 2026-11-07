"""路径工具（只保留日志目录）。

配置由运行期提供，日志写容器内目录。
"""
import os


def get_log_dir() -> str:
    log_dir = os.environ.get('LOG_DIR', '/tmp/rkb-logs')
    os.makedirs(log_dir, exist_ok=True)
    return log_dir
