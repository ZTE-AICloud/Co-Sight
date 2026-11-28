"""Text2SQL 全链路验证：建源 → 扫描 → 建版本 → 队列构建 → 发布 → 查询。

需要一个空库（18-text2sql.sql 已应用）与一个真实外部库；模型用打桩向量，
不依赖模型服务。连接信息用与运行库同一组 RKB_DB_*，脚本自己建 `demo` 外部库
和 `t2s_reader` 只读账号。

    RKB_DB_HOST=127.0.0.1 RKB_DB_PORT=5432 RKB_DB_NAME=t2s_scratch \
    RKB_DB_USER=rag RKB_DB_PASSWORD=... RKB_SECRET_KEY_FILE=/tmp/rkb/secret.key \
    PYTHONPATH=backend/src python3 tools/verify/text2sql-e2e-chain.py

用真实库跑之前注意最后一步会 DROP 某个数据源的向量表（验证缺表报错），
别指向正在用的数据源。

覆盖分表向量的三个关键假设：
  A. 首次构建按维度建出 vector(N) 表 + HNSW 索引；
  B. 维度变化时 ensure_table 报错而不是静默降级；
  C. 向量表缺失时检索直接报错，不用空结果掩盖状态不一致。
"""

import json
import os
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend' / 'src'))

import psycopg2

HOST = os.environ['RKB_DB_HOST']
PORT = int(os.environ['RKB_DB_PORT'])
DB = os.environ.get('RKB_DB_NAME') or 'a'
ADMIN = {'host': HOST, 'port': PORT,
         'user': os.environ.get('RKB_DB_USER') or 'a',
         'password': os.environ.get('RKB_DB_PASSWORD') or 'a'}

failures = []


def check(label, ok, detail=''):
    print(f'{"PASS" if ok else "FAIL":4s}  {label}  {detail}')
    if not ok:
        failures.append(label)


def admin(db=DB):
    return psycopg2.connect(dbname=db, connect_timeout=5, **ADMIN)


# ---------- 1. 外部演示库（只读账号） ----------
conn = admin()
conn.autocommit = True
with conn.cursor() as cur:
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname='t2s_reader'")
    if not cur.fetchone():
        cur.execute("CREATE ROLE t2s_reader LOGIN PASSWORD 't2s_reader' NOSUPERUSER")
    cur.execute("SELECT 1 FROM pg_database WHERE datname='demo'")
    if not cur.fetchone():
        cur.execute('CREATE DATABASE demo')
conn.close()

demo = admin('demo')
demo.autocommit = True
with demo.cursor() as cur:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS region (id int primary key, name varchar(50));
        CREATE TABLE IF NOT EXISTS orders (id int primary key, region_id int references region(id),
                                           amount numeric(10,2), status smallint, created_at timestamp);
        TRUNCATE orders, region;
        INSERT INTO region VALUES (1,'西安市'), (2,'咸阳市');
        INSERT INTO orders VALUES (1,1,100,2,now()), (2,2,200,2,now()), (3,1,50,1,now());
        GRANT CONNECT ON DATABASE demo TO t2s_reader;
        GRANT USAGE ON SCHEMA public TO t2s_reader;
        GRANT SELECT ON ALL TABLES IN SCHEMA public TO t2s_reader;
    """)
demo.close()
print('demo db ready')

# ---------- 2. 应用层全链路 ----------
from text_to_sql import vector_store
from text_to_sql.service import Text2SqlService

MODEL = 'test-embedding'
DIM = 8


def fake_embed(texts, model):
    return [[float(index + 1) for index in range(DIM)] for _ in texts]


service = Text2SqlService(embed=fake_embed)
service._resolve_embedding = lambda requested: (requested or MODEL, DIM)

ds = service.create_datasource({
    'name': f'验证源-{uuid4().hex[:6]}', 'host': '127.0.0.1', 'port': PORT,
    'database': 'demo', 'username': 't2s_reader', 'password': 't2s_reader',
    'schemas': ['public'], 'embeddingModel': MODEL,
})
ds_id = ds['id']
check('建源（含 embeddingModel）', ds['embeddingModel'] == MODEL, ds['embeddingModel'])

scan = service.scan(ds_id)
check('扫描（非超级用户账号）', scan['summary']['tablesAdded'] >= 2,
      str(scan['summary']))

tables = service.list_tables(ds_id)['items']
for table in tables:
    service.update_table(ds_id, table['id'], {'enabled': True})
check('启用表', len(tables) >= 2, f'{len(tables)} 张')

version = service.create_version(ds_id, {}, 'audit')
vid = version['versionId']
built = service.build_version(ds_id, vid)
check('构建到 READY', built['status'] == 'READY', built['status'])

with admin() as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT format_type(a.atttypid, a.atttypmod)
          FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
          JOIN pg_namespace n ON n.oid=c.relnamespace
         WHERE n.nspname='text2sql_index' AND c.relname=%s AND a.attname='embedding'
    """, (vector_store.table_name(ds_id),))
    row = cur.fetchone()
    check('A. 定长向量列', row and row[0] == f'vector({DIM})', str(row))
    cur.execute("SELECT indexdef FROM pg_indexes WHERE schemaname='text2sql_index' "
                "AND indexname=%s", (f'{vector_store.table_name(ds_id)}_hnsw',))
    hnsw = cur.fetchone()
    check('A. HNSW 索引存在', bool(hnsw) and 'hnsw' in hnsw[0],
          (hnsw[0][:60] if hnsw else 'missing'))

published = service.publish(ds_id, {'versionId': vid, 'expectedRevision': version['revision']},
                            'audit')
check('发布', bool(published.get('versionId')), str(published.get('revision')))

# 查询：走检索 + AST + 执行
from text_to_sql.query_service import Text2SqlQueryService

query_service = Text2SqlQueryService(embed=lambda question, model: [1.0] * DIM,
                                     llm=lambda **kwargs: {
                                         'sql': 'SELECT count(*) AS n FROM public.orders',
                                         'explanation': '订单数'})
query_service._rerank_model = None
response = query_service.run_query(ds_id, {'question': '订单总数'}, 'audit')
check('端到端查询成功', response['error'] is None,
      json.dumps(response.get('error'), ensure_ascii=False))
check('查询结果正确', (response.get('result') or {}).get('rows') == [[3]],
      str((response.get('result') or {}).get('rows')))
check('上下文带上了表', 'public.orders' in json.dumps(
    response['retrieval'].get('context') or {}, ensure_ascii=False),
    str((response['retrieval'].get('context') or {}).get('tables')))

# B. 维度变化必须报错
with admin() as conn, conn.cursor() as cur:
    try:
        vector_store.ensure_table(cur, ds_id, DIM + 4)
        check('B. 维度变化报错', False, '未报错')
    except ValueError as error:
        check('B. 维度变化报错', '不一致' in str(error), str(error)[:60])

# C. 向量表缺失时必须报错，不能静默返回空结果
with admin() as conn, conn.cursor() as cur:
    cur.execute(f'DROP TABLE {vector_store.qualified(ds_id)}')
from text_to_sql import query_repository

try:
    query_repository.search_knowledge(vid, [1.0] * DIM, 5, datasource_id=ds_id)
    check('C. 缺表时明确报错', False, '未报错')
except RuntimeError as error:
    check('C. 缺表时明确报错', '还没有向量表' in str(error), str(error)[:60])

print()
print('全部通过' if not failures else f'{len(failures)} 项失败：{failures}')
sys.exit(1 if failures else 0)
