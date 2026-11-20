"""RUNNING 任务协作式取消 E2E。

建一个图谱抽图任务 → 等它进入 RUNNING → 调 ``POST /tasks/{id}/cancel`` →
等 runner 在安全点中止，任务落 CANCELLED，尝试历史也记 CANCELLED。

容器内运行::

    docker cp tools/verify/verify-task-running-cancel.py <rkb>:/tmp/
    docker exec <rkb> python3 -u /tmp/verify-task-running-cancel.py
"""

import json
import os
import sys
import time
import uuid

import requests

sys.path.insert(0, '/app/src')
from infrastructure.db.kb import connection  # noqa: E402

BASE = 'http://127.0.0.1:8091/api/co-knowledge/v1'
ORIGIN = 'http://127.0.0.1:8091'
POLL = 0.1
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
    r = s.post(f'{BASE}/auth/login',
               json={'username': 'admin', 'password': pwd}, timeout=10)
    assert r.status_code == 200, r.text
    return s


def wait_task(kb_id, want_running=True, timeout=60):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = one(
            "SELECT id, status, cancel_requested FROM task_center.task "
            "WHERE task_type='GRAPH_EXTRACT' AND kbase_id=%s "
            'ORDER BY created_at DESC LIMIT 1', (kb_id,))
        if last and (last[1] == 'RUNNING' if want_running
                     else last[1] in ('COMPLETED', 'COMPLETED_WITH_ERRORS',
                                      'FAILED', 'CANCELLED')):
            return last
        time.sleep(POLL)
    raise AssertionError(f'task timeout: {last}')


def cleanup(s, kb_id):
    if not kb_id:
        return
    try:
        page = s.get(f'{BASE}/knowledge-bases/{kb_id}/documents?page=1&size=100',
                     timeout=10).json()
        for row in page.get('items', []):
            s.delete(f'{BASE}/knowledge-bases/{kb_id}/documents/{row["id"]}',
                     timeout=30)
    except Exception:
        pass
    try:
        s.delete(f'{BASE}/knowledge-bases/{kb_id}', timeout=30)
    except Exception:
        pass
    execute('DELETE FROM task_center.task WHERE kbase_id=%s', (kb_id,))


def main():
    s = session()
    embedding = s.get(f'{BASE}/system/embedding-models', timeout=10).json()[0]
    name = f'E2E-CANCEL-{uuid.uuid4().hex[:6]}'
    content = (f'# {name}\n\n' + '\n'.join(
        f'第 {index} 段：Alice 是 Acme 公司的工程师，Bob 是她的同事，'
        f'Acme 公司位于上海，项目编号 {index}。'
        for index in range(80)) + '\n')
    data = {
        'name': name, 'description': 'running cancel e2e', 'category': 10,
        'props': {'embeddingModel': embedding},
        'operatorId': -6, 'schemaId': 'General_Schema',
        'coverFlag': False, 'kwargs': {'llm': LLM},
    }
    r = s.post(f'{BASE}/graph-extractions',
               data={'data': json.dumps(data)},
               files={'file': (f'{name}.md', content, 'text/markdown')},
               timeout=30)
    assert r.status_code == 202, r.text
    kb_id = r.json().get('id')
    assert kb_id, r.text
    task_id = None
    try:
        task = wait_task(kb_id, want_running=True, timeout=30)
        task_id = task[0]
        print('RUNNING task =', task_id)

        cancelled = s.post(f'{BASE}/tasks/{task_id}/cancel',
                           json={'reason': 'running cancel e2e'}, timeout=10)
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()['cancelRequested'] is True, cancelled.text

        final = wait_task(kb_id, want_running=False, timeout=120)
        print('FINAL =', final)
        assert final[0] == task_id, final
        assert final[1] == 'CANCELLED', final
        assert final[2] is True, final

        attempt = one(
            'SELECT status, error_message FROM task_center.task_attempt '
            'WHERE task_id=%s ORDER BY id DESC LIMIT 1', (task_id,))
        assert attempt and attempt[0] == 'CANCELLED', attempt

        kbase = one('SELECT status FROM kb_kbase WHERE kbase_id=%s', (kb_id,))
        assert kbase and kbase[0] == 101, kbase
        print('RUNNING CANCEL TEST PASS')
    finally:
        cleanup(s, kb_id)


if __name__ == '__main__':
    main()
