"""业务库连接与参数化查询。

单库部署后只有一套连接：库名/地址/口令全部来自 ``RKB_DB_*``
（见 :mod:`infrastructure.db.connection_info`）。没有运行态/设计态/发布态之分，
也没有图存储或发布库清表逻辑；模块加载不建连、不执行任何 DDL。
"""

from __future__ import annotations

import psycopg2

from infrastructure.db.connection_info import get_db_conn_info
from infrastructure.logging.logutil import log


class DatabaseOperator:
    """最小数据库操作器：一条连接 + 一个参数化查询口。"""

    def get_db_conn(self):
        info = get_db_conn_info()
        return psycopg2.connect(
            user=info.get('user'),
            password=info.get('password'),
            host=info.get('host'),
            port=info.get('port'),
            database=info.get('database'),
            connect_timeout=2,
        )

    def pg_select_zip_values_operator_with_params(self, sql, params):
        """执行参数化 SELECT，返回 ``(success, rows | error_message)``。

        ``params`` 非 ``None`` 时走 psycopg2 extended query protocol，**不允许**
        堆叠语句；这是图谱检索阻断注入的关键。
        """
        result = False
        conn = cursor = None
        try:
            conn = self.get_db_conn()
            cursor = conn.cursor()
            if params is None:
                cursor.execute(sql)
            else:
                cursor.execute(sql, params)
            values = cursor.fetchall()
            columns = [column[0] for column in cursor.description]
            resultvalues = [dict(zip(columns, row)) for row in values]
            result = True
        except Exception as e:
            log.warning('execute [%s] causes error: %s', sql, e)
            return result, str(e)
        finally:
            if cursor is not None:
                cursor.close()
            if conn is not None:
                conn.close()
        return result, resultvalues


_db_pool = DatabaseOperator()
