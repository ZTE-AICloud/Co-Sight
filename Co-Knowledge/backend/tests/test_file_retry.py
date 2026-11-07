"""手工重试（``file_retry_service``）。

不连 DB / 网络：目录行、属性、存储引用、队列全部用桩替换。重点钉住四件事：

1. **状态闸门**：只有 ``status = 2`` 能重试，原生认领只成功一次；
2. **配置还原**：上传时落库的 ``task_config`` 被原样放回 handle；
3. **旧行回落**：没有 ``task_config`` 时取系统算子默认参数（与上传界面同口径）；
4. **失败兜底**：入队失败要把状态退回 2，不能停在「待处理」。
"""

from __future__ import annotations

import json

import pytest

from knowledge_base.service import file_retry_service as service
from shared.errors.api import KbApiError

ROW = {
    'id': 'file-1',
    'kbase_id': 'kb-1',
    'title': 'guide.pdf',
    'type': 'file',
    'status': 2,
    'fail_reason': 'RetCode.operator.split.error',
}


class _Queue:
    def __init__(self, error=None):
        self.error = error
        self.handles = []

    def submit_task(self, handle):
        self.handles.append(handle)
        if self.error is not None:
            raise self.error
        return 'task-1'


def _patch(monkeypatch, *, row=ROW, core_exists=True, config=None,
           size='1024', claim=True, queue=None, support=None):
    monkeypatch.setattr(service.directory_store, 'get_directory',
                        lambda *args, **kwargs: row)
    monkeypatch.setattr(service.storage, 'core_file_exists', lambda file_id: core_exists)
    monkeypatch.setattr(service.storage, 'core_key', lambda file_id: f'core/{file_id[:4]}/{file_id}')
    monkeypatch.setattr(service.directory_store, 'get_properties',
                        lambda ids, name: {ids[0]: size})
    monkeypatch.setattr(service.kbase_store, 'select_kbase_by_id',
                        lambda kbase_id: {'embedding_model': 'text-embedding-v3'})
    monkeypatch.setattr(service.directory_store, 'get_all_properties',
                        lambda ids: {ids[0]: {'task_config': json.dumps(config)}
                                     if config is not None else {}})
    monkeypatch.setattr(service, '_claim', lambda file_id: claim)
    restored = []
    monkeypatch.setattr(service, '_restore_failed',
                        lambda file_id, reason: restored.append((file_id, reason)))
    queue = queue or _Queue()
    monkeypatch.setattr(service.runtime, 'get_queue', lambda: queue)
    # 默认给一个最小的系统算子：没有它，_default_split_operator 会去连真实 DB。
    if support is None:
        support = lambda payload, emp_no, org_id: {'pdf': [{'id': -1, 'args': []}]}
    from operators.service import operator_service
    monkeypatch.setattr(operator_service, 'support', support)
    return queue, restored


def test_unknown_document_is_404(monkeypatch):
    _patch(monkeypatch, row=None)

    with pytest.raises(KbApiError) as caught:
        service.retry_file('kb-1', 'file-1', 'admin')

    assert caught.value.key == 'file.not.exist'
    assert caught.value.problem_spec().status == 404


def test_only_failed_documents_can_be_retried(monkeypatch):
    queue, _ = _patch(monkeypatch, row={**ROW, 'status': 1})

    with pytest.raises(KbApiError) as caught:
        service.retry_file('kb-1', 'file-1', 'admin')

    assert caught.value.key == 'file.retry.not.allowed'
    assert caught.value.problem_spec().status == 409
    assert queue.handles == []


def test_missing_core_file_is_404(monkeypatch):
    _patch(monkeypatch, core_exists=False)

    with pytest.raises(KbApiError) as caught:
        service.retry_file('kb-1', 'file-1', 'admin')

    assert caught.value.key == 'file.not.exist'


def test_reenqueues_with_the_stored_task_config(monkeypatch):
    config = {
        'operatorSplitDTO': {'operatorId': -1,
                             'args': [{'argName': 'maxWordCount', 'defaultValue': 512},
                                      {'argName': 'overlap', 'defaultValue': 128}]},
        'operatorParseDTO': {'operatorId': 7, 'args': []},
        'regexList': ['a+'],
    }
    queue, _ = _patch(monkeypatch, config=config)

    result = service.retry_file('kb-1', 'file-1', 'admin')

    assert result == {'fileId': 'file-1', 'taskId': 'task-1'}
    handle = queue.handles[0]
    assert handle['fileId'] == 'file-1'
    assert handle['kbaseId'] == 'kb-1'
    assert handle['diskPath'] == 'core/file/file-1'
    assert handle['format'] == 'pdf'
    assert handle['fileName'] == 'guide.pdf'
    assert handle['fileSize'] == 1024
    assert handle['modelName'] == 'text-embedding-v3'
    assert handle['operatorSplitDTO'] == config['operatorSplitDTO']
    assert handle['operatorParseDTO'] == config['operatorParseDTO']
    assert handle['regexList'] == ['a+']


def test_falls_back_to_the_default_split_operator(monkeypatch):
    seen = {}

    def fake_support(payload, emp_no, org_id):
        seen['payload'] = payload
        return {'pdf': [
            {'id': -2, 'args': [{'argName': 'maxWordCount', 'defaultValue': 512}]},
            {'id': -1, 'args': [{'argName': 'maxWordCount', 'defaultValue': 512},
                                {'argName': 'overlap', 'defaultValue': 128}]},
        ]}

    queue, _ = _patch(monkeypatch, config=None, support=fake_support)

    service.retry_file('kb-1', 'file-1', 'admin', org_id='org-1')

    assert seen['payload'] == {'module': 'text_split', 'formats': ['pdf']}
    assert queue.handles[0]['operatorSplitDTO']['operatorId'] == -1
    assert queue.handles[0]['operatorSplitDTO']['args'][1]['argName'] == 'overlap'


def test_no_operator_at_all_is_rejected_before_enqueue(monkeypatch):
    queue, _ = _patch(monkeypatch, config=None,
                      support=lambda payload, emp_no, org_id: {'pdf': []})

    with pytest.raises(KbApiError) as caught:
        service.retry_file('kb-1', 'file-1', 'admin')

    assert caught.value.key == 'RetCode.operator.notfound'
    assert queue.handles == []


def test_losing_the_claim_race_is_a_conflict(monkeypatch):
    queue, _ = _patch(monkeypatch, claim=False)

    with pytest.raises(KbApiError) as caught:
        service.retry_file('kb-1', 'file-1', 'admin')

    assert caught.value.key == 'file.retry.not.allowed'
    assert queue.handles == []


def test_enqueue_failure_restores_the_failed_status(monkeypatch):
    queue, restored = _patch(monkeypatch, queue=_Queue(error=RuntimeError('queue full')))

    with pytest.raises(RuntimeError):
        service.retry_file('kb-1', 'file-1', 'admin')

    assert restored == [('file-1', 'RetCode.operator.split.error')]


def test_default_split_operator_missing_format_returns_none():
    assert service._default_split_operator('', 'admin', None) is None


def test_task_config_is_not_in_the_handle_when_absent(monkeypatch):
    """旧行（没有 task_config）不能把空配置当成算子 DTO 写进 handle。"""
    queue, _ = _patch(monkeypatch, config=None,
                      support=lambda payload, emp_no, org_id: {
                          'pdf': [{'id': -1, 'args': []}]})

    service.retry_file('kb-1', 'file-1', 'admin')

    assert 'operatorParseDTO' not in queue.handles[0]


def test_retry_endpoint_returns_202(monkeypatch):
    """路由契约：``POST /documents/{id}/retry`` → 202 + ``{fileId, taskId}``。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from http_api import register_rkb_api
    from knowledge_base import api as kb_api
    from shared.prefixes import RKB_PREFIX

    seen = {}

    def fake_retry(kbase_id, file_id, emp_no, org_id=None):
        seen.update(kbase_id=kbase_id, file_id=file_id)
        return {'fileId': file_id, 'taskId': 'task-1'}

    monkeypatch.setattr(kb_api.file_retry_service, 'retry_file', fake_retry)
    app = FastAPI()
    register_rkb_api(app)
    client = TestClient(app)

    response = client.post(f'{RKB_PREFIX}/knowledge-bases/kb-1/documents/file-1/retry')

    assert response.status_code == 202
    assert response.json() == {'fileId': 'file-1', 'taskId': 'task-1'}
    assert seen == {'kbase_id': 'kb-1', 'file_id': 'file-1'}
