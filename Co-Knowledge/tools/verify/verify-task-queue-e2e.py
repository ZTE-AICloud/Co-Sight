"""任务持久化队列 E2E：真实后端 + 真实 PostgreSQL。

覆盖：

1. `task_center.task` 的队列列 / 兼容视图存在；
2. LISTEN/NOTIFY 通道可用；
3. **真实文件导入 API**：建库 → 上传 md → 文件状态 1 → 任务行 COMPLETED、
   payload 里 fileHandle 完整、租约已清；
4. **真实图谱抽图车道**：插入一条 operator 不存在的合成 GRAPH_EXTRACT 任务，
   运行中的 graph_extract 车道应认领、执行并落 FAILED，租约清空；
5. `FileTaskQueue.failed_tasks()` 在 DB 模式能查到库里的 FAILED 任务。

用法（容器内，后端与 DB 同进程网络）::

    docker cp tools/verify/verify-task-queue-e2e.py <rkb>:/tmp/
    docker exec <rkb> python3 -u /tmp/verify-task-queue-e2e.py

清理：文件/知识库走 API；合成任务行在 finally 删除。
"""

from __future__ import annotations

import argparse
import json
import os
import select
import sys
import time
import uuid

import requests

sys.path.insert(0, '/app/src')

from infrastructure.db.kb import connection  # noqa: E402
from infrastructure.tasks import pg_queue  # noqa: E402
from knowledge_base.task.queue import FileTaskQueue  # noqa: E402

BASE = 'http://127.0.0.1:8091/api/co-knowledge/v1'
TIMEOUT = 120
POLL = 0.3


def _one(sql, params):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()


def _execute(sql, params):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)


def _delete_task(task_id: str) -> None:
    if task_id:
        _execute('DELETE FROM task_center.task WHERE id = %s', (task_id,))


def _admin_password() -> str:
    value = (os.environ.get('RKB_ADMIN_PASSWORD') or '').strip()
    if value:
        return value
    path = (os.environ.get('RKB_ADMIN_PASSWORD_FILE')
            or '/data/rkb/initial-admin-password')
    try:
        with open(path, encoding='utf-8') as handle:
            return handle.read().strip()
    except OSError:
        return 'admin'


def _session() -> requests.Session:
    session = requests.Session()
    origin = BASE.split('/api/', 1)[0]
    # 本地会话的 CSRF 校验要求 Origin/Referer 的 host 与 Host 一致。
    session.headers.update({'Origin': origin, 'Referer': origin + '/'})
    username = (os.environ.get('RKB_ADMIN_USERNAME') or 'admin').strip()
    response = session.post(
        f'{BASE}/auth/login',
        json={'username': username, 'password': _admin_password()},
        timeout=10,
    )
    if response.status_code not in (200, 204):
        # AUTH_MODE=none 时登录不是必需的；其它失败在这里明确报出来。
        if 'auth' not in (response.text or '').lower():
            raise AssertionError(
                f'login failed: {response.status_code} {response.text[:200]}')
    return session


def check_schema():
    columns = {
        row[0] for row in _all(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='task_center' AND table_name='task'")
    }
    assert {'available_at', 'locked_by', 'locked_until', 'heartbeat_at'} <= columns, columns
    last_two = [
        row[0] for row in _all(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='task_center' AND table_name='task' "
            "ORDER BY ordinal_position DESC LIMIT 2")
    ]
    assert last_two == ['updated_at', 'created_at'], last_two
    views = {
        row[0] for row in _all(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name IN "
            "('kb_import_task','graph_extract_task','graph_import_task') "
            "AND table_type='VIEW'")
    }
    assert views == {'kb_import_task', 'graph_extract_task', 'graph_import_task'}, views
    print('schema/views ok')


def _all(sql, params=()):
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def check_notify():
    conn = pg_queue.listen_connection()
    try:
        pg_queue.notify('e2e_notify_lane')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if select.select([conn], [], [], 0.5)[0]:
                conn.poll()
                payloads = [note.payload for note in conn.notifies]
                if 'e2e_notify_lane' in payloads:
                    print('LISTEN/NOTIFY ok')
                    return
        raise AssertionError('NOTIFY not received')
    finally:
        conn.close()


def check_file_import(session: requests.Session):
    models = session.get(f'{BASE}/system/embedding-models', timeout=10).json()
    if not models:
        raise AssertionError('no embedding model')
    first = models[0]
    model = first if isinstance(first, str) else (
        first.get('value') or first.get('modelName') or first.get('name'))
    name = f'E2E-TASK-{uuid.uuid4().hex[:8]}'
    kb = session.post(
        f'{BASE}/knowledge-bases',
        json={'name': name, 'description': 'task queue e2e',
              'props': {'embeddingModel': model}},
        timeout=10,
    ).json()
    kb_id = kb.get('id') or kb.get('kbaseId')
    if not kb_id:
        raise AssertionError(f'create kb failed: {kb}')
    directory_id = None
    task_id = None
    try:
        rows = session.get(
            f'{BASE}/knowledge-bases/{kb_id}/directories?type=folder&sort=true',
            timeout=10,
        ).json()
        if isinstance(rows, dict):
            rows = rows.get('items') or []
        directory_id = rows[0]['id']
        file_name = f'{name}.md'
        content = f'# {name}\n\nE2E task queue.\n'
        metadata = {
            'kType': 'document', 'directoryId': directory_id,
            'coverFlag': False, 'splitType': 'system', 'parseOperator': {},
            'splitOperator': {'md': {
                'operatorId': -1, 'fileFormat': 'md',
                'args': [
                    {'argName': 'maxWordCount', 'argType': 'int', 'defaultValue': 512},
                    {'argName': 'overlap', 'argType': 'int', 'defaultValue': 128},
                ],
            }},
        }
        uploaded = session.post(
            f'{BASE}/knowledge-bases/{kb_id}/documents',
            data={'metadata': json.dumps(metadata)},
            files={'files': (file_name, content, 'text/markdown')},
            timeout=30,
        ).json()
        file_id = uploaded.get(file_name)
        if not file_id:
            raise AssertionError(f'upload failed: {uploaded}')

        deadline = time.monotonic() + TIMEOUT
        file_row = None
        while time.monotonic() < deadline:
            page = session.get(
                f'{BASE}/knowledge-bases/{kb_id}/documents?page=1&size=100',
                timeout=10,
            ).json()
            file_row = next(
                (row for row in page.get('items', [])
                 if (row.get('title') or row.get('name')) == file_name), None)
            if file_row and file_row.get('status') == 1:
                break
            if file_row and file_row.get('status') == 2:
                raise AssertionError(f'file import failed: {file_row}')
            time.sleep(POLL)
        else:
            raise AssertionError(f'file import timeout: {file_row}')

        task = _one(
            "SELECT id, status, payload, locked_by, locked_until "
            "FROM task_center.task WHERE task_type='FILE_IMPORT' "
            "AND payload->>'fileId' = %s ORDER BY created_at DESC LIMIT 1",
            (file_id,),
        )
        if not task:
            raise AssertionError('file task row not found')
        task_id, status, payload, locked_by, locked_until = task
        assert status == 'COMPLETED', task
        assert payload.get('fileHandle'), payload
        assert locked_by is None and locked_until is None, task
        view = _one('SELECT status FROM public.kb_import_task WHERE id = %s', (task_id,))
        assert view and view[0] == 'COMPLETED', view
        print('file import -> task_center.task ok')
    finally:
        try:
            page = session.get(
                f'{BASE}/knowledge-bases/{kb_id}/documents?page=1&size=100',
                timeout=10,
            ).json()
            for row in page.get('items', []):
                session.delete(
                    f'{BASE}/knowledge-bases/{kb_id}/documents/{row["id"]}',
                    timeout=30)
        except Exception:                                  # noqa: BLE001
            pass
        try:
            session.delete(f'{BASE}/knowledge-bases/{kb_id}', timeout=30)
        except Exception:                                  # noqa: BLE001
            pass
        _delete_task(task_id)


def check_graph_lane():
    task_id = f'e2e{uuid.uuid4().hex}'
    payload = {
        'tmpDir': f'/tmp/e2e-nonexistent-{task_id}/input',
        'dto': {'kbId': f'fake-{task_id}', 'operatorId': 999999},
        'schemaObj': None, 'isUpdate': False, 'cacheSchemaId': None,
        'schemaId': 'None', 'operatorId': 999999, 'fileCount': 1,
    }
    _execute(
        "INSERT INTO task_center.task "
        "(id, task_type, lane, status, progress, attempt, max_attempts, "
        " kbase_id, payload, available_at) "
        "VALUES (%s, 'GRAPH_EXTRACT', 'graph_extract', 'PENDING', 0, 1, 1, "
        "        %s, %s::jsonb, now())",
        (task_id, f'fake-{task_id}', json.dumps(payload)),
    )
    try:
        deadline = time.monotonic() + 30
        row = None
        while time.monotonic() < deadline:
            row = _one(
                'SELECT status, locked_by, locked_until, error_message '
                'FROM task_center.task WHERE id = %s', (task_id,))
            if row and row[0] == 'FAILED':
                break
            time.sleep(POLL)
        else:
            raise AssertionError(f'graph lane did not fail the task: {row}')
        assert row[1] is None and row[2] is None, row
        assert row[3], row
        view = _one(
            "SELECT status FROM public.graph_extract_task WHERE id = %s", (task_id,))
        assert view and view[0] == 'FAIL', view
        print('graph_extract lane claim -> FAILED ok')
    finally:
        _delete_task(task_id)


def check_failed_tasks_db():
    task_id = uuid.uuid4().hex
    payload = {'fileId': task_id, 'fileHandle': {'fileId': task_id, 'fileName': 'x.txt'}}
    _execute(
        "INSERT INTO task_center.task "
        "(id, task_type, lane, status, progress, attempt, max_attempts, "
        " kbase_id, payload, error_message, finish_time, available_at) "
        "VALUES (%s, 'FILE_IMPORT', 'file_import', 'FAILED', 0, 4, 4, "
        "        'e2e-kb', %s::jsonb, 'e2e failure', now(), now())",
        (task_id, json.dumps(payload)),
    )
    queue = FileTaskQueue(queue_mode='db')
    try:
        failed = queue.failed_tasks()
        match = next((task for task in failed if task.task_id == task_id), None)
        assert match is not None, 'failed task not found in DB query'
        assert match.error_message == 'Task failed after 3 retries. Error: e2e failure', \
            match.error_message
        print('failed_tasks DB query ok')
    finally:
        queue.shutdown()
        _delete_task(task_id)


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-file', action='store_true')
    parser.add_argument('--skip-graph', action='store_true')
    args = parser.parse_args(argv)

    check_schema()
    check_notify()
    session = _session()
    if not args.skip_file:
        check_file_import(session)
    if not args.skip_graph:
        check_graph_lane()
    check_failed_tasks_db()
    print('TASK QUEUE E2E PASS')


if __name__ == '__main__':
    main(sys.argv[1:])
