"""统一任务管理面的纯函数与准入逻辑。"""

from datetime import datetime, timezone

import pytest

from infrastructure.tasks import TaskEngine, TaskKind, TaskRejectedError, registry
from infrastructure.tasks import management


def _row(**overrides):
    base = {
        'id': 't1',
        'task_type': 'FILE_IMPORT',
        'lane': 'file_import',
        'status': 'PENDING',
        'priority': 0,
        'progress': 0,
        'attempt': 1,
        'max_attempts': 4,
        'kbase_id': 'kb1',
        'error_message': None,
        'start_time': None,
        'finish_time': None,
        'available_at': datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc),
        'locked_by': None,
        'locked_until': None,
        'heartbeat_at': None,
        'created_at': datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc),
        'updated_at': datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc),
        'payload': {'fileId': 'f1'},
        'extra': {},
    }
    base.update(overrides)
    return base


def test_task_dict_maps_columns_and_omits_payload_by_default():
    item = management._task_dict(_row())

    assert item['taskType'] == 'FILE_IMPORT'
    assert item['availableAt'] == '2026-11-10T12:00:00+00:00'
    assert 'payload' not in item
    assert 'extra' not in item


def test_attempt_dict_maps_duration_and_iso_times():
    item = management._attempt_dict({
        'attempt': 2,
        'worker_id': 'w1',
        'status': 'FAILED',
        'error_message': 'boom',
        'started_at': datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc),
        'finished_at': datetime(2026, 11, 10, 12, 0, 1, 500000,
                                tzinfo=timezone.utc),
    })

    assert item == {
        'attempt': 2,
        'workerId': 'w1',
        'status': 'FAILED',
        'errorMessage': 'boom',
        'startedAt': '2026-11-10T12:00:00+00:00',
        'finishedAt': '2026-11-10T12:00:01.500000+00:00',
        'durationMs': 1500,
    }


def test_attempt_dict_leaves_duration_null_when_unfinished():
    item = management._attempt_dict({
        'attempt': 1, 'status': 'RUNNING',
        'started_at': datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc),
        'finished_at': None,
    })
    assert item['durationMs'] is None
    assert item['finishedAt'] is None


def test_task_dict_includes_file_and_kbase_names():
    item = management._task_dict(_row(
        file_name='report.md', kbase_name='Demo KB'))

    assert item['fileName'] == 'report.md'
    assert item['kbaseName'] == 'Demo KB'


def test_group_dict_zero_fills_status_counts():
    item = management._group_dict({
        'kbase_id': 'kb1',
        'kbase_name': 'Demo KB',
        'total': 3,
        'latest_created_at': datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc),
        'pending': 1,
        'running': 2,
    })

    assert item['kbaseId'] == 'kb1'
    assert item['kbaseName'] == 'Demo KB'
    assert item['total'] == 3
    assert item['byStatus']['PENDING'] == 1
    assert item['byStatus']['RUNNING'] == 2
    assert item['byStatus']['FAILED'] == 0
    assert item['latestCreatedAt'] == '2026-11-10T12:00:00+00:00'


def test_task_dict_includes_payload_for_detail():
    item = management._task_dict(_row(payload={'fileId': 'f1'}), include_payload=True)

    assert item['payload'] == {'fileId': 'f1'}
    assert item['extra'] == {}


def test_parse_statuses_accepts_comma_separated_values():
    assert management._parse_statuses('pending, FAILED') == ['PENDING', 'FAILED']
    assert management._parse_statuses('') is None
    assert management._parse_statuses(None) is None


def test_parse_statuses_rejects_unknown_status():
    with pytest.raises(Exception) as error:
        management._parse_statuses('PENDING,BOGUS')
    assert error.value.problem_spec().status == 422


def test_page_params_rejects_out_of_range():
    assert management._page_params(1, 200) == (1, 200)
    with pytest.raises(Exception):
        management._page_params(0, 20)
    with pytest.raises(Exception):
        management._page_params(1, management.MAX_PAGE_SIZE + 1)


def test_retry_input_available_checks_graph_temp_files(tmp_path):
    assert management._retry_input_available(_row(task_type='FILE_IMPORT'))

    tmp_dir = tmp_path / 'input'
    tmp_dir.mkdir()
    assert management._retry_input_available(
        _row(task_type='GRAPH_EXTRACT', payload={'tmpDir': str(tmp_dir)}))

    zip_path = tmp_path / 'graph.zip'
    zip_path.write_bytes(b'PK')
    assert management._retry_input_available(
        _row(task_type='GRAPH_IMPORT', payload={'zipPath': str(zip_path)}))

    assert not management._retry_input_available(
        _row(task_type='GRAPH_EXTRACT', payload={'tmpDir': str(tmp_path / 'gone')}))
    assert not management._retry_input_available(
        _row(task_type='GRAPH_IMPORT', payload={'zipPath': str(tmp_path / 'gone.zip')}))


def test_set_priority_rejects_non_int_and_out_of_range():
    for value in (None, True, '5', management.PRIORITY_MAX + 1):
        with pytest.raises(Exception) as error:
            management.set_priority('task-id', value)
        assert error.value.problem_spec().status == 422


def _engine_with_lane(mode='db', capacity=2):
    engine = TaskEngine()
    engine.register_lane('lane', mode=mode, capacity=capacity)
    return engine


def test_ensure_capacity_rejects_when_pending_reaches_limit(monkeypatch):
    engine = _engine_with_lane()
    monkeypatch.setattr('infrastructure.tasks.engine.pg_queue.pending_count',
                        lambda lane: 1)
    engine.ensure_capacity('lane')

    monkeypatch.setattr('infrastructure.tasks.engine.pg_queue.pending_count',
                        lambda lane: 2)
    with pytest.raises(TaskRejectedError):
        engine.ensure_capacity('lane')


def test_ensure_capacity_skips_memory_lane_and_unlimited(monkeypatch):
    calls = []
    monkeypatch.setattr('infrastructure.tasks.engine.pg_queue.pending_count',
                        lambda lane: calls.append(lane) or 99)
    _engine_with_lane(mode='memory', capacity=1).ensure_capacity('lane')
    _engine_with_lane(mode='db', capacity=0).ensure_capacity('lane')
    assert calls == []


def test_register_kind_registers_cancel_and_retry_hooks():
    engine = _engine_with_lane()
    cancel_hook = lambda row: None  # noqa: E731
    retry_hook = lambda row: None  # noqa: E731
    engine.register_kind(
        TaskKind(name='kind', lane='lane', queue_mode='db',
                 persist_type='TEST_TASK_TYPE', cancel_hook=cancel_hook,
                 retry_hook=retry_hook),
        lambda record, ctx: None)
    try:
        assert registry.cancel_hook_for('TEST_TASK_TYPE') is cancel_hook
        assert registry.retry_hook_for('TEST_TASK_TYPE') is retry_hook
    finally:
        registry.unregister_cancel_hook('TEST_TASK_TYPE')
        registry.unregister_retry_hook('TEST_TASK_TYPE')
