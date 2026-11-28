"""真实任务链 E2E：文件导入成功/失败、图谱抽图、图谱导入。

容器内运行（后端 + PostgreSQL 同一栈）::

    docker cp tools/verify/verify-real-task-chain-e2e.py <rkb>:/tmp/
    docker exec <rkb> python3 -u /tmp/verify-real-task-chain-e2e.py

覆盖：

1. 文档库上传 md → 文件状态 1 → FILE_IMPORT 任务 COMPLETED、payload 带 fileHandle；
2. 空白 md → 文件状态 2 → 任务重试 4 次后 FAILED；
3. 图谱库建库 + 通用算子 -6 抽取 → GRAPH_EXTRACT SUCCESS、实体可查；
4. 导出图谱 zip → 修改 desc id/name 后导入 → GRAPH_IMPORT COMPLETED、实体可查。

导出的 ``document_chunk.jsonl`` 里 ``type='system'``；导入引擎会把它归一成
NULL 再写 smallint 列，完整导出/导入应该是一轮干净的 COMPLETED。
"""

import io
import json
import os
import sys
import time
import uuid
import zipfile

import requests

sys.path.insert(0, '/app/src')
from infrastructure.db.kb import connection  # noqa: E402

BASE = 'http://127.0.0.1:8091/api/co-knowledge/v1'
ORIGIN = 'http://127.0.0.1:8091'
POLL = 0.5
EMBEDDING = None
LLM = 'deepseek-v4-flash'


def one(sql, params=()):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()


def execute(sql, params=()):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)


def session():
    pwd = (os.environ.get('RKB_ADMIN_PASSWORD') or '').strip()
    if not pwd:
        with open(os.environ.get('RKB_ADMIN_PASSWORD_FILE',
                                 '/data/rkb/initial-admin-password')) as fh:
            pwd = fh.read().strip()
    s = requests.Session()
    s.headers.update({'Origin': ORIGIN, 'Referer': ORIGIN + '/'})
    r = s.post(f'{BASE}/auth/login', json={'username': 'admin', 'password': pwd}, timeout=10)
    assert r.status_code == 200, r.text
    return s


def create_doc_kb(s, name):
    r = s.post(f'{BASE}/knowledge-bases', json={
        'name': name, 'description': 'real task test',
        'props': {'embeddingModel': EMBEDDING}}, timeout=10)
    assert r.status_code in (200, 201), r.text
    return r.json()['id']


def directory_id(s, kb_id):
    rows = s.get(f'{BASE}/knowledge-bases/{kb_id}/directories?type=folder&sort=true',
                 timeout=10).json()
    if isinstance(rows, dict):
        rows = rows.get('items') or []
    return rows[0]['id']


def upload_md(s, kb_id, dir_id, name, content):
    metadata = {
        'kType': 'document', 'directoryId': dir_id, 'coverFlag': False,
        'splitType': 'system', 'parseOperator': {},
        'splitOperator': {'md': {
            'operatorId': -1, 'fileFormat': 'md',
            'args': [
                {'argName': 'maxWordCount', 'argType': 'int', 'defaultValue': 512},
                {'argName': 'overlap', 'argType': 'int', 'defaultValue': 128},
            ],
        }},
    }
    r = s.post(f'{BASE}/knowledge-bases/{kb_id}/documents',
               data={'metadata': json.dumps(metadata)},
               files={'files': (name, content, 'text/markdown')}, timeout=30)
    assert r.status_code in (200, 201, 202), r.text
    body = r.json()
    file_id = body.get(name)
    assert file_id, body
    return file_id


def file_status(s, kb_id, name):
    page = s.get(f'{BASE}/knowledge-bases/{kb_id}/documents?page=1&size=100',
                 timeout=10).json()
    row = next((r for r in page.get('items', [])
                if (r.get('title') or r.get('name')) == name), None)
    return row


def wait_file(s, kb_id, name, timeout=180):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = file_status(s, kb_id, name)
        if last and last.get('status') in (1, 2):
            return last
        time.sleep(POLL)
    raise AssertionError(f'file timeout: {last}')


def wait_task(sql, params, timeout=300):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = one(sql, params)
        if last and last[1] in ('COMPLETED', 'COMPLETED_WITH_ERRORS', 'FAILED'):
            return last
        time.sleep(POLL)
    raise AssertionError(f'task timeout: {last}')


def wait_unlocked(task_id, timeout=15):
    """graph runner 先写终态、引擎后释放租约，两者是两个事务；等锁真正清空。"""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = one('SELECT locked_by, locked_until FROM task_center.task WHERE id=%s',
                   (task_id,))
        if last and last[0] is None and last[1] is None:
            return
        time.sleep(0.05)
    raise AssertionError(f'task lock not released: {last}')


def cleanup_kb(s, kb_id):
    if not kb_id:
        return
    try:
        page = s.get(f'{BASE}/knowledge-bases/{kb_id}/documents?page=1&size=100',
                     timeout=10).json()
        for row in page.get('items', []):
            s.delete(f'{BASE}/knowledge-bases/{kb_id}/documents/{row["id"]}', timeout=30)
    except Exception:
        pass
    try:
        s.delete(f'{BASE}/knowledge-bases/{kb_id}', timeout=30)
    except Exception:
        pass


def delete_tasks_for_kb(kb_id):
    execute('DELETE FROM task_center.task WHERE kbase_id = %s', (kb_id,))


def test_file_success(s):
    name = f'E2E-REAL-{uuid.uuid4().hex[:6]}'
    kb_id = create_doc_kb(s, name)
    task_id = None
    try:
        dir_id = directory_id(s, kb_id)
        file_name = f'{name}.md'
        file_id = upload_md(
            s, kb_id, dir_id, file_name,
            f'# {name}\n\nClaude Code 真实任务测试。\n\n## 第二节\n\n这是用于切片和向量化的正文。')
        row = wait_file(s, kb_id, file_name)
        assert row.get('status') == 1, row
        task = wait_task(
            "SELECT id, status, payload, locked_by, locked_until, extra "
            "FROM task_center.task WHERE task_type='FILE_IMPORT' "
            "AND payload->>'fileId'=%s ORDER BY created_at DESC LIMIT 1",
            (file_id,))
        task_id = task[0]
        assert task[1] == 'COMPLETED', task
        assert task[2].get('fileHandle'), task
        wait_unlocked(task_id)
        extra = task[5] or {}
        assert int(extra.get('chunkCount') or 0) > 0, extra
        assert int(extra.get('vectorCount') or 0) > 0, extra
        assert int(extra.get('indexDocCount') or 0) > 0, extra
        assert set(extra.get('stageTimingsMs') or {}) >= {'parse', 'split', 'embed'}, extra
        chunks = s.get(f'{BASE}/knowledge-bases/{kb_id}/chunks?page=1&size=100',
                       timeout=10).json()
        assert int(chunks.get('total') or 0) > 0, chunks
        print('REAL file success: task COMPLETED, chunks=', chunks.get('total'))
    finally:
        cleanup_kb(s, kb_id)
        delete_tasks_for_kb(kb_id)


def test_file_failure(s):
    name = f'E2E-FAIL-{uuid.uuid4().hex[:6]}'
    kb_id = create_doc_kb(s, name)
    try:
        dir_id = directory_id(s, kb_id)
        file_name = f'{name}.md'
        file_id = upload_md(s, kb_id, dir_id, file_name, '\n\n   \n')
        row = wait_file(s, kb_id, file_name)
        assert row.get('status') == 2, row
        task = wait_task(
            "SELECT id, status, attempt, max_attempts, error_message "
            "FROM task_center.task WHERE task_type='FILE_IMPORT' "
            "AND payload->>'fileId'=%s ORDER BY created_at DESC LIMIT 1",
            (file_id,))
        assert task[1] == 'FAILED', task
        assert task[2] == 4 and task[3] == 4, task
        assert task[4], task
        print('REAL file failure: task FAILED after retries, error=', task[4][:60])
    finally:
        cleanup_kb(s, kb_id)
        delete_tasks_for_kb(kb_id)


def graph_extract(s, embedding):
    name = f'E2E-GRAPH-{uuid.uuid4().hex[:6]}'
    content = (f'# {name}\n\nAlice 是 Acme 公司的工程师，'
               'Bob 是 Alice 的同事。Acme 公司位于上海。\n')
    data = {
        'name': name, 'description': 'real graph task test', 'category': 10,
        'props': {'embeddingModel': embedding},
        'operatorId': -6, 'schemaId': 'General_Schema',
        'coverFlag': False, 'kwargs': {'llm': LLM},
    }
    r = s.post(f'{BASE}/graph-extractions',
               data={'data': json.dumps(data)},
               files={'file': (f'{name}.md', content, 'text/markdown')}, timeout=30)
    assert r.status_code == 202, r.text
    kb_id = r.json().get('id')
    if not kb_id:
        location = r.headers.get('Location', '')
        kb_id = location.rstrip('/').split('/')[-2] if location else None
    assert kb_id, r.headers
    try:
        task = wait_task(
            "SELECT id, status, progress, locked_by, locked_until, error_message, extra "
            "FROM task_center.task WHERE task_type='GRAPH_EXTRACT' "
            "AND kbase_id=%s ORDER BY created_at DESC LIMIT 1",
            (kb_id,), timeout=300)
        assert task[1] == 'COMPLETED', task
        wait_unlocked(task[0])
        extra = task[6] or {}
        assert extra.get('importTaskId'), extra
        assert extra.get('schemaId'), extra
        assert int(extra.get('entity_total') or 0) > 0, extra
        assert int(extra.get('vector_entities') or 0) > 0, extra
        kbase = one('SELECT status, schema_id FROM kb_kbase WHERE kbase_id=%s', (kb_id,))
        assert kbase and kbase[0] == 5, kbase
        query = s.post(f'{BASE}/knowledge-bases/{kb_id}/graph/query',
                       json={'query_type': 'entity'}, timeout=30).json()
        assert int(query.get('entity_num') or 0) > 0, query
        print('REAL graph extract: SUCCESS, entities=', query.get('entity_num'))
        export = s.get(f'{BASE}/knowledge-bases/{kb_id}/graph/export', timeout=60)
        assert export.status_code == 200 and export.content, export.status_code
        return kb_id, export.content
    except Exception:
        cleanup_kb(s, kb_id)
        delete_tasks_for_kb(kb_id)
        raise


def graph_import(s, export_bytes):
    entries = {}
    with zipfile.ZipFile(io.BytesIO(export_bytes)) as archive:
        for name in archive.namelist():
            entries[name] = archive.read(name)
    desc = json.loads(entries['desc.json'])
    new_id = 'graph_' + uuid.uuid4().hex[:16]
    new_name = f'E2E-GIMP-{uuid.uuid4().hex[:6]}'
    desc['id'] = new_id
    desc['name'] = new_name
    desc['desc'] = desc.get('desc') or 'e2e graph'
    entries['desc.json'] = json.dumps(desc, ensure_ascii=False).encode('utf-8')

    # 通用算子导出的 schema 描述可能为空；导入校验要求 schema/实体/边描述非空。
    if 'schema.json' in entries:
        schema = json.loads(entries['schema.json'])
        schema['schema_name'] = schema.get('schema_name') or 'e2e_schema'
        schema['schema_desc'] = schema.get('schema_desc') or 'e2e schema'
        for entity in schema.get('entities') or []:
            entity['entity_desc'] = entity.get('entity_desc') or 'e2e entity'
        for edge in schema.get('edges') or []:
            edge['edge_desc'] = edge.get('edge_desc') or 'e2e edge'
        entries['schema.json'] = json.dumps(schema, ensure_ascii=False).encode('utf-8')
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    r = s.post(f'{BASE}/graph-imports',
               files={'file': ('graph.zip', out.getvalue(), 'application/zip')},
               timeout=60)
    assert r.status_code == 202, r.text
    kb_id = new_id[len('graph_'):]
    try:
        task = wait_task(
            "SELECT id, status, progress, locked_by, locked_until, error_message, extra "
            "FROM task_center.task WHERE task_type='GRAPH_IMPORT' "
            "AND kbase_id=%s ORDER BY created_at DESC LIMIT 1",
            (kb_id,), timeout=300)
        assert task[1] in ('COMPLETED', 'COMPLETED_WITH_ERRORS'), task
        wait_unlocked(task[0])
        extra = task[6] or {}
        assert int(extra.get('vector_entities') or 0) > 0, extra
        assert int(extra.get('vector_edges') or 0) > 0, extra
        assert int(extra.get('entity_total') or 0) > 0, extra
        query = s.post(f'{BASE}/knowledge-bases/{kb_id}/graph/query',
                       json={'query_type': 'entity'}, timeout=30).json()
        assert int(query.get('entity_num') or 0) > 0, query
        print('REAL graph import:', task[1], 'entities=', query.get('entity_num'),
              'warning=', (task[5] or '')[:80])
        return kb_id
    finally:
        cleanup_kb(s, kb_id)
        delete_tasks_for_kb(kb_id)


def main():
    global EMBEDDING
    s = session()
    EMBEDDING = s.get(f'{BASE}/system/embedding-models', timeout=10).json()[0]
    test_file_success(s)
    test_file_failure(s)
    graph_kb, export_bytes = graph_extract(s, EMBEDDING)
    try:
        graph_import(s, export_bytes)
    finally:
        cleanup_kb(s, graph_kb)
        delete_tasks_for_kb(graph_kb.split('graph_')[-1] if graph_kb.startswith('graph_') else graph_kb)
    print('REAL TASK TESTS PASS')


if __name__ == '__main__':
    main()
