"""PG 访问层（建连 + 算子表的读写）。

保留：``execute``（图谱抽取进度回写）。
"""

import logging

import psycopg2

log = logging.getLogger(__name__)


class PGClient:
    def __init__(self, host, database, user, password, port):
        self._host = host
        self._database = database
        self._user = user
        self._password = password
        self._port = port

    def _get_db_params(self):
        db_params = {
            'host': self._host,
            'database': self._database,
            'user': self._user,
            'password': self._password,
            'port': self._port
        }
        return db_params

    def execute(self, sql, params=None, commit=True):
        connection = None
        cursor = None
        try:
            connection = psycopg2.connect(**self._get_db_params())
            cursor = connection.cursor()
            cursor.execute(sql, params)
            if commit:
                connection.commit()
        except Exception:
            # 进度回写由调用方（GraphProcess.update_kbase_process）兜底记录；
            # 这里先记一条带堆栈的日志再上抛，避免失败被静默吞掉。
            log.exception('执行 PG SQL 失败')
            raise
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

