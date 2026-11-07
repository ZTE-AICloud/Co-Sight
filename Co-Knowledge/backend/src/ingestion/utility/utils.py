"""文档处理的配置与路径定位。

本模块**零第三方依赖**：不要引入 tornado 之类的 HTTP 层依赖。

## 路径基准

本文件已迁到 ``ingestion/utility/utils.py``，所以 ``get_project_dir()`` 指向
``ingestion/`` —— ``config/``、``split/operator_all.json`` 都随之定义在包内。
**注意**：系统算子入口（``operators/text_split``）
**不在**这个基准下，它们位于 import 根（``src/``），解析见
``ingestion/split/system_split_manager.py``（用显式的 import 根，不用本函数）。
"""

import os

from pyaml_env import parse_config


def get_project_dir():
    """``ingestion/`` 包目录（本文件上溯两层）。"""
    return os.path.dirname(os.path.dirname(__file__))


def get_config() -> dict:
    project_dir = get_project_dir()
    # 根据环境变量选择配置文件
    env = os.getenv('server_env', 'dev')  # 默认为开发环境
    config_file = f'{project_dir}/config/config_{env}.yaml'
    # 读取配置文件
    return parse_config(config_file)
