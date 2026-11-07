"""数据库连接的**唯一**来源：只读 ``RKB_DB_*``。

单库部署后不再有运行态/设计态/发布态三套连接，也不再从 KMS/密钥文件读口令。
compose 负责把 ``POSTGRES_*`` 映射成 ``RKB_DB_*``；应用只认后者。
"""

from __future__ import annotations

import os

DEFAULT_DB_NAME = 'rag_studio'


def get_db_conn_info() -> dict:
    """返回 psycopg2 连接参数。

    未设 host/port/user 时传 ``None``，让 psycopg2 走本地默认（Unix socket /
    当前用户）—— 宿主上 ``postgresql`` 是 compose DNS 名，解析到不可达地址后会
    卡在 TCP 连接上；部署环境由 compose 显式注入全部 ``RKB_DB_*``。
    """
    return {
        'driver': 'psycopg2',
        'host': (os.environ.get('RKB_DB_HOST') or '').strip() or None,
        'port': (os.environ.get('RKB_DB_PORT') or '').strip() or None,
        'database': (os.environ.get('RKB_DB_NAME') or '').strip() or DEFAULT_DB_NAME,
        'user': (os.environ.get('RKB_DB_USER') or '').strip() or None,
        'password': os.environ.get('RKB_DB_PASSWORD', ''),
    }
