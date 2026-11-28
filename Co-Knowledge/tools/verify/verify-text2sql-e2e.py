"""Text2SQL 真实链路 E2E：数据源 → 语义 → 版本 → 发布 → 查询 → 历史/收藏/反馈。

容器内运行（后端 + PostgreSQL 同一栈）::

    docker cp tools/verify/verify-text2sql-e2e.py <rkb>:/tmp/
    docker exec <rkb> python3 -u /tmp/verify-text2sql-e2e.py

脚本会在本地 PostgreSQL 创建 ``text2sql_demo`` 库与只读账号 ``t2s_reader``，
再通过真实 API 完成建源、扫描、值/指标维护、版本构建发布和查询。

如果数据库账号没有 CREATEDB 权限，请先手工准备：
``text2sql_demo`` 库、只读账号、三张表与样例数据（见脚本 ``SETUP_SQL``）。
"""

import json
import os
import sys
import time

import psycopg2
import requests

sys.path.insert(0, '/app/src')
from infrastructure.db.connection_info import get_db_conn_info  # noqa: E402

BASE = 'http://127.0.0.1:8091/api/co-knowledge/v1'
ORIGIN = 'http://127.0.0.1:8091'
DS_NAME = 'E2E-Text2SQL-Demo'
DEMO_DB = 'text2sql_demo'

SETUP_SQL = """
CREATE TABLE IF NOT EXISTS region_info (city_id int primary key, city_name varchar(100) not null);
CREATE TABLE IF NOT EXISTS user_info (user_id bigint primary key, user_name varchar(100), city_id int references region_info(city_id));
CREATE TABLE IF NOT EXISTS order_info (order_id bigint primary key, user_id bigint references user_info(user_id), pay_amount numeric(12,2), status smallint, create_time timestamp);
TRUNCATE order_info, user_info, region_info;
INSERT INTO region_info VALUES (1,'西安市'),(2,'咸阳市'),(3,'宝鸡市');
INSERT INTO user_info VALUES (1,'陈晨',1),(2,'林悦',1),(3,'王宁',2),(4,'李青',2),(5,'周然',3),(6,'赵欣',3);
INSERT INTO order_info VALUES
 (1,1,52000,2, now() - interval '5 day'),(2,1,41220,2, now() - interval '10 day'),
 (3,2,60000,2, now() - interval '1 day'),(4,3,50000,2, now() - interval '8 day'),
 (5,4,32320,2, now() - interval '2 day'),(6,5,45600,2, now() - interval '12 day'),
 (7,6,18800,2, now() - interval '20 day'),(8,1,12000,2, now() - interval '40 day'),
 (9,2,9000,2, now() - interval '50 day'),(10,2,8000,1, now() - interval '3 day'),
 (11,3,4500,3, now() - interval '6 day'),(12,6,6600,1, now() - interval '1 day');
GRANT CONNECT ON DATABASE {db} TO t2s_reader;
GRANT USAGE ON SCHEMA public TO t2s_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO t2s_reader;
"""


def one(sql, params=()):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()


def connection():
    info = dict(get_db_conn_info())
    info.pop('driver', None)
    database = info.pop('database', 'rag_studio')
    return psycopg2.connect(database=database, connect_timeout=5, **info)


def setup_demo_database():
    info = dict(get_db_conn_info())
    info.pop('driver', None)
    admin = dict(info)
    admin['database'] = 'postgres'
    # 应用账号 rag_app 只有业务库 DML 权限；建库/建表需要 compose 的 POSTGRES_USER。
    if os.environ.get('POSTGRES_USER'):
        admin['user'] = os.environ['POSTGRES_USER']
    if os.environ.get('POSTGRES_PASSWORD'):
        admin['password'] = os.environ['POSTGRES_PASSWORD']
    conn = psycopg2.connect(connect_timeout=5, **admin)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (DEMO_DB,))
        if cur.fetchone() is None:
            cur.execute(f'CREATE DATABASE {DEMO_DB}')
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname='t2s_reader'")
        if cur.fetchone() is None:
            cur.execute("CREATE ROLE t2s_reader LOGIN PASSWORD 't2s_reader'")
    conn.close()
    demo = dict(admin)
    demo['database'] = DEMO_DB
    conn = psycopg2.connect(connect_timeout=5, **demo)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(SETUP_SQL.format(db=DEMO_DB))
    conn.close()
    print('DEMO DB READY')


def session():
    pwd = (os.environ.get('RKB_ADMIN_PASSWORD') or '').strip()
    if not pwd:
        with open(os.environ.get('RKB_ADMIN_PASSWORD_FILE',
                                 '/data/rkb/initial-admin-password')) as fh:
            pwd = fh.read().strip()
    s = requests.Session()
    s.headers.update({'Origin': ORIGIN, 'Referer': ORIGIN + '/'})
    r = s.post(f'{BASE}/auth/login', json={'username': 'admin', 'password': pwd},
               timeout=10)
    assert r.status_code == 200, r.text
    return s


def api(s, method, path, **kwargs):
    kwargs.setdefault('timeout', 60)
    return s.request(method, f'{BASE}{path}', **kwargs)


def ensure_datasource(s):
    payload = {
        'name': DS_NAME, 'dbType': 'postgresql', 'host': 'postgresql',
        'port': 5432, 'database': DEMO_DB, 'schemas': ['public'],
        'username': 't2s_reader', 'password': 't2s_reader',
        'topic': {'name': '电商经营分析', 'description': '订单、用户与城市',
                  'owner': 'admin'},
        'businessDescription': 'Text2SQL 只读演示库',
        'businessTimezone': 'Asia/Shanghai',
        'queryPolicy': {'read_only': True, 'max_rows': 200, 'timeout_ms': 15000},
    }
    rows = api(s, 'GET', '/text2sql/datasources').json()['items']
    existing = next((row for row in rows if row['name'] == DS_NAME), None)
    if existing:
        r = api(s, 'PATCH', f"/text2sql/datasources/{existing['id']}", json=payload)
        assert r.status_code == 200, r.text
        return r.json()['id']
    r = api(s, 'POST', '/text2sql/datasources', json=payload)
    assert r.status_code == 201, r.text
    return r.json()['id']


def enable_tables(s, ds_id):
    r = api(s, 'POST', f'/text2sql/datasources/{ds_id}/connection-test')
    assert r.status_code == 200, r.text
    r = api(s, 'POST', f'/text2sql/datasources/{ds_id}/scan')
    assert r.status_code == 200, r.text
    tables = api(s, 'GET', f'/text2sql/datasources/{ds_id}/tables').json()['items']
    assert {table['fullName'] for table in tables} >= {
        'public.order_info', 'public.region_info', 'public.user_info'}, tables
    for table in tables:
        r = api(s, 'PATCH', f"/text2sql/datasources/{ds_id}/tables/{table['id']}",
                json={'enabled': True})
        assert r.status_code == 200, r.text
    return tables


def ensure_values(s, ds_id, tables):
    columns = {f"{table['fullName']}.{column['name']}": column['id']
               for table in tables for column in table['columns']}
    wanted = [
        (columns['public.order_info.status'], '1', '未支付', ['待付款']),
        (columns['public.order_info.status'], '2', '已支付', ['支付', '已付款']),
        (columns['public.order_info.status'], '3', '已退款', ['退款']),
        (columns['public.region_info.city_name'], '西安市', '西安', ['西安']),
        (columns['public.region_info.city_name'], '咸阳市', '咸阳', ['咸阳']),
    ]
    existing = api(s, 'GET', f'/text2sql/datasources/{ds_id}/values').json()['items']
    have = {(item['columnId'], item['rawValue']) for item in existing}
    for column_id, raw, name, aliases in wanted:
        if (column_id, raw) in have:
            continue
        r = api(s, 'POST', f'/text2sql/datasources/{ds_id}/values', json={
            'columnId': column_id, 'rawValue': raw, 'valueType': 'varchar',
            'businessName': name, 'aliases': aliases, 'sourceType': 'MANUAL'})
        assert r.status_code == 201, r.text


def ensure_metrics(s, ds_id, tables):
    order = next(table for table in tables if table['fullName'] == 'public.order_info')
    wanted = [
        ('pay_amount', '支付金额', 'SUM(order_info.pay_amount)'),
        ('paid_users', '付费用户数', 'COUNT(DISTINCT order_info.user_id)'),
    ]
    existing = api(s, 'GET', f'/text2sql/datasources/{ds_id}/metrics').json()['items']
    have = {item['key'] for item in existing}
    for key, name, expression in wanted:
        if key in have:
            continue
        r = api(s, 'POST', f'/text2sql/datasources/{ds_id}/metrics', json={
            'key': key, 'businessName': name, 'baseTableId': order['id'],
            'expressionSql': expression, 'aggregationBehavior': 'ADDITIVE'})
        assert r.status_code == 201, r.text


def publish(s, ds_id):
    datasource = api(s, 'GET', f'/text2sql/datasources/{ds_id}').json()
    revision = datasource['revision']
    version = api(s, 'POST', f'/text2sql/datasources/{ds_id}/versions',
                  json={}).json()
    version_id = version.get('versionId') or version.get('version_id')
    built = api(s, 'POST',
                f'/text2sql/datasources/{ds_id}/versions/{version_id}/build').json()
    assert built['status'] == 'READY', built
    r = api(s, 'POST', f'/text2sql/datasources/{ds_id}/publication',
            json={'versionId': version_id, 'expectedRevision': revision})
    assert r.status_code == 201, r.text
    datasource = api(s, 'GET', f'/text2sql/datasources/{ds_id}').json()
    assert datasource['status'] == 'indexed', datasource
    return version_id


def query(s, ds_id, payload):
    r = api(s, 'POST', f'/text2sql/datasources/{ds_id}/query', json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def test_query(s, ds_id):
    data = query(s, ds_id, {
        'question': '查询最近30天每个城市的支付订单金额',
        'datePolicy': 'relative', 'parameters': {}, 'model': 'deepseek-v4-flash'})
    assert data['error'] is None, data['error']
    assert data['result']['row_count'] == 3, data['result']
    rows = {row[0]: float(row[1]) for row in data['result']['rows']}
    assert rows['西安市'] > rows['咸阳市'] > rows['宝鸡市'], rows
    assert 'status = 2' in data['sql']['final'], data['sql']['final']
    assert data['validation']['valid'] is True, data['validation']
    assert data['timing']['llm_ms'] > 0 and data['timing']['total_ms'] > 0
    print('QUERY OK', rows, 'llm_ms=', data['timing']['llm_ms'])
    return data


def test_guard(s, ds_id):
    for sql, code in [
        ('DELETE FROM public.order_info', 'SQL_UNSAFE'),
        ('SELECT 1; DROP TABLE public.order_info', 'SQL_UNSAFE'),
        ('SELECT * FROM public.secret', 'SQL_TABLE_NOT_ALLOWED'),
        ('SELECT * FROM public.order_info, public.secret', 'SQL_UNSAFE'),
        ('SELECT * FROM public.order_info FOR UPDATE', 'SQL_UNSAFE'),
    ]:
        data = query(s, ds_id, {'question': 'guard', 'datePolicy': 'relative',
                                'sql': sql})
        assert data['error'] and data['error']['code'] == code, (sql, data)
    data = query(s, ds_id, {'question': 'count', 'datePolicy': 'relative',
                            'sql': 'SELECT count(*) AS n FROM public.order_info'})
    assert data['error'] is None and data['result']['rows'][0][0] == 12, data
    print('SQL GUARD OK')


def test_history_favorites_feedback(s, ds_id, run):
    runs = api(s, 'GET', '/text2sql/runs?size=20').json()
    assert runs['total'] >= 1 and runs['items'][0]['request_id'], runs
    assert api(s, 'GET', f"/text2sql/runs/{run['id']}").status_code == 200

    favorite = api(s, 'POST', '/text2sql/favorites', json={
        'name': '城市支付金额', 'question': '查询最近30天每个城市的支付订单金额',
        'datasourceId': ds_id, 'datePolicy': 'relative', 'parameters': {}})
    assert favorite.status_code == 201, favorite.text
    favorite_id = favorite.json()['id']
    assert api(s, 'GET', '/text2sql/favorites').json()['total'] >= 1
    assert api(s, 'PATCH', f'/text2sql/favorites/{favorite_id}',
               json={'notes': 'e2e'}).status_code == 200
    assert api(s, 'DELETE', f'/text2sql/favorites/{favorite_id}').status_code == 204

    feedback = api(s, 'POST', f"/text2sql/runs/{run['id']}/feedback",
                   json={'category': 'meaning', 'notes': '口径核对'})
    assert feedback.status_code == 201, feedback.text
    assert api(s, 'GET', f'/text2sql/feedback?datasourceId={ds_id}').status_code == 200

    workspace = api(s, 'PUT', '/text2sql/workspace', json={
        'datasourceId': ds_id, 'questionDraft': '草稿',
        'sqlDraft': 'SELECT 1', 'preferences': {'datePolicy': 'relative'}})
    assert workspace.status_code == 200, workspace.text
    assert api(s, 'GET', '/text2sql/workspace').json()['questionDraft'] == '草稿'
    print('HISTORY/FAVORITES/FEEDBACK/WORKSPACE OK')


def main():
    setup_demo_database()
    s = session()
    ds_id = ensure_datasource(s)
    tables = enable_tables(s, ds_id)
    ensure_values(s, ds_id, tables)
    ensure_metrics(s, ds_id, tables)
    version_id = publish(s, ds_id)
    print('PUBLISHED', ds_id, version_id)
    run = test_query(s, ds_id)
    test_guard(s, ds_id)
    test_history_favorites_feedback(s, ds_id, run)
    print('TEXT2SQL E2E PASS')


if __name__ == '__main__':
    main()
