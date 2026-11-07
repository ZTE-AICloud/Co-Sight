import psycopg2


class PgDatabase:
    def __init__(
            self,
            dbname: str,
            host: str,
            port: str,
            user: str,
            password: str) -> None:
        self.dbname = dbname
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self._connection = None

    def get_conn(self):
        if self._connection is None or self._connection.closed:
            self._connection = psycopg2.connect(
                user=self.user,
                password=self.password,
                host=self.host,
                port=self.port,
                database=self.dbname)
        return self._connection

    def commit(self):
        """提交当前事务"""
        if self._connection and not self._connection.closed:
            self._connection.commit()

    def rollback(self):
        """回滚当前事务"""
        if self._connection and not self._connection.closed:
            self._connection.rollback()

    def close(self):
        """关闭数据库连接"""
        if self._connection and not self._connection.closed:
            self._connection.close()

    def execute_query(self, sql, params=None):
        conn = None
        cur = None
        try:
            conn = self.get_conn()
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
            
            # 检查description是否存在且不为None
            if cur.description is None:
                return []
                
            columns = [column[0] for column in cur.description]
            return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            raise e
        finally:
            if cur:
                cur.close()

    def execute(self, sql, params=None, commit=True):
        conn = None
        cur = None
        try:
            conn = self.get_conn()
            cur = conn.cursor()
            cur.execute(sql, params)
            if commit:
                conn.commit()
        except Exception as e:
            if conn:
                conn.rollback()
            raise e
        finally:
            if cur:
                cur.close()

    def create_pg_schema(self, schema_name: str = 'public') -> None:
        self.execute(f'CREATE SCHEMA IF NOT EXISTS {schema_name};')
