"""图谱写路径验证：schema 导入必须落到**唯一的** ``rag_studio``。

    docker cp tools/verify/verify-graph-write-path.py rag-studio-rag-knowledge-base-1:/tmp/
    docker exec rag-studio-rag-knowledge-base-1 python3 /tmp/verify-graph-write-path.py

脚本自己清理导入的 schema（按名字删），不留痕迹。
"""
import io
import json
import os
import time
import urllib.request
import zipfile

import psycopg2

# 对外只有一个前缀；根路径 `/graph/schema/import` 会 404。
# 路由实际是 `<RKB_PREFIX>/graph/schema/import`。
RKB = 'http://127.0.0.1:8091/api/co-knowledge/v1'
# schema 名校验只允许字母/数字/下划线/中文（连字符会被 0005 拒绝）
NAME = 'b3pre_write_%d' % int(time.time())


def pg(dbname):
    return psycopg2.connect(host=os.environ.get('RKB_DB_HOST', os.environ.get('POSTGRES_HOST', 'postgresql')),
                            port=os.environ.get('RKB_DB_PORT', os.environ.get('POSTGRES_PORT', '5432')),
                            user=os.environ.get('RKB_DB_USER', os.environ.get('POSTGRES_USER', 'rag')),
                            password=os.environ.get('RKB_DB_PASSWORD', os.environ.get('POSTGRES_PASSWORD', '')),
                            dbname=dbname)


def build_zip():
    # schema 校验要求实体/边也带描述（只有类型名会被 0005 拒绝）
    schema = {
        'schema_name': NAME,
        'schema_desc': 'B3-pre 合并验证临时 schema',
        'entities': [{
            'entity_type': 'Person', 'entity_desc': '人物实体',
            'properties': [{
                'name': 'name', 'type': 'STRING', 'desc': '姓名',
                'is_primary': True, 'is_embedding': False, 'is_index': True,
            }],
        }],
        'edges': [{
            'edge_type': 'Knows', 'edge_desc': '认识关系', 'direction': 'two-way',
            'source_entity': 'Person', 'target_entity': 'Person',
            'properties': [{
                'name': 'since', 'type': 'DATE', 'desc': '认识时间',
                'is_embedding': False, 'is_index': True,
            }],
        }],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('schema.json', json.dumps(schema, ensure_ascii=False))
    return buffer.getvalue()


def multipart(content):
    b = '----kbapiboundary'
    body = (f'--{b}\r\nContent-Disposition: form-data; name="schema_file"; '
            f'filename="s.zip"\r\nContent-Type: application/zip\r\n\r\n').encode()
    return body + content + f'\r\n--{b}--\r\n'.encode(), b


def main():
    content, boundary = multipart(build_zip())
    req = urllib.request.Request(f'{RKB}/graph/schema/import', data=content, method='POST',
                                 headers={'Content-Type': f'multipart/form-data; boundary={boundary}',
                                          'X-Emp-No': 'admin', 'username': 'admin'})
    with urllib.request.urlopen(req, timeout=120) as response:
        body = json.loads(response.read())
    print('导入响应:', json.dumps(body, ensure_ascii=False)[:300])

    failures = []
    dbname = 'rag_studio'
    try:
        conn = pg(dbname)
    except Exception as error:
        print(f'  {dbname}: 连不上（{error}）')
        failures.append(f'{dbname} 连不上：{error}')
    else:
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT to_regclass('public.graph_schema')")
                exists = cursor.fetchone()[0] is not None
                count = None
                if exists:
                    cursor.execute('SELECT count(*) FROM graph_schema WHERE schema_name = %s', (NAME,))
                    count = cursor.fetchone()[0]
            print(f'  {dbname}: graph_schema 表存在={exists} 本次导入行数={count}')
            if not (exists and count == 1):
                failures.append(f'{dbname} 应当有这次导入的行，实际 exists={exists} count={count}')
        finally:
            conn.close()

    # 清理：删掉本次导入的 schema
    conn = pg('rag_studio')
    try:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM graph_schema WHERE schema_name = %s', (NAME,))
            print(f'清理：删除 {cursor.rowcount} 行')
        conn.commit()
    finally:
        conn.close()

    print('\n'.join(f'FAIL {f}' for f in failures) or 'ok  写路径单向落到 rag_studio')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
