"""统一任务管理面 E2E：列表/统计/详情/取消/重试/优先级/准入错误。

容器内运行（后端 + PostgreSQL 同一栈）::

    docker cp tools/verify/verify-task-management.py <rkb>:/tmp/
    docker exec <rkb> python3 -u /tmp/verify-task-management.py

取消/重试/优先级用 ``file_import_internal`` 车道上的合成任务验证：该 lane 没有
worker 认领，任务不会被执行；测试结束删除全部合成行。
"""

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

BASE = 'http://127.0.0.1:8091/api/co-knowledge/v1'
ORIGIN = 'http://127.0.0.1:8091'
LANE = 'file_import_internal'
EMBEDDING = None


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


def api(s, method, path, **kwargs):
    kwargs.setdefault('timeout', 30)
    return s.request(method, f'{BASE}{path}', **kwargs)


def insert_task(task_id, status='PENDING', priority=0, task_type='FILE_IMPORT',
                payload='{}', kbase_id='mgmt-e2e'):
    execute(
        "INSERT INTO task_center.task "
        "(id, task_type, lane, status, progress, attempt, max_attempts, kbase_id, "
        " payload, extra, available_at, priority, finish_time, locked_by, locked_until) "
        "VALUES (%s, %s, %s, %s, 0, 1, 4, %s, %s::jsonb, NULL, now(), %s, "
        "        CASE WHEN %s IN ('COMPLETED','FAILED','CANCELLED') THEN now() END, "
        "        CASE WHEN %s = 'RUNNING' THEN 'mgmt-test' END, "
        "        CASE WHEN %s = 'RUNNING' THEN now() + interval '1 minute' END)",
        (task_id, task_type, LANE, status, kbase_id, payload, priority,
         status, status, status))


def task_row(task_id):
    return one(
        'SELECT status, priority, attempt, cancel_requested, finish_time '
        'FROM task_center.task WHERE id=%s', (task_id,))


def create_doc_kb(s, name):
    r = api(s, 'POST', '/knowledge-bases', json={
        'name': name, 'description': 'cancel hook e2e',
        'props': {'embeddingModel': EMBEDDING}})
    assert r.status_code in (200, 201), r.text
    return r.json()['id']


def directory_id(s, kb_id):
    rows = api(s, 'GET',
               f'/knowledge-bases/{kb_id}/directories?type=folder&sort=true').json()
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
    r = api(s, 'POST', f'/knowledge-bases/{kb_id}/documents',
            data={'metadata': json.dumps(metadata)},
            files={'files': (name, content, 'text/markdown')})
    assert r.status_code in (200, 201, 202), r.text
    file_id = r.json().get(name)
    assert file_id, r.text
    return file_id


def wait_file(s, kb_id, name, timeout=120):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        page = api(s, 'GET',
                   f'/knowledge-bases/{kb_id}/documents?page=1&size=100').json()
        last = next((row for row in page.get('items', [])
                     if (row.get('title') or row.get('name')) == name), None)
        if last and last.get('status') in (1, 2):
            return last
        time.sleep(0.3)
    raise AssertionError(f'file timeout: {last}')


def cleanup_kb(s, kb_id):
    try:
        page = api(s, 'GET',
                   f'/knowledge-bases/{kb_id}/documents?page=1&size=100').json()
        for row in page.get('items', []):
            api(s, 'DELETE', f'/knowledge-bases/{kb_id}/documents/{row["id"]}')
    except Exception:
        pass
    try:
        api(s, 'DELETE', f'/knowledge-bases/{kb_id}')
    except Exception:
        pass


def test_cancel_notify():
    conn = pg_queue.listen_connection()
    try:
        pg_queue.notify_cancel('probe-task')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if select.select([conn], [], [], 0.5)[0]:
                conn.poll()
                while conn.notifies:
                    note = conn.notifies.pop(0)
                    if (note.channel == pg_queue.CANCEL_NOTIFY_CHANNEL
                            and note.payload == 'probe-task'):
                        print('MGMT cancel NOTIFY OK')
                        return
        raise AssertionError('cancel NOTIFY not received')
    finally:
        conn.close()


def test_list_stats_detail(s):
    listing = api(s, 'GET', '/tasks?size=5')
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert set(body) >= {'items', 'total', 'page', 'pageSize'}, body
    assert body['pageSize'] == 5 and len(body['items']) <= 5
    assert body['total'] >= len(body['items'])

    stats = api(s, 'GET', '/tasks/stats')
    assert stats.status_code == 200, stats.text
    stats_body = stats.json()
    assert stats_body['total'] >= body['total']
    assert set(stats_body['byStatus']) >= {
        'PENDING', 'RUNNING', 'RETRY', 'COMPLETED', 'COMPLETED_WITH_ERRORS',
        'FAILED', 'CANCELLED'}
    assert 'queueDepth' in stats_body and 'oldestPendingAgeSeconds' in stats_body

    task_id = body['items'][0]['id']
    detail = api(s, 'GET', f'/tasks/{task_id}')
    assert detail.status_code == 200, detail.text
    detail_body = detail.json()
    assert 'payload' in detail_body and 'extra' in detail_body
    assert 'fileName' in body['items'][0] and 'kbaseName' in body['items'][0]
    print('MGMT list/stats/detail OK, total=', body['total'],
          'queueDepth=', stats_body['queueDepth'])


def test_groups_and_names(s):
    kept = api(s, 'GET', '/tasks?keyword=E2E-PAYLOAD&size=5')
    assert kept.status_code == 200, kept.text
    rows = kept.json()['items']
    assert any(row.get('fileName') == 'E2E-PAYLOAD-734b0c.md' for row in rows), rows
    assert any(row.get('kbaseName') == 'E2E-PAYLOAD-734b0c' for row in rows), rows

    groups = api(s, 'GET', '/tasks/groups?keyword=E2E-PAYLOAD&size=5')
    assert groups.status_code == 200, groups.text
    group_body = groups.json()
    assert group_body['total'] >= 1, group_body
    group = group_body['items'][0]
    assert group['kbaseName'] == 'E2E-PAYLOAD-734b0c', group
    assert group['total'] >= 1, group
    assert 'taskTotal' in group_body, group_body

    children = api(s, 'GET',
                   f"/tasks?kbase_id={group['kbaseId']}&size=20")
    assert children.status_code == 200, children.text
    assert children.json()['total'] >= 1, children.text
    print('MGMT groups/file/kbase names OK')


def test_filters_and_errors(s):
    filtered = api(s, 'GET', '/tasks?task_type=FILE_IMPORT&status=FAILED&size=5')
    assert filtered.status_code == 200, filtered.text
    for item in filtered.json()['items']:
        assert item['taskType'] == 'FILE_IMPORT'
        assert item['status'] == 'FAILED'

    bad_status = api(s, 'GET', '/tasks?status=PENDING,BOGUS')
    assert bad_status.status_code == 422, bad_status.text
    assert bad_status.json()['code'] == 'validation_failed'

    bad_size = api(s, 'GET', '/tasks?size=201')
    assert bad_size.status_code == 422, bad_size.text

    sample = api(s, 'GET', '/tasks?size=1').json()['items'][0]
    by_keyword = api(s, 'GET', f"/tasks?keyword={sample['id']}")
    assert by_keyword.status_code == 200, by_keyword.text
    assert any(item['id'] == sample['id'] for item in by_keyword.json()['items'])

    missing = api(s, 'GET', '/tasks/does-not-exist')
    assert missing.status_code == 404, missing.text
    assert missing.json()['code'] == 'task_not_found'
    print('MGMT filters/errors OK')


def test_cancel_retry_priority(s):
    cancel_id = uuid.uuid4().hex
    retry_id = uuid.uuid4().hex
    running_id = uuid.uuid4().hex
    completed_id = uuid.uuid4().hex
    low_id = uuid.uuid4().hex
    high_id = uuid.uuid4().hex
    expired_id = uuid.uuid4().hex
    ids = [cancel_id, retry_id, running_id, completed_id, low_id, high_id, expired_id]
    try:
        insert_task(cancel_id)
        insert_task(retry_id)
        insert_task(running_id, status='RUNNING')
        insert_task(completed_id, status='COMPLETED')
        insert_task(low_id, priority=0)
        insert_task(high_id, priority=10)
        insert_task(expired_id, status='FAILED', task_type='GRAPH_IMPORT',
                    payload='{"zipPath": "/tmp/definitely-missing-graph.zip"}')

        cancelled = api(s, 'POST', f'/tasks/{cancel_id}/cancel',
                        json={'reason': 'e2e cancel'})
        assert cancelled.status_code == 200, cancelled.text
        cancelled_body = cancelled.json()
        assert cancelled_body['status'] == 'CANCELLED', cancelled_body
        assert cancelled_body['cancelRequested'] is True, cancelled_body
        assert cancelled_body['errorMessage'] == 'e2e cancel', cancelled_body
        row = task_row(cancel_id)
        assert row[0] == 'CANCELLED' and row[4] is not None, row

        again = api(s, 'POST', f'/tasks/{cancel_id}/cancel')
        assert again.status_code == 409, again.text
        assert again.json()['code'] == 'task_not_cancellable'

        running = api(s, 'POST', f'/tasks/{running_id}/cancel')
        assert running.status_code == 200, running.text
        assert running.json()['status'] == 'RUNNING', running.text
        assert running.json()['cancelRequested'] is True, running.text
        assert pg_queue.cancel_requested_ids([running_id]) == [running_id]
        assert pg_queue.cancel_running(running_id, 'mgmt-test',
                                       'Cancelled by user'), task_row(running_id)
        assert task_row(running_id)[0] == 'CANCELLED', task_row(running_id)

        retried = api(s, 'POST', f'/tasks/{retry_id}/cancel')
        assert retried.status_code == 200, retried.text
        retried = api(s, 'POST', f'/tasks/{retry_id}/retry')
        assert retried.status_code == 200, retried.text
        assert retried.json()['status'] == 'PENDING', retried.text
        row = task_row(retry_id)
        assert row[0] == 'PENDING' and row[2] == 1 and row[3] is False, row

        not_retryable = api(s, 'POST', f'/tasks/{completed_id}/retry')
        assert not_retryable.status_code == 409, not_retryable.text
        assert not_retryable.json()['code'] == 'task_not_retryable'

        expired = api(s, 'POST', f'/tasks/{expired_id}/retry')
        assert expired.status_code == 409, expired.text
        assert expired.json()['code'] == 'task_input_expired'

        patched = api(s, 'PATCH', f'/tasks/{low_id}', json={'priority': 50})
        assert patched.status_code == 200, patched.text
        assert patched.json()['priority'] == 50, patched.text
        first = one(
            'SELECT id FROM task_center.task WHERE id IN (%s, %s) '
            'ORDER BY priority DESC, created_at LIMIT 1',
            (low_id, high_id))
        assert first and first[0] == low_id, first

        claimed = pg_queue.claim(LANE, ['FILE_IMPORT'], 'mgmt-claim-probe', 60)
        assert claimed and claimed['id'] == low_id, claimed
        pg_queue.release(claimed['id'], 'mgmt-claim-probe')

        running_patch = api(s, 'PATCH', f'/tasks/{running_id}', json={'priority': 9})
        assert running_patch.status_code == 409, running_patch.text
        assert running_patch.json()['code'] == 'task_not_queued'

        bad_priority = api(s, 'PATCH', f'/tasks/{high_id}', json={'priority': 1001})
        assert bad_priority.status_code == 422, bad_priority.text
        print('MGMT cancel/retry/priority OK')
    finally:
        for task_id in ids:
            execute('DELETE FROM task_center.task WHERE id=%s', (task_id,))


def test_cancel_hook(s):
    """取消真实文件任务（合成行指向真实 fileId）要同步文件状态。"""
    name = f'E2E-MGMT-{uuid.uuid4().hex[:6]}'
    kb_id = create_doc_kb(s, name)
    task_id = uuid.uuid4().hex
    try:
        dir_id = directory_id(s, kb_id)
        file_name = f'{name}.md'
        file_id = upload_md(
            s, kb_id, dir_id, file_name,
            f'# {name}\n\n用于验证取消回调会同步文件状态。\n')
        row = wait_file(s, kb_id, file_name)
        assert row.get('status') == 1, row

        insert_task(task_id, payload=json.dumps({'fileId': file_id}),
                    kbase_id=kb_id)
        cancelled = api(s, 'POST', f'/tasks/{task_id}/cancel',
                        json={'reason': 'hook e2e'})
        assert cancelled.status_code == 200, cancelled.text

        file_row = one('SELECT status, fail_reason FROM kb_directory WHERE id=%s',
                       (file_id,))
        assert file_row and file_row[0] == 2, file_row
        assert file_row[1] == 'Task cancelled', file_row

        retried = api(s, 'POST', f'/tasks/{task_id}/retry')
        assert retried.status_code == 200, retried.text
        file_row = one('SELECT status, fail_reason FROM kb_directory WHERE id=%s',
                       (file_id,))
        assert file_row and file_row[0] == 0, file_row
        assert file_row[1] is None, file_row
        print('MGMT cancel/retry hooks OK')
    finally:
        cleanup_kb(s, kb_id)
        execute('DELETE FROM task_center.task WHERE id=%s OR kbase_id=%s',
                (task_id, kb_id))


def test_attempt_history(s):
    task_id = uuid.uuid4().hex
    try:
        insert_task(task_id)
        execute(
            "UPDATE task_center.task SET status='RUNNING', locked_by='mgmt-e2e', "
            "locked_until=now() + interval '1 minute', start_time=now() WHERE id=%s",
            (task_id,))
        execute(
            "UPDATE task_center.task SET status='FAILED', error_message='first boom', "
            "finish_time=now(), locked_by=NULL, locked_until=NULL WHERE id=%s",
            (task_id,))

        detail = api(s, 'GET', f'/tasks/{task_id}')
        assert detail.status_code == 200, detail.text
        attempts = detail.json()['attempts']
        assert len(attempts) == 1, attempts
        assert attempts[0]['status'] == 'FAILED', attempts
        assert attempts[0]['errorMessage'] == 'first boom', attempts
        assert attempts[0]['durationMs'] is not None, attempts

        retried = api(s, 'POST', f'/tasks/{task_id}/retry')
        assert retried.status_code == 200, retried.text
        execute(
            "UPDATE task_center.task SET status='RUNNING', locked_by='mgmt-e2e', "
            "locked_until=now() + interval '1 minute', start_time=now() WHERE id=%s",
            (task_id,))
        execute(
            "UPDATE task_center.task SET status='COMPLETED', progress=100, "
            "finish_time=now(), locked_by=NULL, locked_until=NULL WHERE id=%s",
            (task_id,))

        attempts = api(s, 'GET', f'/tasks/{task_id}').json()['attempts']
        assert [item['status'] for item in attempts] == ['FAILED', 'COMPLETED'], attempts
        print('MGMT attempt history OK')
    finally:
        execute('DELETE FROM task_center.task WHERE id=%s', (task_id,))


def main():
    global EMBEDDING
    s = session()
    EMBEDDING = api(s, 'GET', '/system/embedding-models').json()[0]
    before = int(one('SELECT count(*) FROM task_center.task')[0])
    test_cancel_notify()
    test_list_stats_detail(s)
    test_groups_and_names(s)
    test_filters_and_errors(s)
    test_cancel_retry_priority(s)
    test_cancel_hook(s)
    test_attempt_history(s)
    after = int(one('SELECT count(*) FROM task_center.task')[0])
    assert after == before, (before, after)
    print('MGMT cleanup OK, task rows=', after)
    print('TASK MANAGEMENT TESTS PASS')


if __name__ == '__main__':
    main()
